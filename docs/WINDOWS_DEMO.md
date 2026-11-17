# Windows validation

## Optional ChatGPT-owned alerts

If Codex installed VisumWay, the saved-chat route applies when you configure
`agent.codex_app_thread`. Select that chat in the ChatGPT desktop app, then put
the app in the background. Enable turn-completion notifications in ChatGPT
and notification banners for ChatGPT in Windows. When Windows Do Not Disturb
is on, allow ChatGPT under **Set priority notifications** if you want it to
show banners during that time.

Run `visumway status` followed by `visumway crashtest --agent codex`. The status should
report a running runtime. Expect the crash to appear in `visumway events`,
with a `queued` incident in `visumway incidents`. Check for a completed turn
in the alerts chat and a banner from ChatGPT. Click the banner to verify
that the app opens the same chat. The app can also show the alert later
in Windows Notification Center.

To verify restart persistence, reboot and sign in. Run `visumway status`
before manually starting any VisumWay component. Launch ChatGPT, open the
same alerts chat, put the app in the background, and repeat the crash test.
Watch for the new native event and app reply. The default wake budget is
four per hour, with a five-minute cooldown for crashes of the same program.

[ChatGPT notifications](https://learn.chatgpt.com/docs/notifications?surface=app)
and [Windows notification settings](https://support.microsoft.com/en-us/windows/experience/notifications-and-do-not-disturb-in-windows).

## Stand-alone VisumWay notifications

Goal: sign in, use Windows with no AI app open, crash a real program, and get a native notification written by your own signed-in model. Click it and the agent opens with that conversation.

Run these in a normal (not administrator) terminal. Each step says what you should see. If a step does not match, stop and record what happened in `docs/VERIFICATION.md`.

## 1. Install and set up

```powershell
python -m pip install . # or use Install-VisumWay.ps1 from the verified bundle
visumway setup --agent codex
visumway wakes preview
visumway wakes enable --agent codex
```

Expect a plan and successful registrations for the notification identity, the
`VisumWayReflex` per-user logon task, and the `VisumWay\Events` event subscription.
Both tasks can run on battery power. The event subscription covers application
crashes, application hangs, and display-driver resets.

The independent alert route is the default for a new installation.
A new wake uses the installed
signed-in agent CLI. Windows presents the model's reply under the VisumWay
notification identity, with the configured assistant name as its title.
Use `--agent claude` throughout when Claude Code performs the first setup.
Either agent can use the shared tools. The installing agent keeps
notification ownership.

## 2. Name your assistant (optional)

Edit `%USERPROFILE%\.visumway\config.json` and set `"identity": "Vinci"`
under `agent`. The running listener reloads the setting.

## 3. Check which brain is available

```
visumway agent list
```

Expect your agent to show an installed path and a confirmed account method.
Run the probe to verify that the account can complete a background turn.
If Claude reports invalid OAuth credentials, sign in again using
`claude auth login` and repeat the probe.

## 4. Verify the wake connection (one tiny model call)

```
visumway agent probe
```

Expect: `"verified": true`. If not, the `detail` line is the reason. Record it.

## 5. Verify the wiring (no tokens)

```
visumway verify --send-test-notification --agent codex
```

Expect a test notification under your assistant's name. Check the banner or
open Notification Center with **Win+N**. The CLI verifies submission,
registration, and a live runtime heartbeat. Seeing the notification confirms
presentation.

## 6. The demonstration

For the ordinary notification test, run the disposable crash from a
separate PowerShell window. For the fully quit variant, use **Ctrl+Q**
in ChatGPT on Windows, then check its process state in PowerShell.

```powershell
Get-Process ChatGPT -ErrorAction SilentlyContinue
visumway status
```

The fully quit variant starts with empty process output and an available
wake budget. Leave ChatGPT closed and trigger the crash.

```
visumway crashtest --agent codex
```

Expect, within about a minute:

1. A notification under your assistant's name, in the model's own words, about `python.exe` crashing, with **Investigate** and **Later** buttons.
2. `visumway events` shows `app.crash  python.exe` and one `WAKE` line.
3. `visumway incidents` shows the incident as `notified`.

Click the notification body to resume the original agent session. Claude
Code uses `claude --resume` in the incident's workspace. Codex uses its
terminal resume command, with an optional ChatGPT deep link when
`open.codex_in_app` is enabled. **Investigate** starts the interactive
session with a fixed investigation prompt.

For independent delivery evidence, check the process list again while
the banner is present and before clicking. The tray icon and process list
measure different things. [ChatGPT Windows keyboard shortcuts](https://learn.chatgpt.com/docs/app/commands).

After the same-program cooldown has passed, use another available wake to
test **Later**. The same message returns after the configured snooze with
no new `WAKE` line.

## 7. Prove it survives a restart

Reboot and sign in. Leave Windows Startup Apps in their usual state.
Check for a live runtime before manually starting VisumWay.

```
visumway status
visumway crashtest --agent codex
```

Expect: `runtime_running: true` without you starting anything, and the notification arrives as before.

## 8. Prove it is idle when idle

Use the computer normally for an hour, then:

```
visumway status
```

Expect: `wakes` counts only the crashes you caused.

## Things most likely to need fixing on first run

- **No notification appears.** Run `visumway verify --send-test-notification --agent NAME` with the installing agent's name and read the `desktop bubble` line. Check Windows notification settings and Focus Assist. The toast is shown through Windows PowerShell 5.1.
- **Notification shows under a generic name.** The AppUserModelId registration did not take. Check `HKCU\Software\Classes\AppUserModelId\VisumWay.Agent`.
- **Crash is not noticed.** Look in Event Viewer under Windows Logs and
  Application for an `Application Error` record for `python.exe`.
  Check the installed event task and `visumway events` for a cooldown
  or budget decision. Run `visumway bridge run windows-events` to
  diagnose a native event query failure.
- **A graphics timeout is missing.** Windows can report it as Display 4101
  in System or as Windows Error Reporting 1001 with `LiveKernelEvent` code
  `117` in Application. Run `visumway bridge install windows-events` to
  refresh an older installation's subscription. See
  [the Windows verification results](VERIFICATION.md) and
  [Microsoft's description of `VIDEO_TDR_TIMEOUT_DETECTED`](https://learn.microsoft.com/windows-hardware/drivers/debugger/bug-check-0x117---video-tdr-timeout-detected).
- **Clicking opens nothing.** Read the output of `visumway open <incident id>`
  to check the incident and terminal launcher. To test Windows protocol
  dispatch separately, use PowerShell `Start-Process 'visumway://open/<incident id>'`.
  Check `HKCU\Software\Classes\visumway\shell\open\command`.
- **The agent opens without the conversation.** The session could not be resumed from the workspace folder. `visumway incidents --json` shows whether a session id was captured (`resumable`).
- **A console window flashes.** Something is being started without the no-window flag. Note which step.

## Remove everything

```
visumway uninstall --purge
```
