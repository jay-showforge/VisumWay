"""Turn a host blueprint into the installation plan the coding agent executes.

Each connection gets a status:
  ready  - works now with what is on the machine
  setup  - VisumWay ships it; the agent only has to configure it
  build  - the agent must install or write a host-specific bridge, following
           docs/BRIDGE_SPEC.md
  note   - a fact about this machine the user should know; nothing to do
"""
from __future__ import annotations

from .bridges import desktop, visual


def _visual(bp: dict) -> list:
    server = bp["display"]["server"]
    backends = bp["display"]["capture_backends"]
    stream = {
        "windows-dwm": "Windows Graphics Capture (fallback: DXGI Desktop Duplication)",
        "wayland": "xdg-desktop-portal ScreenCast + PipeWire",
        "x11": "XComposite/XShm capture",
        "macos-quartz": "ScreenCaptureKit",
    }.get(server)
    rows = []
    desktop_backends = [name for name in backends if name != visual.WINDOWS_BACKEND]
    if desktop_backends:
        rows.append(("Visual: on-demand frame", "setup", "Desktop capture command detected: %s. Run `visumway verify` in the graphical session to validate capture." % desktop_backends[0]))
    elif server == "none":
        rows.append(("Visual: on-demand frame", "build", "No display session detected (headless?). Skip, or run setup inside the desktop session."))
    else:
        rows.append(("Visual: on-demand frame", "build", "Find a desktop capture backend for %s. See BRIDGE_SPEC section 4." % server))
    if server == "windows-dwm":
        if visual.WINDOWS_BACKEND in backends:
            rows.append(("Visual: a display or application window", "setup",
                         "Windows Graphics Capture helper detected. Run `visumway verify` and use `visumway capture --list` to select a target."))
        else:
            rows.append(("Visual: a display or application window", "build",
                         "Build or install the Windows visual helper using docs/WINDOWS_VISUAL.md, then run `visumway verify`."))
    elif stream:
        rows.append(("Visual: a display or application window", "build",
                     "Provide target listing and an on-demand frame using %s, following BRIDGE_SPEC section 4." % stream))
    if backends:
        rows.append(("Visual: active-task watch", "setup",
                     "Connect an MCP-capable agent to `visumway mcp`. Use watch_start, watch_frame, and watch_stop on an available capture target."))
    if server == "windows-dwm":
        rows.append(("Visual: live stream", "note",
                     "The current Windows Graphics Capture helper supports a bounded window feed. "
                     "Use watch_start with mode buffered, then watch_read. Run visumway verify to check helper support."))
    elif stream:
        rows.append(("Visual: live stream", "build", "Build the stream bridge on %s per BRIDGE_SPEC section 4." % stream))
    return rows


def _events(bp: dict) -> list:
    rows = [("OS events: disk space, watched processes", "setup", "Built in. Enable/adjust under `sources` in config.json.")]
    sm = bp["service_manager"]
    if sm == "windows-task-scheduler":
        rows.append(("OS events: app crashes, hangs, display-driver resets", "setup",
                     "Shipped. `visumway setup` (or `visumway bridge install windows-events`) creates Task Scheduler "
                     "event triggers. Windows is the listener, so idle cost is nothing. Test with `visumway crashtest`."))
    else:
        if sm == "systemd":
            rows.append(("OS events: application crashes", "setup",
                         "Install `visumway bridge install linux-journal`. Uses a systemd user timer "
                         "to inspect *accessible user-journal crash hints* once a minute; system-wide "
                         "crashes can require extra permissions and are not guaranteed."))
        elif sm == "launchd":
            rows.append(("OS events: application crashes", "setup",
                         "Install `visumway bridge install macos-reports`. A launchd WatchPaths job "
                         "notices new DiagnosticReports files after login."))
        else:
            rows.append(("OS events: application crashes", "build",
                         "No supported native event trigger detected; use process watch or write a host adapter."))
    return rows


