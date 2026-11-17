"""Built-in polling event sources.

Polling is the fallback. Where the operating system can deliver an event
itself (Windows Task Scheduler event triggers, systemd, launchd), prefer an
OS-triggered bridge that runs `visumway emit ...`; it costs nothing while
idle. See docs/BRIDGE_SPEC.md.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ..bridges import system
from ..events import Event


class Source:
    name = "source"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.interval = float(cfg.get("interval_s", 60))
        self._next = 0.0

    def maybe_poll(self, now: float) -> list:
        if now < self._next:
            return []
        self._next = now + self.interval
        try:
            return self.poll()
        except Exception:
            return []  # a broken sensor must not take down the runtime

    def poll(self) -> list:
        raise NotImplementedError


class ProcessWatch(Source):
    """Emits process.exited when a watched program stops running."""
    name = "process_watch"

    def __init__(self, cfg, lister=system.list_processes):
        super().__init__(cfg)
        self.lister = lister
        self.names = {n.lower() for n in cfg.get("names", [])}
        self.seen: set = set()

    def poll(self) -> list:
        running = {p["name"].lower() for p in self.lister()} & self.names
        gone = self.seen - running
        self.seen = running
        return [Event(type="process.exited", source=self.name, subject=n, severity="warning")
                for n in sorted(gone)]


class DiskSpace(Source):
    """Emits disk.low_space once when free space drops under the threshold."""
    name = "disk"

    def __init__(self, cfg, usage=shutil.disk_usage):
        super().__init__(cfg)
        self.usage = usage
        self.paths = cfg.get("paths") or [Path.home().anchor or "/"]
        self.low: set = set()

    def poll(self) -> list:
        out = []
        for p in self.paths:
            u = self.usage(p)
            pct = 100.0 * u.free / u.total if u.total else 100.0
            if pct < float(self.cfg.get("min_free_pct", 5)):
                if p not in self.low:
                    self.low.add(p)
                    out.append(Event(type="disk.low_space", source=self.name, subject=str(p),
                                     severity="critical",
                                     data={"free_pct": round(pct, 2), "free_bytes": u.free}))
            else:
                self.low.discard(p)
        return out


def build(sources_cfg: dict) -> list:
    out = []
    for cls in (ProcessWatch, DiskSpace):
        cfg = sources_cfg.get(cls.name, {})
        if cfg.get("enabled"):
            out.append(cls(cfg))
    return out
