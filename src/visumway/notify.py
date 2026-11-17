"""Outbound communication bridge: how the AI (not the bridge) reaches the user.

The runtime never writes conversational messages on the model's behalf. The
only messages VisumWay itself sends are labelled system notices (for example,
"a wake failed").
"""
from __future__ import annotations

import json
import time
import urllib.request

from . import incidents
from .bridges import desktop
from .paths import Home

MAX_MESSAGE = 4000


def _post(url: str, body: bytes, headers: dict, timeout: float = 10.0) -> int:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


def send(home: Home, cfg: dict, message: str, title: str = "", sender: str = "agent",
         incident_id: "str | None" = None) -> list:
    """Deliver to every configured channel. Returns one result dict per channel.

    With an incident_id the desktop notification becomes clickable: it opens
    the agent's interface with that incident's context.
    """
    message = str(message)[:MAX_MESSAGE]
    title = str(title or "")[:120]
    if incident_id and not incidents.ID_RE.match(str(incident_id)):
        incident_id = None
    if incident_id and sender != "visumway-system":
        incidents.update(home, incident_id, message=message)
    results = []
    for ch in cfg.get("notify", {}).get("channels", [{"type": "file"}]):
        kind = ch.get("type")
        res = {"channel": kind, "ok": False}
        try:
            if kind == "file":
                home.outbox.parent.mkdir(parents=True, exist_ok=True)
                with open(home.outbox, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": time.time(), "sender": sender, "title": title,
                                        "message": message, "incident_id": incident_id}) + "\n")
                res["ok"] = True
            elif kind == "desktop":
                res.update(desktop.show(home, cfg, title or cfg.get("agent", {}).get("identity", ""),
                                        message, incident_id))
            elif kind == "ntfy":
                headers = {"Content-Type": "text/plain; charset=utf-8"}
                if title:
                    # HTTP headers must be latin-1 safe.
                    headers["Title"] = title.encode("ascii", "replace").decode("ascii")
                if ch.get("token"):
                    headers["Authorization"] = "Bearer %s" % ch["token"]
                res["status"] = _post(ch["url"], message.encode("utf-8"), headers)
                res["ok"] = 200 <= res["status"] < 300
            elif kind == "webhook":
                body = json.dumps({"title": title, "message": message, "sender": sender,
                                   "text": message}).encode("utf-8")
                res["status"] = _post(ch["url"], body, {"Content-Type": "application/json"})
                res["ok"] = 200 <= res["status"] < 300
            else:
                res["error"] = "unknown channel type"
        except Exception as e:  # network failures must never crash the runtime
            res["error"] = "%s: %s" % (type(e).__name__, e)
        results.append(res)
    if incident_id and sender != "visumway-system" and any(r["ok"] for r in results):
        inc = incidents.get(home, incident_id)
        if inc and inc.get("status") not in ("opened", "snoozed"):
            incidents.update(home, incident_id, status="notified", notified_at=time.time())
    return results
