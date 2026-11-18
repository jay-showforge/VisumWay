# Architecture

## Separation of responsibilities

```
            AI brain (any model, asleep by default)
                 ^                         |
     wake + event report            tool calls, messages
                 |                         v
   +-------------------------------------------------------+
   |              Installed infrastructure                 |
   |                                                       |
   |  bridges --> inbox --> reflex runtime --> wake adapter|
   |  (sensors)   (files)   (rules, budget)    (one call)  |
   |                                                       |
   |  tool interface (MCP): blueprint, events, processes,  |
   |  screen frame, notify          notify channels --> you|
   +-------------------------------------------------------+
                 ^                         |
              events                    queries
                 |                         v
        Computer body: OS, GPU, CPU, apps, devices, network
```

`visumway setup` inspects the host, configures the available connections,
and exits. The installed listener handles events, and agents start the CLI
or MCP tools as needed. Those components work independently of the setup
process.

## Two directions of traffic

**Body to brain (reflex path).** Always available, almost always silent.

1. A bridge notices something and writes an event to the inbox. On Windows the crash bridge is started by Task Scheduler at the moment the event-log record is written.
2. The reflex runtime drains the inbox once a second and matches each event against the rules: `ignore`, `log`, or `wake`.
3. Wake-worthy events are held for a short aggregation window so a burst becomes one report.
4. The report is checked against the per-subject cooldown and the wake budget.
5. An **incident** is created, and the selected agent is started once, non-interactively, using the user's existing sign-in, with a prompt containing the report.
6. The model's reply is its message. It is shown as a desktop notification under the agent's name, linked to the incident. The agent process exits.
7. If the user clicks, the `visumway://` handler looks the incident up and opens the agent's interactive interface, resuming the session from step 5.

Steps 1 to 4 and step 7's lookup use no model. Step 5 is the only place tokens are spent without a person present.

On Windows, `visumway setup --agent NAME` binds one
agent to the independent path and registers a Start Menu identity and
per-user protocol handler. Every adapter uses the same notification bridge.
That bridge receives message text and an incident ID. The optional app
launcher is resolved by the incident's original agent adapter. The Codex
deep link is available when explicitly configured. Other supported
adapters can resume using their interactive CLI in the incident workspace.

If the user opts into `agent.codex_app_thread`, step 5 submits the event report to
the local Codex queue over App Server stdio. The loaded chat processes the
turn and the ChatGPT app owns completion notifications and click handling.
VisumWay records queue acceptance and the saved chat ID. The usual event
budget still applies, and the runtime opens no Codex process while idle.

**Brain to body (tool path).** Exists only while an agent session is running.

Any local agent host that supports MCP can start `visumway mcp` and use the same
blueprint, event history, process list, on-demand frames, and Windows
accessibility reader where the host OS supports it. The host
whose label matches the notification assignment can also use
`notify_user`. Sessions exit independently of the listener.

## Why a file inbox

Any program can report an event by writing a small JSON file and renaming
it into place. The VisumWay home's filesystem permissions control access.
The files survive a runtime restart. The listener checks the inbox once a
second. Its idle CPU use measured about 0.03% of one core on a headless
Linux VM.

The operating system can run the event collector. A Windows event-log
subscription triggers its scheduled task when a matching record arrives.
On Linux, a systemd user timer checks the journal periodically.

Windows starts the single reflex runtime at sign-in. A repeating Task
Scheduler trigger can replace a terminated runtime, and Windows ignores
that trigger while the task is already running. The recovery path starts
the listener only. A wake still requires an eligible event and a saved
budget reservation.

## Wake adapter boundary

Each agent adapter defines how to check sign-in, invoke a background turn,
read its reply, and resume the resulting session. Its command and output
format live in the adapter settings. The optional Codex saved-chat route
has a separate App Server bridge. Credentials, model choice, and tool
permissions stay with the agent host.

A provider update can change its flags, login status format, or session
interface. Run `visumway agent list` to check what is installed and
`visumway agent probe` to verify a real turn against that version.
The shared CLI/MCP tools and event history remain available with wakes
paused.

## Incidents: continuity without a running model

A wake produces three things that must stay connected: the report, the message the model wrote, and the agent session it wrote it in. The incident record holds all three under one random id. The notification carries only that id. This is what lets "click the bubble and keep talking" work hours later with nothing running in between, and what lets **Later** show the same words again without asking the model to repeat itself.

Woken agents always run in `<home>/workspace`, because agent CLIs store sessions per working folder and a session can only be resumed from where it was created.

## Which brain

`agents.py` reports three separate facts for an adapter: installed, signed
in, verified. First setup assigns the installing agent as the notification
owner. Later setup calls from other agents reuse the installation. The
listener reloads wake settings and drops old queued reports on pause.
Already-started turns can finish. An account-backed adapter checks its
permitted login methods before starting headless inference.
`visumway agent probe` makes one small model call and records the result
against the adapter's version.

Discovery distinguishes a desktop app from its command-line adapter. The
independent alert route wakes the CLI. The explicitly configured Windows
Codex saved-chat option uses the app queue described above.

## Identity without a running model

The agent's name and standing instructions are in `config.json`. What happened while it was asleep is in the event log, readable through the `recent_events` tool. A fresh invocation therefore picks up the same role with the relevant history, without any session being kept open. Carrying a full conversation between invocations is a roadmap item.

## Visual access

Level 1, shipped: a single frame on request, through whatever the host provides.
On Windows, the independently installed `windows-visual.exe` uses Windows
Graphics Capture for individual displays and application windows. VisumWay
discovers the helper and calls it only for a selected target. The CLI and MCP
share the same target and frame interface. Desktop-wide capture retains the
PowerShell GDI backend. See [Windows visual setup](WINDOWS_VISUAL.md).

A sampled watch opens capture on each request and returns a frame when its
digest changes. The Windows buffered watch opens one native session on a
selected window for an active lease. It samples locally and keeps a
bounded history of changed frames in memory. The connected agent reads
the history with a cursor. There is no model invocation or unsolicited
image upload from the capture process.

Two limits are worth stating plainly. Operating systems mediate screen capture through the compositor; there is no supported tap on the GPU ahead of it, and protected content is excluded by design. And a model watching continuously would be continuous inference, which is exactly what this project exists to avoid. So the visual connection is always available and only active on demand.

## State on disk

```
~/.visumway/
  config.json        rules, agent adapters, sources, channels
  blueprint.json     last host scan
  PLAN.md            installation plan from that scan
  MANIFEST.md        written by the installing agent
  inbox/             pending events (rejected/ holds malformed ones)
  state/events.jsonl event history (rotates at 5 MB)
  state/daemon.json  runtime heartbeat, active agent, wake setting and remaining budget
  state/budget.json  wake timestamps, so the budget survives restarts
  state/incidents/   one record per wake: report, message, session, status
  state/agents.json  probe results, tied to each agent's version
  workspace/         working folder for woken agents (sessions resume from here)
  logs/wakes/        one record per model invocation
  outbox/            messages sent on the file channel
  bridges/           host-specific bridges built during setup
```
