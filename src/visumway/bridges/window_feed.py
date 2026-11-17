"""A bounded, in-memory history driven by one native Windows capture session."""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import threading
import time
from collections import deque
from uuid import uuid4

from . import visual
from ..proc import NO_WINDOW

MAX_EDGE = 1280
MAX_FPS = 10
MAX_HISTORY = 30
MAX_PNG_BYTES = 6 * 1024 * 1024
MAX_BUFFER_BYTES = 24 * 1024 * 1024
MAX_REPLY_IMAGE_BYTES = 6 * 1024 * 1024


def _bounded(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}")
    return value


class WindowFeed:
    def __init__(self, target, max_edge, lease, fps, history, process):
        self.id = uuid4().hex
        self.target = target
        self.max_edge = max_edge
        self.deadline = time.monotonic() + lease
        self.history = history
        self._process = process
        self._condition = threading.Condition()
        self._frames = deque()
        self._bytes = 0
        self._sequence = 0
        self._digest = b""
        self._ended = False
        self._error = ""
        self._reader = threading.Thread(target=self._receive, name="visumway-window-feed", daemon=True)
        self._reader.start()

    @classmethod
    def start(cls, home, target, max_edge, lease, fps, history):
        _bounded(max_edge, 1, MAX_EDGE, "max_edge")
        _bounded(lease, 1, visual.WATCH_LEASE_MAX, "lease_seconds")
        _bounded(fps, 1, MAX_FPS, "fps")
        _bounded(history, 1, MAX_HISTORY, "history_seconds")
        if not isinstance(target, str) or not target.startswith("window:"):
            raise ValueError("Buffered mode requires a specific Windows window from list_capture_targets.")
        available = visual.targets(home)
        if not available.get("window_feed"):
            raise ValueError("Buffered mode requires the Windows visual helper with window-feed support.")
        if not any(row["id"] == target for row in available["targets"]):
            raise ValueError("Window is unavailable. Run list_capture_targets again.")
        command = [str(visual._helper(home)), "feed", target, str(max_edge), str(lease), str(fps)]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, creationflags=NO_WINDOW)
        return cls(target, max_edge, lease, fps, history, process)

    def _trim(self, now):
        while self._frames and (self._frames[0][0] < now - self.history or self._bytes > MAX_BUFFER_BYTES):
            _, _, stale = self._frames.popleft()
            self._bytes -= len(stale)

    def _clear(self):
        self._frames.clear()
        self._bytes = 0

    def _receive(self):
        process = self._process
        error = ""
        try:
            while True:
                line = process.stdout.readline(257)
                if not line:
                    break
                if len(line) > 256 or not line.endswith(b"\n"):
                    raise ValueError("Invalid visual feed header")
                header = json.loads(line)
                count = _bounded(header["bytes"], 0, MAX_PNG_BYTES, "frame bytes")
                if count:
                    renderer = header["renderer"]
                    if renderer not in ("d3d11", "warp"):
                        raise ValueError("Unknown visual feed renderer")
                    elapsed = _bounded(header["elapsed_ms"], 0, visual.WATCH_LEASE_MAX * 1000, "elapsed_ms")
                    png = process.stdout.read(count)
                    if len(png) != count or len(png) < 24 or png[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
                        raise ValueError("Invalid visual feed image")
                    width, height = struct.unpack(">II", png[16:24])
                    if not 1 <= min(width, height) <= max(width, height) <= self.max_edge:
                        raise ValueError("Visual feed dimensions exceed max_edge")
                    digest = hashlib.sha256(png).digest()
                with self._condition:
                    now = time.monotonic()
                    if self._ended or now >= self.deadline:
                        self._clear()
                        break
                    if count and digest != self._digest:
                        self._digest = digest
                        self._sequence += 1
                        info = {"sequence": self._sequence, "elapsed_ms": elapsed, "width": width,
                                "height": height, "renderer": renderer, "backend": visual.WINDOWS_BACKEND}
                        self._frames.append((now, info, png))
                        self._bytes += len(png)
                        self._condition.notify_all()
                    self._trim(now)
        except (OSError, TypeError, ValueError, KeyError) as exc:
            error = str(exc)
        finally:
            if process.poll() is None:
                # On EOF, allow the helper to return its own exit status.
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            detail = process.stderr.read(400).decode("utf-8", errors="replace").strip()
            for pipe in (process.stdin, process.stdout, process.stderr):
                pipe.close()
            with self._condition:
                self._error = error or detail or "Windows visual feed ended."
                self._ended = True
                if time.monotonic() >= self.deadline:
                    self._clear()
                self._condition.notify_all()

    def read(self, after, limit, wait):
        _bounded(after, 0, visual.WATCH_LEASE_MAX * MAX_FPS, "after_sequence")
        _bounded(limit, 1, 4, "limit")
        _bounded(wait, 0, 5, "wait_seconds")
        until = min(time.monotonic() + wait, self.deadline)
        with self._condition:
            while not self._ended and self._sequence <= after and time.monotonic() < until:
                self._condition.wait(max(0, until - time.monotonic()))
            now = time.monotonic()
            result = {"watch_id": self.id, "target": self.target, "next_after_sequence": after}
            if now >= self.deadline:
                self._clear()
                return dict(result, status="expired", frames=[]), []
            if after > self._sequence:
                raise ValueError("after_sequence is ahead of this watch")
            self._trim(now)
            oldest = self._frames[0][1]["sequence"] if self._frames else self._sequence + 1
            result["missed"] = max(0, oldest - after - 1)
            frames, images = [], []
            size = 0
            for _, info, png in self._frames:
                if info["sequence"] <= after:
                    continue
                if len(frames) == limit or size + len(png) > MAX_REPLY_IMAGE_BYTES:
                    break
                images.append(png)
                frames.append(dict(info, content_index=len(images)))
                size += len(png)
            if frames:
                result["next_after_sequence"] = frames[-1]["sequence"]
            elif result["missed"]:
                result["next_after_sequence"] = self._sequence
            if self._ended:
                result["error"] = self._error
            result["has_more"] = self._sequence > result["next_after_sequence"]
            status = "ready" if frames else ("unavailable" if self._ended else "waiting")
            return dict(result, status=status, frames=frames), images

    def close(self):
        with self._condition:
            self._ended = True
            self._clear()
            self._condition.notify_all()
        if self._process.poll() is None:
            self._process.kill()
        self._reader.join(timeout=2)
