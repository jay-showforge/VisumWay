# Roadmap

The [platform matrix](PLATFORM_MATRIX.md) describes the available bridges.
The [verification record](VERIFICATION.md) records the version, environment,
and outcome for each check.

## Available in the desktop agent preview

- Host discovery, a machine-specific setup plan, and shared CLI/MCP tools.
  An installing agent can reserve optional notifications and other agents
  can reuse the same setup.
- On Windows, direct reads of accessible app controls, display and window
  capture, and a bounded buffer of changed window frames during an active
  watch.
- Windows event-triggered wakes, independent native alerts, and click to
  reopen the originating Codex conversation. Prior live tests covered
  an application crash, a hang, and reboot into the listener.
- Per-user macOS DiagnosticReports and Linux journal bridges, with native
  login and alert validation tracked below. Hosted CI runs the unit suite
  and CLI/MCP smoke checks on all three platforms.

## Next validation

1. **macOS desktop.** Verify a fresh setup in a signed-in desktop session.
   Exercise capture permissions, an active watch, launchd startup, a native
   DiagnosticReports event, alert delivery, and uninstall.
2. **Linux desktop coverage.** Repeat the
   [Ubuntu/WSL2 X11 acceptance test](LINUX_VALIDATION.md) on a physical
   Linux desktop and on Wayland. Check GNOME/KDE capture permissions and
   notification actions. The WSL2 test already exercised native tools,
   a signed-in wake, distribution restart, and uninstall.
3. **Agent adapters.** Complete a signed-in Claude Code wake and confirm
   notification click-to-resume. Recheck the Codex CLI and the optional
   saved-chat route when their interfaces change.
4. **Performance.** Repeat the [Calculator pilot](BENCHMARK.md) with at
   least ten matched pairs. Add tasks in apps with different accessibility
   coverage before making broader performance claims.

## Later

- Add native window capture and direct control reads on other desktops where
  host permissions and APIs allow them.
- Give woken agents narrowly scoped, read-only access to relevant diagnostics.
- Expand hardware diagnostics and bridge health checks.
- Design authenticated replies to off-device notifications.

The local runtime listens while idle. Model calls stay on demand and agent
actions use the permissions granted by their host.
