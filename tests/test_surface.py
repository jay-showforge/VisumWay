import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from visumway import config as config_mod
from visumway import mcp_server, plan, service, verify
from visumway.bridges import visual
from visumway.discover import discover
from visumway.events import Event, EventLog
from visumway.paths import Home

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def cli(home, *args, input=None):
    env = dict(os.environ, PYTHONPATH=SRC, VISUMWAY_HOME=str(home))
    return subprocess.run([sys.executable, "-m", "visumway", *args], capture_output=True, text=True,
                          input=input, env=env, timeout=60)


class DiscoverPlanTests(unittest.TestCase):
    def test_blueprint_shape_and_plan(self):
        bp = discover()
        for key in ("os", "cpu", "gpus", "display", "service_manager", "agent_runtimes", "python"):
            self.assertIn(key, bp)
        self.assertGreaterEqual(bp["cpu"]["logical_cores"], 1)
        rows = plan.build_plan(bp, config_mod.DEFAULT_CONFIG)
        self.assertTrue(all(r["status"] in ("ready", "setup", "build", "note") for r in rows))
        md = plan.render_markdown(bp, rows)
        self.assertIn("| Connection | Status |", md)

    def test_plan_for_windows_rtx_host(self):
        bp = {"hostname": "Desktop-PC", "memory_bytes": 32 * 2**30,
              "os": {"system": "Windows", "release": "11", "arch": "AMD64"},
              "cpu": {"name": "x", "logical_cores": 16},
              "gpus": [{"name": "NVIDIA GeForce RTX 4070", "vendor": "nvidia", "driver": "560.1",
                        "query_tool": "nvidia-smi", "memory_mb": 12282}],
              "display": {"server": "windows-dwm", "capture_backends": ["powershell-gdi"]},
              "service_manager": "windows-task-scheduler",
              "agent_runtimes": {"codex": "C:/codex.cmd"}}
        rows = {r["connection"]: r for r in plan.build_plan(bp, config_mod.DEFAULT_CONFIG)}
        self.assertEqual(rows["Visual: on-demand frame"]["status"], "setup")
        self.assertIn("Windows Graphics Capture", rows["Visual: live stream"]["action"])
        self.assertEqual(rows["Visual: live stream"]["status"], "note")
        self.assertIn("Task Scheduler", rows["OS events: app crashes, hangs, display-driver resets"]["action"])
        self.assertEqual(rows["OS events: app crashes, hangs, display-driver resets"]["status"], "setup")
        # installed is not the same as verified: the plan must not call it ready
        self.assertEqual(rows["Wake-up: agent"]["status"], "setup")
        self.assertIn("codex", rows["Wake-up: agent"]["action"])
        self.assertEqual(rows["Communication: desktop notification bubble"]["status"], "setup")


class ConfigTests(unittest.TestCase):
    def test_user_config_merges_and_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Home(tmp).ensure()
            home.config.write_text(json.dumps({"agent": {"default": "codex"},
                                               "reflex": {"budget": {"max_wakes_per_hour": 1}}}))
            cfg = config_mod.load(home)
            self.assertEqual(cfg["agent"]["default"], "codex")
            self.assertIn("claude", cfg["agent"]["adapters"])
            self.assertEqual(cfg["reflex"]["budget"], {"max_wakes_per_hour": 1, "max_wakes_per_day": 20})
            home.config.write_text(json.dumps({"reflex": {"rules": [{"match": "x", "action": "explode"}]}}))
            with self.assertRaises(config_mod.ConfigError):
                config_mod.load(home)


