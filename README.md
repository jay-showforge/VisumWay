# VisumWay

**Give your AI eyes and a body.**

VisumWay gives a local AI agent ways to see what’s on its computer, read
what apps expose, and check what happened after it acted. Set it up once
and any compatible local agent can use the same tools through the CLI or MCP.

![Out of the Screen. A robot takes shape from a monitor's circuits, connected to a keyboard and mouse.](docs/assets/visumway-out-of-the-screen.png)

[Download v0.2.6 for Windows x64](https://github.com/jay-showforge/VisumWay/releases/tag/v0.2.6) · [Agent setup](SETUP.md) · [Platform support](docs/PLATFORM_MATRIX.md)

## See the result of your own work

In a live Windows test, Codex saw a clipped **Launch** button in a running
game, fixed the layout using an authorized tool, and looked again to
verify the fix. In the same test series, a buffered window feed caught a
visual state that lasted just **552 ms** between requests. The agent
could go back and see it. [Live test record](docs/VERIFICATION.md#v024--windows-buffered-watch).

- **Read the app.** Windows accessibility inspection returns labels, states,
  and bounds for controls the app exposes. In two matched Calculator trials,
  Codex completed the full task in **23.3 s vs. 34.3 s with screenshots**
  using the same keyboard actions. That’s **32% less time** in this benchmark.
  [Method and raw timings](docs/BENCHMARK.md).
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
budget control when an event gets an agent turn. A verified Windows crash
woke signed-in Codex and produced a native alert that reopened the chat
with its response. [Windows walkthrough](docs/WINDOWS_DEMO.md).

VisumWay uses **zero model tokens while idle**. A visual watch runs on an
explicit lease and ends on stop, expiry, or disconnect. Event history is
local. An enabled wake sends a bounded report to the selected agent, which
may send it to its provider. Agent actions use the host's existing
permissions. [Security and privacy](docs/SECURITY.md).

## Platform support

The shared setup targets **Windows, macOS, and Linux**. The prebuilt
bundle, direct control reads, buffered window capture, and live Codex
desktop tests are Windows results. macOS and Linux have their own capture
and event backends and still need live desktop validation. The
[platform matrix](docs/PLATFORM_MATRIX.md) and [verification record](docs/VERIFICATION.md)
show which paths have been exercised.

## Build with VisumWay

- [Architecture](docs/ARCHITECTURE.md) explains discovery, the local runtime, and optional agent wakes.
- [Bridge specification](docs/BRIDGE_SPEC.md) covers reporting events and extending capture.
- [Roadmap](docs/ROADMAP.md) tracks platform parity and new bridges.
- [Agent development guide](AGENTS.md) covers working on the repository.

[MIT License](LICENSE)
