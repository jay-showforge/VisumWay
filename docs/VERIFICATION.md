# Verification record

What has actually been run, where, and what has not. Update this file whenever something is exercised on a real machine. Do not move a line up a level without doing the run.

## v0.2.6 — Shared setup without a wake adapter

- The same isolated CLI and MCP smoke passed on Windows and Ubuntu under
  WSL. An unrecognized local agent set up the shared tools, a second
  agent reused the installation with the configuration unchanged, and
  the foreground listener logged a test crash for the second agent to
  read over MCP. No model wakes occurred.
- The smoke used disposable homes and a foreground listener. It did
  not test native Linux desktop capture, login registration, or live
  event collectors. macOS setup and capture still need host validation.

## v0.2.5 — Read Windows controls directly

- Built and installed the offline Windows x64 bundle in a fresh Python
  environment. Native control inspection reported a button's name, role,
  coordinates, and both disabled and enabled states as the fixture
  changed. The list limit, truncation flag, and unknown-name case were
  also checked.
- On the same disposable window, nine named-control reads took a median
  of 84.6 ms and returned 579 bytes over MCP. Nine 820-pixel window
  captures took a median of 357.8 ms and returned 49,025 bytes. These
  are local tool measurements before model processing.
- A signed-in Codex turn used the installed accessibility bridge to
  recover the randomized ticket, button state, and exact coordinates.
  The trace recorded no image payloads.
- Native snapshot and buffered watch stop, expiry, and disconnect
  checks passed. All 87 runnable Windows regression tests passed
  across the regular suite and the loopback test rerun. Four
  POSIX-only tests were skipped.

## v0.2.4 — Windows buffered watch

- Built the helper from source and installed the offline x64 bundle into
  a fresh Python environment. Windows Graphics Capture returned a native
  snapshot and buffered frames. Explicit stop, lease expiry, and a
  disconnected stdin each stopped the helper.
- Ran a signed-in Codex turn against the installed bundle and a
  disposable game. Codex read the random ticket and local diagnostic
  code, spotted a clipped button, moved it through a fixture-only
  action, and verified the whole button in the updated image.
- The buffered watch sampled at a maximum of 8 fps. Codex read all
  three randomized game states in order. The middle state lasted
  552 ms and disappeared during an 18-second period without a watch
  read. The next read returned the two queued images in 3.5 ms at
  the MCP transport, with zero retained changes missed. A repeat read
  of the unchanged window returned 305 bytes of metadata and no image.
  The earlier sampled watch had missed its equivalent middle state.
- All 86 runnable Windows regression tests passed across the sandboxed
  suite and the localhost notification rerun. Four POSIX-only tests
  were skipped. The GitHub workflow has yet to run for this build.

## November 17, 2026 — v0.2.3 release review

- All 85 runnable tests passed across the Windows suite and focused
  reruns. Four POSIX-only tests were skipped. The loopback notification
  test passed separately with localhost networking available.
- Tests covered first setup, read-only reuse by another agent, shared
  MCP access, notification ownership, and discarding queued reports on
  pause. The installed wheel exposed capture and events to both
  Codex- and Claude-labeled sessions. Only the installing agent could
  see or call `notify_user`.
- An offline Windows x64 ZIP installed into a fresh Python 3.13 environment
  and a disposable VisumWay home. The native helper passed its protocol
  check and listed desktop, display, and window targets. A regression test
  confirmed that modified helper bytes are rejected before execution.
- The local ZIP uses the reviewed v0.2.1 helper with SHA-256
  `833c3ece43ceea552abc580cf861edbac9cd39f9fc3195df6cebe4a85010dc32`.
  The GitHub workflow is prepared to compile the helper from source and
  attest the bundle. It has not run for this candidate.
- The signed-in background wake and click-through evidence below applies
  to v0.2.1. The v0.2.3 review used stand-ins for Codex and Claude Code.

## Levels

- **A. Real**: run on a real machine of that kind, with the real component.
- **B. Stand-in**: the real VisumWay code ran end to end, with one external component replaced by a stand-in (a fake agent CLI, a fake notifier, sample event-log records).
- **C. Written only**: implemented from documentation; never executed on its target.

