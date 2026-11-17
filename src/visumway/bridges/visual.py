"""Select a host visual bridge and fetch one image on demand."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from ..paths import Home
from ..proc import run_full

WINDOWS_BACKEND = "windows-graphics-capture"
WINDOWS_HELPER = "windows-visual.exe"
_HELPER_VERSION = "visumway-windows-visual 1"
_TARGET = re.compile(r"(?:display:[0-9]{1,20}|window:[0-9]{1,20}:[0-9]{1,10})")
_MAX_EDGE = 4096
WATCH_LEASE_MAX = 600

_PS_CAPTURE = (
    "$ErrorActionPreference='Stop';"
    "try {"
    "Add-Type -Namespace VisumWay -Name Dpi -MemberDefinition "
    "'[DllImport(\"user32.dll\")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr value);';"
    "[void][VisumWay.Dpi]::SetThreadDpiAwarenessContext([IntPtr](-4));"
    "} catch {};"
    "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
    "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
    "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
    "$g=[System.Drawing.Graphics]::FromImage($bmp);"
    "$g.CopyFromScreen($b.Left,$b.Top,0,0,$bmp.Size);"
    "$g.Dispose(); $limit=[int]$env:VISUMWAY_CAPTURE_EDGE; $edge=[Math]::Max($bmp.Width,$bmp.Height);"
    "if($limit -gt 0 -and $edge -gt $limit){"
    "$w=[Math]::Max(1,[int][Math]::Floor($bmp.Width*$limit/$edge));"
    "$h=[Math]::Max(1,[int][Math]::Floor($bmp.Height*$limit/$edge));"
    "$small=New-Object System.Drawing.Bitmap $bmp,$w,$h; $bmp.Dispose(); $bmp=$small};"
    "$bmp.Save($env:VISUMWAY_CAPTURE_FILE,[System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()"
)


def _candidates(path: str) -> list:
    """Desktop capture commands retained for hosts without a target helper."""
    if os.name == "nt":
        return [("powershell-gdi", ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _PS_CAPTURE])]
    if sys.platform == "darwin":
        return [("screencapture", ["screencapture", "-x", path])]
    wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    x11 = bool(os.environ.get("DISPLAY"))
    out = []
    if wayland:
        out += [("grim", ["grim", path]),
                ("gnome-screenshot", ["gnome-screenshot", "-f", path]),
                ("spectacle", ["spectacle", "-b", "-n", "-o", path])]
    if x11:
        out += [("scrot", ["scrot", "-o", path]),
                ("maim", ["maim", path]),
                ("import", ["import", "-window", "root", path]),
                ("gnome-screenshot", ["gnome-screenshot", "-f", path])]
    return out


def _helper(home: "Home | None" = None) -> Path:
    return (home or Home()).bridges / WINDOWS_HELPER


def installed(home: "Home | None" = None) -> "bool | None":
    if os.name == "nt":
        return _helper(home).is_file()
    return None


def install(home: Home, source: "str | None", expected_sha256: "str | None" = None) -> list:
    """Install the independent Windows helper from an explicit local binary."""
    if os.name != "nt":
        return ["windows-visual: not applicable on this OS"]
    if source is None:
        return ["FAILED: supply an existing helper .exe. See docs/WINDOWS_VISUAL.md for the build command."]
    if not expected_sha256 or not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha256):
        return ["FAILED: supply the helper's trusted SHA-256 with --sha256 before running it."]
    try:
        candidate = Path(source).resolve(strict=True)
        if not candidate.is_file() or candidate.suffix.lower() != ".exe":
            raise ValueError("expected a local .exe file")
        with tempfile.TemporaryDirectory(dir=home.bridges) as stage:
            binary = Path(stage) / WINDOWS_HELPER
            shutil.copyfile(candidate, binary)
            digest = hashlib.sha256()
            with binary.open("rb") as file:
                for chunk in iter(lambda: file.read(65536), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected_sha256.lower():
                raise ValueError("helper SHA-256 mismatch")
            result = run_full([str(binary), "--version"], timeout=5)
            if result["rc"] != 0 or result["stdout"].strip() != _HELPER_VERSION:
                raise ValueError(result["stderr"].strip() or "unrecognized visual helper build")
            binary.replace(_helper(home))
    except (OSError, ValueError) as error:
        return ["FAILED: windows-visual: %s" % error]
    return ["Installed Windows visual helper at %s. Run visumway verify." % _helper(home)]


def remove(home: Home) -> list:
    if not installed(home):
        return []
    try:
        _helper(home).unlink(missing_ok=True)
    except OSError as error:
        return ["FAILED: could not remove Windows visual helper: %s" % error]
    return ["Removed Windows visual helper"]


def backends(home: "Home | None" = None) -> list:
    """Detect installed capture backends without collecting any pixels."""
    seen = []
    for name, argv in _candidates("x.png"):
        if name not in seen and shutil.which(argv[0]):
            seen.append(name)
    if installed(home):
        seen.append(WINDOWS_BACKEND)
    return seen


def targets(home: "Home | None" = None) -> dict:
    """Return available capture selectors; this makes no capture request."""
    choices = [{"id": "desktop", "kind": "desktop"}] if any(
        backend != WINDOWS_BACKEND for backend in backends(home)) else []
    detail = {}
    if installed(home):
        result = run_full([str(_helper(home)), "targets"], timeout=5)
        if result["rc"] == 0:
            try:
                report = json.loads(result["stdout"])
                rows = report["targets"]
                if not isinstance(rows, list):
                    raise ValueError
                detail["window_feed"] = "window-feed" in report.get("features", [])
                detail["window_controls"] = "window-controls" in report.get("features", [])
                choices.extend(row for row in rows[:512] if isinstance(row, dict)
                               and isinstance(row.get("id"), str) and _TARGET.fullmatch(row["id"]))
            except (TypeError, KeyError, ValueError):
                detail["targeted_capture_error"] = "Windows visual helper returned invalid target data."
        else:
            detail["targeted_capture_error"] = result["stderr"].strip() or "Could not list Windows targets."
    elif os.name == "nt":
        detail["targeted_capture_error"] = "Windows visual helper is not installed. Run visumway plan."
    if not choices:
        detail["error"] = detail.get("targeted_capture_error", "No capture backend found in this session.")
    return {"ok": bool(choices), "targets": choices, **detail}


def inspect_window(home: Home, target: str, limit: int = 24, name: "str | None" = None) -> dict:
    """Read accessibility properties scoped to one window. No pixels or UI actions."""
    if not isinstance(target, str) or not _TARGET.fullmatch(target) or not target.startswith("window:"):
        return {"ok": False, "error": "Select one Windows window from list_capture_targets."}
    if type(limit) is not int or not 1 <= limit <= 64:
        return {"ok": False, "error": "limit must be an integer from 1 to 64."}
    if name is not None:
        try:
            valid = (isinstance(name, str) and bool(name) and len(name.encode("utf-16-le")) <= 320
                     and all(ord(char) >= 32 for char in name))
        except UnicodeError:
            valid = False
        if not valid:
            return {"ok": False, "error": "name must be up to 160 UTF-16 units, without control characters."}
    if not installed(home):
        return {"ok": False, "error": "Install the current Windows visual helper to inspect controls."}
    result = run_full([str(_helper(home)), "controls", target, str(limit)], timeout=5, input=(name or "") + "\n")
    if result["rc"] != 0:
        detail = (result["stderr"] or "Windows UI Automation unavailable").strip()[:240]
        return {"ok": False, "error": detail}
    try:
        report = json.loads(result["stdout"])
        if (report["pid"] != int(target.rsplit(":", 1)[1])
                or not isinstance(report["controls"], list) or len(report["controls"]) > limit
                or type(report["truncated"]) is not bool or not isinstance(report["title"], str)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "Windows visual helper returned invalid control data."}
    return dict(report, ok=True, target=target)


def _png_size(path: Path) -> tuple:
    with path.open("rb") as file:
        header = file.read(24)
    if len(header) < 24 or header[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        raise ValueError("Capture did not produce a PNG.")
    size = struct.unpack(">II", header[16:24])
    if not all(size):
        raise ValueError("Capture produced an empty frame.")
    return size


def capture(path: "str | None" = None, timeout: float = 15.0, *, target: str = "desktop",
            max_edge: "int | None" = None, home: "Home | None" = None) -> dict:
    """Capture one requested desktop, display, or window into a PNG file."""
    if max_edge is not None and (type(max_edge) is not int or not 1 <= max_edge <= _MAX_EDGE):
        return {"ok": False, "error": "Maximum edge must be an integer from 1 to %d." % _MAX_EDGE}
    if target != "desktop":
        if not isinstance(target, str) or not _TARGET.fullmatch(target):
            return {"ok": False, "error": "Unknown selector. Run visumway capture --list."}
        if not installed(home):
            return {"ok": False, "error": "Selected display and window capture requires the Windows visual helper."}
    elif max_edge is not None and os.name != "nt":
        return {"ok": False, "error": "Desktop resizing is available in the Windows bridge."}

    destination = Path(path).absolute() if path is not None else None
    requested_size = (max_edge or _MAX_EDGE) if target != "desktop" else max_edge
    try:
        with tempfile.TemporaryDirectory(prefix="visumway-", dir=destination.parent if destination else None) as tmp:
            staged = Path(tmp) / "frame.png"
            env = dict(os.environ, VISUMWAY_CAPTURE_FILE=str(staged), VISUMWAY_CAPTURE_EDGE=str(max_edge or 0))
            commands = _candidates(str(staged)) if target == "desktop" else [
                (WINDOWS_BACKEND, [str(_helper(home)), "capture", target, str(requested_size), str(staged)])]
            shot = _run_capture(commands, staged, env, timeout, requested_size)
            if shot["ok"]:
                if destination is None:
                    fd, name = tempfile.mkstemp(prefix="visumway-", suffix=".png")
                    os.close(fd)
                    destination = Path(name)
                    try:
                        staged.replace(destination)
                    except OSError:
                        destination.unlink(missing_ok=True)
                        raise
                else:
                    staged.replace(destination)
                shot["path"] = str(path) if path is not None else str(destination)
                shot["target"] = target
            return shot
    except OSError as error:
        return {"ok": False, "error": str(error)}


def capture_bytes(home: Home, target: str, max_edge: "int | None", timeout: float = 15.0) -> tuple:
    with tempfile.TemporaryDirectory(prefix="visumway-mcp-") as tmp:
        path = Path(tmp) / "image.png"
        shot = capture(str(path), timeout=timeout, home=home, target=target, max_edge=max_edge)
        shot.pop("path", None)
        return shot, path.read_bytes() if shot["ok"] else None


@dataclass
class Watch:
    """A pull-only lease on a selected surface. Stores no images or opened handles."""

    target: str
    max_edge: "int | None"
    deadline: float
    id: str = field(default_factory=lambda: uuid4().hex)
    sequence: int = 0
    digest: bytes = b""

    @classmethod
    def start(cls, home: Home, target: str, max_edge: "int | None", lease: int) -> "Watch":
        if type(lease) is not int or not 1 <= lease <= WATCH_LEASE_MAX:
            raise ValueError("Lease must be an integer from 1 to %d seconds." % WATCH_LEASE_MAX)
        if max_edge is not None and (type(max_edge) is not int or not 1 <= max_edge <= _MAX_EDGE):
            raise ValueError("Maximum edge must be an integer from 1 to %d." % _MAX_EDGE)
        if target == "desktop" and max_edge is not None and os.name != "nt":
            raise ValueError("Desktop resizing is available in the Windows bridge.")
        available = targets(home)
        if not any(item["id"] == target for item in available["targets"]):
            raise ValueError(available.get("error", "Target is unavailable. Run list_capture_targets."))
        return cls(target, max_edge, time.monotonic() + lease)

    def frame(self, home: Home) -> tuple:
        result = {"watch_id": self.id, "target": self.target, "sequence": self.sequence}
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            return dict(result, status="expired"), None
        shot, png = capture_bytes(home, self.target, self.max_edge, min(remaining, 15.0))
        if time.monotonic() >= self.deadline:
            return dict(result, status="expired"), None
        if png is None:
            return dict(result, status="unavailable", error=shot["error"]), None
        digest = hashlib.sha256(png).digest()
        if digest == self.digest:
            return dict(result, status="unchanged"), None
        self.digest = digest
        self.sequence += 1
        return dict(shot, watch_id=self.id, status="changed", sequence=self.sequence), png


def _run_capture(commands: list, path: Path, env: dict, timeout: float, max_edge: "int | None") -> dict:
    errors = []
    for backend, argv in commands:
        if backend != WINDOWS_BACKEND and not shutil.which(argv[0]):
            continue
        path.unlink(missing_ok=True)
        result = run_full(argv, env=env, timeout=timeout)
        if result["rc"] != 0:
            errors.append("%s: %s" % (backend, (result["stderr"] or "capture failed").strip()[:200]))
            continue
        try:
            width, height = _png_size(path)
            if max_edge and max(width, height) > max_edge:
                raise ValueError("Frame exceeded the requested size.")
            shot = {"ok": True, "backend": backend, "width": width, "height": height}
            if backend == WINDOWS_BACKEND:
                renderer = json.loads(result["stdout"])["renderer"]
                if renderer not in ("d3d11", "warp"):
                    raise ValueError("Windows visual helper returned an unknown renderer.")
                shot["renderer"] = renderer
            return shot
        except (OSError, KeyError, TypeError, ValueError) as error:
            errors.append("%s: %s" % (backend, error))
    return {"ok": False, "error": "; ".join(errors) or "No desktop capture backend available in this session."}
