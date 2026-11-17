"""macOS per-user DiagnosticReports bridge (no LLM, no external dependencies).

Launchd watches the user's diagnostic reports directory.  Each activation
scans a bounded set of new .ips/.crash/.hang reports and writes compact events
into the existing inbox.  No persistent observer is needed between changes.

The host must validate this bridge on a real Mac; sandbox tests exercise the
parser, deduplication and generated launchd job, not macOS behavior.
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import sys
import time
from pathlib import Path

from ..events import Event, write_event
from ..paths import Home
from ..proc import run_full

LABEL = "com.visumway.diagnosticreports"
SUFFIXES = {".ips", ".crash", ".hang"}
MAX_FILES = 500
MAX_READ = 256 * 1024


def reports_dir() -> Path:
    return Path.home() / "Library" / "Logs" / "DiagnosticReports"


def job_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / (LABEL + ".plist")


def describe(home: Home, directory: "Path | None" = None) -> dict:
    directory = directory or reports_dir()
    job = {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "visumway", "--home", str(home.root),
                             "bridge", "run", "macos-reports"],
        "RunAtLoad": True,
        "WatchPaths": [str(directory)],
        "ProcessType": "Background",
    }
    return {"path": job_path(), "content": plistlib.dumps(job), "directory": directory}


def _title(path: Path, text: str) -> str:
    # Modern .ips reports frequently have a JSON metadata line, followed by
    # a separate JSON payload.  Older .crash reports are line-oriented.
    for line in text.splitlines()[:12]:
        if line.lstrip().startswith("{"):
            try:
                obj = json.loads(line)
                for key in ("procName", "app_name", "name"):
                    if isinstance(obj.get(key), str):
                        return obj[key][:200]
            except (ValueError, TypeError):
                pass
        m = re.match(r"^(?:Process|Command):\s*(.{1,200})$", line)
        if m:
            return m.group(1).split(" [", 1)[0].strip()[:200]
    return path.name[:200]


def report_event(path: Path, root: Path, stamp: float) -> "Event | None":
    if path.suffix.lower() not in SUFFIXES or path.is_symlink():
        return None
    try:
        # Resolve before reading to avoid files pointing out of the monitored dir.
        if path.resolve().parent != root.resolve():
            return None
        with path.open("rb") as f:
            text = f.read(MAX_READ).decode("utf-8", "replace")
    except OSError:
        return None
    is_hang = path.suffix.lower() == ".hang" or "spindump" in path.name.lower()
    return Event(type="app.hang" if is_hang else "app.crash", source="macos-reports",
                 severity="error", subject=_title(path, text),
                 data={"report_name": path.name[:200]}, ts=stamp)


def collect(home: Home, directory: "Path | None" = None) -> list:
    """Baseline on first run; afterward emit only new or modified reports."""
    directory = directory or reports_dir()
    state_path = home.state / "macos-reports.json"
    try:
        old = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    current = {}
    candidates = []
    if directory.is_dir():
        try:
            entries = sorted((p for p in directory.iterdir()
                              if p.suffix.lower() in SUFFIXES and p.is_file() and not p.is_symlink()),
                             key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_FILES]
        except OSError:
            entries = []
        for path in entries:
            try:
                st = path.stat()
            except OSError:
                continue
            key = path.name
            fingerprint = [st.st_mtime_ns, st.st_size]
            current[key] = fingerprint
            if isinstance(old, dict) and old.get(key) != fingerprint:
                candidates.append((path, st.st_mtime))
    emitted = []
    for path, stamp in reversed(candidates):
        ev = report_event(path, directory, stamp)
        if ev:
            write_event(home, ev)
            emitted.append(ev)
    home.state.mkdir(parents=True, exist_ok=True)
    temp = state_path.with_suffix(".tmp")
    temp.write_text(json.dumps(current, sort_keys=True), encoding="utf-8")
    os.replace(temp, state_path)
    return emitted


def supported() -> bool:
    return sys.platform == "darwin"


def installed(home: Home) -> "bool | None":
    if not supported():
        return None
    try:
        spec = describe(home)
        return spec["path"].read_bytes() == spec["content"]
    except OSError:
        return False


def install(home: Home) -> list:
    if not supported():
        return ["macos-reports: not applicable on this OS"]
    spec = describe(home)
    spec["directory"].mkdir(parents=True, exist_ok=True)
    collect(home)  # baseline: don't notify about crashes from before install
    spec["path"].parent.mkdir(parents=True, exist_ok=True)
    spec["path"].write_bytes(spec["content"])
    res = run_full(["launchctl", "load", "-w", str(spec["path"])], timeout=30)
    return (["ok: launchd DiagnosticReports bridge"] if res["rc"] == 0 else
            ["FAILED: launchd DiagnosticReports bridge: " + res["stderr"][:300]])


def remove(home: Home) -> list:
    if not supported():
        return []
    path = job_path()
    run_full(["launchctl", "unload", "-w", str(path)], timeout=30)
    try:
        path.unlink()
    except OSError:
        pass
    return ["removed macOS DiagnosticReports launchd bridge"]
