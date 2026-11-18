# One VisumWay command; host-native wiring

Windows, macOS, and Linux use the same shared installation contract.
`visumway setup` inspects the host, writes a plan, and installs the host's
supported event and startup connections. Any agent with local shell or
MCP access can reuse that installation. Automatic notifications are
optional and use a wake adapter for the agent that first declared itself
during setup.

## Validation by environment

The v0.2.7 GitHub Actions jobs ran the unit suite and `visumway init` /
`visumway verify` on all three platforms with Python 3.9 and 3.13. The
workflow checks the core in a temporary home. The separate live tests
exercise installed services, real events, and visible alerts.
[v0.2.7 CI run](https://github.com/jay-showforge/VisumWay/actions/runs/44223145347)

| Platform | Evidence | Remaining end-to-end checks |
| --- | --- | --- |
| Windows | The GitHub-built v0.2.7 x64 ZIP installed in a fresh environment. Earlier live Windows 11 tests exercised UI Automation, buffered window capture, real signed-in Codex wakes, native toasts, and chat resume. | Signed-in Claude Code wake and chat resume. |
| macOS | The macOS 3.13 runner initialized the core, completed the MCP handshake, and captured a 1024×768 desktop frame through `screencapture`. | Fresh per-user setup, interactive capture permissions and watch, launchd at sign-in, real crash pickup, notifications, and a signed-in wake. |
| Linux | Hosted core and MCP checks passed. An Ubuntu-on-WSL smoke tested shared setup and a foreground listener with a test event. | Native Linux desktop capture and watch, login startup, journal delivery, notifications, and a signed-in wake. |

## Available backends

| Capability | Windows | Linux | macOS |
| --- | --- | --- | --- |
| Host scan, agent-readable plan | Python-native | Python-native | Python-native |
| Startup | Task Scheduler ONLOGON | systemd `--user`, or XDG autostart | LaunchAgent |
| Local event trigger | Application Error / Hang / Display Task Scheduler triggers | `linux-journal` systemd user timer, best-effort | `macos-reports` launchd WatchPaths |
| Notification | WinRT toast via Windows PowerShell | `notify-send` | `osascript`, optionally `terminal-notifier` |
| Notification click | Protocol activation, Investigate/Later | `notify-send --wait` action helper | Optional `terminal-notifier` click-to-open; no buttons yet |
| On-demand desktop frame | PowerShell GDI | Existing native/screenshot backend | Existing native/screenshot backend |
| On-demand display or application window | Windows Graphics Capture helper and WARP fallback | Native target selection pending | Native target selection pending |
| Change-deduplicated active-task watch | Desktop, display or application window. Tested with signed-in Codex. | Desktop where a capture backend is present. Host verification pending. | Desktop subject to screen-recording permission. Host verification pending. |
| Buffered window feed and direct control reads | Windows Graphics Capture and UI Automation. Live Codex tests passed. | Native bridges for these capabilities pending | Native bridges for these capabilities pending |
| Optional signed-in wakes | Codex CLI live verified. Claude Code adapter available, with a successful signed-in wake pending. Optional Codex saved-chat route. | CLI adapters available. Signed-in wake pending. | CLI adapters available. Signed-in wake pending. |

## Verify on each host

1. In a normal user desktop session, install the package and run
   `visumway setup`. An installing agent can add `--agent NAME` to
   reserve optional notifications for itself.
   Do not run as admin/root merely to bypass OS security restrictions.
2. Run `visumway verify` and try a shared tool over the CLI or MCP.
3. For optional notifications, use `visumway agent list` and verify a
   visible alert with `visumway verify --send-test-notification --agent NAME`
   after connecting the installing agent's adapter.
4. `visumway bridge list` should show the host event bridge installed. Trigger
   a genuine supported event; verify it appears in `visumway events`.
5. With a user's permission, run `visumway agent probe` (a small real model
   call), and test the actual wake-to-notification flow.
6. Sign out and back in or reboot. Confirm runtime startup, a real event,
   notification delivery, and `visumway status` with no idle inference.
7. `visumway uninstall --purge` must remove all installed parts.

## Platform limitations to investigate on real machines

- **Windows:** Native Shell COM creates the Start Menu shortcut with
  `System.AppUserModel.ID`. Windows 11 stored toasts under this ID and
  Task Scheduler delivered a real Application Error 1000 on battery power.
  See [the verification record](VERIFICATION.md) for the remaining checks.
- **Linux:** A user-only journal reader does not necessarily see system-wide
  coredumps. The periodic timer is low-overhead but not an instant trigger;
  tighter coverage needs a supported OS-specific integration and explicit
  permission where required. XDG autostart requires a compliant desktop login.
- **macOS:** The DiagnosticReports watcher is only a best-effort per-user
  signal. AppleScript notifications can display text but provide no click
  actions. `terminal-notifier` is an optional supported utility for
  click-to-open via a fixed incident ID; it needs permission and host testing.
- **Agent adapters:** The independent wake path invokes a signed-in CLI and
  delivers the reply through the native notifier. The optional Windows
  Codex saved-chat route queues the report through App Server and uses the
  ChatGPT app's completion notifications for that chat. The provider-specific
  wake paths can be checked with `visumway agent probe`.
