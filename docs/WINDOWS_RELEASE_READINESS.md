# Windows release readiness

The v0.2.5 candidate adds direct Windows accessibility inspection.
Signed-in Codex read a fixture's ticket and exact control state and
bounds without an image. See the [verification record](VERIFICATION.md).

The v0.2.4 candidate added a native buffered window watch. The signed-in
Codex test recovered a brief visual change between model requests. See
the [verification record](VERIFICATION.md#v024--windows-buffered-watch).

The v0.2.3 candidate established notification ownership with the installing
agent. Other agents reuse the same tools. Fresh installs opt in to
automatic wakes. The [offline x64 bundle](WINDOWS_BUNDLE.md) passed installation
and native target enumeration. See the [release review](VERIFICATION.md)
for the checks still pending. The signed-in Windows results below were
recorded with v0.2.1.

The independent alert build is ready for review as a Windows release
candidate validated with signed-in Codex.

## Latest Windows retests

| Status | Checks |
| --- | --- |
| Passed with signed-in Codex | The full-desktop retest used the installed visual bridge. Codex correctly read the randomized ticket and application status from the returned frame. This complements the earlier live window-watch and crash correlation. |
| Passed with signed-in Codex | Two real graphics timeouts reset the Intel Iris Xe D3D11 device. The first exposed a missing Windows Error Reporting event path. After the repair, the second reached the installed listener, woke Codex once, and Windows stored its native notification. The user saw a banner when the saved alert was redisplayed and clicked it to open the exact graphics chat. |
| Passed in a fresh standard local Windows account | Offline installation, host discovery, native visual bridge installation, and purge passed. Background setup stopped before binding because the account had no Codex command. The test recorded zero wakes and removed the temporary account, profile, and staging files. |
| Passed with signed-in Codex | Closing the disposable “Not Responding” window through the Windows dialog produced Application Hang 1002. VisumWay matched the live process, woke Codex once, delivered the model reply through the native notification bridge, and opened the exact Codex chat on activation. |
| Regression suite | 82 passed and four POSIX-only tests were skipped. |

## November 16 release retest

| Status | Checks |
| --- | --- |
| Passed on Windows | Rebuilt the included Windows x64 helper twice with identical executable hashes. Live checks covered 1920×1080 desktop capture, selected and occluded windows, integrated Intel Iris Xe through D3D11, WARP software rendering, and protected target rejection. |
| Passed with the signed-in Codex model | A real window watch supplied changing frames and skipped duplicates. Codex read both ticket numbers and state changes, identified the GPU and capture backend, matched the window PID to crash record 11921, and stopped the watch. Windows delivered one native message from three additional crashes aggregated into a single wake. |
| Passed on Windows | The real CLI reported an empty, isolated login environment as signed out. VisumWay blocked that invocation and also rejected an unavailable agent command. Actual retained Application Hang records were parsed without replaying duplicates. |
| Passed after repair | The first listener crash-recovery run timed out. In a fresh wheel install with the revised scheduler, Windows replaced the terminated listener in 54 seconds without a model wake. The clean environment passed every bridge check, a signed-in probe, repair, and purge. |
| Passed on Windows | The restored listener stayed active for a 60.4-second idle sample with zero new model wakes, zero visual-helper activity, and zero growth in the completed test session. |
| Passed with ChatGPT fully quit | Crash record 11960 triggered a signed-in Codex reply and a native VisumWay popup while the observer saw no ChatGPT desktop processes. The user clicked the banner, opening the exact saved Codex chat. The listener stayed active with zero new wakes and no visual-helper activity in the next 60.1 seconds. The earlier closed-app attempt had timed out. |
| Earlier attempts | The first full-desktop observation was withheld because the fixture could not cover the desktop. The replacement fixture passed in the latest retest. The hung fixture produced no Application Hang 1002 event. |
| Skipped | Four POSIX-only cases in the Windows unit suite. Linux and macOS host testing was outside this review. |

The exact event record IDs and built-helper hash are in [Verification](VERIFICATION.md).

## Verified on Windows 11

- This PC uses its existing ChatGPT account and Codex CLI. Windows reported
  real Application Error 1000 records 11778 and 11781. The installed listener
  applied its existing budget and started one bounded Codex turn per event.
- With ChatGPT open and with it minimized, the Windows notification system
  displayed the model-generated message under the VisumWay sender. The user
  clicked the minimized test's banner and the exact saved Codex chat opened.
- After a real reboot, VisumWay started at Windows sign-in and stayed idle
  for 60 seconds. A real crash then produced an independent notification
  before the user saw a ChatGPT tray icon. Clicking opened the correct
  Codex chat in the desktop app, and the tray icon appeared. VisumWay
  recorded zero new wakes during a second 60-second interval after the alert.
- Installation, repair after a missing shortcut, refusal to remove another
  installation's registrations, and full VisumWay purge passed in a temporary
  Windows home. The original configuration, listener, and visual helper were
  restored. The registered Windows notification permission reported Enabled.
- The original signed-in Eyes & Body run remains recorded in
  [Verification](VERIFICATION.md). Live checks after restoration confirmed
  Windows desktop and display capture and the eleven-tool MCP interface.
  After reboot, the desktop Codex session used the installed MCP to list
  native capture targets and look up the recorded Windows crash. The
  bundled Windows x64 helper is the same tested binary.
- The full Windows offline regression suite passed 74 tests. Four POSIX-only
  cases were skipped.
- The single-agent update kept Codex as the sole installed wake binding.
  A signed-in Codex probe and the full installed bridge checks passed.
  The update's regression suite passed 78 tests and skipped four POSIX-only cases.

## Scope of this release review

- Codex is the live validation agent for this build. The capture, event,
  and notification bridges are shared. Account detection, invocation, and
  session resume depend on the selected agent adapter.
- The separate fresh Windows profile was an offline installation test. The
  signed-in notification, click, and reboot tests used the existing account.

## Local installation and removal

Follow the [Windows validation guide](WINDOWS_DEMO.md). Use
`visumway setup --agent NAME` to bind the installation
to a single signed-in agent and use independent Windows notifications. A
click uses the incident's own adapter. The Codex app deep link is optional.

`visumway uninstall --purge` removes the VisumWay home, runtime, and native
bridge registrations. If you added the Codex MCP server separately, use
`codex mcp remove visumway` to unregister that entry. To remove the Python
package too, run `python -m pip uninstall visumway` using the Python that
installed it.
