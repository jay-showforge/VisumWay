"""Submit a wake to a saved Codex chat through the local App Server queue."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import uuid

from .. import __version__
from ..proc import NO_WINDOW


def open_thread(thread_id: str) -> bool:
    """Ask Windows to open an existing Codex thread in the desktop app."""
    if os.name != "nt":
        return False
    try:
        if str(uuid.UUID(thread_id)) != thread_id:
            return False
        os.startfile("codex://threads/" + thread_id)
        return True
    except (OSError, ValueError, AttributeError):
        return False


def _exchange(process, thread_id, prompt, result):
    def send(method, params=None, request_id=None):
        packet = {"method": method}
        if params is not None:
            packet["params"] = params
        if request_id is not None:
            packet["id"] = request_id
        process.stdin.write(json.dumps(packet) + "\n")
        process.stdin.flush()

    def receive(request_id):
        for line in process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if not isinstance(message, dict) or message.get("id") != request_id:
                continue
            if "error" in message:
                raise OSError(str(message["error"].get("message", "Codex App Server request failed"))[:300])
            return message.get("result") or {}
        raise OSError("Codex App Server closed before replying")

    try:
        send("initialize", {"clientInfo": {"name": "visumway", "version": __version__},
                            "capabilities": {"experimentalApi": True}}, 0)
        receive(0)
        send("initialized")
        send("thread/queue/add", {"threadId": thread_id, "clientUserMessageId": str(uuid.uuid4()),
                                  "input": [{"type": "text", "text": prompt, "textElements": []}]}, 1)
        submission = receive(1).get("queuedSubmission") or {}
        if not isinstance(submission.get("id"), str) or not submission["id"]:
            raise OSError("Codex App Server did not confirm the queue entry")
        result.put(submission["id"])
    except (OSError, ValueError, AttributeError) as exc:
        result.put(OSError(str(exc)))


def enqueue(exe: str, thread_id: str, prompt: str, *, cwd, env, timeout: float = 20) -> str:
    """Return the queue ID. A loaded owner can consume it after this process exits."""
    result: queue.Queue = queue.Queue()
    with subprocess.Popen([exe, "app-server", "--stdio"], cwd=cwd, env=env, creationflags=NO_WINDOW,
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          encoding="utf-8", errors="replace") as process:
        worker = threading.Thread(target=_exchange, args=(process, thread_id, prompt, result), daemon=True)
        worker.start()
        try:
            response = result.get(timeout=timeout)
        except queue.Empty as exc:
            process.kill()
            raise OSError("Codex App Server timed out") from exc
        finally:
            worker.join()
            process.stdin.close()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if isinstance(response, OSError):
            raise response
        return response
