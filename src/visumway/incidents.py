"""Incidents: the memory that links one wake to its notification and its follow-up.

Each wake that reaches a model creates one incident. The notification carries
only the incident id; clicking it looks the incident up locally. That is what
lets a click reopen the agent "with the context preserved" without any model
staying awake in between.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid

from .paths import Home

ID_RE = re.compile(r"^[0-9a-f]{12}$")
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
STATUSES = ("new", "queued", "notified", "quiet", "failed", "snoozed", "opened")


def _path(home: Home, incident_id: str):
    if not ID_RE.match(str(incident_id)):
        raise ValueError("bad incident id")
    return home.incidents / (incident_id + ".json")


def create(home: Home, report: dict, agent: str) -> dict:
    home.incidents.mkdir(parents=True, exist_ok=True)
    inc = {"id": uuid.uuid4().hex[:12], "created": time.time(), "status": "new", "agent": agent,
           "report": report, "message": None, "session_id": None, "snooze_until": None,
           "cwd": str(home.workspace)}
    _write(home, inc)
    return inc


def _write(home: Home, inc: dict) -> None:
    path = _path(home, inc["id"])
    fd, tmp = tempfile.mkstemp(prefix=path.stem + "-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(inc, f, indent=2, default=str)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def get(home: Home, incident_id: str) -> "dict | None":
    try:
        with open(_path(home, incident_id), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def update(home: Home, incident_id: str, **fields) -> "dict | None":
    inc = get(home, incident_id)
    if inc is None:
        return None
    if "session_id" in fields and fields["session_id"] is not None:
        # The session id ends up on a command line; accept only a plain token.
        if not SESSION_RE.fullmatch(str(fields["session_id"])):
            fields["session_id"] = None
    inc.update(fields)
    inc["updated"] = time.time()
    _write(home, inc)
    return inc


def recent(home: Home, n: int = 20) -> list:
    try:
        names = [x for x in os.listdir(home.incidents) if x.endswith(".json")]
    except OSError:
        return []
    out = []
    for name in names:
        inc = get(home, name[:-5]) if ID_RE.match(name[:-5]) else None
        if inc:
            out.append(inc)
    out.sort(key=lambda i: i.get("created", 0))
    return out[-n:] if n else out


def summary(inc: dict) -> dict:
    r = inc.get("report", {})
    return {"id": inc["id"], "status": inc.get("status"), "agent": inc.get("agent"),
            "event": r.get("type"), "subject": r.get("subject"), "count": r.get("count"),
            "created": inc.get("created"), "message": inc.get("message"),
            "resumable": bool(inc.get("session_id"))}
