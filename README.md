# VisumWay

**Let your desktop agent check its own work. Let your computer wake it when something breaks.**

VisumWay sets up the local connections that let an agent read app state,
look at a window, and respond to operating system events. The installer
checks what the computer supports and leaves the tools and optional event
listener in place. Set it up once and compatible agents can share those
tools through the CLI or MCP.

![Out of the Screen. A robot takes shape from a monitor's circuits, connected to a keyboard and mouse.](docs/assets/visumway-out-of-the-screen.png)

[Download v0.2.9 for Windows x64](https://github.com/jay-showforge/VisumWay/releases/tag/v0.2.9) · [Agent setup](SETUP.md) · [Platform support](docs/PLATFORM_MATRIX.md) · [Licensing](#license-and-commercial-integrations)

## See what the agent can verify

In a live Windows test, Codex saw a clipped **Launch** button in a running
game, fixed the layout using an authorized tool, and looked again to
verify the fix. A buffered window watch also let Codex recover a visual
change that lasted **552 ms** between requests.
[Live test record](docs/VERIFICATION.md#v024--windows-buffered-watch)

- **Read the app.** On Windows, an agent can read accessible labels, states,
  and control bounds directly when the app exposes them. A two-pair
  Calculator pilot compared direct reads with screenshot reads.
  [Pilot results and limitations](docs/BENCHMARK.md)
- **See what pixels can tell you.** Request an image when you need to judge a
  layout, check rendering, or see a game. On Windows, follow a single window
  in an active session and retrieve changed frames from a short local buffer.
- **Follow the evidence.** Connect a window to its process and inspect local
  events. An agent can check whether an app responded, changed, or crashed
  after it used its authorized tools.

## Quick start

Give this repository to an agent that can run local commands and say:

> “Use VisumWay and get yourself set up on this computer.”

The agent follows [SETUP.md](SETUP.md). VisumWay checks the host, discovers
available connections, and writes a machine-specific `PLAN.md`. The agent
uses that plan to connect and verify what works on your computer.

On Windows x64, the [offline bundle](docs/WINDOWS_BUNDLE.md) includes the
native capture and accessibility helper. You can also install the shared
core from a checkout on Windows, macOS, or Linux with Python 3.9+:

```sh
python -m pip install .
visumway setup
visumway verify
```

**Try it on Windows.** Open an app you’re working on and ask your agent:
“Use VisumWay to inspect this window. Tell me what you can read directly
and capture the window if you need to check the layout.”

### Use the same setup from a second agent

Say “Use VisumWay” in the second agent. If it can run commands locally,
it can use the shared CLI immediately. For native MCP calls, point both
hosts at the same installation:

```sh
codex mcp add visumway -- visumway mcp --agent codex
claude mcp add --transport stdio --scope user visumway -- visumway mcp --agent claude
```

If the agent cannot find `visumway`, use its absolute path. For a custom
installation, put the same `--home PATH` before `mcp` in both entries.
Use `list_capture_targets` to find a window, `inspect_window` for Windows
controls, and `capture_screen` for pixels.
[Windows capture and buffered watch](docs/WINDOWS_VISUAL.md#follow-a-window-during-an-active-task).

## Optional crash alerts, one agent in charge

The first named installer (`visumway setup --agent NAME`) reserves
notification ownership. Other local agents can look through the same
connections and use the same event history. The first agent keeps the job
of replying to background events.

Automatic wakes start paused. If a supported adapter is bound to your
existing sign-in, the owner can review `visumway wakes preview` and enable
alerts with `visumway wakes enable --agent NAME`. Local rules and a wake
budget control when an event gets an agent turn. In a live Windows test,
a crash woke signed-in Codex while ChatGPT was fully closed. Windows
showed the agent's reply as a native alert, and clicking the alert
opened the conversation. [Windows walkthrough](docs/WINDOWS_DEMO.md)

Background wakes and chat resume depend on each agent's adapter and
installed version. The independent alert uses the signed-in CLI.
The optional saved-chat route uses Codex App Server. After a provider
update, check the adapter with `visumway agent list` and run
`visumway agent probe` if you want to confirm a real background turn.
The shared tools can be used with automatic wakes paused.

VisumWay uses **zero model tokens while idle**. A visual watch runs on an
explicit lease and ends on stop, expiry, or disconnect. Event history is
local. An enabled wake sends a bounded report to the selected agent, which
may send it to its provider. Agent actions use the host's existing
permissions. [Security and privacy](docs/SECURITY.md).

## Platform support

GitHub Actions ran the unit suite and CLI/MCP smoke checks on Windows,
macOS, and Linux with Python 3.9 and 3.13.

| Platform | What has been verified |
| --- | --- |
| **Windows** | Clean offline install, direct control reads, buffered window capture, and real Codex crash wakes with native alerts and chat resume on Windows 11. |
| **macOS** | Hosted checks included a real desktop frame via `screencapture` and an MCP handshake. A signed-in desktop session is still needed to validate login startup, crash delivery, and notifications end to end. |
| **Linux** | Ubuntu 24.04 under WSL2 with Xvfb passed real X11 capture, MCP watch, journal crash detection, a signed-in native Codex wake, Dunst notification actions, distribution restart, and uninstall. Physical-desktop and Wayland validation remain pending. |

[Platform matrix](docs/PLATFORM_MATRIX.md) · [Verification record](docs/VERIFICATION.md) · [Linux test and setup](docs/LINUX_VALIDATION.md)

## Build with VisumWay

- [Architecture](docs/ARCHITECTURE.md) explains discovery, the local runtime, and optional agent wakes.
- [Bridge specification](docs/BRIDGE_SPEC.md) covers reporting events and extending capture.
- [Roadmap](docs/ROADMAP.md) tracks platform parity and new bridges.
- [Agent development guide](AGENTS.md) covers working on the repository.

## License and commercial integrations

VisumWay v0.2.9 is source-available under the **Business Source License
1.1**. Install it for your own use or deploy it internally at work for
free, including for paid work.

If you provide VisumWay as a built-in feature of an agent product for
third parties, you need a commercial license once that product reaches
**US$50,000 in gross revenue over the preceding 12 months**. The license
defines how to count subscriptions and sales of product bundles.
[License and Additional Use Grant](LICENSE)

For commercial licensing or help with integration, compatibility
testing, and support, contact [licensing@tenzorpipe.org](mailto:licensing@tenzorpipe.org).
Include the product, target platforms, and how VisumWay would be included.

v0.2.9 converts to Apache 2.0 on November 17, 2030, or sooner if the
four-year limit in the license applies. v0.2.6 was released under MIT.
