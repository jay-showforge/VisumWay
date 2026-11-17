"""Open the agent's interactive interface in a visible terminal window.

Used when the user clicks a notification. The user is present at that point,
so the agent runs interactively under its normal permission prompts.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys

from .agents import resolve_executable

LINUX_TERMINALS = (
    ("x-terminal-emulator", ["-e"]), ("gnome-terminal", ["--"]), ("konsole", ["-e"]),
    ("xfce4-terminal", ["-x"]), ("kitty", []), ("alacritty", ["-e"]), ("xterm", ["-e"]),
)


def windows_command_line(argv: list) -> str:
    """cmd /k strips the outer quotes of its argument, so the whole command
    gets one extra pair around it."""
    return 'cmd /k "%s"' % subprocess.list2cmdline(argv)


def build(argv: list, cwd: str, cfg: dict) -> "tuple":
    """Return (popen_args, popen_kwargs) for launching argv in a terminal."""
    override = cfg.get("open", {}).get("terminal_argv")
    if override:
        out = []
        for part in override:
            out.extend(argv if part == "{command}" else [part])
        return out, {"cwd": cwd}
    if os.name == "nt":
        resolved = [resolve_executable(argv[0]) or argv[0]] + list(argv[1:])
        command = windows_command_line(resolved) if resolved[0].lower().endswith((".cmd", ".bat")) else resolved
        return command, {
            "cwd": cwd, "creationflags": getattr(subprocess, "CREATE_NEW_CONSOLE", 0)}
    if sys.platform == "darwin":
        script = 'tell application "Terminal"\nactivate\ndo script %s\nend tell' % (
            '"%s"' % ("cd %s && %s" % (shlex.quote(cwd), " ".join(shlex.quote(a) for a in argv))
                      ).replace("\\", "\\\\").replace('"', '\\"'))
        return ["osascript", "-e", script], {}
    for name, flag in LINUX_TERMINALS:
        if shutil.which(name):
            return [name] + flag + list(argv), {"cwd": cwd}
    return None, {}


def launch(argv: list, cwd: str, cfg: dict) -> dict:
    args, kwargs = build(argv, cwd, cfg)
    if args is None:
        return {"ok": False, "error": "no terminal emulator found; set open.terminal_argv in config.json"}
    try:
        os.makedirs(cwd, exist_ok=True)
        subprocess.Popen(args, **kwargs)
        return {"ok": True}
    except OSError as e:
        return {"ok": False, "error": str(e)}
