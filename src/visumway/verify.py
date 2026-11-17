"""`visumway verify`: prove the connections work instead of saying "installed".

Uses the built-in selftest wake, which exercises inbox -> rules -> wake
dispatch end to end without spending a single model token.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from . import config as config_mod
from . import agents, service
from .bridges import desktop, system, visual, winevents, linuxevents, macevents
from .daemon import Daemon, daemon_alive
from .events import Event, write_event
from .paths import Home
from .policy import SELFTEST_TYPE

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def _mcp_check(home: Home) -> tuple:
    env = dict(os.environ, VISUMWAY_HOME=str(home.root))
    src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    req = "\n".join(json.dumps(m) for m in [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "visumway-verify", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "reflex_status", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "watch_frame", "arguments": {"watch_id": "unopened"}}},
    ]) + "\n"
    try:
        p = subprocess.run([sys.executable, "-m", "visumway", "mcp"], input=req, capture_output=True,
                           text=True, timeout=30, env=env)
        replies = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
        tools = next(r for r in replies if r.get("id") == 2)["result"]["tools"]
        call = next(r for r in replies if r.get("id") == 3)["result"]
        inactive = next(r for r in replies if r.get("id") == 4)["result"]
        watch_tools = {"watch_start", "watch_frame", "watch_read", "watch_stop", "inspect_window"}
        if (len(replies) == 4 and watch_tools <= {tool["name"] for tool in tools}
                and not call.get("isError") and inactive.get("isError")
                and json.loads(inactive["content"][0]["text"]) == {"status": "inactive"}):
            return PASS, "MCP server answered; %d tools exposed" % len(tools)
        return FAIL, "unexpected MCP replies"
    except Exception as e:
        return FAIL, "MCP server failed: %s" % e


def _wake_check(home: Home, cfg: dict) -> tuple:
    try:
        home.selftest.unlink()
    except OSError:
        pass
    ev = Event(type=SELFTEST_TYPE, source="verify")
    live = daemon_alive(home)
    write_event(home, ev)
    local = None
    if not live:
        local = Daemon(home, cfg)
    deadline = time.time() + 20
    ok = False
    while time.time() < deadline:
        if local:
            local.tick()
        try:
            if json.loads(home.selftest.read_text(encoding="utf-8")).get("event_id") == ev.id:
                ok = True
                break
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    if local:
        local.stop()
    if not ok:
        return FAIL, "synthetic wake signal was not delivered within 20s"
    if live:
        return PASS, "installed runtime received a synthetic event and dispatched a wake (0 tokens)"
    return WARN, "wake path works, but the reflex runtime is not running; start it with `visumway service install`"


def run_checks(home: Home, send_test_notification: bool = False) -> list:
    checks = []

    def add(name, status, detail):
        checks.append({"check": name, "status": status, "detail": detail})

    try:
        home.ensure()
        cfg = config_mod.load(home)
        add("config", PASS if home.config.exists() else WARN,
            str(home.config) if home.config.exists() else "no config.json yet; using defaults (run `visumway init`)")
    except Exception as e:
        add("config", FAIL, str(e))
        return checks

    add("blueprint", PASS if home.blueprint.exists() else WARN,
        "host blueprint saved" if home.blueprint.exists() else "run `visumway init` to scan this machine")

    add("wake path", *_wake_check(home, cfg))
    add("agent interface", *_mcp_check(home))

    default = cfg["agent"].get("default")
    if not cfg["agent"]["bound"]:
        owner = cfg["agent"]["installer"]
        detail = ("Notifications reserved for %s; no wake adapter is connected." % owner if owner else
                  "Optional. The shared tools are available; no wake adapter is connected.")
        add("agent wake-up", PASS, detail)
    elif default not in cfg["agent"]["adapters"]:
        add("agent wake-up", FAIL, "agent.default '%s' has no adapter" % default)
    else:
        info = agents.inspect(home, cfg, default)
        if not info["installed"]:
            add("agent wake-up", WARN, "'%s' is not installed; real wakes will fail" % default)
        elif info["verified"]:
            add("agent wake-up", PASS, "%s: background invocation verified (%s)" % (info["label"], info["version"]))
        elif info["signed_in"] is False:
            add("agent wake-up", WARN, "%s is installed but not signed in" % info["label"])
        else:
            add("agent wake-up", WARN, "%s is installed%s, but background invocation is not verified: "
                "run `visumway agent probe` (one tiny real call)"
                % (info["label"], " and signed in" if info["signed_in"] else ""))

    procs = system.list_processes()
    add("process bridge", PASS if procs else FAIL, "%d processes visible" % len(procs))

    shot = visual.capture(home=home)
    if shot["ok"]:
        add("visual bridge", PASS, "captured a %dx%d desktop frame via %s" %
            (shot["width"], shot["height"], shot["backend"]))
        try:
            os.unlink(shot["path"])
        except OSError:
            pass
    else:
        add("visual bridge", WARN, shot["error"])

    targeted = visual.installed(home)
    if targeted is not None:
        if not targeted:
            add("Windows visual targets", WARN, "helper missing; follow docs/WINDOWS_VISUAL.md")
        else:
            targets = visual.targets(home)
            add("Windows buffered watch", PASS if targets.get("window_feed") else WARN,
                "native window feed available" if targets.get("window_feed") else
                "install the current Windows visual helper for buffered watches")
            add("Windows control inspection", PASS if targets.get("window_controls") else WARN,
                "UI Automation bridge available" if targets.get("window_controls") else
                "install the current Windows visual helper to inspect controls")
            display = next((t for t in targets["targets"] if t.get("kind") == "display"), None)
            if display:
                with tempfile.TemporaryDirectory(prefix="visumway-verify-") as tmp:
                    frame = visual.capture(os.path.join(tmp, "display.png"), home=home,
                                           target=display["id"], max_edge=800)
                    if frame["ok"]:
                        add("Windows visual targets", PASS, "captured a %dx%d display frame using %s; select a window separately" %
                            (frame["width"], frame["height"], frame["renderer"]))
                    else:
                        add("Windows visual targets", WARN, frame["error"])
            else:
                add("Windows visual targets", WARN, targets.get("targeted_capture_error", "no live display was listed"))

    channels = cfg["notify"]["channels"] if cfg["agent"]["bound"] else []
    kinds = [c["type"] for c in channels]
    if "desktop" in kinds:
        kind = desktop.backend()
        if not kind:
            add("desktop bubble", WARN, "no desktop notification backend in this session")
        elif send_test_notification:
            res = desktop.show(home, cfg, cfg["agent"].get("identity", "VisumWay"),
                               "VisumWay verify: this is a test notification.")
            add("desktop bubble", PASS if res["ok"] else FAIL,
                "notification submitted to %s; confirm visible on the host screen" % kind if res["ok"] else res.get("error", "failed"))
        elif kind == "windows-toast":
            res = desktop.windows_status(home)
            detail = "WinRT notifications enabled (pass --send-test-notification to show one)"
            add("desktop bubble", PASS if res["ok"] else WARN, detail if res["ok"] else res["error"])
        else:
            add("desktop bubble", PASS, "%s available (pass --send-test-notification to show one)" % kind)
        reg = desktop.registered(home)
        if reg is not None:
            add("click handler", PASS if reg else WARN,
                "visumway:// handler registered" if reg else "not registered: run `visumway setup`")
    remote = [c for c in channels if c["type"] in ("ntfy", "webhook")]
    if remote and send_test_notification:
        from . import notify
        only = dict(cfg, notify={"channels": remote})
        res = notify.send(home, only, "VisumWay verify: test notification.", title="VisumWay", sender="visumway-system")
        bad = [r for r in res if not r["ok"]]
        add("remote channel", FAIL if bad else PASS, json.dumps(bad) if bad else "test sent on %d channel(s)" % len(res))
    elif remote:
        add("remote channel", PASS, "%d configured (pass --send-test-notification to test delivery)" % len(remote))
    app_thread = cfg["agent"].get("codex_app_thread") if default == "codex" else None
    if app_thread:
        add("Codex app alerts", WARN,
            "configured for a saved chat; verify the real app turn and notification with a native event")
    if cfg["agent"]["bound"] and "desktop" not in kinds and not remote and not app_thread:
        add("communication", WARN, "only the local file channel is configured; the AI cannot reach the user")

    for name, mod in (("windows-events", winevents), ("linux-journal", linuxevents),
                      ("macos-reports", macevents)):
        bridge = mod.installed(home)
        if bridge is not None and (name != "linux-journal" or linuxevents.supported()):
            add("event bridge", PASS if bridge else WARN,
                ("%s definition present; verify real OS event delivery" % name) if bridge
                else ("not installed: run `visumway bridge install %s`" % name))

    inst = service.installed(home)
    add("persistence", PASS if inst else WARN,
        "runtime service is installed" if inst else "service not installed (or unknown): run `visumway service install`, then re-verify after a reboot")
    return checks


def render(checks: list) -> str:
    lines = ["%-4s  %-16s %s" % (c["status"], c["check"], c["detail"]) for c in checks]
    fails = sum(c["status"] == FAIL for c in checks)
    warns = sum(c["status"] == WARN for c in checks)
    lines.append("")
    lines.append("%d passed, %d warnings, %d failed" % (len(checks) - fails - warns, warns, fails))
    return "\n".join(lines)
