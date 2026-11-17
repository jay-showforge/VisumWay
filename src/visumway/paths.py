"""Where VisumWay keeps its installed state on a host.

Everything lives under one directory (default ~/.visumway, override with the
VISUMWAY_HOME environment variable) so the install is easy to inspect,
back up, and remove.
"""
from __future__ import annotations

import os
from pathlib import Path


class Home:
    def __init__(self, root: "str | os.PathLike | None" = None):
        if root is None:
            root = os.environ.get("VISUMWAY_HOME") or (Path.home() / ".visumway")
        self.root = Path(root).expanduser().resolve()
        self.config = self.root / "config.json"
        self.blueprint = self.root / "blueprint.json"
        self.plan = self.root / "PLAN.md"
        self.inbox = self.root / "inbox"
        self.rejected = self.inbox / "rejected"
        self.state = self.root / "state"
        self.events = self.state / "events.jsonl"
        self.heartbeat = self.state / "daemon.json"
        self.budget = self.state / "budget.json"
        self.selftest = self.state / "selftest.marker"
        self.wakes = self.root / "logs" / "wakes"
        self.outbox = self.root / "outbox" / "messages.jsonl"
        self.incidents = self.state / "incidents"
        self.agents = self.state / "agents.json"
        self.workspace = self.root / "workspace"  # cwd for woken agents; sessions resume from here
        self.bridges = self.root / "bridges"

    def ensure(self) -> "Home":
        for d in (self.root, self.inbox, self.rejected, self.state, self.wakes, self.outbox.parent,
                  self.incidents, self.workspace, self.bridges):
            d.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            # Event history and diagnostics can be sensitive: owner-only.
            try:
                os.chmod(self.root, 0o700)
            except OSError:
                pass
        return self
