# Bridge specification

Contracts for everything that plugs into VisumWay. A coding agent building a host-specific bridge follows this document.

## 1. Event

```json
{
  "type": "app.crash",
  "subject": "Game.exe",
  "severity": "error",
  "source": "windows-eventlog",
  "data": {"exception": "0xc0000005", "report_path": "C:\\...\\Report.wer"},
  "ts": 1794764108.4,
  "id": "a1b2c3d4e5f6"
}
```

| Field | Required | Rules |
| --- | --- | --- |
| `type` | yes | Lowercase `domain.what`, matching `^[a-z0-9][a-z0-9_.-]{0,63}$` |
| `subject` | no | What it is about. Up to 200 characters. Aggregation and cooldown are per `type` + `subject`. |
| `severity` | no | `info`, `warning`, `error`, `critical`. Default `info`. |
| `source` | no | Name of the bridge. |
| `data` | no | Small JSON object, under 8 KB. Put large diagnostics on disk and pass a path. |
| `ts`, `id` | no | Filled in if absent. |

Reserved types: `app.crash`, `app.hang`, `process.exited`, `gpu.error`, `disk.low_space`, `disk.health`, `update.*`, `window.*`, `input.*`, `network.*`, `power.*`, `visumway.selftest`. Add new domains freely; add a default rule if the new type should wake.

Choose `subject` so repeats of the same problem share it. Do not put timestamps or counters in it.

## 2. Delivering an event

Either run

```
visumway emit <type> [--subject S] [--severity LEVEL] [--source NAME] [--data k=v ...] [--json '{...}']
```

or write the JSON object to `<home>/inbox/<anything>.json.tmp` and rename it to `<anything>.json`. The rename is what makes delivery atomic. Malformed files are moved to `inbox/rejected/`.

## 3. Event bridges: let the OS listen

Order of preference:

1. **OS-triggered.** The operating system starts a short command at the moment of the event. Idle cost is nothing.
2. **Built-in polling source** (`sources/`). For things with no OS trigger. Keep intervals long.
3. **A resident helper process.** Last resort. Must not use meaningful CPU while idle.

Starting points, to be confirmed on the host before use:

**Windows.** Shipped as the `windows-events` bridge (`visumway bridge install windows-events`): scheduled tasks with event triggers start `visumway bridge run windows-events`, which reads new records with `wevtutil` and writes events to the inbox. The pattern, for further bridges:

```
schtasks /Create /TN "VisumWay\AppCrash" /SC ONEVENT /EC Application ^
  /MO "*[System[Provider[@Name='Application Error'] and EventID=1000]]" ^
  /TR "<home>\bridges\app-crash.cmd" /F
```

The script reads the newest matching record (for example with `Get-WinEvent`), extracts the program name, and calls `visumway emit app.crash --subject <exe> --severity error`. Same pattern for `Application Hang` and for display-driver events mapped to `gpu.error`. Verify the provider names and event IDs on the target machine.

**Linux.** Shipped `linux-journal` bridge: a per-user systemd timer scans *accessible user journal records* once a minute for explicit crash hints. System-wide coredump records may be restricted, so this is not a comprehensive host crash sensor. A privileged optional system component would need separate design and user approval.

**macOS.** Shipped `macos-reports` bridge: a per-user launchd `WatchPaths` job scans `~/Library/Logs/DiagnosticReports` for new `.ips`, `.crash`, and `.hang` files, baseline-protected and deduplicated. Confirm report coverage and path on a real Mac.

Rules for every event bridge:

- Never call a model. Never contact the user. Only report.
- Be safe to trigger many times in a row; the runtime handles aggregation.
- Install under `<home>/bridges/` and be listed in the manifest with removal steps.
- Add a check to `verify.py`.

## 4. Visual bridges

The single-frame interface ships as `visumway capture` and the MCP tool
`capture_screen`. Use `visumway capture --list` or `list_capture_targets`
to discover selectors. The desktop selector works with the existing host
screenshot backend. The Windows helper adds current-session `display:` and
`window:` selectors and closes the capture session after one frame.
See [Windows visual setup](WINDOWS_VISUAL.md).

On Windows, `inspect_window` reads accessibility labels, roles, state,
and bounds from the selected window. Use an exact name for one control,
or an omitted name for a short list. The read returns structured data
and does not capture pixels or click controls.

### Leased watch

Each MCP stdio connection can hold one watch for an active task.

