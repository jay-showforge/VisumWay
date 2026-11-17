"""Make the reflex runtime persistent: start at login, restart on failure.

After this step VisumWay the setup tool is finished; the installed runtime
keeps working without it and without any agent session.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from .bridges import wintasks
from .paths import Home
from .proc import NO_WINDOW, run_full

LABEL = "com.visumway.reflex"
TASK = "VisumWayReflex"


def _python() -> str:
    exe = sys.executable
    if os.name == "nt":  # pythonw has no console window
        w = Path(exe).with_name("pythonw.exe")
        if w.exists():
            return str(w)
    return exe


def _stop_windows_listener(home: Home) -> "str | None":
    """Stop the scheduled instance and clear only its stale heartbeat."""
    import ctypes
    from ctypes import wintypes

    from .daemon import read_heartbeat

    hb = read_heartbeat(home)
    pid = hb.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    process = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if process:
        try:
            if kernel.WaitForSingleObject(process, 0) != 0:
                stopped = run_full(["schtasks", "/End", "/TN", TASK], timeout=20)
                if kernel.WaitForSingleObject(process, 10000) != 0:
                    return (stopped["stderr"] or stopped["stdout"]).strip()[:200] or "listener did not stop"
        finally:
            kernel.CloseHandle(process)
    elif ctypes.get_last_error() != 87:  # ERROR_INVALID_PARAMETER means the process is gone.
        return "could not check the existing listener process"
    if read_heartbeat(home).get("pid") == pid:
        home.heartbeat.unlink(missing_ok=True)
    return None


def describe(home: Home, system: "str | None" = None, user_sid: str = "") -> dict:
    """Return {kind, files: {path: content}, commands: [argv]} for this OS."""
    system = system or ("windows" if os.name == "nt" else "macos" if sys.platform == "darwin" else
                        "linux" if shutil.which("systemctl") and Path("/run/systemd/system").exists() else
                        "linux-xdg" if (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
                        and (os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or
                             os.environ.get("XDG_SESSION_TYPE") in ("x11", "wayland")) else
                        "linux-none")
    py = _python()
    if system == "windows":
        path = home.bridges / "windows-reflex-task.xml"
        task = wintasks.definition(py, ["-m", "visumway", "--home", str(home.root), "run"], user_sid)
        return {"kind": "windows-task-scheduler", "files": {str(path): task},
                "commands": [["schtasks", "/Create", "/TN", TASK, "/XML", str(path), "/F"],
                             ["schtasks", "/Run", "/TN", TASK]],
                "remove": [["schtasks", "/End", "/TN", TASK], ["schtasks", "/Delete", "/TN", TASK, "/F"]]}
    if system == "linux-none":
        return {"kind": "unavailable", "files": {}, "commands": [], "remove": []}
    if system == "linux-xdg":
        # The XDG autostart spec is broadly supported by graphical Linux
        # desktops, including machines without a systemd user manager.
        path = Path.home() / ".config" / "autostart" / "visumway.desktop"
        def quote_desktop(value):
            # Freedesktop Desktop Entry Exec quoting (do not use a shell).
            return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
        launch = " ".join(quote_desktop(v) for v in
                          [py, "-m", "visumway", "--home", str(home.root), "run"])
        entry = ("[Desktop Entry]\nType=Application\nName=VisumWay Reflex\n"
                 "Comment=Computer event listener; model inference remains idle\n"
                 "Exec=" + launch + "\nTerminal=false\nX-GNOME-Autostart-enabled=true\n")
        return {"kind": "xdg-autostart", "files": {str(path): entry},
                "commands": [], "remove": []}
    if system == "macos":
        path = Path.home() / "Library" / "LaunchAgents" / (LABEL + ".plist")
        plist = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>%s</string>
  <key>ProgramArguments</key><array><string>%s</string><string>-m</string><string>visumway</string><string>run</string></array>
  <key>EnvironmentVariables</key><dict><key>VISUMWAY_HOME</key><string>%s</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
""" % (xml_escape(LABEL), xml_escape(py), xml_escape(str(home.root)))
        return {"kind": "launchd", "files": {str(path): plist},
                "commands": [["launchctl", "load", "-w", str(path)]],
                "remove": [["launchctl", "unload", "-w", str(path)]]}
    path = Path.home() / ".config" / "systemd" / "user" / "visumway.service"
    import shlex
    unit = """[Unit]
Description=VisumWay reflex runtime (no LLM; wakes the configured agent on significant events)

[Service]
ExecStart=%s -m visumway run
Environment=VISUMWAY_HOME=%s
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
""" % (shlex.quote(py), shlex.quote(str(home.root)))
    return {"kind": "systemd-user", "files": {str(path): unit},
            "commands": [["systemctl", "--user", "daemon-reload"],
                         ["systemctl", "--user", "enable", "--now", "visumway.service"]],
            "remove": [["systemctl", "--user", "disable", "--now", "visumway.service"]]}