## Linux (cloud VM, Python 3.13, headless)

| What | Level | Notes |
| --- | --- | --- |
| Test suite, 54 tests | A | `python -W error -m unittest discover -s tests -t .` |
| Host scan, plan, config, CLI, MCP server | A | |
| Reflex runtime: rules, aggregation, cooldown, budget, restart | A | Idle cost measured: ~22 MB, 0.03% of a core |
| Zero model calls while idle | A | Guarded by `test_idle_makes_no_model_calls` |
| Whole chain: setup, runtime, crash event, model message, click, session resumed, uninstall | B | Real commands and a real running runtime. Two stand-ins: the agent CLI was a shell script named `claude`, and the crash was an emitted `app.crash` event, not an OS-detected crash |
| Agent discovery: installed / signed in / verified, re-verify on version change | B | Stand-in `claude` and `codex` |
| Reading Claude Code's JSON reply and session id | B | Reply shape taken from a real `claude -p --output-format json` run (v2.1.325) |
| Authentication failure is reported as a system notice, not as the AI | B | The real CLI returns exit code 0 with `is_error: true` when not signed in; that real output is a test fixture |
| Notification with buttons, click dispatched to Later | B | Real code path with a stand-in `notify-send` |
| Later: redelivered after the snooze with no model call | A | |
| ntfy and webhook delivery | B | Against a local HTTP server |
| A real model waking and writing a message | Not done | The Claude Code CLI in the build environment was not signed in |
| A real notification on a real desktop | Not done | Headless machine |
| systemd user service | C | Unit file generated, not started |

## Windows 11 Home, build 26200

This Windows laptop has an Intel Core i5-1240P, 16 logical processors,
15.7 GiB of RAM, Intel Iris Xe Graphics (driver 32.0.101.7092), and the
interactive Windows Explorer/DWM desktop. Discovery found Codex CLI
0.169.0-alpha.11.1 (bundled with ChatGPT desktop 26.1111.2228.0),
Claude Code, Gemini CLI, and Ollama. Only Codex was used for inference.
Native interfaces exercised include Task Scheduler, Windows Event Log,
Windows PowerShell and Shell COM, WinRT toasts, GDI capture, and local
Codex App Server stdio.

### Verified on this machine

