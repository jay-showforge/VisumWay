"""Subprocess helpers shared by every bridge.

On Windows the runtime runs windowless (pythonw). Without CREATE_NO_WINDOW each
console program it starts would flash a console window on the user's desktop.
"""
from __future__ import annotations

import os
import subprocess

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def run(cmd: list, timeout: float = 8.0, env: "dict | None" = None) -> str:
    """Run a command, return stdout ('' on any failure). Never raises."""
    p = run_full(cmd, timeout=timeout, env=env)
    return p["stdout"] if p["rc"] == 0 else ""


def run_full(cmd: list, timeout: float = 8.0, env: "dict | None" = None, cwd=None,
             input: "str | None" = None) -> dict:
    """Run a command, return {rc, stdout, stderr}. rc is None if it could not run."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd,
                           input=input, stdin=None if input is not None else subprocess.DEVNULL,
                           encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        return {"rc": p.returncode, "stdout": p.stdout or "", "stderr": p.stderr or ""}
    except subprocess.TimeoutExpired:
        return {"rc": None, "stdout": "", "stderr": "timed out"}
    except (OSError, subprocess.SubprocessError) as e:
        return {"rc": None, "stdout": "", "stderr": str(e)}
