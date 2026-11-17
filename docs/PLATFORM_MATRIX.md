# One VisumWay command; host-native wiring

Windows, macOS, and Linux use the same shared installation contract.
`visumway setup` inspects the host, writes a plan, and installs the host's
supported event and startup connections. Any agent with local shell or
MCP access can reuse that installation. Automatic notifications are
optional and use a wake adapter for the agent that first declared itself
during setup.

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
| Signed-in model | Claude Code/Codex CLI, needs real probe | Same | Same |

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
- **Every platform:** No existing desktop chat window is used as a wake engine.
  A signed-in CLI agent is the on-demand brain, its existing-account auth must
  be verified, and native notification delivery is independent of the chat UI.
