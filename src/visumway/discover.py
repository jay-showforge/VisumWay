"""Host Blueprint Engine: examine this computer and describe what it has.

Read-only. Produces a machine-specific blueprint that the setup plan (and the
coding agent doing the install) is built from.
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import sys
import time

from . import __version__, agents
from .bridges import visual
from .bridges.system import run
from .paths import Home

AGENT_RUNTIMES = ("claude", "codex", "gemini", "ollama", "llama-server", "lms")


def _ps(command: str) -> str:
    return run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + command], timeout=15)


def _memory_bytes() -> "int | None":
    try:
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) * 1024
        if sys.platform == "darwin":
            return int(run(["sysctl", "-n", "hw.memsize"]).strip())
        if os.name == "nt":
            return int(_ps("(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory").strip())
    except (ValueError, OSError):
        pass
    return None


def _cpu_name() -> str:
    try:
        if os.path.exists("/proc/cpuinfo"):
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        if sys.platform == "darwin":
            return run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        if os.name == "nt":
            name = _ps("(Get-CimInstance Win32_Processor).Name").strip()
            if name:
                return name
    except OSError:
        pass
    return platform.processor() or platform.machine()


def _gpus() -> list:
    gpus = []
    if shutil.which("nvidia-smi"):
        out = run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                   "--format=csv,noheader,nounits"])
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                gpus.append({"name": parts[0], "vendor": "nvidia",
                             "memory_mb": int(parts[1]) if parts[1].isdigit() else None,
                             "driver": parts[2], "query_tool": "nvidia-smi"})
    if gpus:
        return gpus
    names = []
    drivers = {}
    if os.name == "nt":
        raw = _ps("Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion | ConvertTo-Json -Compress")
        try:
            controllers = json.loads(raw)
        except ValueError:
            controllers = []
        if isinstance(controllers, dict):
            controllers = [controllers]
        drivers = {row["Name"]: row.get("DriverVersion") for row in controllers or [] if row.get("Name")}
        names = list(drivers)
    elif sys.platform == "darwin":
        names = [l.split(":", 1)[1] for l in run(["system_profiler", "SPDisplaysDataType"], timeout=20).splitlines()
                 if "Chipset Model" in l]
    elif shutil.which("lspci"):
        names = [l.split(":", 2)[-1] for l in run(["lspci"]).splitlines()
                 if any(k in l for k in ("VGA", "3D controller", "Display controller"))]
    for n in names:
        n = n.strip()
        if n:
            low = n.lower()
            vendor = next((v for v in ("nvidia", "amd", "intel", "apple") if v in low), "unknown")
            if "radeon" in low:
                vendor = "amd"
            gpus.append({"name": n, "vendor": vendor, "memory_mb": None, "driver": drivers.get(n), "query_tool": None})
    return gpus


def _display(home: "Home | None" = None) -> dict:
    session = os.environ.get("XDG_SESSION_TYPE", "")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    if os.name == "nt":
        server = "windows-dwm"
        if ctypes.windll.user32.GetShellWindow():
            desktop = "Windows shell"
        session = os.environ.get("SESSIONNAME") or ("interactive" if desktop else "")
    elif sys.platform == "darwin":
        server = "macos-quartz"
    elif os.environ.get("WAYLAND_DISPLAY"):
        server = "wayland"
    elif os.environ.get("DISPLAY"):
        server = "x11"
    else:
        server = "none"
    return {"server": server, "session_type": session, "desktop": desktop,
            "capture_backends": visual.backends(home)}


def _service_manager() -> str:
    if os.name == "nt":
        return "windows-task-scheduler"
    if sys.platform == "darwin":
        return "launchd"
    if shutil.which("systemctl") and os.path.isdir("/run/systemd/system"):
        return "systemd"
    if (sys.platform.startswith("linux") and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
            and (os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or
                 os.environ.get("XDG_SESSION_TYPE") in ("x11", "wayland"))):
        return "xdg-autostart"
    return "none"


def discover(home: "Home | None" = None) -> dict:
    return {
        "visumway_version": __version__,
        "generated_at": time.time(),
        "hostname": platform.node(),
        "os": {"system": platform.system(), "release": platform.release(),
               "version": platform.version(), "arch": platform.machine()},
        "cpu": {"name": _cpu_name(), "logical_cores": os.cpu_count()},
        "memory_bytes": _memory_bytes(),
        "gpus": _gpus(),
        "display": _display(home),
        "service_manager": _service_manager(),
        "agent_runtimes": {name: exe for name in AGENT_RUNTIMES if (exe := agents.resolve_executable(name))},
        "python": {"version": platform.python_version(), "executable": sys.executable},
    }
