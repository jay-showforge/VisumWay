"""The reflex engine: decides, locally and with zero model tokens, what happens
to each event: ignore it, log it, or wake the AI.

Wake-worthy events are aggregated (15 crashes in a minute become one report),
rate-limited per subject by a cooldown, and capped by an inference budget.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from fnmatch import fnmatchcase

from .events import Event

SELFTEST_TYPE = "visumway.selftest"
SELFTEST_AGENT = "selftest"
DAY = 86400.0
HOUR = 3600.0


@dataclass
class Decision:
    action: str  # ignore | log | wake
    reason: str


@dataclass
class Batch:
    key: str
    first: Event
    rule: dict
    deadline: float
    count: int = 1
    last_ts: float = 0.0
    samples: list = field(default_factory=list)


@dataclass
class WakeReport:
    key: str
    type: str
    subject: str
    severity: str
    count: int
    first_ts: float
    last_ts: float
    samples: list
    suppressed_since_last_wake: int = 0
    agent: "str | None" = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class ReflexEngine:
    def __init__(self, reflex_cfg: dict, wake_times=None, clock=time.time):
        self.cfg = reflex_cfg
        self.clock = clock
        self.pending: dict = {}
        self.cooldown_until: dict = {}
        self.suppressed: dict = {}
        self.wake_times: list = sorted(wake_times or [])

    def _rule_for(self, ev: Event):
        for rule in self.cfg.get("rules", []):
            if fnmatchcase(ev.type, rule["match"]) and fnmatchcase(ev.subject, rule.get("subject", "*")):
                return rule
        return None

    def ingest(self, ev: Event) -> Decision:
        now = self.clock()
        if ev.type == SELFTEST_TYPE:
            self.pending[ev.key() + "|" + ev.id] = Batch(
                key=ev.key(), first=ev, rule={"agent": SELFTEST_AGENT}, deadline=now,
                last_ts=ev.ts, samples=[ev.to_dict()])
            return Decision("wake", "selftest")

        rule = self._rule_for(ev)
        action = rule["action"] if rule else self.cfg.get("default_action", "log")
        if action != "wake":
            return Decision(action, "rule" if rule else "default")
        if not self.cfg["wakes_enabled"]:
            return Decision("log", "wakes_paused")

        key = ev.key()
        batch = self.pending.get(key)
        if batch:
            batch.count += 1
            batch.last_ts = ev.ts
            if len(batch.samples) < 3:
                batch.samples.append(ev.to_dict())
            return Decision("wake", "aggregated")
        if self.cooldown_until.get(key, 0) > now:
            self.suppressed[key] = self.suppressed.get(key, 0) + 1
            return Decision("log", "cooldown")
        self.pending[key] = Batch(
            key=key, first=ev, rule=rule or {}, last_ts=ev.ts, samples=[ev.to_dict()],
            deadline=now + float(self.cfg.get("aggregate_window_s", 5)))
        return Decision("wake", "queued")

    def budget_remaining(self) -> dict:
        now = self.clock()
        self.wake_times = [t for t in self.wake_times if t > now - DAY]
        b = self.cfg.get("budget", {})
        hour_used = sum(1 for t in self.wake_times if t > now - HOUR)
        return {
            "hour": max(0, int(b.get("max_wakes_per_hour", 4)) - hour_used),
            "day": max(0, int(b.get("max_wakes_per_day", 20)) - len(self.wake_times)),
        }

    def due(self) -> list:
        """Return [(WakeReport, blocked_reason_or_None)] for batches ready to send."""
        now = self.clock()
        out = []
        for pkey in [k for k, b in self.pending.items() if b.deadline <= now]:
            b = self.pending.pop(pkey)
            report = WakeReport(
                key=b.key, type=b.first.type, subject=b.first.subject,
                severity=max((s.get("severity", "info") for s in b.samples),
                             key=("info", "warning", "error", "critical").index),
                count=b.count, first_ts=b.first.ts, last_ts=b.last_ts, samples=b.samples,
                agent=SELFTEST_AGENT if b.first.type == SELFTEST_TYPE else None)
            if b.first.type == SELFTEST_TYPE:
                out.append((report, None))
                continue
            cooldown = float(b.rule.get("cooldown_s", self.cfg.get("default_cooldown_s", 300)))
            self.cooldown_until[b.key] = now + cooldown
            remaining = self.budget_remaining()
            if remaining["hour"] <= 0 or remaining["day"] <= 0:
                out.append((report, "budget_exhausted"))
                continue
            self.wake_times.append(now)
            report.suppressed_since_last_wake = self.suppressed.pop(b.key, 0)
            out.append((report, None))
        return out
