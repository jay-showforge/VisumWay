"""The reflex runtime: the small always-on process that is NOT an LLM.

Each tick it polls enabled sources, drains the inbox, applies reflex rules,
and hands due wake reports to a worker thread. While nothing matches a wake
rule it makes no model call of any kind.
"""
from __future__ import annotations

import json
import math
import os
import queue
import tempfile
import threading
import time

from . import config as config_mod
from . import incidents, notify, sources, wake
from .events import EventLog, drain_inbox
from .filelock import LockBusy, exclusive
from .paths import Home
from .policy import SELFTEST_TYPE, ReflexEngine

HEARTBEAT_EVERY = 10.0
ALIVE_WITHIN = 30.0
SNOOZE_CHECK_EVERY = 30.0


def read_heartbeat(home: Home) -> dict:
    try:
        return json.loads(home.heartbeat.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def daemon_alive(home: Home) -> bool:
    hb = read_heartbeat(home)
    return bool(hb) and not hb.get("stopped") and time.time() - hb.get("last_tick", 0) < ALIVE_WITHIN


class Daemon:
    def __init__(self, home: Home, cfg: "dict | None" = None, clock=time.time, runner=wake.run_wake):
        self.home = home.ensure()
        self.cfg = config_mod.load(home) if cfg is None else cfg
        self._live_config = cfg is None
        self._config_stamp = None
        self._config_ok = True
        self.clock = clock
        self.runner = runner
        self.log = EventLog(home)
        budget = self._load_budget()
        self.budget_readable = budget is not None
        self.engine = ReflexEngine(self.cfg["reflex"], wake_times=budget, clock=clock)
        self.sources = sources.build(self.cfg.get("sources", {}))
        self.started = time.time()
        self._last_hb = 0.0
        self._next_snooze = 0.0
        self._q: "queue.Queue" = queue.Queue()
        self._worker = threading.Thread(target=self._work, name="visumway-wake", daemon=True)
        self._worker.start()

    def _load_budget(self) -> "list | None":
        try:
            values = json.loads(self.home.budget.read_text(encoding="utf-8"))
            if isinstance(values, list) and all(type(t) in (float, int) and math.isfinite(t) for t in values):
                return values
            return None
        except FileNotFoundError:
            return []
        except (OSError, ValueError, TypeError, OverflowError):
            return None

    def _save_budget(self) -> bool:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.home.state,
                                             prefix="budget-", suffix=".tmp", delete=False) as file:
                temporary = file.name
                json.dump(self.engine.wake_times, file)
            os.replace(temporary, self.home.budget)
            temporary = None
        except OSError:
            return False
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
        return True

    def _work(self) -> None:
        while True:
            item = self._q.get()
            try:
                if item is None:
                    return
                config_at_queue, report = item
                if report.type != SELFTEST_TYPE and self._live_config:
                    try:
                        current = config_mod.load(self.home)
                    except (OSError, ValueError, TypeError, AttributeError):
                        current = None
                    if current != config_at_queue:
                        self.log.append({"kind": "wake_blocked", "reason": "config_changed",
                                         "report": report.to_dict()})
                        continue
                try:
                    result = self.runner(self.home, config_at_queue, report)
                except Exception as e:  # never let a wake failure kill the worker
                    result = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
                result.pop("stdout_tail", None)
                result.pop("stderr_tail", None)
                self.log.append(dict(result, kind="wake"))
            finally:
                self._q.task_done()

    def _reload_config(self) -> bool:
        if not self._live_config:
            return False
        try:
            info = self.home.config.stat()
            stamp = (info.st_mtime_ns, info.st_size, info.st_ino)
        except FileNotFoundError:
            stamp = ()
        except OSError:
            return self._apply_config(None)
        if stamp == self._config_stamp:
            return False
        try:
            current = config_mod.load(self.home)
        except (OSError, ValueError, TypeError, AttributeError):
            return self._apply_config(None)
        self._config_stamp = stamp
        return self._apply_config(current)

    def _apply_config(self, current: "dict | None") -> bool:
        valid = current is not None
        if self._config_ok == valid and (not valid or current == self.cfg):
            return False
        self._config_ok = valid
        self.engine.pending.clear()
        if valid:
            if current["sources"] != self.cfg["sources"]:
                self.sources = sources.build(current["sources"])
            self.cfg = current
        self.engine.cfg = dict(self.cfg["reflex"], wakes_enabled=self._wakes_enabled())
        return True

    def _wakes_enabled(self) -> bool:
        return self._config_ok and self.cfg["reflex"]["wakes_enabled"]

    def tick(self) -> int:
        """Process everything currently pending. Returns the number of events seen."""
        config_changed = self._reload_config()
        now = self.clock()
        if not self.budget_readable:
            budget = self._load_budget()
            if budget is not None:
                self.engine.wake_times = sorted(budget)
                self.budget_readable = True
        events = []
        for src in self.sources:
            events.extend(src.maybe_poll(now))
        events.extend(drain_inbox(self.home))
        for ev in events:
            decision = self.engine.ingest(ev)
            if decision.action != "ignore":
                self.log.append({"kind": "event", "event": ev.to_dict(),
                                 "action": decision.action, "reason": decision.reason})
        for report, blocked in self.engine.due():
            if not blocked and report.type != SELFTEST_TYPE:
                if not self.budget_readable:
                    blocked = "budget_unreadable"
                elif not self._save_budget():
                    blocked = "budget_write_failed"
            if blocked:
                self.log.append({"kind": "wake_blocked", "reason": blocked, "report": report.to_dict()})
            else:
                self._q.put((self.cfg, report))
        if self._config_ok and now >= self._next_snooze:
            self._next_snooze = now + SNOOZE_CHECK_EVERY
            self.redeliver_snoozed(now)
        if config_changed or time.time() - self._last_hb >= HEARTBEAT_EVERY:
            self.heartbeat()
        return len(events)

    def redeliver_snoozed(self, now: float) -> int:
        """"Later" was clicked and the time is up: show the same message again.
        The stored text is reused, so this costs no model tokens."""
        sent = 0
        for inc in incidents.recent(self.home, 200):
            if inc.get("status") == "snoozed" and (inc.get("snooze_until") or 0) <= now and inc.get("message"):
                incidents.update(self.home, inc["id"], status="new", snooze_until=None)
                notify.send(self.home, self.cfg, inc["message"],
                            title=self.cfg.get("agent", {}).get("identity", ""),
                            sender=inc.get("agent") or "agent", incident_id=inc["id"])
                self.log.append({"kind": "redelivered", "incident_id": inc["id"]})
                sent += 1
        return sent

    def heartbeat(self, stopped: bool = False) -> None:
        self._last_hb = time.time()
        try:
            self.home.heartbeat.write_text(json.dumps({
                "pid": os.getpid(), "started": self.started, "last_tick": self._last_hb,
                "stopped": stopped,
                "notification_agent": (self.cfg["agent"]["default"]
                                       if self._config_ok and self.cfg["agent"].get("bound", True) else None),
                "automatic_wakes_enabled": self._wakes_enabled(),
                "budget_remaining": self.engine.budget_remaining() if self.budget_readable else {"hour": 0, "day": 0},
            }), encoding="utf-8")
        except OSError:
            pass

    def wait_idle(self, timeout: float = 30.0) -> None:
        """Block until queued wakes have finished (used by tests and verify)."""
        end = time.time() + timeout
        while self._q.unfinished_tasks and time.time() < end:
            time.sleep(0.02)

    def stop(self) -> None:
        self._q.put(None)
        self._worker.join(timeout=5)
        self.heartbeat(stopped=True)

    def run_forever(self, interval: float = 1.0) -> int:
        try:
            with exclusive(self.home.state / "listener.lock", blocking=False):
                return self._run_locked(interval)
        except LockBusy:
            print("visumway: a reflex runtime is already running")
            return 1

    def _run_locked(self, interval: float) -> int:
        # The OS lock is released on exit. A recent heartbeat may belong to
        # the listener that systemd or Task Scheduler just replaced.
        self.heartbeat()
        try:
            while True:
                self.tick()
                time.sleep(interval)
        except KeyboardInterrupt:
            return 0
        finally:
            self.stop()
