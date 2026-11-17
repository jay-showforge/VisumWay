# Roadmap

Status as of v0.2.1 cross-platform candidate. Ordered task details are in `AGENTS.md`; what has really been run is in `docs/VERIFICATION.md`.

| Milestone | What it means | Status |
| --- | --- | --- |
| Host Blueprint Engine | Scan the machine, produce a machine-specific plan | Done (Linux tested) |
| Independent Runtime | Installed components keep working after setup closes | Done; start-at-sign-in unverified |
| Wake-Up Bridge | A system event invokes an otherwise inactive model | Done with stand-in; real signed-in run pending |
| Agent availability | Discover installed / signed in / verified, existing account only | Done with stand-ins |
| Desktop notification bubble | The model's message, native, under the agent's name | Windows written, unrun; Linux tested with stand-in |
| Interactive bubbles | Click resumes the conversation; Investigate; Later | Done with stand-in |
| Windows event bridge | Crashes, hangs, display-driver resets, zero idle inference | Verified on Windows 11 with signed-in Codex |
| AI-Initiated Communication away from the desk | ntfy, webhook | Done one-way |
| Real Visual Access | Desktop and window streams on demand | Single frame done; leased stream specified |
| Universal Installation | Same one-sentence setup on different machines and agents | `visumway setup` exists; Native bridges selected by host; Windows first real acceptance target |

## v0.3: proven on Windows
1. `docs/WINDOWS_DEMO.md` passing end to end, including after reboot
2. Claude Code and Codex both verified with real runs
3. Read-only investigation before the model speaks
4. `gpu_status` tool for NVIDIA

## v0.4: Eyes
5. Leased visual stream on Windows Graphics Capture, exposed as watch tools
6. Window-level capture and change detection

## v0.5: Conversation
7. Reply from a phone, authenticated, waking the agent with context
8. Per-agent permissions and routing when several agents share one computer
9. Opening a desktop chat app on click, if those apps publish a way to do it

## Later
- Validate and expand Linux (journald, coredump, PipeWire) and macOS bridges
- Application bridges: apps exposing state to authorised agents
- Local rule editor (the ignore / log / wake switches as a small UI)
- Self-repair: `visumway verify --repair` re-runs setup for connections that broke after an OS or driver update
- Wake budget in tokens or cost, not only invocation counts

## Not planned
- Keeping a model running to watch the screen. It contradicts the core rule.
- A hosted service or accounts. Everything is local and self-managed.
- Modifying models or requiring a particular provider.
