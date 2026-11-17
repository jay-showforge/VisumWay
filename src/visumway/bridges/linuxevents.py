"""Linux journal crash hints using a systemd --user timer.

This bridge is deliberately best-effort: system-wide systemd-coredump records
may not be visible to an unprivileged user.  Never imply that its presence
proves comprehensive crash detection.  The timer is dormant between checks;
no model call is made while it runs.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from ..events import Event, write_event
from ..paths import Home
from ..proc import run_full

SERVICE = "visumway-linux-events.service"
TIMER = "visumway-linux-events.timer"
COREDUMP_ID = "fc2e22bc6ee647b6b90729ab34a250b1"


def describe(home: Home) -> dict:
    root = Path.home() / ".config" / "systemd" / "user"
    # systemd-unit quoting: escapes whitespace and literal shell-special chars
    # in ExecStart, which is NOT a shell invocation.
    import shlex
    command = " ".join(shlex.quote(a) for a in
                       [sys.executable, "-m", "visumway", "--home", str(home.root),
                        "bridge", "run", "linux-journal"])
    unit = """[Unit]
Description=VisumWay Linux journal crash collector (no AI inference)

[Service]
Type=oneshot
ExecStart=%s
""" % command
    timer = """[Unit]
Description=VisumWay journal scan while user is signed in

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
AccuracySec=15s
Unit=%s

[Install]
WantedBy=timers.target
""" % SERVICE
    return {root / SERVICE: unit, root / TIMER: timer}


def parse_records(text: str) -> list:
    """Find clear crash records; don't treat arbitrary errors as crashes."""
    out = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(item, dict):
            continue
        msg = item.get("MESSAGE", "")
        if not isinstance(msg, str):
            continue
        is_coredump = str(item.get("MESSAGE_ID", "")).lower() == COREDUMP_ID
        is_dumped = bool(re.search(r"\bcode=dumped\b", msg, re.I))
        if not (is_coredump or is_dumped):
            continue
        subject = (item.get("COREDUMP_COMM") or item.get("_COMM") or
                   item.get("SYSLOG_IDENTIFIER") or "unknown")
        if not isinstance(subject, str):
            subject = "unknown"
        micros = item.get("__REALTIME_TIMESTAMP", "0")
        try:
            stamp = int(micros) / 1_000_000
        except (ValueError, TypeError):
            stamp = 0.0
        out.append((item.get("__CURSOR", ""), Event(
            type="app.crash", source="linux-journal", severity="error", subject=subject[:200],
            data={"journal_message": msg[:300]}, ts=stamp or time.time())))
    return out


def collect(home: Home, runner=run_full) -> list:
    state_file = home.state / "linux-journal.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        state = {}
    cursor = state.get("cursor")
    # Using --user is deliberately permission-free. This won't see protected
    # system-wide crashes; the capability plan must disclose that limitation.
    cmd = ["journalctl", "--user", "--no-pager", "-o", "json", "-n", "200"]
    if cursor:
        cmd += ["--after-cursor", cursor]
    res = runner(cmd, timeout=30)
    if res.get("rc") != 0:
        return []
    # Every returned entry contributes to the cursor, including non-crashes.
    seen = []
    for line in res.get("stdout", "").splitlines():
        try:
            entry = json.loads(line)
            if isinstance(entry, dict) and isinstance(entry.get("__CURSOR"), str):
                seen.append(entry["__CURSOR"])
        except (TypeError, ValueError):
            pass
    emitted = []
    if cursor is not None:  # on first run baseline, don't replay older entries
        for _, ev in parse_records(res.get("stdout", "")):
            write_event(home, ev)
            emitted.append(ev)
    if seen or cursor is None:
        home.state.mkdir(parents=True, exist_ok=True)
        tmp = state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"cursor": seen[-1] if seen else ""}), encoding="utf-8")
        os.replace(tmp, state_file)
    return emitted


def supported() -> bool:
    return sys.platform.startswith("linux") and bool(shutil.which("journalctl")) and bool(shutil.which("systemctl")) and Path("/run/systemd/system").exists()


def installed(home: Home) -> "bool | None":
    if not sys.platform.startswith("linux"):
        return None
    spec = describe(home)
    return all(p.is_file() and p.read_text(encoding="utf-8") == content for p, content in spec.items())


def install(home: Home) -> list:
    if not supported():
        return ["linux-journal: not applicable (requires systemd user services)"]
    collect(home)  # create a baseline
    for path, content in describe(home).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for cmd in (["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "--now", TIMER]):
        res = run_full(cmd, timeout=30)
        if res["rc"]:
            return ["FAILED: Linux journal timer: " + res["stderr"][:300]]
    return ["ok: Linux user-journal crash-hint timer installed (best-effort)"]


def remove(home: Home) -> list:
    if not sys.platform.startswith("linux"):
        return []
    run_full(["systemctl", "--user", "disable", "--now", TIMER], timeout=30)
    for path in describe(home):
        try:
            path.unlink()
        except OSError:
            pass
    run_full(["systemctl", "--user", "daemon-reload"], timeout=30)
    return ["removed Linux user-journal timer"]
