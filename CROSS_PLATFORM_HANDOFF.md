# VisumWay v0.2.1 — Platform validation handoff

This is an incremental continuation of v0.2, **not a rewrite**.

## What was implemented in this handoff

- A native-event bridge registry supporting Windows Task Scheduler, Linux user
  journal timer, and macOS DiagnosticReports LaunchAgent watch paths.
- Windows PowerShell/C# Start Menu `.lnk` creation carrying AppUserModelID for
  toast identity, and uninstall cleanup.
- Linux XDG graphical autostart fallback; headless Linux without a user service
  manager is reported as unsupported rather than pretending persistence works.
- macOS XML-safe LaunchAgent and optional clickable terminal-notifier path.
- Unattended Claude/Codex invocation blocked unless the token-free login check
  confirms an existing account (API-key-only or unknown auth is rejected).
- Host plan reports a detected screenshot command as unverified until a real
  frame is successfully captured.
- OS-specific tests and docs/PLATFORM_MATRIX.md.

## Your next task (Windows, Linux or Mac)

1. Read `AGENTS.md`, `SETUP.md`, and `docs/PLATFORM_MATRIX.md`.
2. Run the full test suite. Do not assume unit tests prove live host behavior.
3. Run `visumway setup` in your normal logged-in desktop session; inspect the
   generated `~/.visumway/PLAN.md`. Fix host-specific installation issues.
4. Confirm a **real native** desktop bubble with `visumway verify --send-test-notification`.
   On Windows verify the Start Menu AUMID shortcut, toast presentation and both
   button actions. On macOS verify AppleScript fallback and optionally
   terminal-notifier click-to-open. On Linux check D-Bus session and action clicks.
5. Test a real OS event bridge, wake a signed-in CLI agent if available, and
   verify the **model's own message** appears as a desktop bubble with the full
   chat app closed. Never introduce API keys or extra billing.
6. Restart the computer and re-test. Record PASS/WARN/FAIL and actual evidence
   in `docs/VERIFICATION.md`. Keep untested claims labeled unverified.
7. Confirm `visumway uninstall --purge` removes all installed startup/event/
   desktop registrations on that OS.

## Rules that remain unchanged

The user's only instruction should be "Use VisumWay and get yourself set up on
this computer." VisumWay scans and generates a plan; the coding agent assembles
the required host-specific bridges. The bridges remain installed independently.
There must be zero idle LLM inference, no model polling, no API-key setup, no
separate model billing, and no bypass of OS/agent permissions. One installed
model can be swapped for another compatible provider using the same bridge
interface. Retain tests and source history.
