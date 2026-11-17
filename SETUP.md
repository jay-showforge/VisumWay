# Setting yourself up with VisumWay

You are an AI coding agent. A user asked you to use VisumWay to set yourself up on this computer. Follow these steps in order. Do not skip verification.

## Ground rules

- Use the account the user is already signed in with. Never ask for, create, or configure an API key, and never switch to API billing to make something work.
- An agent being installed or signed in is not proof that it can be woken in the background. Only `visumway agent probe` establishes that. Report what is verified and what is not.
- A request to get VisumWay and set it up authorizes the normal per-user
  installation. If a step needs rights or services beyond the user's
  request, explain the specific step before proceeding.
- Nothing you install may call a model on a timer or in a loop. The only path to a model is a reflex rule with action `wake`.
- If a step cannot be done on this host, record it as not done and continue. Do not claim it works.

## Steps

1. **Check for an existing installation.** Run `visumway status` if the
   command is available. If `shared_tools_configured` is true, use the
   reported home and go to step 3. That reuses the current wiring and
   leaves notification ownership alone.

2. **Install the shared tools.** On Windows x64, use the
   [verified bundle](docs/WINDOWS_BUNDLE.md) if available. On Windows,
   macOS, or Linux, install from the checkout with
   `python -m pip install .` using Python 3.9 or newer. Use a virtual
   environment if the system Python is managed. Keep the command or
   interpreter's absolute path so the agent host can find it.

   Run `visumway setup --agent NAME` using your own label, such as
   `codex`, `claude`, or another local host's name. The label reserves
   notifications for this installer even if no wake adapter is available.
   If your host has no stable label, run `visumway setup` for shared tools
   without assigning notifications. Both paths create the host plan and
   install the available event bridges and login service. Setup performs
   no model calls. See the [platform matrix](docs/PLATFORM_MATRIX.md).

3. **Connect and verify.** Use `visumway events`, `visumway status`, and
   `visumway capture` from any agent with local shell access. If your host
   supports MCP, add the local stdio command `visumway mcp`. If you
   installed VisumWay, include `--agent NAME` after `mcp` to identify this
   session as the notification owner when a wake adapter is bound. Use
   the same VisumWay home in every host. The
   [README](README.md#quick-start) has example registrations.

   Run `visumway verify` and try a read-only tool on the real host. Check
   the plan before adding platform-specific bridges. For Windows source
   installs, see [Windows visual setup](docs/WINDOWS_VISUAL.md).

4. **Add notifications if asked.** The shared tools work without a
   wake adapter. If the installing agent has a background command and
   a confirmed existing sign-in, setup can bind it. If the adapter
   becomes ready later, rerun setup with that same installing label.
   Any other agent can use the tools without changing the reservation,
   adapter, settings, or notification registrations.

   Automatic wakes start paused. Show the user `visumway wakes preview`
   before enabling them with `visumway wakes enable --agent NAME`.
   When instructed to verify real background inference, run
   `visumway agent probe` and test native delivery with
   `visumway verify --send-test-notification --agent NAME`. The probe
   makes one small model call. Use
   [the Windows demo guide](docs/WINDOWS_DEMO.md) for a full authorized
   crash and reboot test. The installing agent can pause future wakes
   with `visumway wakes pause --agent NAME`.

5. **Report what worked.** Summarize which tools the host can use,
   whether a wake adapter is bound, and what you verified. If you
   installed anything beyond the standard package, record it in
   `<home>/MANIFEST.md` together with how to uninstall it.

## Uninstall on Windows

Run `visumway uninstall` to remove the runtime, Windows event task, toast
identity, click handler, and native helper while retaining local history.
Use `visumway uninstall --purge` to also remove the VisumWay home. If you
added the Codex MCP entry separately, run `codex mcp remove visumway`.
For Claude Code, run `claude mcp remove --scope user visumway`.
Use the installation's Python to run `python -m pip uninstall visumway`
if the package should be removed too.