| What | Evidence |
| --- | --- |
| Windows installation | `visumway --version` reported 0.2.1. The current-user interactive logon task started and produced a live heartbeat. Native Windows event and logon tasks ran without administrator rights. Linux and macOS event bridges were skipped. |
| Automatic startup after reboot | Windows booted at 8:38:30 p.m. Pacific on November 15. Task Scheduler launched the listener at 8:38:56 p.m., and its live heartbeat was confirmed before any manual start. |
| Real Windows crash on battery | `crashtest` called Windows fail-fast in a dedicated Python child. Application Error 1000 records 11503 and 11505 were collected after replacing battery-blocked legacy tasks, with one successful scheduled run and one aggregated wake. |
| Native event and wake budget after reboot | The task handled Application Error record 11606 and exited successfully. VisumWay recorded the event with the same listener process. The hourly budget persisted and blocked the wake, leaving the total at four. |
| Codex reply after reboot | Temporarily raised the hourly limit from four to five and reloaded the scheduled listener. Windows Application Error record 11612 queued one Codex turn. The `VisumWay alerts` chat completed the turn with a reply identifying `libffi-8.dll` as the reported faulting module. The normal limit of four was restored on the running listener. No matching Notification Center entry was found for this turn. |
| Visible app popup after reboot | With File Explorer in front and Windows accepting banners at both trigger and Codex handoff, Application Error record 11616 reached the `VisumWay alerts` chat. Codex completed the turn, and the user confirmed seeing the popup. The test allowed one extra wake at an hourly ceiling of six and restored the normal ceiling of four on the running listener. No matching Notification Center database entry was found when queried. |
| Quiet ChatGPT startup after reboot | Windows booted at 10:07:22 p.m. Pacific on November 15. The existing Windows Startup Apps entry launched ChatGPT at 10:09:06 p.m. The observer recorded zero unminimized or foreground ChatGPT windows in 189 samples. After both the app and the listener were running, a 60-second idle interval produced zero VisumWay wakes and zero new task or token records in the alerts chat. |
| Alert readiness after quiet startup | Application Error record 11735 reached Codex's saved alerts-chat queue. During the 70-second follow-up no turn or popup appeared. The desktop app later reported the alerts chat as `notLoaded`. The installed app used a private stdio App Server and did not have a shared control socket. The documented chat deep link opens a window. No supported quiet preload was verified. |
| Existing ChatGPT sign-in | `codex login status` returned ChatGPT login. The read-only headless probe completed and captured a saved session. The real crash wake returned a model-generated message. |
| Original VisumWay toast | The user saw the VisumWay popup. Windows stored the model's reply and the incident-specific Investigate and Later actions. Windows shell activation of the registered incident URL opened an interactive Codex process with the exact saved session ID. |
| Desktop chat continuity | The registered `codex://threads/<uuid>` deep link loaded the saved crash session in the ChatGPT desktop app. The desktop app read back the original completed turn and reply. |
| ChatGPT's own notification | A real crash (Application Error record 11508) went through Task Scheduler and VisumWay's local App Server queue. The loaded `VisumWay alerts` chat completed the turn. Windows Notification Center recorded the exact model reply under `OpenAI.Codex_2p2nqsd0c76g0!App`, including ChatGPT's inline Reply action. The separate VisumWay toast channel and its shell registrations were removed from this install. |
| Visible app popup and click | Windows showed ChatGPT banners enabled and Do Not Disturb on. ChatGPT was added to the allowed priority apps. The repeat crash (record 11512) produced a Notification Center entry headed `VisumWay alerts`, but the user missed the banner. After ending desktop automation, Windows reported it was accepting notifications. A separate manual retest queued into the same chat, and the user confirmed seeing the app's popup and clicking it to open `VisumWay alerts`. |
| Process and visual bridges | Enumerated live Windows processes and captured a nonempty frame through the PowerShell GDI backend. |
| Idle model activity | The live runtime advanced its heartbeat for 98 seconds with the same PID and no change to the wake files or persisted wake budget. The offline idle test also asserts zero agent invocations. |
| Offline regression tests | `python -W error -m unittest discover -s tests -t .` on Windows, Python 3.13.5. 68 discovered, 64 passed, and four POSIX shell cases skipped. |

### Windows native visual bridge

Tested locally on the same Windows 11 laptop with Intel Iris Xe integrated
graphics. The native executable was built for x64 using Visual Studio Build
Tools and Windows SDK 10.0.26100. The Windows visual helper was installed in
the existing VisumWay home after passing the live test in a temporary home.

| What | Evidence |
| --- | --- |
| Discovery and installation | A temporary home detected the desktop fallback first. After installing the helper, discovery listed Windows Graphics Capture and the plan reported the executable as present with verification still required. |
| Whole desktop and individual display | Fixed Windows DPI virtualization in the PowerShell GDI fallback. Its unscaled PNG then matched the real 1920×1080 display instead of the 1280×720 logical desktop. A bounded desktop request produced 640×360. The native display produced 800×450 using D3D11. |
| Application window | Captured the test window with the CLI. The PNG was 650×393 and decoded to the known fixture's colors and text. Verified occlusion on the live display and confirmed that the MCP response still contained the selected window's pixels. |
| CPU-only renderer | Forced WARP on the selected window. It produced a 480×290 PNG with the fixture's expected pixels. The capture session still ran on Windows' compositor. |
| Invalid surfaces and cleanup | The live helper rejected a minimized window and a window marked `WDA_EXCLUDEFROMCAPTURE`. It created no PNG for those requests. After the MCP request, its temporary image directory was empty. Removing the native helper in the temporary home left the desktop fallback available. |
| Existing installation | The live `visumway verify` passed both visual checks, the eight-tool MCP handshake, the zero-token wake-path self-test, and the persistence check. The existing listener PID and config hash matched before and after. The wake count stayed at six and no visual helper process remained after the requests. |
| Regression suite | Windows, Python 3.13.5. 73 tests discovered, 69 passed, and four POSIX-only cases skipped. The Windows helper build was added to CI. Remote CI and the new native path on other operating systems were not run in this pass. |

