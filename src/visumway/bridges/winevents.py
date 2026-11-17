"""Windows event bridge: application crashes, hangs and display-driver resets.

Windows is the listener. A Task Scheduler task with event-log subscriptions starts
`visumway bridge run windows-events` at the moment a matching record is
written, so this bridge uses no CPU and no memory while idle. The run reads
the new records with wevtutil and drops events into the inbox.

See docs/VERIFICATION.md for the real event types exercised.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from calendar import timegm
from collections import deque
from pathlib import Path
from xml.sax.saxutils import escape

from .. import proc
from ..events import Event, write_event
from ..paths import Home
from . import wintasks

NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"
FIRST_RUN_WINDOW_S = 120

TASK = r"VisumWay\Events"
LEGACY_TASKS = (r"VisumWay\AppCrash", r"VisumWay\AppHang", r"VisumWay\GpuError")
GRAPHICS_REPORTS = "graphics_reports"
REPORT_IDS = "graphics_report_ids"
GRAPHICS_REPORT_DATA = "Data[@Name='EventName']='LiveKernelEvent' and Data[@Name='P1']='117'"
FILTERS = {
    "Application": "((Provider[@Name='Application Error'] and EventID=1000) or "
                   "(Provider[@Name='Application Hang'] and EventID=1002))",
    "System": "Provider[@Name='Display'] and EventID=4101",
    GRAPHICS_REPORTS: "Provider[@Name='Windows Error Reporting'] and EventID=1001",
}


def parse_events(xml_text: str, *, strict: bool = False) -> list:
    """Parse `wevtutil qe ... /f:xml` output (a sequence of <Event> elements)."""
    try:
        root = ET.fromstring("<root>%s</root>" % xml_text)
    except ET.ParseError as error:
        if strict:
            raise OSError("Windows Event Log returned invalid XML") from error
        return []
    out = []
    for ev in root.iter(NS + "Event"):
        system = ev.find(NS + "System")
        if system is None:
            continue
        provider = system.find(NS + "Provider")
        created = system.find(NS + "TimeCreated")
        data, named = [], {}
        for d in ev.iter(NS + "Data"):
            text = (d.text or "").strip()
            data.append(text)
            if d.get("Name"):
                named[d.get("Name")] = text
        try:
            out.append({
                "record_id": int(system.findtext(NS + "EventRecordID") or 0),
                "event_id": int(system.findtext(NS + "EventID") or 0),
                "provider": provider.get("Name") if provider is not None else "",
                "time": _parse_time(created.get("SystemTime") if created is not None else ""),
                "data": data, "named": named,
            })
        except ValueError:
            continue
    return out


def _parse_time(s: str) -> float:
    try:
        return float(timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")))
    except (ValueError, TypeError):
        return 0.0


def _field(rec: dict, name: str, index: int) -> str:
    if rec["named"].get(name):
        return rec["named"][name]
    return rec["data"][index] if len(rec["data"]) > index else ""


def _process_id(rec: dict) -> dict:
    raw = rec["named"].get("ProcessId", "")
    if not raw:
        return {}
    try:
        pid = int(raw, 16 if raw.lower().startswith("0x") else 10)
    except ValueError:
        return {}
    return {"pid": pid} if pid > 0 else {}


def to_event(rec: dict) -> "Event | None":
    provider = rec["provider"]
    try:
        if provider == "Application Error":
            return Event(type="app.crash", source="windows-events", severity="error",
                         subject=_field(rec, "AppName", 0) or "unknown",
                         data={"event_id": rec["event_id"], "exception_code": _field(rec, "ExceptionCode", 6),
                               "faulting_module": _field(rec, "ModuleName", 3),
                               "app_version": _field(rec, "AppVersion", 1),
                               "record_id": rec["record_id"], **_process_id(rec)}, ts=rec["time"] or time.time())
        if provider == "Application Hang":
            return Event(type="app.hang", source="windows-events", severity="error",
                         subject=_field(rec, "AppName", 0) or "unknown",
                         data={"event_id": rec["event_id"], "record_id": rec["record_id"],
                               **_process_id(rec)}, ts=rec["time"] or time.time())
        if provider == "Display":
            return Event(type="gpu.error", source="windows-events", severity="error",
                         subject=(rec["data"][0] if rec["data"] else "") or "display driver",
                         data={"event_id": rec["event_id"], "record_id": rec["record_id"],
                               "meaning": "display driver stopped responding and recovered"},
                         ts=rec["time"] or time.time())
        if provider == "Windows Error Reporting" and rec["event_id"] == 1001:
            if rec["named"].get("EventName") == "LiveKernelEvent" and rec["named"].get("P1") == "117":
                return Event(type="gpu.error", source="windows-events", severity="error", subject="display driver",
                             data={"event_id": 1001, "record_id": rec["record_id"], "live_kernel_code": "0x117",
                                   "meaning": "Windows reported a display-driver timeout"},
                             ts=rec["time"] or time.time())
    except Exception:
        return None
    return None


def _selection(stream: str, after: "int | None" = None) -> tuple:
    log = "Application" if stream == GRAPHICS_REPORTS else stream
    system = FILTERS[stream]
    if after is not None:
        system += " and EventRecordID>%d" % after
    data = " and EventData[%s]" % GRAPHICS_REPORT_DATA if stream == GRAPHICS_REPORTS else ""
    return log, "*[System[%s]%s]" % (system, data)


def _report_id(rec: dict) -> str:
    try:
        return uuid.UUID(rec["named"].get("ReportId", "")).hex
    except ValueError:
        return ""


def _query(stream: str, after: int, newest_only: bool, runner) -> list:
    log, query = _selection(stream, after)
    cmd = ["wevtutil", "qe", log, "/q:" + query, "/f:xml"]
    cmd += ["/c:1", "/rd:true"] if newest_only else ["/c:512", "/rd:false"]
    result = runner(cmd, timeout=20)
    if result["rc"] != 0:
        raise OSError("Windows Event Log query failed for " + log)
    return parse_events(result["stdout"], strict=True)


def collect(home: Home, runner=proc.run_full, now=time.time, baseline: bool = False) -> list:
    """Read event-log records not yet seen and emit them. Returns the events."""
    state_path = home.state / "winevents.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        state = {}
    except ValueError as error:
        raise OSError("Windows Event Log cursor is invalid") from error
    if not isinstance(state, dict):
        raise OSError("Windows Event Log cursor is invalid")
    reports = state.pop(REPORT_IDS, [])
    if (any(type(value) is not int or value < 0 for value in state.values())
            or not isinstance(reports, list) or any(not isinstance(item, str) for item in reports)):
        raise OSError("Windows Event Log cursor is invalid")
    recent_reports = deque(reports, maxlen=64)
    emitted = []
    for log in FILTERS:
        last = state.get(log)
        if baseline and last is not None:
            continue
        if last is None:
            # First run: take only the record that triggered us, if it is fresh.
            newest = _query(log, 0, True, runner)
            recs = [] if baseline else [r for r in newest if now() - r["time"] <= FIRST_RUN_WINDOW_S]
            state[log] = max([r["record_id"] for r in newest] or [0])
            if log == GRAPHICS_REPORTS and baseline and newest:
                report_id = _report_id(newest[0])
                if report_id:
                    recent_reports.append(report_id)
        else:
            recs = _query(log, int(last), False, runner)
            state[log] = max([int(last)] + [r["record_id"] for r in recs])
        for rec in recs:
            ev = to_event(rec)
            if ev is None:
                continue
            report_id = _report_id(rec) if log == GRAPHICS_REPORTS else ""
            if report_id and report_id in recent_reports:
                continue
            write_event(home, ev)
            emitted.append(ev)
            if report_id:
                recent_reports.append(report_id)
        # Commit each channel after its successful query and inbox writes.
        home.state.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=home.state, prefix="winevents-") as directory:
            tmp = Path(directory) / "cursor.json"
            tmp.write_text(json.dumps({**state, REPORT_IDS: list(recent_reports)}), encoding="utf-8")
            tmp.replace(state_path)
    return emitted


def _pythonw() -> str:
    w = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return w if os.path.exists(w) else sys.executable


def task_definition(home: Home, sid: str) -> str:
    queries = "".join(
        '<Query Id="%d" Path="%s"><Select Path="%s">%s</Select></Query>' %
        (index, log, log, escape(selection))
        for index, (log, selection) in enumerate(map(_selection, FILTERS))
    )
    return wintasks.definition(_pythonw(), ["-m", "visumway", "--home", str(home.root),
                                           "bridge", "run", "windows-events"], sid,
                               subscription="<QueryList>" + queries + "</QueryList>")


def supported() -> bool:
    return os.name == "nt" and bool(shutil.which("schtasks")) and bool(shutil.which("wevtutil"))


def install(home: Home) -> list:
    if not supported():
        return ["windows-events: not applicable on this OS"]
    sid = wintasks.user_sid()
    if not sid:
        return ["FAILED: could not identify the current Windows user SID for the event task"]
    match = wintasks.registration_matches(TASK, home.root, ["bridge", "run", "windows-events"])
    if match is False:
        return ["FAILED: Windows event task belongs to a different installation"]
    path = home.bridges / "windows-events-task.xml"
    path.write_text(task_definition(home, sid), encoding="utf-16")
    try:
        collect(home, baseline=True)
    except OSError as error:
        return ["FAILED: %s" % error]
    argv = ["schtasks", "/Create", "/TN", TASK, "/XML", str(path)]
    res = proc.run_full(argv + (["/F"] if match else []), timeout=30)
    if res["rc"] != 0:
        return ["FAILED: scheduled task " + TASK, "  " + (res["stderr"] or res["stdout"]).strip()[:300]]
    return ["ok: scheduled task " + TASK] + _remove_tasks(home, LEGACY_TASKS)


def _remove_tasks(home: Home, names: tuple) -> list:
    log = []
    for name in names:
        match = wintasks.registration_matches(name, home.root, ["bridge", "run", "windows-events"])
        if match is False:
            log.append("FAILED: Windows event task belongs to a different installation: " + name)
        if not match:
            continue
        res = proc.run_full(["schtasks", "/Delete", "/TN", name, "/F"], timeout=30)
        log.append(("ok: removed task " if res["rc"] == 0 else "FAILED: could not remove task ") + name)
    return log


def remove(home: Home) -> list:
    if not supported():
        return []
    log = _remove_tasks(home, (TASK,) + LEGACY_TASKS)
    if not any(line.startswith("FAILED") for line in log):
        (home.bridges / "windows-events-task.xml").unlink(missing_ok=True)
    return log


def installed(home: Home) -> "bool | None":
    if not supported():
        return None
    return wintasks.registration_matches(TASK, home.root, ["bridge", "run", "windows-events"]) is True
