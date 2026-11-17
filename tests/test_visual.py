import base64
import io
import json
import os
import shutil
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from visumway import mcp_server
from visumway.bridges import visual, window_feed
from visumway.paths import Home

PNG_HEADER = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">II", 620, 350)
TARGET = "window:12345:42"


class VisualTests(unittest.TestCase):
    def test_control_query_is_scoped_and_sends_the_label_over_stdin(self):
        payload = {"pid": 42, "title": "Fixture", "controls": [{"name": "Export",
                   "enabled": False}], "truncated": False}
        response = {"rc": 0, "stdout": json.dumps(payload), "stderr": ""}
        with tempfile.TemporaryDirectory() as temp, patch.object(visual, "installed", return_value=True), \
             patch.object(visual, "run_full", return_value=response) as run:
            home = Home(temp)
            self.assertFalse(visual.inspect_window(home, "desktop")["ok"])
            self.assertFalse(visual.inspect_window(home, TARGET, name="a\nb")["ok"])
            run.assert_not_called()
            reply = mcp_server.call_tool(home, "inspect_window", {"target": TARGET, "name": "Export"})
            result = json.loads(reply["content"][0]["text"])
            self.assertEqual(result["controls"], payload["controls"])
            self.assertEqual(run.call_args.args[0][1:], ["controls", TARGET, "24"])
            self.assertEqual(run.call_args.kwargs["input"], "Export\n")
            self.assertEqual(len(reply["content"]), 1)

    def test_buffered_mcp_reads_changed_frames_by_sequence(self):
        def record(png, elapsed):
            header = json.dumps({"bytes": len(png), "renderer": "d3d11", "elapsed_ms": elapsed})
            return header.encode() + b"\n" + png

        frames = [PNG_HEADER + bytes([i]) for i in range(3)]
        process = type("FeedProcess", (), {"poll": lambda self: 0})()
        process.stdin = io.BytesIO()
        process.stdout = io.BytesIO(record(frames[0], 0) + record(frames[0], 125) +
                                    record(frames[1], 250) + record(frames[2], 500))
        process.stderr = io.BytesIO()
        session = {}
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(visual, "targets", return_value={"window_feed": True, "targets": [{"id": TARGET}]}), \
             patch.object(window_feed.subprocess, "Popen", return_value=process), \
             patch.object(window_feed, "MAX_BUFFER_BYTES", len(frames[0]) * 2):
            home = Home(temp).ensure()
            result = mcp_server.call_tool(home, "watch_start", {"target": TARGET, "mode": "buffered"}, session)
            watch_id = json.loads(result["content"][0]["text"])["watch_id"]
            watch = session["watch"]
            watch._reader.join(timeout=2)
            self.addCleanup(watch.close)
            result = mcp_server.call_tool(home, "watch_read", {"watch_id": watch_id, "limit": 1}, session)
            report = json.loads(result["content"][0]["text"])
            self.assertEqual((report["status"], report["next_after_sequence"], report["missed"]), ("ready", 2, 1))
            self.assertTrue(report["has_more"])
            self.assertEqual(base64.b64decode(result["content"][1]["data"]), frames[1])
            result = mcp_server.call_tool(home, "watch_read",
                                          {"watch_id": watch_id, "after_sequence": 2}, session)
            report = json.loads(result["content"][0]["text"])
            self.assertEqual(report["frames"][0]["elapsed_ms"], 500)
            self.assertFalse(report["has_more"])
            self.assertEqual(base64.b64decode(result["content"][1]["data"]), frames[2])
            mcp_server.call_tool(home, "watch_stop", {"watch_id": watch_id}, session)
            self.assertTrue(mcp_server.call_tool(home, "watch_read", {"watch_id": watch_id}, session)["isError"])

    @unittest.skipUnless(os.name == "nt", "Windows executable installation")
    def test_modified_helper_is_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Home(temp).ensure()
            candidate = home.root / "candidate.exe"
            candidate.write_bytes(b"modified")
            with patch.object(visual, "run_full") as run:
                result = visual.install(home, str(candidate), "0" * 64)
            run.assert_not_called()
            self.assertIn("SHA-256 mismatch", result[0])
            self.assertFalse(visual.installed(home))

    def test_targeted_failure_never_captures_the_desktop_or_overwrites_output(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "keep.png"
            output.write_bytes(b"original")
            with patch.object(visual, "installed", return_value=True), \
                 patch.object(visual, "run_full", return_value={"rc": 1, "stdout": "", "stderr": "window vanished"}) as run, \
                 patch.object(visual, "_candidates") as desktop:
                shot = visual.capture(str(output), target=TARGET, home=Home(temp))
            self.assertFalse(shot["ok"])
            self.assertIn("window vanished", shot["error"])
            self.assertEqual(run.call_args.args[0][1:4], ["capture", TARGET, "4096"])
            desktop.assert_not_called()
            self.assertEqual(output.read_bytes(), b"original")
            self.assertEqual(list(Path(temp).iterdir()), [output])

    def test_invalid_arguments_never_launch_a_helper(self):
        with patch.object(visual, "run_full") as run:
            self.assertFalse(visual.capture(target="window:0 & echo hello")["ok"])
            self.assertFalse(visual.capture(max_edge=True)["ok"])
            self.assertFalse(visual.capture(max_edge=4097)["ok"])
            run.assert_not_called()

    def test_desktop_fallback_cannot_return_a_failed_backends_staged_file(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "out.png"

            def candidate(path):
                return [("first", ["first", path]), ("second", ["second", path])]

            def run(argv, **kwargs):
                if argv[0] == "first":
                    Path(argv[1]).write_bytes(PNG_HEADER)
                    return {"rc": 1, "stdout": "", "stderr": "failed"}
                return {"rc": 0, "stdout": "", "stderr": ""}

            with patch.object(visual, "_candidates", side_effect=candidate), \
                 patch.object(shutil, "which", return_value="backend"), \
                 patch.object(visual, "run_full", side_effect=run):
                self.assertFalse(visual.capture(str(output))["ok"])
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_mcp_target_returns_image_and_removes_private_staging_files(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Home(temp)
            retained = []

            def capture(path, **args):
                self.assertEqual(args, {"home": home, "target": TARGET, "max_edge": 800, "timeout": 15.0})
                retained.append(Path(path))
                retained[0].write_bytes(PNG_HEADER)
                return {"ok": True}

            with patch.object(visual, "capture", side_effect=capture):
                result = mcp_server.call_tool(home, "capture_screen", {"target": TARGET, "max_edge": 800})
            image = result["content"][0]
            self.assertEqual(image["mimeType"], "image/png")
            self.assertEqual(base64.b64decode(image["data"], validate=True), PNG_HEADER)
            self.assertFalse(retained[0].parent.exists())

    def test_listing_does_not_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Home(temp)
            metadata = {"targets": [{"id": TARGET, "kind": "window", "pid": 42}]}
            with patch.object(visual, "backends", return_value=["powershell-gdi", visual.WINDOWS_BACKEND]), \
                 patch.object(visual, "installed", return_value=True), \
                 patch.object(visual, "run_full", return_value={"rc": 0, "stdout": json.dumps(metadata), "stderr": ""}) as run:
                result = mcp_server.call_tool(home, "list_capture_targets", {})
            self.assertEqual(run.call_args.args[0][1:], ["targets"])
            self.assertEqual([t["id"] for t in json.loads(result["content"][0]["text"])["targets"]], ["desktop", TARGET])