### Real Codex eyes-and-body test

The existing ChatGPT sign-in ran one supervised Codex CLI turn with the
VisumWay MCP tools. API-key environment variables were stripped. The test
used the installed Windows helper and the installed Task Scheduler event
bridge. A disposable native window displayed two randomly chosen ticket
numbers. The prompt supplied the fixture's process name. The ticket numbers,
labels, colors, and counts were available to Codex through the actual
desktop and window pixels. A driver advanced the fixture between samples
and called Windows fail-fast in that fixture only.

| Check | Observed result |
| --- | --- |
| Real desktop interpretation | Codex read “Dispatch Board \| VisumWay Live Fixture” and identified the Windows taskbar and Search box from the whole-desktop image. |
| Real window interpretation | Codex read `VW-27578`, `READY TO EXPORT`, `Export report` and queue depth 2 in the first window sample. It read `VW-89589`, `EXPORT PAUSED`, `Retry export` and queue depth 7 in the changed sample. |
| Track a change | A single watch returned `changed` at sequence 1, `unchanged` at sequence 1, `changed` at sequence 2, `unchanged` at sequence 2, then `unavailable`. Windows Graphics Capture returned two 1400×735 images. Duplicate and unavailable samples carried no image. |
| Relate the display to Windows activity | Codex matched selector `window:1574010:15152` to `VisumWayEyesFixture.exe` by PID 15152. It checked that the process disappeared and retrieved the installed event bridge's actual Application Error 1000, record 11757, with PID 15152, faulting module `VisumWayEyesFixture.exe`, and exception `0xC0000602`. |
| End the watch and return to idle | The unavailable sample closed the watch and the one-turn CLI exited. A subsequent 60.4-second observation found no visual helper, no new wake logs, and zero new turn or token markers in the alerts chat. The installed listener's heartbeat continued. |
| Local Codex registration | Registered the installed `visumway mcp` command in the shared Codex configuration. The live LLM evidence is from the CLI; it does not depend on a separate ChatGPT desktop test. |
| Alert on the same event | The fixture's crash queued a wake in the saved chat. The queue entry was still pending and no matching ChatGPT notification was found. Only that test entry was removed. |
| Final Windows checks | `visumway verify --json` passed the eleven-tool MCP handshake, desktop and display captures, process check, installed event and runtime checks, and zero-token wake-path self-test. It retained a warning for the saved-chat popup. The offline regression suite passed 72 tests and skipped four POSIX-only cases. |

The first CLI attempt exercised the approval check and got no images.
The test rerun enabled only the observation tools with Codex's per-server
`writes` approval mode. The tools are marked read-only and the real run
used the read-only sandbox. This testing override was scoped to that
invocation. The watch samples on request and filters duplicate deliveries.
Continuous video and changes between samples were outside the live test.

### Remaining host checks

- Inline Reply was present and was not exercised.
- Verify a supported quiet alerts-chat preload and then repeat the cold
  tray-start test for ChatGPT-owned completion banners. The independent
  VisumWay toast was verified separately.
- Linux and macOS desktop-watch host tests and native target capture, and
  continuous native streaming.

### Independent Windows alerts

This run used `visumway setup --windows-background` with the same installed
Codex CLI and existing ChatGPT account. The setup switched this PC off the
saved-chat queue, registered the `VisumWay.Agent` Windows sender and its
protocol handler, and restarted the per-user listener. ChatGPT's Windows
startup setting stayed enabled.