| MCP tool | Behavior |
| --- | --- |
| `watch_start` | Takes a selector from `list_capture_targets`, an optional maximum edge on Windows, and a lease in seconds (defaults to 120, maximum 600). Returns a watch ID. Use `mode: "buffered"` to start native capture for a Windows window. The default mode, `sample`, captures only on request. |
| `watch_frame` | Samples the original target. Returns image content and a higher sequence number when the encoded PNG changes. An identical sample returns only metadata. If the target is unavailable or the lease expires, the watch ends. |
| `watch_read` | For buffered watches, returns changed frames in order after `after_sequence`, with a `next_after_sequence` cursor. `content_index` identifies the image for each frame. `missed` reports expired or evicted changes and `has_more` signals more retained changes. |
| `watch_stop` | Invalidates the watch ID and discards its state. Closing the MCP connection has the same effect. |

A sampled watch keeps the last PNG digest. Buffered mode uses one Windows
Graphics Capture session, up to 10 samples per second and up to 30 seconds
of history, with a 24 MiB memory cap for retained images. It skips adjacent
identical frames and sends images only in reply to reads. A transition
shorter than the sampling cadence can still be missed. Protected or
disappeared targets end capture without falling back to the full desktop.

## 5. Hardware bridges

On-demand tools that answer a question about the body (`gpu_status`, `disk_health`, `temperatures`). Wrap the vendor tool, return compact JSON, and register the tool in `mcp_server.py`. If a hardware condition should wake the agent, that is an event bridge under section 3.

## 6. Agent adapter

In `config.json` under `agent.adapters.<name>`:

| Key | Meaning |
| --- | --- |
| `argv` | Non-interactive command as a list. `{prompt}` is substituted, or the prompt goes to stdin. |
| `prompt_via` | `arg` (default) or `stdin`. Use `stdin` for long prompts and on Windows. |
| `output` | How to read the reply: `text`, `claude-json`, `codex-jsonl`. Parsers return message, session id, and error. |
| `deliver_stdout` | The model's reply is its message to the user. A reply of `NOTHING` sends nothing. |
| `open_argv` | Interactive command that resumes `{session_id}`. Run when the notification is clicked. |
| `investigate_argv` | As `open_argv`, plus `{investigate_prompt}` (fixed text). Run for the Investigate button. |
| `fresh_argv` | Interactive command used when there is no session to resume. `{context_prompt}` names the incident file. |
| `login_check` | Token-free command that reports sign-in state. |
| `account_methods` | Exact login method names accepted for an account-backed adapter. A successful login check is required before wake or probe. |
| `account_provider` | Optional expected `apiProvider` in an authentication status JSON response. Claude Code uses `firstParty`. |
| `strip_env` | Credentials and provider-routing environment variables removed from the account check and wake. |
| `timeout_s` | Hard limit for one invocation. |

The agent runs in `<home>/workspace` with `VISUMWAY_HOME`, `VISUMWAY_WAKE_ID` and `VISUMWAY_INCIDENT_ID` set. A failure, a timeout, a missing command, or an error reported inside the agent's own output is recorded and produces a labelled system notice, never a message attributed to the AI.

A new adapter is not "supported" until `visumway agent probe <name>` passes on a real machine and its real output is added as a test fixture.

Do not put permission-bypass flags or API keys in a shared default.

## 7. Notification channels

Implemented in `notify.py`: `desktop`, `file`, `ntfy`, `webhook`. A channel takes a message, an optional title, a sender label and an optional incident id, returns `{"channel", "ok", ...}`, and must never raise.

### Desktop notification bridge

| OS | Mechanism | Click |
| --- | --- | --- |
| Windows | Toast through Windows PowerShell 5.1 and WinRT, under AppUserModelId `VisumWay.Agent` whose display name is the agent's identity. Setup also creates the required Start Menu shortcut carrying that AUMID. | Protocol activation: body `visumway://open/<id>`, buttons `visumway://investigate/<id>` and `visumway://later/<id>` |
| Linux | `notify-send`; with an incident, a short-lived helper waits for the action | The helper calls the same handler directly |
| macOS | Built-in `osascript` `display notification`; optional `terminal-notifier` with `-execute` | Click-to-open if the optional notifier is installed; no native Investigate/Later buttons yet |

Requirements for any desktop bridge:

- Shows nothing and runs nothing while idle.
- The click payload is an action name and an incident id, nothing else. Titles and messages are escaped for the notification format.
- Works with every AI application closed.
- Registration is per user, needs no admin rights, and is undone by `visumway uninstall`.

### Click handler

`visumway open <link-or-id>` validates the link and loads the incident. For
`open` or `investigate`, it looks up the original agent's app or terminal
launcher and uses the incident's session and workspace. If that adapter has
been removed, the click reports it as unavailable. The `later` action
snoozes the incident and the runtime re-shows its stored message after
`reflex.snooze_minutes`.

## 8. Acceptance for any bridge

1. Works after the installing agent's session has closed.
2. Works after a reboot.
3. Uses no model tokens and negligible CPU while idle.
4. Has a `verify` check.
5. Is listed in the manifest with how to repair and remove it.
