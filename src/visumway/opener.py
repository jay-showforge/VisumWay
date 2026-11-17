"""What happens when the user clicks a notification.

The click delivers a visumway:// URL. Anything on the machine (including a web
page) can try to open such a URL, so the URL is allowed to carry exactly two
things: one of three fixed action names and an incident id. Everything else,
including all text that reaches a command line, comes from local state.
"""
from __future__ import annotations

import re
import time

from . import agents, incidents, terminal
from .paths import Home

URL_RE = re.compile(r"^visumway://(open|investigate|later)/([0-9a-f]{12})/?$")
ACTIONS = ("open", "investigate", "later")

# Fixed text only: these strings are placed on a command line.
INVESTIGATE_PROMPT = ("I clicked Investigate on your notification. Look into this incident now and "
                      "tell me what you find. Ask before changing anything.")
CONTEXT_PROMPT = "Read the VisumWay incident report at {incident_file} and help me with it."
CONTEXT_INVESTIGATE = ("Read the VisumWay incident report at {incident_file}, investigate it, and "
                       "tell me what you find. Ask before changing anything.")


def parse(target: str, action: "str | None" = None) -> "tuple":
    """Return (action, incident_id) or raise ValueError."""
    target = str(target).strip()
    m = URL_RE.match(target)
    if m:
        return m.group(1), m.group(2)
    if incidents.ID_RE.match(target):
        action = action or "open"
        if action not in ACTIONS:
            raise ValueError("unknown action")
        return action, target
    raise ValueError("not a VisumWay incident link")


def handle(home: Home, cfg: dict, target: str, action: "str | None" = None,
           launcher=terminal.launch) -> dict:
    try:
        action, incident_id = parse(target, action)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    inc = incidents.get(home, incident_id)
    if inc is None:
        return {"ok": False, "error": "unknown incident"}

    if action == "later":
        minutes = float(cfg.get("reflex", {}).get("snooze_minutes", 30))
        incidents.update(home, incident_id, status="snoozed", snooze_until=time.time() + minutes * 60)
        return {"ok": True, "action": "later", "snoozed_minutes": minutes}

    agent_cfg = cfg.get("agent", {})
    name = inc.get("agent")
    adapter = agent_cfg.get("adapters", {}).get(name)
    if adapter is None:
        return {"ok": False, "error": "the original incident adapter '%s' is unavailable" % name}
    session = inc.get("session_id")
    if session and not incidents.SESSION_RE.fullmatch(str(session)):
        session = None
    surface = agents.open_app(cfg, name, session) if action == "open" and session else None
    if surface:
        incidents.update(home, incident_id, status="opened", opened_at=time.time(), opened_surface=surface)
        return {"ok": True, "action": action, "resumed": True, "surface": surface}
    incident_file = str(home.incidents / (incident_id + ".json"))

    resumed = bool(session and adapter.get("open_argv"))
    if resumed:
        template = adapter.get("investigate_argv") if action == "investigate" and adapter.get("investigate_argv") \
            else adapter["open_argv"]
    else:
        template = adapter.get("fresh_argv")
        if not template:
            return {"ok": False, "error": "agent '%s' has no interactive command configured" % inc.get("agent")}
    context = (CONTEXT_INVESTIGATE if action == "investigate" else CONTEXT_PROMPT).format(
        incident_file=incident_file)
    subs = {"{session_id}": session or "", "{investigate_prompt}": INVESTIGATE_PROMPT,
            "{context_prompt}": context, "{incident_file}": incident_file}
    argv = [subs.get(part, part) for part in template]

    res = launcher(argv, inc.get("cwd") or str(home.workspace), cfg)
    if res.get("ok"):
        incidents.update(home, incident_id, status="opened", opened_at=time.time(), opened_surface="terminal")
    return dict(res, action=action, resumed=resumed, argv=argv)