def _hardware(bp: dict) -> list:
    gpus = bp["gpus"]
    if not gpus:
        return [("Hardware: GPU", "build", "No GPU identified. Determine the adapter and its vendor query tool.")]
    rows = []
    for g in gpus:
        if g.get("query_tool"):
            rows.append(("Hardware: %s" % g["name"], "ready", "Queried via %s (driver %s)." % (g["query_tool"], g.get("driver"))))
        else:
            rows.append(("Hardware: %s" % g["name"], "build", "Identified, but no telemetry tool found for vendor '%s'. Install the vendor CLI or write a hardware bridge." % g["vendor"]))
    return rows


SIGN_IN = {"claude": "`claude auth login`", "codex": "`codex login`"}


def _wake(cfg: dict, agents: list, apps: list) -> list:
    rows = []
    default = cfg.get("agent", {}).get("default")
    installed = [a for a in agents if a["installed"]]
    chosen = next((a for a in agents if a["name"] == default and a["installed"]), None)
    if not cfg["agent"].get("bound", True):
        owner = cfg["agent"].get("installer")
        detail = ("Optional. Notifications are reserved for '%s'. Configure its wake adapter and rerun "
                  "`visumway setup --agent NAME` when you want alerts." % owner if owner else
                  "Optional. The shared tools work without a wake adapter. The installing agent can "
                  "declare itself with `visumway setup --agent NAME` to configure alerts.")
        rows.append(("Wake-up: agent", "note", detail))
    elif not installed:
        rows.append(("Wake-up: agent", "build",
                     "No agent command found. Install one the user already has an account for "
                     "(Claude Code for a Claude account, Codex CLI for a ChatGPT account, Ollama for local models). "
                     "No API key is needed."))
    elif chosen is None:
        rows.append(("Wake-up: agent", "setup", "Reinstall the notification agent '%s' to restore alerts. "
                     "Other installed agents can use the shared tools: %s."
                     % (default, ", ".join(a["name"] for a in installed))))
    elif chosen["verified"]:
        rows.append(("Wake-up: agent", "ready", "%s: background invocation verified on this machine (%s)."
                     % (chosen["label"], chosen["version"])))
    elif chosen["signed_in"] is False:
        rows.append(("Wake-up: agent", "setup", "%s is installed but not signed in. Have the user sign in with their existing account: %s. Then `visumway agent probe`."
                     % (chosen["label"], SIGN_IN.get(chosen["name"], "its login command"))))
    else:
        state = "signed in" if chosen["signed_in"] else "sign-in state unknown"
        rows.append(("Wake-up: agent", "setup", "%s is installed (%s) but background invocation is NOT yet verified. "
                     "With the user's OK, run `visumway agent probe` (one tiny real call)." % (chosen["label"], state)))
    if default == "codex" and cfg["agent"].get("codex_app_thread"):
        rows.append(("Communication: ChatGPT app alerts", "setup",
                     "VisumWay queues into the configured Codex chat. Keep it loaded in the app and "
                     "enable turn-completion banners. Test with a real OS event."))
    for a in installed:
        if a["api_key_env_ignored"]:
            rows.append(("Wake-up: billing", "note", "%s: %s is set in the environment and removed for wakes; VisumWay must still confirm account authentication before invoking the model."
                         % (a["name"], ", ".join(a["api_key_env_ignored"]))))
    names = {a["name"] for a in installed}
    for app in apps:
        if app["sibling"] == "codex" and default == "codex" and cfg["agent"].get("codex_app_thread"):
            rows.append(("Agent app: %s" % app["label"], "note",
                         "The app processes queued turns while the configured Codex chat is loaded."))
            continue
        via = ("It is woken through %s, which uses the same sign-in." % app["sibling"]) if app["sibling"] in names \
            else ("Install %s to wake that account's model." % app["sibling"])
        rows.append(("Agent app: %s" % app["label"], "note",
                     "Detected. It has no supported way to be invoked in the background. " + via))
    return rows