def install(home: Home, enable: bool = True, *, restart: bool = False) -> list:
    """Write service files and (optionally) run the enabling commands."""
    spec = describe(home)
    log = []
    if spec["kind"] == "windows-task-scheduler":
        task_exists = wintasks.registration_matches(TASK, home.root, ["run"])
        if task_exists is False:
            return ["FAILED: Windows listener task belongs to a different installation"]
        sid = wintasks.user_sid()
        if not sid:
            return ["FAILED: could not identify the current Windows user SID"]
        spec = describe(home, "windows", user_sid=sid)
        if restart and enable and task_exists:
            error = _stop_windows_listener(home)
            if error:
                return ["FAILED: could not restart the existing Windows listener: " + error]
    if spec["kind"] == "unavailable":
        return ["not installed: no user desktop login or systemd user manager detected; "
                "configure persistence on the target machine"]
    for path, content in spec["files"].items():
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        encoding = "utf-16" if spec["kind"] == "windows-task-scheduler" else "utf-8"
        Path(path).write_text(content, encoding=encoding)
        log.append("wrote %s" % path)
    for argv in spec["commands"]:
        if not enable:
            log.append("run: %s" % " ".join(argv))
            continue
        try:
            if spec["kind"] == "windows-task-scheduler" and not task_exists and "/Create" in argv:
                argv = argv[:-1]  # Never force replacement of an unrecognized task.
            p = subprocess.run(argv, capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
            log.append("%s: %s" % ("ok" if p.returncode == 0 else "FAILED", " ".join(argv)))
            if p.returncode != 0:
                log.append("  " + (p.stderr or p.stdout).strip()[:300])
                if spec["kind"] == "windows-task-scheduler":
                    break
        except (OSError, subprocess.SubprocessError) as e:
            log.append("FAILED: %s (%s)" % (" ".join(argv), e))
    if spec["kind"] == "xdg-autostart" and enable:
        log.append("ok: XDG autostart installed (activates at next graphical login)")
    return log


def remove(home: Home) -> list:
    """Stop the runtime service and delete its definition."""
    spec = describe(home)
    log = []
    if spec["kind"] == "windows-task-scheduler":
        match = wintasks.registration_matches(TASK, home.root, ["run"])
        if match is False:
            return ["FAILED: Windows listener task belongs to a different installation"]
        if match:
            disabled = run_full(["schtasks", "/Change", "/TN", TASK, "/Disable"], timeout=20)
            if disabled["rc"] != 0:
                return ["FAILED: could not disable the Windows listener before removal"]
            error = _stop_windows_listener(home)
            if error:
                return ["FAILED: Windows listener did not stop: " + error]
        spec["remove"] = spec["remove"][1:] if match else []
    for argv in spec.get("remove", []):
        res = run_full(argv, timeout=30)
        status = "ok" if res["rc"] == 0 else "FAILED" if os.name == "nt" else "skipped"
        log.append("%s: %s" % (status, " ".join(argv)))
        if status == "FAILED":
            return log
    for path in spec["files"]:
        try:
            Path(path).unlink()
            log.append("deleted %s" % path)
        except OSError:
            pass
    return log


def installed(home: Home) -> "bool | None":
    """True/False if we can tell, None if unknown."""
    spec = describe(home)
    if spec["kind"] == "windows-task-scheduler":
        return wintasks.registration_matches(TASK, home.root, ["run"]) is True
    return spec["kind"] != "unavailable" and all(Path(p).exists() for p in spec["files"])