| Check | Observed result |
| --- | --- |
| ChatGPT open | Application Error 1000 record **11778** named the fail-fast test child, PID 8396. The scheduled event listener woke Codex, which wrote a reply identifying `libffi-8.dll` and saved a new session. Windows stored the matching reply and incident link under `VisumWay.Agent`. The user confirmed the popup appeared. |
| ChatGPT minimized | Windows confirmed the app window was minimized when fail-fast record **11781** was triggered (PID 16504). Codex returned in 11.3 seconds and saved the session. Windows stored the exact model reply under `VisumWay.Agent`. The user saw the banner and clicked it to open the crash chat. The protocol handler recorded `opened_surface: codex-app` for that session. |
| Real reboot and automatic startup | Windows rebooted at 11:21:27 p.m. Pacific. The listener started automatically about 37 seconds later. After 60.5 seconds with zero wakes, the test triggered Application Error 1000 record **11845** (PID 11348). No ChatGPT process was present at the trigger. Windows recorded a ChatGPT process starting at 11:23:33 p.m., about two seconds before VisumWay wrote its outbox entry. The user saw the independent popup before any ChatGPT tray icon appeared. Clicking the popup opened the desktop app to the matching Codex session, and the ChatGPT icon then appeared in the tray. |
| Idle after the reboot wake | The clicked session showed the completed crash turn and was idle. During a separate 60.2-second interval after the click, the listener's heartbeat advanced with zero new VisumWay wakes and no visual-helper activity. |
| Earlier fully quit attempt | The original ChatGPT process from sign-in was still running. The one-shot observer withheld the crash and was removed. See the successful November 16 retest below. |
| Windows permission validation | The real WinRT notifier reported `Enabled`, and the relevant task actions and user-scoped protocol matched the installed home. The regression suite covers Windows reporting disabled notifications. |
| Setup, recovery, and purge | A disposable home with spaces in its path installed the event and sign-in tasks, shell registrations, and the native visual helper. VisumWay detected a missing Start Menu shortcut, and rerunning setup repaired it. A second home was refused control of the owned tasks and click registration. A real `uninstall --purge` removed the disposable home, both tasks, the shortcut, the notification identity and protocol, and the helper. The original install was restored and live verification passed. The final lifecycle run preserved its configuration byte-for-byte. |

The disposable install did not modify the separately registered Codex MCP
entry or the signed-in account. The previously verified Eyes & Body session
used the same Windows helper. The restored installation passed the real
desktop and display capture checks and the eleven-tool MCP handshake.
After the reboot, the registered VisumWay MCP tools also worked directly
from the desktop Codex session. They listed native capture targets and
returned the same crash record by executable name.
The Windows regression suite passed 74 tests. Four POSIX-only cases were
skipped.

### Windows release retest, November 16

| Check | Result |
| --- | --- |
| Windows regression suite | 81 passed, 4 POSIX-only tests skipped. Windows ran the local loopback and process tests. |
| Reviewed native helper | Reviewed `bridges/windows-visual/capture.cpp` and rebuilt with Visual Studio Build Tools. Two separate output directories produced the same executable SHA-256, `833c3ece43ceea552abc580cf861edbac9cd39f9fc3195df6cebe4a85010dc32`. The installed helper uses those bytes. |
| Native desktop and window capture | The rebuild passed a real 1920×1080 desktop capture, Windows Graphics Capture through D3D11 on Intel Iris Xe, individual and occluded window capture through MCP, WARP software rendering, and rejection of protected/minimized targets without desktop fallback. |
| Real signed-in Codex visual retest | Codex read tickets `VW-84625` and `VW-22540`, the state and button changes, and queue depths 2 and 7 from a native test window. The bridge suppressed duplicate frames. Codex named the GPU, driver, backend and renderer, correlated watched PID 17904 with actual crash record 11921, and stopped the watch. A fresh whole-desktop model run was withheld because the fixture could not reliably cover the desktop. Native desktop capture passed separately. The follow-up model sample still listed the crashing window, so this run provides crash correlation and not a new proof of when the window disappears. |
| Real Windows crash burst | Three distinct fail-fast children produced Application Error 1000 records 11924, 11925 and 11926. The installed listener recorded one queued event and two aggregated events, then one successful signed-in Codex wake with count 3 and native Windows delivery. |
| Clean wheel install and runtime recovery | A freshly installed wheel in a clean virtual environment and disposable VisumWay home passed all live checks using the existing Windows profile and signed-in Codex. Unplanned termination initially reproduced a Task Scheduler restart failure. With the recovery trigger, Windows replaced listener PID 3292 with PID 18736 in 54 seconds with zero model wakes. Repair and purge passed. The original home and configuration were restored byte-for-byte. |
| Idle after the retest | For 60.4 seconds after restoration, the listener PID stayed the same and its heartbeat advanced. Across 60 samples there were no visual-helper processes, no new wake logs and no growth in the completed Codex burst session's transcript. |
| Real retained hang records | The collector parsed Windows Application Hang 1002 records 8003, 9556 and 11082 from the actual Application log. A second isolated read emitted zero duplicates. |
| First hang test | Windows reported the disposable window as hung. The test's close request stalled, and the owned fixture was terminated during cleanup. No matching new Application Hang 1002 record reached the listener in this attempt. |
| Account and data handling | An empty temporary `CODEX_HOME` was reported signed out and refused inference. A nonexistent Codex command was reported unavailable. The installed default home and event log had no allow entries for Everyone, Authenticated Users or built-in Users. Tests verified credential-field redaction, strict event-report framing, and safe notification arguments. |
| Fully quit desktop test | The first observer timed out and withheld the crash. The retry took 186 process samples through click, with zero ChatGPT desktop processes seen before the trigger and through delivery. Native Application Error 1000 record **11960** matched fixture PID 25364. The installed listener woke signed-in Codex in 9.045 seconds and Windows stored the exact reply as a `VisumWay.Agent` toast, 16.55 seconds after the trigger. The first ChatGPT process was observed starting 5.77 seconds after Windows stored the toast. The user clicked it and confirmed it worked. The incident opener and the desktop app both resolved the same session, which contained the completed crash reply and was idle. Over the next 60.1 seconds the same listener advanced its heartbeat with zero new wakes and no visual-helper activity. |

