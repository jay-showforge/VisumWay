"""Command line: the surface both humans and agents use."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from . import (__version__, agents, config as config_mod, incidents, notify, opener, plan as plan_mod,
               service, verify as verify_mod, wake)
from .bridges import desktop, visual, winevents, linuxevents, macevents
from .daemon import Daemon, daemon_alive, read_heartbeat
from .discover import discover
from .events import Event, EventError, EventLog, write_event
from .paths import Home


BRIDGES = {"windows-events": winevents, "linux-journal": linuxevents, "macos-reports": macevents}


def _write_plan(home: Home, cfg: dict, infos: "list | None" = None) -> str:
    bp = discover(home)
    home.blueprint.write_text(json.dumps(bp, indent=2), encoding="utf-8")
    if infos is None:
        infos = agents.inspect_all(home, cfg)
    md = plan_mod.render_markdown(bp, plan_mod.build_plan(bp, cfg, infos, agents.desktop_apps()))
    home.plan.write_text(md, encoding="utf-8")
    return md


def _init(home: Home, args) -> int:
    home.ensure()
    created = config_mod.write_default(home)
    print(_write_plan(home, config_mod.load(home)))
    print("Home: %s (config %s)" % (home.root, "created" if created else "kept"))
    return 0


def _setup(home: Home, args) -> int:
    """Install the shared tools, with an optional wake binding for the installer."""
    user = config_mod.read_user(home)
    configured = user.get("agent", {}).get("default")
    installer = config_mod.installing_agent(user)
    pick = args.agent
    if (installer and pick != installer) or (user.get("setup_complete") and not pick):
        print("VisumWay is already set up at %s. Use the shared CLI or MCP tools here." % home.root)
        if configured:
            print("The notification agent is %s." % configured)
        elif installer:
            print("Notifications are reserved for %s if it configures a wake adapter." % installer)
        return 0
    if args.windows_background and os.name != "nt":
        print("--windows-background is available on Windows.", file=sys.stderr)
        return 2
    home.ensure()
    log = ["config: %s" % ("created" if config_mod.write_default(home) else "kept")]
    if pick and not installer:
        config_mod.update_user(home, {"agent": {"installer": pick}}, expected_installer=installer)
        installer = pick
    cfg = config_mod.load(home)
    selected = agents.inspect(home, cfg, pick) if pick in cfg["agent"]["adapters"] else None
    wake_ready = bool(selected and selected["installed"]
                      and (not selected["requires_account"] or selected["billing_safe"]))
    if not configured and wake_ready:
        config_mod.update_user(home, {"agent": {"default": pick}, "reflex": {"wakes_enabled": False}},
                               expected_agent=configured, expected_installer=installer)
        configured = pick
        cfg = config_mod.load(home)
    if configured:
        log.append("notification agent: '%s'" % configured)
    if pick and not wake_ready:
        if selected is None:
            reason = "no configured wake adapter"
        elif not selected["installed"]:
            reason = "agent command unavailable"
        else:
            reason = "existing account sign-in was not confirmed (%s)" % selected["auth"]
        log.append("Automatic wake unavailable for '%s': %s. The shared tools can still be installed." % (pick, reason))
    elif not pick:
        log.append("Shared tools only. No notification agent was assigned.")
    if args.windows_background and wake_ready:
        channels = [c for c in cfg["notify"]["channels"] if c["type"] != "desktop"]
        if not any(c["type"] == "file" for c in channels):
            channels.append({"type": "file"})
        # Establish the delivery route before changing how live events wake the agent.
        toast_log = desktop.register(home, cfg)
        if any(line.startswith("FAILED") for line in toast_log):
            print("\n".join(toast_log), file=sys.stderr)
            return 1
        account = {"use_account_login": True}
        if cfg["agent"].get("codex_app_thread"):
            account["codex_app_thread"] = ""
        config_mod.update_user(home, {
            "agent": account,
            "notify": {"channels": [{"type": "desktop"}] + channels},
        }, expected_agent=pick)
        cfg = config_mod.load(home)
        log += toast_log
        log.append("wake delivery: signed-in agent with independent Windows toast")
    elif configured and any(channel["type"] == "desktop" for channel in cfg["notify"]["channels"]):
        log += desktop.register(home, cfg)
    elif configured and desktop.registered(home):
        log += desktop.unregister(home)
    if not args.no_service:
        log += service.install(home, restart=args.windows_background and wake_ready)
    if not args.no_bridges:
        for name, mod in BRIDGES.items():
            log += mod.install(home)
    plan = _write_plan(home, cfg, [selected] if selected else [])
    success = not any(line.startswith("FAILED") for line in log)
    if success:
        config_mod.update_user(home, {"setup_complete": True})
    print(plan)
    print("\n".join(log))
    print("\nNext: `visumway verify`, then connect this host to `visumway mcp` or use the shared CLI.")
    if wake_ready:
        print(wake.privacy_notice(cfg))
        if not cfg["reflex"]["wakes_enabled"]:
            print("Automatic wakes are paused. Run `visumway wakes preview`, then "
                  "`visumway wakes enable --agent %s` if the user wants alerts." % pick)
    return 0 if success else 1


def _uninstall(home: Home, args) -> int:
    if args.purge and home.root.exists():
        user_config = config_mod.read_user(home)
        if (home.root in (home.root.parent, Path.home().resolve()) or not isinstance(user_config, dict)
                or user_config.get("version") != 1 or not home.state.is_dir()
                or not home.bridges.is_dir()):
            print("Refusing to purge a directory without an initialized VisumWay home.", file=sys.stderr)
            return 2
    log = []
    if not args.no_bridges:
        for mod in BRIDGES.values():
            log += mod.remove(home)
        log += visual.remove(home)
    if not args.no_service:
        log += service.remove(home)
    log += desktop.unregister(home)
    if args.purge and not any(line.startswith("FAILED") for line in log):
        try:
            if home.root.exists():
                shutil.rmtree(home.root)
            log.append("removed VisumWay home %s" % home.root)
        except OSError as error:
            log.append("FAILED: could not purge %s: %s" % (home.root, error))
    else:
        log.append("kept %s (use --purge to delete it)" % home.root)
    print("\n".join(log))
    return 1 if any(line.startswith("FAILED") for line in log) else 0


def _agent(home: Home, args) -> int:
    home.ensure()
    cfg = config_mod.load(home)
    if args.action == "probe":
        if not args.name and not cfg["agent"]["bound"]:
            print("No notification agent is configured. Specify an adapter to probe.", file=sys.stderr)
            return 2
        res = agents.probe(home, cfg, args.name or cfg["agent"]["default"])
        print(json.dumps(res, indent=2))
        return 0 if res["verified"] else 1
    out = {"default": cfg["agent"]["default"] if cfg["agent"]["bound"] else None,
           "installer": cfg["agent"]["installer"],
           "agents": agents.inspect_all(home, cfg),
           "desktop_apps": agents.desktop_apps()}
    print(json.dumps(out, indent=2))
    return 0


def _wakes(home: Home, args) -> int:
    cfg = config_mod.load(home)
    print(wake.privacy_notice(cfg))
    if args.action == "preview":
        print(wake.preview(cfg))
        return 0
    if not _require_notification_owner(cfg, args.agent):
        return 2
    enabled = args.action == "enable"
    config_mod.update_user(home, {"reflex": {"wakes_enabled": enabled, "wake_revision": uuid4().hex}},
                           expected_agent=args.agent)
    print("Automatic wakes enabled." if enabled else
          "Automatic wakes paused. An invocation already in progress can finish.")
    return 0


def _incidents(home: Home, args) -> int:
    for inc in incidents.recent(home, args.n):
        s = incidents.summary(inc)
        if args.json:
            print(json.dumps(s))
            continue
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s["created"] or 0))
        print("%s  %s  %-8s %s %s x%s  %s" % (when, s["id"], s["status"], s["event"], s["subject"] or "",
                                             s["count"], (s["message"] or "")[:70]))
    return 0


def _open(home: Home, args) -> int:
    res = opener.handle(home, config_mod.load(home), args.target, args.action)
    print(json.dumps(res))
    return 0 if res.get("ok") else 1


def _notify_wait(home: Home, args) -> int:
    desktop.wait_and_dispatch(home, config_mod.load(home), args.incident, args.title, args.message)
    return 0


def _bridge(home: Home, args) -> int:
    if args.action == "list":
        for name, mod in {**BRIDGES, "windows-visual": visual}.items():
            state = mod.installed(home)
            print("%-16s %s" % (name, "not applicable on this OS" if state is None
                                else "installed" if state else "not installed"))
        return 0
    if args.name == "windows-visual":
        if args.action == "run":
            print("Use visumway capture --list or visumway capture --target ID.", file=sys.stderr)
            return 2
        log = (visual.install(home.ensure(), args.source, args.sha256)
               if args.action == "install" else visual.remove(home))
        print("\n".join(log))
        return 1 if any(l.startswith("FAILED") for l in log) else 0
    if args.source is not None or args.sha256 is not None:
        print("A helper path and SHA-256 are supported by bridge install windows-visual.", file=sys.stderr)
        return 2
    mod = BRIDGES.get(args.name or "")
    if mod is None:
        print("visumway bridge: choose from %s" % ", ".join(BRIDGES), file=sys.stderr)
        return 2
    home.ensure()
    if args.action == "run":
        for ev in mod.collect(home):
            print("%s %s" % (ev.type, ev.subject))
        return 0
    log = mod.install(home) if args.action == "install" else mod.remove(home)
    print("\n".join(log))
    return 1 if any(l.startswith("FAILED") for l in log) else 0


def _crashtest(home: Home, args) -> int:
    """Crash a dedicated child process so the OS records a real
    application crash. Nothing is emitted by hand: the installed bridge must notice."""
    if not _require_notification_owner(config_mod.load(home), args.agent):
        return 2
    code = ("import ctypes; ctypes.windll.kernel32.RaiseFailFastException(None, None, 0)"
            if os.name == "nt" else "import ctypes; ctypes.string_at(0)")
    p = subprocess.run([sys.executable, "-c", code],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    crashed = p.returncode >= 0x80000000 if os.name == "nt" else p.returncode < 0
    if crashed:
        print("test child crashed (exit code %s). Check `visumway events` and your notifications." % p.returncode)
    else:
        print("test child did not report a native crash (exit code %s)." % p.returncode, file=sys.stderr)
    return 0 if crashed else 1


def _discover(home: Home, args) -> int:
    print(json.dumps(discover(home), indent=2))
    return 0


def _plan(home: Home, args) -> int:
    bp = discover(home)
    cfg = config_mod.load(home)
    rows = plan_mod.build_plan(bp, cfg, agents.inspect_all(home, cfg), agents.desktop_apps())
    print(json.dumps(rows, indent=2) if args.json else plan_mod.render_markdown(bp, rows))
    return 0


def _run(home: Home, args) -> int:
    return Daemon(home).run_forever(interval=args.interval)


def _emit(home: Home, args) -> int:
    data = {}
    try:
        if args.json:
            data = json.loads(args.json)
        for pair in args.data or []:
            k, _, v = pair.partition("=")
            data[k] = v
        ev = Event(type=args.type, source=args.source, subject=args.subject,
                   severity=args.severity, data=data)
    except (EventError, ValueError) as e:
        print("visumway emit: %s" % e, file=sys.stderr)
        return 2
    home.ensure()
    write_event(home, ev)
    print(ev.id)
    return 0


def _events(home: Home, args) -> int:
    for rec in EventLog(home).tail(args.n):
        if args.json:
            print(json.dumps(rec))
            continue
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(rec.get("logged_at", 0)))
        if rec.get("kind") == "event":
            ev = rec["event"]
            print("%s  %-6s %-22s %s  (%s)" % (when, rec["action"], ev["type"], ev.get("subject", ""), rec["reason"]))
        elif rec.get("kind") == "wake":
            r = rec.get("report", {})
            print("%s  WAKE   %-22s %s  x%s agent=%s ok=%s" % (when, r.get("type"), r.get("subject", ""),
                                                              r.get("count"), rec.get("agent"), rec.get("ok")))
        elif rec.get("kind") == "redelivered":
            print("%s  AGAIN  incident %s shown again (snooze ended, no model call)" % (when, rec.get("incident_id")))
        else:
            r = rec.get("report", {})
            print("%s  BLOCK  %-22s %s  (%s)" % (when, r.get("type"), r.get("subject", ""), rec.get("reason")))
    return 0


def _status(home: Home, args) -> int:
    cfg = config_mod.load(home)
    hb = read_heartbeat(home)
    alive = daemon_alive(home)
    day = EventLog(home).tail(0, since=time.time() - 86400)
    wakes = [r for r in day if r.get("kind") == "wake" and r.get("agent") != "selftest"]
    out = {
        "home": str(home.root),
        "shared_tools_configured": bool(cfg.get("setup_complete") or cfg["agent"]["bound"]),
        "installing_agent": cfg["agent"]["installer"],
        "runtime_running": alive,
        "runtime_pid": hb.get("pid") if alive else None,
        "llm_invocations_while_idle": 0,
        "last_24h": {"events_logged": sum(r.get("kind") == "event" for r in day),
                     "wakes": len(wakes),
                     "wakes_blocked_by_budget": sum(r.get("kind") == "wake_blocked"
                                                    and r.get("reason", "").startswith("budget_") for r in day)},
        "budget": cfg["reflex"]["budget"],
        "budget_remaining": hb.get("budget_remaining") if alive else None,
        "default_agent": cfg["agent"]["default"] if cfg["agent"]["bound"] else None,
        "notification_agent": hb.get("notification_agent") if alive else None,
        "automatic_wakes_enabled": hb.get("automatic_wakes_enabled") if alive else None,
        "configured_wakes_enabled": cfg["reflex"]["wakes_enabled"],
        "notify_channels": [c["type"] for c in cfg["notify"]["channels"]],
    }
    print(json.dumps(out, indent=2))
    return 0


def _notify(home: Home, args) -> int:
    cfg = config_mod.load(home)
    agent = args.agent or os.environ.get("VISUMWAY_WAKE_AGENT")
    if not _require_notification_owner(cfg, agent):
        return 2
    home.ensure()
    results = notify.send(home, cfg, args.message, title=args.title, sender=agent,
                          incident_id=os.environ.get("VISUMWAY_INCIDENT_ID"))
    print(json.dumps(results))
    return 0 if any(r["ok"] for r in results) else 1


def _capture(home: Home, args) -> int:
    if args.list and (args.path or args.max_edge is not None):
        print("Use --list without an output path or size.", file=sys.stderr)
        return 2
    shot = (visual.targets(home) if args.list else
            visual.capture(args.path, target=args.target, max_edge=args.max_edge, home=home))
    print(json.dumps(shot))
    return 0 if shot["ok"] else 1


def _mcp(home: Home, args) -> int:
    from . import mcp_server
    home.ensure()
    return mcp_server.serve(home, agent=args.agent)


def _verify(home: Home, args) -> int:
    if args.send_test_notification and not _require_notification_owner(config_mod.load(home), args.agent):
        return 2
    checks = verify_mod.run_checks(home, send_test_notification=args.send_test_notification)
    print(json.dumps(checks, indent=2) if args.json else verify_mod.render(checks))
    return 1 if any(c["status"] == verify_mod.FAIL for c in checks) else 0


def _require_notification_owner(cfg: dict, agent: "str | None") -> bool:
    if config_mod.is_notification_owner(cfg, agent):
        return True
    print("This command requires the agent that set up notifications.", file=sys.stderr)
    return False


def _service(home: Home, args) -> int:
    if args.action == "show":
        spec = service.describe(home)
        for path, content in spec["files"].items():
            print("# %s\n%s" % (path, content))
        for argv in spec["commands"]:
            print("$ " + " ".join(argv))
        return 0
    log = service.install(home.ensure(), enable=not args.no_enable)
    print("\n".join(log))
    return 1 if any(l.startswith("FAILED") for l in log) else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="visumway", description="Give your AI a body. Keep its brain on demand.")
    p.add_argument("--version", action="version", version="visumway " + __version__)
    p.add_argument("--home", help="install directory (default ~/.visumway or $VISUMWAY_HOME)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="scan this computer, write config, blueprint and the setup plan").set_defaults(fn=_init)

    s = sub.add_parser("setup", help="install everything: identity, click handler, start-at-login runtime, event bridges")
    s.add_argument("--agent", metavar="NAME", help="reserve optional notifications for the installing agent")
    s.add_argument("--windows-background", action="store_true",
                   help="use signed-in CLI wakes and independent Windows toasts instead of a loaded ChatGPT chat")
    s.add_argument("--no-service", action="store_true")
    s.add_argument("--no-bridges", action="store_true")
    s.set_defaults(fn=_setup)

    s = sub.add_parser("uninstall", help="remove the service, bridges and registrations")
    s.add_argument("--no-bridges", action="store_true", help="skip removal of native event bridges")
    s.add_argument("--purge", action="store_true", help="also delete the VisumWay home directory")
    s.add_argument("--no-service", action="store_true", help="leave the start-at-login service alone")
    s.set_defaults(fn=_uninstall)

    s = sub.add_parser("agent", help="list or probe agent adapters")
    s.add_argument("action", choices=["list", "probe"])
    s.add_argument("name", nargs="?")
    s.set_defaults(fn=_agent)

    s = sub.add_parser("wakes", help="preview the event report or enable or pause automatic model wakes")
    s.add_argument("action", choices=["preview", "enable", "pause"])
    s.add_argument("--agent", metavar="NAME", help="the installing agent for enable or pause")
    s.set_defaults(fn=_wakes)

    s = sub.add_parser("incidents", help="recent wakes and what was said")
    s.add_argument("-n", type=int, default=20)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=_incidents)

    s = sub.add_parser("open", help="open the agent with an incident's context (what a notification click runs)")
    s.add_argument("target", help="incident id or visumway:// link")
    s.add_argument("--action", choices=["open", "investigate", "later"])
    s.set_defaults(fn=_open)

    s = sub.add_parser("notify-wait")  # internal: Linux notification click helper
    s.add_argument("incident")
    s.add_argument("title")
    s.add_argument("message")
    s.set_defaults(fn=_notify_wait)

    s = sub.add_parser("bridge", help="host bridges: list, install, remove, run")
    s.add_argument("action", choices=["list", "install", "remove", "run"])
    s.add_argument("name", nargs="?")
    s.add_argument("source", nargs="?", help="local .exe for install windows-visual")
    s.add_argument("--sha256", help="trusted SHA-256 of the Windows visual helper")
    s.set_defaults(fn=_bridge)

    s = sub.add_parser("crashtest", help="crash a test process to exercise automatic alerts")
    s.add_argument("--agent", metavar="NAME", help="the installing agent")
    s.set_defaults(fn=_crashtest)
    sub.add_parser("discover", help="print the host blueprint as JSON").set_defaults(fn=_discover)
    s = sub.add_parser("plan", help="print the installation plan")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=_plan)

    s = sub.add_parser("run", help="run the reflex runtime (normally started by the service)")
    s.add_argument("--interval", type=float, default=1.0)
    s.set_defaults(fn=_run)

    s = sub.add_parser("emit", help="send an event to the runtime (what bridges call)")
    s.add_argument("type", help="e.g. app.crash, gpu.error")
    s.add_argument("--subject", default="", help="what it is about, e.g. Game.exe")
    s.add_argument("--severity", default="info", choices=["info", "warning", "error", "critical"])
    s.add_argument("--source", default="cli")
    s.add_argument("--data", action="append", metavar="KEY=VALUE")
    s.add_argument("--json", help="event data as a JSON object")
    s.set_defaults(fn=_emit)

    s = sub.add_parser("events", help="show recent event history")
    s.add_argument("-n", type=int, default=20)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=_events)

    sub.add_parser("status", help="runtime, budget and activity summary").set_defaults(fn=_status)

    s = sub.add_parser("notify", help="send the user a message through the configured channels")
    s.add_argument("message")
    s.add_argument("--title", default="")
    s.add_argument("--agent", metavar="NAME", help="the installing agent")
    s.set_defaults(fn=_notify)

    s = sub.add_parser("capture", help="list visual targets or capture one frame to a PNG")
    s.add_argument("path", nargs="?")
    mode = s.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="list capture selectors without capturing a frame")
    mode.add_argument("--target", default="desktop", help="desktop or a selector from capture --list")
    s.add_argument("--max-edge", type=int, help="bound the PNG's longest edge in pixels (Windows)")
    s.set_defaults(fn=_capture)

    s = sub.add_parser("mcp", help="serve the shared agent tool interface (MCP over stdio)")
    s.add_argument("--agent", metavar="NAME", help="label this host for notification access")
    s.set_defaults(fn=_mcp)

    s = sub.add_parser("verify", help="test the installed connections end to end")
    s.add_argument("--json", action="store_true")
    s.add_argument("--send-test-notification", action="store_true")
    s.add_argument("--agent", metavar="NAME", help="the installing agent for sending a test notification")
    s.set_defaults(fn=_verify)

    s = sub.add_parser("service", help="make the runtime start at login")
    s.add_argument("action", choices=["show", "install"])
    s.add_argument("--no-enable", action="store_true", help="write files but do not start the service")
    s.set_defaults(fn=_service)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(Home(args.home), args)
    except config_mod.ConfigError as e:
        print("visumway: %s" % e, file=sys.stderr)
        return 2
    except OSError as e:
        print("visumway: %s" % e, file=sys.stderr)
        return 1