def _comms(bp: dict, cfg: dict) -> list:
    if not cfg["agent"].get("bound", True):
        return [("Communication: notifications", "note", "Skipped until the installing agent has a wake adapter.")]
    kinds = [c["type"] for c in cfg.get("notify", {}).get("channels", [])]
    rows = []
    if bp["os"]["system"] == "Windows" and cfg["agent"].get("codex_app_thread"):
        rows.append(("Communication: independent Windows alerts", "setup",
                     "Use `visumway setup --agent codex --windows-background` to run the signed-in CLI and show native "
                     "notifications when the ChatGPT window is open, minimized, or closed."))
    if "desktop" in kinds:
        kind = desktop.backend()
        if bp["os"]["system"] == "Windows":
            rows.append(("Communication: desktop notification bubble", "setup",
                         "Native Windows toast under the agent's name. `visumway setup` registers the identity and the "
                         "click handler. Test with `visumway verify --send-test-notification --agent NAME`."))
        elif kind:
            rows.append(("Communication: desktop notification bubble", "ready", "Backend: %s." % kind))
        else:
            rows.append(("Communication: desktop notification bubble", "build", "No notification backend in this session (install libnotify / run inside the desktop session)."))
    remote = [k for k in kinds if k in ("ntfy", "webhook")]
    if remote:
        rows.append(("Communication: away from the computer", "ready", "Channels: %s." % ", ".join(remote)))
    else:
        rows.append(("Communication: away from the computer", "setup", "Optional. Ask whether the user wants phone push (ntfy) and add it under notify.channels."))
    return rows


def _persistence(bp: dict) -> list:
    sm = bp["service_manager"]
    if sm == "none":
        return [("Persistence: runtime survives reboot", "build", "No supported service manager. Arrange for `visumway run` to start at login.")]
    return [("Persistence: runtime survives reboot", "setup",
             "`visumway setup` configures %s to start the local runtime at user login; verify after reboot." % sm)]


def build_plan(bp: dict, cfg: dict, agents: "list | None" = None, apps: "list | None" = None) -> list:
    if agents is None:
        # Without a live inspection, fall back to what the blueprint saw on PATH.
        adapters = cfg.get("agent", {}).get("adapters", {})
        agents = [{"name": n, "label": a.get("label", n), "installed": bp["agent_runtimes"].get(a["argv"][0]),
                   "version": None, "signed_in": None, "verified": False, "api_key_env_ignored": []}
                  for n, a in adapters.items()]
    rows = []
    rows += _visual(bp)
    rows += _events(bp)
    rows += _hardware(bp)
    rows.append(("Applications: running processes", "ready", "Built in (`list_processes` tool)."))
    rows += _wake(cfg, agents, apps or [])
    rows += _comms(bp, cfg)
    rows += _persistence(bp)
    return [{"connection": c, "status": s, "action": a} for c, s, a in rows]


def render_markdown(bp: dict, rows: list) -> str:
    mem = bp.get("memory_bytes")
    gpus = ", ".join(g["name"] for g in bp["gpus"]) or "none identified"
    lines = [
        "# VisumWay Host Installation Plan",
        "",
        "Generated from a real scan of this machine by `visumway init`.",
        "",
        "| Host | |",
        "| --- | --- |",
        "| Computer | %s |" % bp["hostname"],
        "| Operating system | %s %s (%s) |" % (bp["os"]["system"], bp["os"]["release"], bp["os"]["arch"]),
        "| CPU | %s (%s logical cores) |" % (bp["cpu"]["name"], bp["cpu"]["logical_cores"]),
        "| Memory | %s |" % ("%.1f GB" % (mem / 2**30) if mem else "unknown"),
        "| Graphics | %s |" % gpus,
        "| Display | %s |" % bp["display"]["server"],
        "| Agent runtimes | %s |" % (", ".join(sorted(bp["agent_runtimes"])) or "none found"),
        "",
        "| Connection | Status | What the agent does |",
        "| --- | --- | --- |",
    ]
    lines += ["| %s | **%s** | %s |" % (r["connection"], r["status"], r["action"]) for r in rows]
    lines += ["", "Status: **ready** works now. **setup** is shipped, configure it. **build** needs a host-specific bridge (see docs/BRIDGE_SPEC.md).",
              "**note** is information; nothing to do.",
              "", "When every row is done, run `visumway verify`.", ""]
    return "\n".join(lines)