### Full desktop, new Windows profile, and driver recovery, November 16

| Check | Result |
| --- | --- |
| Full desktop through the installed visual bridge | A full-screen fixture showed a randomly selected ticket and status. The installed MCP desktop capture returned a 1400×787 image. Signed-in Codex read ticket `569776`, identified the application-status panel, and read “Waiting for review” from the frame. Both values matched the fixture after the reading. The test closed the fixture. |
| Separate, initially empty Windows profile | Windows loaded a newly created standard local user's profile. Offline wheel installation, host discovery, native visual bridge installation, and VisumWay purge succeeded. The profile had no Codex command or configuration, so Windows background setup stopped before binding an agent and recorded no wakes. The disposable account, Windows profile, and staging files were removed. The signed-in workflow was exercised in the existing Windows profile. |
| Real GPU timeout and recovery | The administrator-approved Microsoft DXCap test reset the integrated Intel Iris Xe device. The running D3D11 device returned `0x887A0007` and a new hardware device initialized successfully. Windows emitted Error Reporting records `11969` and `11970` for the same `LiveKernelEvent` report with code `117`. The host did not produce Display 4101. |
| Graphics bridge retest | After adding the `LiveKernelEvent` 117 subscription, a second real GPU reset produced records `11972` and `11973` for one Windows report. The installed listener collected `11972` and skipped the archived copy. Signed-in Codex returned one message, and Windows stored the exact text as a native `VisumWay.Agent` toast linked to the graphics incident. The user reported no visible banner from this delivery. |
| Visible graphics banner and exact resume | With desktop automation released, Windows reported accepting banners and the user brought File Explorer forward. Redisplaying the saved model response through the same Windows notification bridge produced a visible banner. The user clicked its body and confirmed it opened the graphics chat. VisumWay recorded `codex-app` opening the matching session. Redisplay used the saved incident and consumed no model call. |
| Recovery and idle after graphics delivery | For 60.7 seconds the listener advanced its heartbeat with zero new wakes and no visual-helper processes. One check reported desktop composition temporarily unavailable while whole-desktop GDI capture still passed. A later native 640×360 monitor capture succeeded on the D3D11 path and all installed health checks passed. |
| Fresh application hang | Earlier attempts produced no 1002 record. In the successful retest, the user chose **Close the program** in the Windows hang dialog. Windows closed the fixture and emitted Application Hang 1002 record `11978` with PID `24796`. The installed listener collected it, signed-in Codex generated a reply in 8.374 seconds, and Windows delivered it through the native toast bridge. Activating that notification opened the matching Codex session. |
| Idle after hang delivery | The same runtime advanced its heartbeat for 60.9 seconds with zero new wakes and no visual-helper processes. |
| Regression suite after the graphics repair | 82 passed and four POSIX-only tests were skipped. The Windows suite exercised migration to the new event query, duplicate report handling, and rejection of unrelated kernel reports. |

