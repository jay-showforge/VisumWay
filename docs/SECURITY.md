# Security and privacy

VisumWay gives an AI agent standing awareness of a computer and a way to be started without a person present. That is powerful and deserves care.

## What VisumWay does

- Keeps all state in one directory, owner-only on POSIX systems.
- Stores event history locally. Each automatic wake sends a cleaned event
  report to the selected agent, which may send it to its provider. An
  active agent can also request local data through the CLI or MCP, and
  configured ntfy or webhook channels receive notification content.
- Wraps machine-originated data in a delimited block, strips control
  characters, bounds its size, and redacts recognized credential fields
  before an unattended wake. Local logs retain the original event.
- Caps automatic model invocations per hour and per day, and rate-limits
  per subject. A wake is blocked when the runtime cannot read or commit
  the budget.
- Labels its own notices as `visumway-system` so they cannot be mistaken for the AI.
- Captures on request. An explicit Windows buffered window watch can keep
  capturing that window for a short lease between requests. It holds
  frames in memory and releases the capture session at stop, expiry, or
  disconnect.
- Starts new installs with automatic model wakes paused. Use
  `visumway wakes preview` to inspect a synthetic example of the outgoing
  report. The installing agent can enable it with
  `visumway wakes enable --agent NAME`. The report may include
  app names, paths, times, diagnostics, and the machine name. Named
  credential fields are redacted, and secrets in free text can still appear.
- Uses the agent's existing account sign-in and strips API-key environment variables from wake invocations.
- Accepts from a notification click only one of three fixed actions and a random incident id. Session ids are checked against a plain-token pattern before they reach a command line; machine data never does.
- Registers its notification identity and click handler per user (HKCU), without admin rights, and removes them on uninstall.

## What VisumWay does not do

- It does not sandbox the agent. What a woken agent may read or change is decided by the agent host's permission settings. Configure those deliberately.
- It does not authenticate who writes to the inbox beyond filesystem permissions. Any program running as the same user can emit events.
- It does not encrypt its files at rest.
- The installing agent's label controls access to notification commands and
  the MCP `notify_user` tool. An agent label is a way to coordinate clients.
  Local programs under the same OS user can change VisumWay's configuration.

## Risks to understand before enabling automatic wakes

**Prompt injection through the machine.** Process names, window titles, file paths, and log lines are attacker-influenced. A program could name itself with text meant to steer the model. The report format reduces this risk and cannot remove it. The effective control is limiting what an unattended agent is permitted to do. Start with read-and-notify only.

**Unattended actions.** A woken agent acts with no one watching. Keep automatic repair off until you trust the specific rule and scope. "Investigate and tell me" is a safe default; "fix it" should be a decision the user makes per kind of change.

`visumway wakes pause --agent NAME` stops new automatic calls while keeping event
history and shared tools available. A turn already running or accepted
by the optional Codex app queue can finish. Existing configured
installations retain their wake setting when upgraded.

**Spend.** Every wake costs tokens or local compute. The budget is the backstop. Set it for the worst day, not the average one.

**Notification channels.** A public ntfy topic is readable by anyone who knows its name. Use a long random topic, or a self-hosted server with a token. Do not let the agent put secrets, file contents, or screenshots into notifications.

**Screen contents.** A frame can contain passwords, messages, and other people's information. Capture is on demand only, and the stream bridge requires a lease. Agents should capture a window rather than the whole desktop when that is enough.

**The `visumway://` link.** Any program, including a web page, can ask Windows to open such a link. A link can only name an existing incident (a 48-bit random id) and one of open, investigate, later. The worst a forged link with a guessed id can do is open your own agent on your own incident or snooze it. If that surface is unwanted, remove the `desktop` channel and run `visumway uninstall` followed by `visumway setup`.

**Account usage.** The bundled Codex and Claude Code wake adapters use the
user's existing account sign-in. Background turns use the account's plan
limits, and the wake budget caps invocations. Check the provider's terms
for automated use of your plan.

**Remote control.** Replying to the agent from a phone (a roadmap item) means remote input can cause actions on the computer. It must not ship without authentication of the sender and a design review.

## Reporting a vulnerability

Open a private security advisory on the GitHub repository rather than a public issue.
