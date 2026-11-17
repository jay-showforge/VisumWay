"""Events, the inbox (how bridges hand events to the runtime), and the event log.

The inbox is VisumWay's universal bridge interface: any program, in any
language, becomes a bridge by atomically dropping a small JSON file into
<home>/inbox/. No sockets, no ports, no auth protocol; filesystem permissions
are the access control.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field

from .paths import Home

SEVERITIES = ("info", "warning", "error", "critical")
_TYPE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
MAX_DATA_BYTES = 8192
MAX_LOG_BYTES = 5 * 1024 * 1024


class EventError(ValueError):
    pass


@dataclass
class Event:
    type: str
    source: str = "manual"
    subject: str = ""
    severity: str = "info"
    data: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __post_init__(self):
        if not isinstance(self.type, str) or not _TYPE_RE.match(self.type):
            raise EventError("event type must match %s" % _TYPE_RE.pattern)
        if self.severity not in SEVERITIES:
            raise EventError("severity must be one of %s" % (SEVERITIES,))
        if not isinstance(self.data, dict):
            raise EventError("data must be an object")
        self.subject = str(self.subject)[:200]
        self.source = str(self.source)[:64]
        if len(json.dumps(self.data, default=str)) > MAX_DATA_BYTES:
            raise EventError("data exceeds %d bytes; store diagnostics on disk and pass a path" % MAX_DATA_BYTES)

    def key(self) -> str:
        return "%s|%s" % (self.type, self.subject)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        if not isinstance(d, dict):
            raise EventError("event must be a JSON object")
        known = {k: d[k] for k in ("type", "source", "subject", "severity", "data", "ts", "id") if k in d}
        if "type" not in known:
            raise EventError("event needs a 'type'")
        if "ts" in known:
            known["ts"] = float(known["ts"])
        if "id" in known:
            known["id"] = re.sub(r"[^A-Za-z0-9_-]", "", str(known["id"]))[:32] or uuid.uuid4().hex[:12]
        return cls(**known)


def write_event(home: Home, event: Event) -> str:
    """Atomically place an event in the inbox. Safe to call from any process."""
    home.inbox.mkdir(parents=True, exist_ok=True)
    name = "%017.6f-%s.json" % (event.ts, event.id)
    tmp = home.inbox / (name + ".tmp")
    tmp.write_text(json.dumps(event.to_dict()), encoding="utf-8")
    os.replace(tmp, home.inbox / name)
    return name


def drain_inbox(home: Home, limit: int = 500) -> list:
    """Read and remove pending events. Malformed files are quarantined."""
    try:
        names = sorted(n for n in os.listdir(home.inbox) if n.endswith(".json"))
    except FileNotFoundError:
        return []
    out = []
    for name in names[:limit]:
        path = home.inbox / name
        try:
            out.append(Event.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            path.unlink()
        except (EventError, ValueError, TypeError, OSError):
            try:
                home.rejected.mkdir(parents=True, exist_ok=True)
                os.replace(path, home.rejected / name)
            except OSError:
                pass
    return out


class EventLog:
    """Append-only JSONL history on disk. Reading it costs no model tokens."""

    def __init__(self, home: Home):
        self.path = home.events

    def append(self, record: dict) -> None:
        record.setdefault("logged_at", time.time())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.path.stat().st_size > MAX_LOG_BYTES:
                os.replace(self.path, str(self.path) + ".1")
        except OSError:
            pass
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def tail(self, n: int = 20, since: float = 0.0) -> list:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines[-max(n, 0) * 4 or None:] if since == 0.0 else lines:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("logged_at", 0) >= since:
                out.append(rec)
        return out[-n:] if n else out