## macOS

Level C throughout. Notifications are basic and have no click actions.

## Agent CLIs

| Agent | What was checked | Still to confirm |
| --- | --- | --- |
| Claude Code 2.1.325 | `claude -p --output-format json` reply shape, `claude auth status` JSON, `--resume` flag present in `--help` | A signed-in headless run; resuming a headless session interactively from the same folder; behaviour on Windows |
| Codex CLI | Signed-in read-only `exec` and real Windows wakes on 0.169.0-alpha.11.1. Verified native alerts and exact chat resume after reboot and with ChatGPT fully quit through delivery. | Live Linux and macOS |
| Ollama | Nothing run | Model name must be set in `config.json` |

### Windows single-agent binding

- A real Codex CLI probe completed with the existing ChatGPT account and
  captured a resumable session. The installed listener was reloaded with
  Codex as its single selected adapter. Its configuration was preserved
  byte-for-byte, and the eleven-tool MCP handshake, native Windows notifier,
  click registration, event task, and desktop/display capture checks passed.
- Claude Code 2.1.138 reported a local first-party Claude account. Its isolated
  live request failed with `401 OAuth access token is invalid`. Claude's real
  Windows delivery and resume remain unverified. Codex remained selected
  throughout the isolated attempt.
- The Windows regression suite covers explicit selection with multiple
  available accounts, rejection of conflicting wake rules, and routing the
  click to the original incident adapter after a switch. It also checks that
  a missing adapter cannot send a click to a different provider.

## Known limitations

- The optional Codex app queue needs a loaded chat for ChatGPT's own
  completion banner. The independent Windows toast can be delivered with
  ChatGPT fully quit and opens the configured app or terminal on click.
- Claude Code and the Claude desktop app keep separate sign-ins on the same account. The user signs in to Claude Code once.
- A woken agent runs with the agent host's default non-interactive permissions, and its reply is the message. Those defaults are expected to prevent unattended changes to the system (Claude Code declines tools that need approval; Codex runs in its read-only sandbox). Confirm this in the real runs before relying on it.
- Toasts need the runtime to be in the user's desktop session. It is, because it starts at sign-in as a scheduled task. It would not work as a system service.

## 2026-11-15 v0.2.1 cross-platform development pass

The v0.2 ZIP was independently extracted and its original 54 tests passed in
this Linux container. Then platform adapter work was added:

- macOS `.ips` / `.crash` / `.hang` report parser, launchd `WatchPaths` job,
  first-run baseline and duplicate suppression — **unit-tested only, NOT on macOS**.
- Linux user-journal crash-hint reader, baseline/cursor tracking, systemd user
  timer — **unit-tested with simulated journal JSON, NOT installed on real desktop**.
- Linux XDG autostart fallback and XML-safe macOS LaunchAgent config —
  **generated and parsed on Linux; user login behavior still untested**.
- Windows toast AUMID Start Menu shortcut creation via built-in Shell COM —
  **script and metadata inspected on Linux; NOT run on Windows**.
- macOS optional `terminal-notifier` click command — **argument quoting and
  incident validation tested with a stand-in; NOT shown on macOS**.
- Claude/Codex unattended wake guard now refuses missing/unknown/API-key-only
  authentication for the shipped provider CLI commands. This was tested with
  stand-in login responses, not with real signed-in provider CLIs.
- Host plan no longer considers an installed screen-capture executable proof
  that a graphical frame can actually be captured.

This earlier pass used stand-ins. The Windows host pass above records later
live results.

On a headless Linux runner without systemd user services or a graphical login,
setup now reports persistence as unavailable rather than silently installing an
XDG autostart file that would never run. The target host can still use
`visumway init` and `visumway verify` for non-GUI checks.