class McpTests(unittest.TestCase):
    def test_watch_samples_one_target_and_drops_duplicate_frames(self):
        home = Home()
        target = "window:12:34"
        choices = {"ok": True, "targets": [{"id": target}]}
        shot = {"ok": True, "target": target, "width": 200, "height": 100}
        session = {}

        def message(name, args):
            reply = mcp_server.handle(home, {"id": 1, "method": "tools/call",
                                            "params": {"name": name, "arguments": args}}, session)
            result = reply["result"]
            return json.loads(result["content"][0]["text"]), result["content"][1:]

        with patch.object(visual, "targets", return_value=choices), patch.object(
                visual, "capture_bytes", side_effect=[(shot, b"a"), (shot, b"a"), (shot, b"b"),
                                                      ({"ok": False, "error": "window closed"}, None)]) as capture:
            watch, _ = message("watch_start", {"target": target, "max_edge": 300})
            capture.assert_not_called()
            args = {"watch_id": watch["watch_id"]}
            for status, sequence, images in [("changed", 1, 1), ("unchanged", 1, 0),
                                             ("changed", 2, 1), ("unavailable", 2, 0)]:
                frame, attachments = message("watch_frame", args)
                self.assertEqual((frame["status"], frame["sequence"], len(attachments)), (status, sequence, images))
            self.assertEqual(message("watch_frame", args)[0]["status"], "inactive")
            self.assertEqual(capture.call_count, 4)
            self.assertTrue(all(call.args[:3] == (home, target, 300) for call in capture.call_args_list))

    def test_watch_release_and_expiry_prevent_capture(self):
        home = Home()
        session = {}
        target = "desktop"
        choices = {"ok": True, "targets": [{"id": target}]}
        with patch.object(visual, "targets", return_value=choices), patch.object(visual, "capture_bytes") as capture, \
                patch.object(visual.time, "monotonic", return_value=13) as clock:
            args = {"target": target, "lease_seconds": 1}
            mcp_server.call_tool(home, "watch_start", args, session)
            previous = {"watch_id": session["watch"].id}
            mcp_server.call_tool(home, "watch_start", args, session)
            active = {"watch_id": session["watch"].id}
            self.assertTrue(mcp_server.call_tool(home, "watch_frame", previous, session)["isError"])
            self.assertTrue(mcp_server.call_tool(home, "watch_frame", active, {})["isError"])
            mcp_server.call_tool(home, "watch_stop", active, session)
            self.assertTrue(mcp_server.call_tool(home, "watch_frame", active, session)["isError"])
            mcp_server.call_tool(home, "watch_start", args, session)
            active = {"watch_id": session["watch"].id}
            clock.return_value = 14
            result = mcp_server.call_tool(home, "watch_frame", active, session)
            self.assertEqual(json.loads(result["content"][0]["text"])["status"], "expired")
            self.assertEqual(session, {})
            capture.assert_not_called()

    def test_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Home(tmp).ensure()
            config_mod.update_user(home, {"agent": {"default": "codex"},
                                          "notify": {"channels": [{"type": "file"}]}})
            EventLog(home).append({"kind": "event", "event": Event(type="app.crash").to_dict(),
                                   "action": "log", "reason": "rule"})
            msgs = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "recent_events", "arguments": {"limit": 5}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "notify_user", "arguments": {"message": "hi"}}},
                {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "nope"}},
                {"jsonrpc": "2.0", "id": 6, "method": "bogus"},
            ]
            out = io.StringIO()
            mcp_server.serve(home, io.StringIO("\n".join(map(json.dumps, msgs)) + "\nnot json\n"), out, agent="codex")
            replies = [json.loads(l) for l in out.getvalue().splitlines()]
            by_id = {r["id"]: r for r in replies}
            self.assertEqual(len(replies), 7)  # the notification gets no reply
            self.assertEqual(by_id[1]["result"]["protocolVersion"], "2024-11-05")
            names = {t["name"] for t in by_id[2]["result"]["tools"]}
            self.assertEqual(names, {"host_blueprint", "recent_events", "recent_incidents", "reflex_status",
                                     "list_processes", "capture_screen", "list_capture_targets", "inspect_window", "notify_user",
                                     "watch_start", "watch_frame", "watch_read", "watch_stop"})
            self.assertIn("app.crash", by_id[3]["result"]["content"][0]["text"])
            self.assertFalse(by_id[4]["result"].get("isError"))
            self.assertEqual(json.loads(home.outbox.read_text())["message"], "hi")
            self.assertEqual(by_id[5]["error"]["code"], -32602)
            self.assertEqual(by_id[6]["error"]["code"], -32601)
            self.assertEqual(by_id[None]["error"]["code"], -32700)


class ServiceTests(unittest.TestCase):
    def test_each_os_has_a_definition(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Home(tmp)
            for system, kind in (("linux", "systemd-user"), ("macos", "launchd"),
                                 ("windows", "windows-task-scheduler")):
                spec = service.describe(home, system)
                self.assertEqual(spec["kind"], kind)
                self.assertTrue(spec["commands"])
                self.assertTrue(spec["remove"])
                text = " ".join(spec["files"].values()) + " ".join(" ".join(c) for c in spec["commands"])
                self.assertIn("visumway", text)


class CliTests(unittest.TestCase):
    def test_full_flow_through_the_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = cli(tmp, "init")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("VisumWay Host Installation Plan", r.stdout)
            for f in ("config.json", "blueprint.json", "PLAN.md"):
                self.assertTrue(os.path.exists(os.path.join(tmp, f)))
            config_mod.update_user(Home(tmp), {"agent": {"default": "codex"},
                                               "notify": {"channels": [{"type": "file"}]}})
            self.assertEqual(cli(tmp, "emit", "Bad Type").returncode, 2)
            self.assertEqual(cli(tmp, "emit", "update.completed", "--subject", "driver").returncode, 0)
            self.assertEqual(cli(tmp, "notify", "hello", "--agent", "codex").returncode, 0)
            r = cli(tmp, "verify", "--json")
            checks = {c["check"]: c["status"] for c in json.loads(r.stdout)}
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertNotIn("FAIL", checks.values(), checks)
            self.assertEqual(checks["agent interface"], "PASS")
            self.assertEqual(checks["wake path"], "WARN")  # works, but no runtime service running here
            status = json.loads(cli(tmp, "status").stdout)
            self.assertEqual(status["llm_invocations_while_idle"], 0)
            self.assertIn("update.completed", cli(tmp, "events").stdout)

    def test_verify_against_a_live_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli(tmp, "init")
            config_mod.update_user(Home(tmp), {"sources": {"disk": {"enabled": False}}})
            env = dict(os.environ, PYTHONPATH=SRC, VISUMWAY_HOME=tmp)
            proc = subprocess.Popen([sys.executable, "-m", "visumway", "run", "--interval", "0.1"], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                import time
                for _ in range(100):
                    if os.path.exists(os.path.join(tmp, "state", "daemon.json")):
                        break
                    time.sleep(0.05)
                status, detail = verify._wake_check(Home(tmp), config_mod.load(Home(tmp)))
                self.assertEqual(status, "PASS", detail)
                # a second runtime refuses to start
                second = cli(tmp, "run")
                self.assertEqual(second.returncode, 1)
            finally:
                proc.terminate()
                proc.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
