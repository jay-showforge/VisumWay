# Windows visual bridge

VisumWay discovers the capture tools on the host and records the next step in
`visumway plan`. The Windows visual helper is a separate executable. It
lists displays and application windows and uses Windows Graphics Capture to
collect one requested frame. The Windows desktop fallback continues to use
GDI through Windows PowerShell.

## Install the helper

Use a normal interactive Windows session and an existing VisumWay installation.
Run the commands from the repository root. Start with `visumway discover`
and `visumway plan` to check the host and the helper's installation state.

The [verified Windows x64 bundle](WINDOWS_BUNDLE.md) installs the helper
with the Python CLI.

To build locally, use Visual Studio Build Tools with Desktop development
with C++ and a Windows SDK that includes C++/WinRT (tested SDK 10.0.26100).
Use the installer for the host architecture. The build and capture are
local operations.

```powershell
& .\bridges\windows-visual\build.ps1
$helper = '.\build\windows-visual\windows-visual.exe'
$digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $helper).Hash
visumway bridge install windows-visual $helper --sha256 $digest
visumway bridge list
visumway verify
```

For a downloaded executable, obtain the expected hash from its verified
bundle or another trusted source. The installer checks the staged hash
before running the executable's protocol check, then installs it in
`<home>/bridges/windows-visual.exe`. The helper requires an interactive
Windows desktop and the Windows Graphics Capture API (window and monitor
interop requires Windows 10 version 1903 or newer). It tries the default
D3D11 adapter and uses Windows' WARP software renderer if hardware device
creation fails. No service registration is needed for the visual helper.
[Microsoft's window capture API](https://learn.microsoft.com/windows/win32/api/windows.graphics.capture.interop/nf-windows-graphics-capture-interop-igraphicscaptureiteminterop-createforwindow).

## Request a frame

```powershell
visumway capture --list
visumway capture .\desktop.png --max-edge 1600
visumway capture .\selected.png --target '<id returned by --list>' --max-edge 1200
```

IDs are valid for the current desktop session and can change when displays or
windows are recreated. To identify a window use its process ID and bounds.
The listing also marks the foreground window and primary display. It omits
window titles and does no capture. Minimized, cloaked, and protected windows
are excluded. Windows controls which content it exposes. If a specific target
fails, select it again after restoring it.

An agent host using `visumway mcp` can call `list_capture_targets` and then
`capture_screen` with the returned ID as `target`. Omit `target` for a
desktop frame. `max_edge` defaults to 1600 pixels in the Windows MCP tool.
The tool returns PNG image content and removes its staging files. The shell
command saves the image to the requested path and returns its dimensions,
backend, and native renderer where applicable.

Each capture ends after one frame. No helper process, frame pool, or timer
runs between calls. Windows' built-in capture indicator remains enabled.

## Read controls directly

Use `inspect_window` with a Windows window selector from
`list_capture_targets`. It reads the app's accessibility tree and
returns control labels, roles, enabled and focused state, selection or
toggle state where available, and screen bounds. Pass `name` to get the
first case-insensitive exact label match. Without a name it lists up to
24 controls by default and reports if traversal was truncated.

Use the labels and state to decide what to do next. Use a frame for
graphics, clipping, color, and controls the app does not expose. The tool
does not invoke controls or fetch text field values. Protected controls'
names are omitted, and app text is untrusted data. Control properties
come from [Windows UI Automation](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-cachingforclients).

## Follow a window during an active task

Use `list_processes` to match the app's executable and PID to the selector
from `list_capture_targets`. Use `watch_start` with its window selector and
`mode: "buffered"` to follow changes between model requests. This opens one
native Windows Graphics Capture session. The default maximum rate is
8 frames per second, with an 8-second history of changed images.

Call `watch_read` with the watch ID and `after_sequence: 0`. Pass
`next_after_sequence` back on the next read. If `has_more` is true, keep
reading to see all retained changes. Each frame has an elapsed time and a
`content_index` that points to its image. `missed` counts changes evicted
since that cursor. The helper keeps the history in memory and stops when
the lease expires, the window becomes unavailable, or the MCP connection
closes. Use `watch_stop` as soon as the task is done.

For a sampled watch, use the default `mode: "sample"` and call
`watch_frame` whenever you need a snapshot.

Use `recent_events` with the executable name as `subject` to investigate a
disappeared application. For an Application Error record that names a process
ID, match that ID to the PID in the window selector.

## Check and repair

- A helper listed by discovery proves it is installed. A successful
  `visumway verify` checks both the desktop fallback and a real individual
  display frame when the helper is installed. Use `capture --target` on a
  known window to check the window path.
- If display capture fails, run from the intended interactive session and use
  `capture --list` again. For a missing or incompatible executable, rebuild
  or install the helper for the host architecture.
- Run `visumway bridge remove windows-visual` to remove just the helper.
  Running `visumway uninstall` also removes it. The desktop fallback remains
  available after removing the helper alone.

See [the verification record](VERIFICATION.md) for the tested hardware and
the checks still open.
