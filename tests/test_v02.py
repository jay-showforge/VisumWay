"""v0.2: agent discovery and verification, incidents, desktop notification
bridge, click handling, snooze, Windows event bridge."""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from visumway import agents, cli, config as config_mod, incidents, mcp_server, notify, opener, terminal, wake
from visumway.bridges import codexapp, desktop, winevents
from visumway.daemon import Daemon
from visumway.events import Event, drain_inbox, write_event
from visumway.paths import Home
from visumway.policy import WakeReport

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
SESSION = "f1793174-256f-4142-84d6-559c7add9c16"
CLAUDE_OK = json.dumps({"type": "result", "is_error": False, "session_id": SESSION, "total_cost_usd": 0.01,
                        "result": "Hey, how's everything going? I noticed Game.exe crashed. Want me to take a look?"})
# Captured from a real `claude -p --output-format json` run without credentials (exit code 0!).
CLAUDE_AUTH_ERROR = json.dumps({"type": "result", "subtype": "success", "is_error": True, "session_id": SESSION,
                                "total_cost_usd": 0, "terminal_reason": "api_error",
                                "result": "Authentication error · This may be a temporary network issue, please try again"})
CODEX_JSONL = "\n".join(json.dumps(x) for x in [
    {"type": "thread.started", "thread_id": "0199a213-81c0-7800-8aa1-bbab2a035a53"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "item_0", "type": "reasoning", "text": "thinking"}},
    {"type": "item.completed", "item": {"id": "item_1", "type": "agent_message", "text": "Your app crashed. Want a look?"}},
    {"type": "turn.completed", "usage": {"input_tokens": 10}},
])


def base_cfg():
    return json.loads(json.dumps(config_mod.DEFAULT_CONFIG))


def fake_agent(cfg, stdout, name="claude", rc=0, extra=""):
    """Point an adapter at a Python stand-in that prints `stdout`."""
    script = "import sys,os\nsys.stdin.read()\n%s\nsys.stdout.write(%r)\nsys.exit(%d)" % (extra, stdout, rc)
    adapter = cfg["agent"]["adapters"][name]
    adapter["argv"] = [sys.executable, "-c", script]
    auth = {"loggedIn": True, "authMethod": adapter["account_methods"][0], "apiProvider": "firstParty"}
    adapter["login_check"] = [sys.executable, "-c", "print(%r)" % json.dumps(auth)]
    cfg["agent"]["default"] = name
    return cfg


def report(subject="Game.exe"):
    ev = Event(type="app.crash", subject=subject, severity="error")
    return WakeReport(key=ev.key(), type=ev.type, subject=ev.subject, severity="error", count=1,
                      first_ts=ev.ts, last_ts=ev.ts, samples=[ev.to_dict()])


class TempHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Home(self.tmp.name).ensure()
        self.cfg = base_cfg()
        self.shown = []
        patcher = mock.patch.object(desktop, "show", side_effect=self._show)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def _show(self, home, cfg, title, message, incident_id=None):
        self.shown.append({"title": title, "message": message, "incident_id": incident_id})
        return {"ok": True, "backend": "fake"}


class OutputParsing(unittest.TestCase):
    def test_claude_json(self):
        p = agents.parse_output("claude-json", CLAUDE_OK)
        self.assertEqual((p.session_id, p.error), (SESSION, None))
        self.assertIn("Game.exe crashed", p.message)
        self.assertEqual(agents.parse_output("claude-json", "[%s]" % CLAUDE_OK).session_id, SESSION)

    def test_claude_error_is_an_error_not_a_message(self):
        p = agents.parse_output("claude-json", CLAUDE_AUTH_ERROR)
        self.assertEqual(p.message, "")
        self.assertIn("Authentication error", p.error)
        self.assertTrue(agents.parse_output("claude-json", "not json").error)

    def test_codex_jsonl(self):
        p = agents.parse_output("codex-jsonl", CODEX_JSONL)
        self.assertEqual(p.session_id, "0199a213-81c0-7800-8aa1-bbab2a035a53")
        self.assertEqual(p.message, "Your app crashed. Want a look?")
        failed = agents.parse_output("codex-jsonl", json.dumps({"type": "error", "message": "not logged in"}))
        self.assertEqual(failed.error, "not logged in")
        self.assertEqual(agents.parse_output("codex-jsonl", "plain words").message, "plain words")


class AgentBinding(TempHome):
    def test_setup_uses_the_installing_agents_explicit_account(self):
        infos = [{"name": name, "installed": name, "verified": False, "requires_account": True,
                  "billing_safe": True, "auth": "confirmed"} for name in ("claude", "codex")]
        parser = cli.build_parser()
        with mock.patch.object(agents, "inspect_all", return_value=infos), \
             mock.patch.object(agents, "inspect", return_value=infos[0]) as inspect, \
             mock.patch.object(cli, "_write_plan", return_value="plan"), \
             mock.patch.object(desktop, "register") as register, \
             mock.patch("builtins.print"):
            self.assertEqual(cli._setup(self.home, parser.parse_args(["setup", "--no-bridges", "--no-service"])), 0)
            register.assert_not_called()
            inspect.assert_not_called()
            self.assertTrue(config_mod.read_user(self.home)["setup_complete"])
            self.assertFalse(config_mod.load(self.home)["agent"]["bound"])
            args = parser.parse_args(["setup", "--agent", "claude", "--no-bridges", "--no-service"])
            self.assertEqual(cli._setup(self.home, args), 0)
            saved = self.home.config.read_bytes()
            # Even a request with all install options uses the existing body.
            for command in (["setup"], ["setup", "--agent", "codex", "--windows-background"]):
                self.assertEqual(cli._setup(self.home, parser.parse_args(command)), 0)
                self.assertEqual(self.home.config.read_bytes(), saved)
        self.assertEqual(config_mod.read_user(self.home)["agent"]["default"], "claude")
        self.assertEqual(inspect.call_args.args[-1], "claude")
        register.assert_called_once()
        self.assertFalse(config_mod.load(self.home)["reflex"]["wakes_enabled"])

    def test_unrecognized_installer_gets_shared_tools_and_reserves_optional_notifications(self):
        path = ["--home", str(self.home.root)]
        with mock.patch.object(agents, "inspect") as inspect, \
             mock.patch.object(cli, "_write_plan", return_value="plan"), \
             mock.patch.object(cli.service, "install", return_value=[]) as service_install, \
             mock.patch.object(desktop, "register", return_value=[]) as register, \
             mock.patch.dict(cli.BRIDGES, {}, clear=True), mock.patch("builtins.print"):
            self.assertEqual(cli.main(path + ["setup", "--agent", "another-host"]), 0)
            cfg = config_mod.load(self.home)
            self.assertFalse(cfg["agent"]["bound"])
            self.assertEqual(cfg["agent"]["installer"], "another-host")
            self.assertFalse(cfg["reflex"]["wakes_enabled"])
            self.assertEqual(cli.main(path + ["agent", "probe"]), 2)
            saved = self.home.config.read_bytes()
            self.assertEqual(cli.main(path + ["setup", "--agent", "codex"]), 0)
            self.assertEqual(self.home.config.read_bytes(), saved)
            service_install.assert_called_once()
            inspect.assert_not_called()
            register.assert_not_called()
            config_mod.update_user(self.home, {"agent": {"adapters": {"another-host": {"argv": ["fixture"]}}}})
            inspect.return_value = {"installed": True, "requires_account": False}
            self.assertEqual(cli.main(path + ["setup", "--agent", "another-host"]), 0)
            updated = config_mod.load(self.home)
            self.assertTrue(config_mod.is_notification_owner(updated, "another-host"))
            self.assertFalse(updated["reflex"]["wakes_enabled"])
            register.assert_called_once()

    def test_signed_out_installer_can_install_shared_tools(self):
        path = ["--home", str(self.home.root)]
        info = {"installed": True, "requires_account": True, "billing_safe": False, "auth": "none"}
        with mock.patch.object(agents, "inspect", return_value=info), \
             mock.patch.object(cli, "_write_plan", return_value="plan"), \
             mock.patch.object(desktop, "register") as register, mock.patch("builtins.print"):
            self.assertEqual(cli.main(path + ["setup", "--agent", "codex", "--no-service", "--no-bridges"]), 0)
            register.assert_not_called()
        cfg = config_mod.load(self.home)
        self.assertTrue(cfg["setup_complete"])
        self.assertEqual(cfg["agent"]["installer"], "codex")
        self.assertFalse(cfg["agent"]["bound"])

    def test_other_agent_can_use_shared_tools_but_cannot_control_notifications(self):
        config_mod.write_default(self.home)
        config_mod.update_user(self.home, {
            "agent": {"default": "codex"}, "reflex": {"aggregate_window_s": 0},
            "sources": {"disk": {"enabled": False}}, "notify": {"channels": [{"type": "file"}]},
        })
        calls = []

        def runner(home, cfg, report):
            owner = cfg["agent"]["default"]
            calls.append((owner, report.subject))
            return {"ok": True, "agent": owner}

        listener = Daemon(self.home, runner=runner)
        self.addCleanup(listener.stop)

        def emit(subject):
            write_event(self.home, Event(type="app.crash", subject=subject))
            listener.tick()
            listener.wait_idle()

        codex, claude = {"agent": "codex"}, {"agent": "claude"}
        path = ["--home", str(self.home.root)]
        with mock.patch("builtins.print"):
            emit("paused.exe")
            self.assertEqual(calls, [])
            self.assertEqual(cli.main(path + ["wakes", "enable", "--agent", "claude"]), 2)
            self.assertEqual(cli.main(path + ["wakes", "enable"]), 2)
            self.assertEqual(cli.main(path + ["wakes", "enable", "--agent", "codex"]), 0)
            emit("first.exe")
            self.assertTrue(mcp_server.call_tool(self.home, "notify_user", {"message": "hi"}, claude)["isError"])
            self.assertFalse(mcp_server.call_tool(self.home, "notify_user", {"message": "hi"}, codex)["isError"])
            for session in (codex, claude):
                listing = mcp_server.handle(self.home, {"id": 1, "method": "tools/list"}, session)
                names = {tool["name"] for tool in listing["result"]["tools"]}
                self.assertIn("capture_screen", names)
                self.assertEqual("notify_user" in names, session is codex)
            self.assertEqual(cli.main(path + ["notify", "hello", "--agent", "claude"]), 2)
            self.assertEqual(cli.main(path + ["verify", "--send-test-notification", "--agent", "claude"]), 2)
            self.assertEqual(cli.main(path + ["crashtest", "--agent", "claude"]), 2)
            self.assertEqual(cli.main(path + ["wakes", "pause", "--agent", "claude"]), 2)
            self.assertEqual(cli.main(path + ["setup", "--agent", "claude"]), 0)
            emit("next.exe")
            for session in (codex, claude):
                output = mcp_server.call_tool(self.home, "recent_events", {"limit": 10}, session)
                self.assertIn("first.exe", output["content"][0]["text"])
            self.assertEqual(cli.main(path + ["wakes", "pause", "--agent", "codex"]), 0)
            emit("paused-again.exe")
        self.assertEqual(calls, [("codex", "first.exe"), ("codex", "next.exe")])

    def test_pause_drops_queued_reports_while_first_wake_finishes(self):
        config_mod.update_user(self.home, {
            "agent": {"default": "codex"}, "reflex": {"aggregate_window_s": 0},
            "sources": {"disk": {"enabled": False}},
        })
        began, finish = threading.Event(), threading.Event()
        calls = []

        def runner(home, cfg, report):
            calls.append(cfg["agent"]["default"])
            began.set()
            finish.wait(5)
            return {"ok": True}

        listener = Daemon(self.home, runner=runner)
        self.addCleanup(listener.stop)
        write_event(self.home, Event(type="app.crash", subject="first.exe", ts=1))
        write_event(self.home, Event(type="app.crash", subject="queued.exe", ts=2))
        listener.tick()
        try:
            self.assertTrue(began.wait(3))
            with mock.patch("builtins.print"):
                self.assertEqual(cli.main(["--home", str(self.home.root), "wakes", "pause", "--agent", "codex"]), 0)
        finally:
            finish.set()
        listener.wait_idle()
        self.assertEqual(calls, ["codex"])

    @unittest.skipUnless(os.name == "nt", "Windows single-agent binding")
    def test_windows_rejects_a_second_agent_in_a_wake_rule(self):
        self.cfg["reflex"]["rules"] = [{"match": "app.crash", "action": "wake", "agent": "codex"}]
        with self.assertRaisesRegex(config_mod.ConfigError, "another agent"):
            config_mod.validate(self.cfg)
        event = report()
        event.agent = "codex"
        with mock.patch.object(agents, "invoke") as invoke:
            result = wake.run_wake(self.home, self.cfg, event)
        self.assertFalse(result["ok"])
        invoke.assert_not_called()

    def test_claude_requires_first_party_account_status(self):
        status = {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "bedrock"}
        with mock.patch.object(agents, "resolve_executable", return_value="claude"), \
             mock.patch.object(agents.proc, "run_full", return_value={
                 "rc": 0, "stdout": json.dumps(status), "stderr": ""}) as runner:
            self.assertFalse(agents.invoke(self.home, self.cfg, "claude", "incident")["ok"])
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(runner.call_args.args[0], ["claude", "auth", "status"])


class WakeAndIncidents(TempHome):
    def test_codex_app_wake_queues_into_chat_without_sending_a_second_toast(self):
        self.cfg["agent"]["default"] = "codex"
        self.cfg["agent"]["codex_app_thread"] = SESSION
        with mock.patch.object(agents, "resolve_executable", return_value="codex"), \
             mock.patch.object(agents, "_login_state", return_value=(True, "chatgpt account")), \
             mock.patch.object(codexapp, "enqueue", return_value="queue-entry") as enqueue:
            result = wake.run_wake(self.home, self.cfg, report())
        self.assertTrue(result["ok"])
        self.assertEqual(enqueue.call_args.args[:2], ("codex", SESSION))
        self.assertIn("<event-report>", enqueue.call_args.args[2])
        inc = incidents.get(self.home, result["incident_id"])
        self.assertEqual((inc["status"], inc["session_id"], inc["queue_id"]), ("queued", SESSION, "queue-entry"))
        self.assertEqual(self.shown, [])
        self.assertFalse(self.home.outbox.exists())

    def test_codex_app_queue_refuses_api_only_login(self):
        with mock.patch.object(agents, "resolve_executable", return_value="codex"), \
             mock.patch.object(agents, "_login_state", return_value=(True, "api key")), \
             mock.patch.object(codexapp, "enqueue") as enqueue:
            result = agents.invoke(self.home, self.cfg, "codex", "event", app_thread=SESSION)
        self.assertFalse(result["ok"])
        enqueue.assert_not_called()

    def test_wake_delivers_the_models_own_message_as_a_clickable_bubble(self):
        fake_agent(self.cfg, CLAUDE_OK)
        self.cfg["agent"]["identity"] = "Vinci"
        result = wake.run_wake(self.home, self.cfg, report())
        self.assertTrue(result["ok"], result)
        inc = incidents.get(self.home, result["incident_id"])
        self.assertEqual((inc["status"], inc["session_id"], inc["agent"]), ("notified", SESSION, "claude"))
        self.assertEqual(len(self.shown), 1)
        self.assertEqual(self.shown[0]["title"], "Vinci")
        self.assertEqual(self.shown[0]["incident_id"], inc["id"])
        self.assertIn("Want me to take a look?", self.shown[0]["message"])
        self.assertEqual(inc["message"], self.shown[0]["message"])

    def test_auth_error_never_reaches_the_user_as_the_ai(self):
        fake_agent(self.cfg, CLAUDE_AUTH_ERROR)  # exit code 0, like the real CLI
        result = wake.run_wake(self.home, self.cfg, report())
        self.assertFalse(result["ok"])
        self.assertEqual(incidents.get(self.home, result["incident_id"])["status"], "failed")
        self.assertEqual(len(self.shown), 1)
        self.assertEqual(self.shown[0]["title"], "VisumWay system notice")
        self.assertIsNone(self.shown[0]["incident_id"])
        self.assertIn("waking the AI failed", self.shown[0]["message"])

    def test_model_may_decide_to_say_nothing(self):
        fake_agent(self.cfg, json.dumps({"type": "result", "is_error": False, "result": "NOTHING",
                                         "session_id": SESSION}))
        result = wake.run_wake(self.home, self.cfg, report())
        self.assertTrue(result["ok"])
        self.assertEqual(self.shown, [])
        self.assertEqual(incidents.get(self.home, result["incident_id"])["status"], "quiet")

    def test_api_keys_are_withheld_so_the_account_login_is_used(self):
        leak = "sys.stdout.write('KEY' if os.environ.get('ANTHROPIC_API_KEY') else 'CLEAN'); sys.exit(0)"
        self.cfg["agent"]["adapters"]["claude"]["output"] = "text"
        fake_agent(self.cfg, "", extra=leak)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            self.assertEqual(agents.invoke(self.home, self.cfg, "claude", "x")["message"], "CLEAN")
            self.cfg["agent"]["use_account_login"] = False
            self.assertEqual(agents.invoke(self.home, self.cfg, "claude", "x")["message"], "CLEAN")

    def test_agent_runs_in_the_workspace_and_knows_its_incident(self):
        probe = ("sys.stdout.write(os.getcwd()+'|'+os.environ.get('VISUMWAY_INCIDENT_ID','')); sys.exit(0)")
        self.cfg["agent"]["adapters"]["claude"]["output"] = "text"
        fake_agent(self.cfg, "", extra=probe)
        result = wake.run_wake(self.home, self.cfg, report())
        cwd, incident_id = result["message"].split("|")
        self.assertEqual(os.path.realpath(cwd), os.path.realpath(str(self.home.workspace)))
        self.assertEqual(incident_id, result["incident_id"])

    def test_hostile_session_id_is_dropped(self):
        inc = incidents.create(self.home, report().to_dict(), "claude")
        incidents.update(self.home, inc["id"], session_id='x" & calc.exe & "')
        self.assertIsNone(incidents.get(self.home, inc["id"])["session_id"])
        self.assertIsNone(incidents.get(self.home, "../../etc/passwd"))
        self.assertIsNone(incidents.update(self.home, "../../etc/passwd", status="opened"))


class ClickHandling(TempHome):
    def setUp(self):
        super().setUp()
        self.launched = []
        self.inc = incidents.create(self.home, report().to_dict(), "claude")

    def launcher(self, argv, cwd, cfg):
        self.launched.append((argv, cwd))
        return {"ok": True}

    def test_only_strict_links_are_accepted(self):
        good = "visumway://investigate/" + self.inc["id"]
        self.assertEqual(opener.parse(good), ("investigate", self.inc["id"]))
        for bad in ("visumway://run/" + self.inc["id"], "visumway://open/" + self.inc["id"] + "?x=1",
                    "visumway://open/../../x", "http://open/" + self.inc["id"], "visumway://open/ZZZ",
                    good + " & calc.exe", ""):
            with self.assertRaises(ValueError, msg=bad):
                opener.parse(bad)
        res = opener.handle(self.home, self.cfg, "visumway://open/000000000000", launcher=self.launcher)
        self.assertEqual((res["ok"], self.launched), (False, []))

    def test_click_resumes_the_same_session_in_the_same_folder(self):
        incidents.update(self.home, self.inc["id"], session_id=SESSION)
        res = opener.handle(self.home, self.cfg, "visumway://open/" + self.inc["id"], launcher=self.launcher)
        self.assertTrue(res["ok"] and res["resumed"])
        argv, cwd = self.launched[0]
        self.assertEqual(argv, ["claude", "--resume", SESSION])
        self.assertEqual(cwd, str(self.home.workspace))
        self.assertEqual(incidents.get(self.home, self.inc["id"])["status"], "opened")

    def test_codex_popup_can_open_the_app_and_preserves_the_terminal_fallback(self):
        incidents.update(self.home, self.inc["id"], agent="codex", session_id=SESSION)
        self.cfg["open"] = {"codex_in_app": True}
        with mock.patch.object(codexapp, "open_thread", return_value=True) as start:
            result = opener.handle(self.home, self.cfg, self.inc["id"], launcher=self.launcher)
        start.assert_called_once_with(SESSION)
        self.assertEqual(result["surface"], "codex-app")
        self.assertEqual(self.launched, [])
        self.assertEqual(incidents.get(self.home, self.inc["id"])["status"], "opened")
        with mock.patch.object(codexapp, "open_thread", return_value=False):
            result = opener.handle(self.home, self.cfg, self.inc["id"], launcher=self.launcher)
        self.assertTrue(result["resumed"])
        self.assertEqual(self.launched[0][0], ["codex", "resume", SESSION])

    def test_click_uses_the_original_adapter_after_changing_default(self):
        incidents.update(self.home, self.inc["id"], session_id=SESSION)
        self.cfg["agent"]["default"] = "codex"
        self.cfg["open"] = {"codex_in_app": True}
        with mock.patch.object(codexapp, "open_thread") as launch_app:
            self.assertTrue(opener.handle(self.home, self.cfg, self.inc["id"], launcher=self.launcher)["ok"])
            launch_app.assert_not_called()
        self.assertEqual(self.launched[0][0], ["claude", "--resume", SESSION])
        self.cfg["agent"]["adapters"].pop("claude")
        result = opener.handle(self.home, self.cfg, self.inc["id"], launcher=self.launcher)
        self.assertIn("original incident adapter", result["error"])
        self.assertEqual(len(self.launched), 1)

    def test_investigate_button_adds_a_fixed_instruction(self):
        incidents.update(self.home, self.inc["id"], session_id=SESSION)
        opener.handle(self.home, self.cfg, "visumway://investigate/" + self.inc["id"], launcher=self.launcher)
        self.assertEqual(self.launched[0][0], ["claude", "--resume", SESSION, opener.INVESTIGATE_PROMPT])

    def test_without_a_session_the_agent_opens_with_the_incident_file(self):
        res = opener.handle(self.home, self.cfg, self.inc["id"], launcher=self.launcher)
        self.assertFalse(res["resumed"])
        argv = self.launched[0][0]
        self.assertEqual(argv[0], "claude")
        self.assertIn(self.inc["id"] + ".json", argv[1])
        self.assertNotIn("Game.exe", " ".join(argv))  # machine data never goes on a command line

    def test_later_snoozes_and_the_runtime_shows_it_again_without_a_model(self):
        incidents.update(self.home, self.inc["id"], status="notified", message="Your game crashed.")
        res = opener.handle(self.home, self.cfg, "visumway://later/" + self.inc["id"], launcher=self.launcher)
        self.assertEqual((res["ok"], self.launched), (True, []))
        self.assertEqual(incidents.get(self.home, self.inc["id"])["status"], "snoozed")
        calls = []
        self.cfg["sources"]["disk"]["enabled"] = False
        d = Daemon(self.home, self.cfg, runner=lambda *a: calls.append(a) or {"ok": True})
        self.assertEqual(d.redeliver_snoozed(time.time()), 0)  # not due yet
        self.assertEqual(d.redeliver_snoozed(time.time() + 31 * 60), 1)
        d.stop()
        self.assertEqual(calls, [])
        self.assertEqual(self.shown[-1], {"title": self.cfg["agent"]["identity"],
                                          "message": "Your game crashed.", "incident_id": self.inc["id"]})
        self.assertEqual(incidents.get(self.home, self.inc["id"])["status"], "notified")

    def test_terminal_command_construction(self):
        self.assertEqual(terminal.windows_command_line([r"C:\Program Files\nodejs\claude.cmd", "--resume", SESSION]),
                         'cmd /k ""C:\\Program Files\\nodejs\\claude.cmd" --resume %s"' % SESSION)
        cfg = {"open": {"terminal_argv": ["myterm", "--run", "{command}"]}}
        args, kwargs = terminal.build(["claude", "--resume", "x"], "/w", cfg)
        self.assertEqual((args, kwargs), (["myterm", "--run", "claude", "--resume", "x"], {"cwd": "/w"}))


class DesktopBridge(unittest.TestCase):
    def test_toast_payload_is_wellformed_and_escaped(self):
        nasty = 'He said "hi" <script>&</script>'
        root = ET.fromstring(desktop.toast_xml("Vin<ci", nasty, "0123456789ab"))
        self.assertEqual(root.get("activationType"), "protocol")
        self.assertEqual(root.get("launch"), "visumway://open/0123456789ab")
        texts = [t.text for t in root.iter("text")]
        self.assertEqual(texts[:2], ["Vin<ci", nasty])
        actions = {a.get("content"): a.get("arguments") for a in root.iter("action")}
        self.assertEqual(actions, {"Investigate": "visumway://investigate/0123456789ab",
                                   "Later": "visumway://later/0123456789ab"})
        plain = ET.fromstring(desktop.toast_xml("VisumWay system notice", "x"))
        self.assertIsNone(plain.get("launch"))
        self.assertEqual(list(plain.iter("action")), [])
        malformed = ET.fromstring(desktop.toast_xml("VisumWay", "bad\x00 & good", "a" * 12 + "\n"))
        self.assertIsNone(malformed.get("launch"))
        self.assertEqual(list(malformed.iter("text"))[1].text, "bad & good")

    def test_windows_status_reports_os_permission(self):
        with mock.patch.object(desktop, "registered", return_value=True), \
             mock.patch.object(desktop.proc, "run_full", return_value={
                 "rc": 0, "stdout": "DisabledForApplication", "stderr": ""}):
            self.assertEqual(desktop.windows_status(Home()), {
                "ok": False, "error": "Windows toast setting: DisabledForApplication"})

    def test_click_during_delivery_retains_opened_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Home(tmp).ensure()
            incident_id = incidents.create(home, {}, "codex")["id"]
            cfg = {"notify": {"channels": [{"type": "desktop"}, {"type": "file"}]}}

            def click(*args):
                self.assertEqual(incidents.get(home, incident_id)["message"], "The application crashed.")
                incidents.update(home, incident_id, status="opened")
                return {"ok": True}

            with mock.patch.object(desktop, "show", side_effect=click):
                results = notify.send(home, cfg, "The application crashed.", incident_id=incident_id)
            self.assertTrue(all(result["ok"] for result in results))
            self.assertEqual(incidents.get(home, incident_id)["status"], "opened")

    def test_windows_registration_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Home(tmp)
            plan = desktop.registry_plan(home, {"agent": {"identity": "Vinci"}})
            keys = {(k, n): v for k, n, v in plan}
            self.assertEqual(keys[(r"Software\Classes\AppUserModelId\VisumWay.Agent", "DisplayName")], "Vinci")
            self.assertEqual(keys[(r"Software\Classes\visumway", "URL Protocol")], "")
            cmd = keys[(r"Software\Classes\visumway\shell\open\command", "")]
            self.assertTrue(cmd.endswith('open "%1"'))
            self.assertIn(str(home.root), cmd)
            self.assertTrue(all(k.startswith("Software\\Classes") for k, _, _ in plan))  # per-user only

    def test_linux_button_click_is_dispatched(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Home(tmp).ensure()
            seen = []
            runner = lambda argv, timeout: seen.append(argv) or {"rc": 0, "stdout": "investigate\n", "stderr": ""}
            handler = lambda home, cfg, incident, action: {"ok": True, "got": (incident, action)}
            res = desktop.wait_and_dispatch(home, {}, "0123456789ab", "Vinci", "msg", runner=runner, handler=handler)
            self.assertEqual(res["got"], ("0123456789ab", "investigate"))
            self.assertIn("--action=later=Later", seen[0])
            dismissed = desktop.wait_and_dispatch(home, {}, "0123456789ab", "Vinci", "msg", handler=handler,
                                                  runner=lambda a, timeout: {"rc": 0, "stdout": "", "stderr": ""})
            self.assertIsNone(dismissed["action"])

    def test_desktop_channel_failure_does_not_break_other_channels(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Home(tmp).ensure()
            with mock.patch.object(desktop, "backend", return_value=None):
                res = notify.send(home, {"notify": {"channels": [{"type": "desktop"}, {"type": "file"}]}}, "hi")
            self.assertEqual([(r["channel"], r["ok"]) for r in res], [("desktop", False), ("file", True)])


def _event_xml(provider, event_id, record, data, when="2026-11-15T21:00:00.1234567Z", named=False):
    cells = "".join("<Data%s>%s</Data>" % ((" Name='%s'" % n) if named else "", v) for n, v in data)
    return ("<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System>"
            "<Provider Name='%s'/><EventID Qualifiers='0'>%d</EventID><Level>2</Level>"
            "<TimeCreated SystemTime='%s'/><EventRecordID>%d</EventRecordID><Channel>Application</Channel>"
            "</System><EventData>%s</EventData></Event>" % (provider, event_id, when, record, cells))


CRASH_DATA = [("AppName", "Game.exe"), ("AppVersion", "1.0.0.0"), ("AppTimeStamp", "65000000"),
              ("ModuleName", "d3d11.dll"), ("ModuleVersion", "10.0.0.0"), ("ModuleTimeStamp", "12345678"),
              ("ExceptionCode", "c0000005"), ("FaultingOffset", "0000000000012345"), ("ProcessId", "0x1a2b")]


class WindowsEventBridge(unittest.TestCase):
    def test_crash_record_becomes_an_event(self):
        for named in (False, True):
            recs = winevents.parse_events(_event_xml("Application Error", 1000, 5001, CRASH_DATA, named=named))
            ev = winevents.to_event(recs[0])
            self.assertEqual((ev.type, ev.subject, ev.severity), ("app.crash", "Game.exe", "error"))
            self.assertEqual(ev.data["exception_code"], "c0000005")
            self.assertEqual(ev.data["faulting_module"], "d3d11.dll")
            self.assertEqual(ev.data["event_id"], 1000)
            self.assertEqual(ev.data.get("pid"), 0x1A2B if named else None)
        hang = winevents.to_event(winevents.parse_events(
            _event_xml("Application Hang", 1002, 5002, [("AppName", "Editor.exe")]))[0])
        self.assertEqual((hang.type, hang.subject), ("app.hang", "Editor.exe"))
        gpu = winevents.to_event(winevents.parse_events(_event_xml("Display", 4101, 77, [("", "nvlddmkm")]))[0])
        self.assertEqual((gpu.type, gpu.subject), ("gpu.error", "nvlddmkm"))
        self.assertEqual(winevents.parse_events("garbage <<<"), [])

    def test_collect_emits_each_record_once_and_never_replays_history(self):
        now = 1794776400.0  # 2026-11-15T21:00:00Z
        log = {"Application": [(4000, "2026-11-01T00:00:00.0Z", "Old.exe")], "System": []}

        def runner(cmd, timeout):
            name = cmd[2]
            if "Windows Error Reporting" in cmd[3]:
                return {"rc": 0, "stdout": ""}
            after = int(re.search(r"EventRecordID>(\d+)", cmd[3]).group(1))
            rows = [r for r in log[name] if r[0] > after]
            rows = rows[-1:] if "/rd:true" in cmd else rows
            xml = "".join(_event_xml("Application Error", 1000, r[0], [("AppName", r[2])] + CRASH_DATA[1:], when=r[1])
                          for r in rows)
            return {"rc": 0, "stdout": xml}

        with tempfile.TemporaryDirectory() as tmp:
            home = Home(tmp).ensure()
            clock = lambda: now
            self.assertEqual(winevents.collect(home, runner, clock), [])  # install baseline: old crash ignored
            log["Application"] += [(4001, "2026-11-15T20:59:58.0Z", "Game.exe"),
                                   (4002, "2026-11-15T20:59:59.0Z", "Game.exe")]
            first = winevents.collect(home, runner, clock)
            self.assertEqual([e.data["record_id"] for e in first], [4001, 4002])
            self.assertEqual(winevents.collect(home, runner, clock), [])  # nothing new, nothing repeated
            self.assertEqual([e.subject for e in drain_inbox(home)], ["Game.exe", "Game.exe"])

    def test_first_run_takes_the_record_that_triggered_it(self):
        now = 1794776400.0
        xml = _event_xml("Application Error", 1000, 9, CRASH_DATA, when="2026-11-15T20:59:30.0Z")
        with tempfile.TemporaryDirectory() as tmp:
            home = Home(tmp).ensure()
            got = winevents.collect(home, lambda cmd, timeout: {
                "rc": 0, "stdout": xml if cmd[2] == "Application" and "Windows Error Reporting" not in cmd[3]
                else ""}, lambda: now)
            self.assertEqual([e.subject for e in got], ["Game.exe"])

    def test_graphics_reports_skip_existing_and_deduplicate_report_stages(self):
        report = "09b21040-59c6-4991-9a93-70407dc20ea0"
        later = "f59b41ac-c7a3-44cb-8228-190d40033e07"
        rows = []

        def graphics_record(number, identifier, code="117"):
            return number, _event_xml("Windows Error Reporting", 1001, number, [
                ("EventName", "LiveKernelEvent"), ("P1", code), ("ReportId", identifier)], named=True)

        def runner(cmd, timeout):
            if "Windows Error Reporting" not in cmd[3]:
                return {"rc": 0, "stdout": ""}
            self.assertIn("Data[@Name='P1']='117'", cmd[3])
            after = int(re.search(r"EventRecordID>(\d+)", cmd[3]).group(1))
            selected = [xml for number, xml in rows if number > after]
            return {"rc": 0, "stdout": "".join(selected[-1:] if "/rd:true" in cmd else selected)}

        with tempfile.TemporaryDirectory() as tmp:
            home = Home(tmp).ensure()
            (home.state / "winevents.json").write_text('{"Application": 41, "System": 25}', encoding="utf-8")
            rows.append(graphics_record(40, report))
            self.assertEqual(winevents.collect(home, runner, baseline=True), [])
            rows += [graphics_record(42, report.upper()), graphics_record(43, later)]
            first = winevents.collect(home, runner)
            self.assertEqual([(e.type, e.data["record_id"], e.data["live_kernel_code"]) for e in first],
                             [("gpu.error", 43, "0x117")])
            rows += [graphics_record(44, later), graphics_record(45, "", code="193")]
            self.assertEqual(winevents.collect(home, runner), [])
            self.assertEqual([e.data["record_id"] for e in drain_inbox(home)], [43])

    def test_failed_baseline_does_not_save_a_zero_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Home(tmp).ensure()
            for result in ({"rc": 5, "stdout": ""}, {"rc": 0, "stdout": "<broken"}):
                with self.assertRaises(OSError):
                    winevents.collect(home, lambda cmd, timeout: result, baseline=True)
                self.assertFalse((home.state / "winevents.json").exists())
                self.assertEqual(drain_inbox(home), [])

    def test_scheduled_task_definitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Home(os.path.join(tmp, "home & space"))
            sid = "S-1-5-21-1001"
            task = ET.fromstring(winevents.task_definition(home, sid))
            ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
            subscription = ET.fromstring(task.findtext(".//t:Subscription", namespaces=ns))
            selects = {log: " ".join(row.text for row in subscription.findall(".//Select") if row.get("Path") == log)
                       for log in ("Application", "System")}
            self.assertIn("Application Error", selects["Application"])
            self.assertIn("Application Hang", selects["Application"])
            self.assertIn("Data[@Name='EventName']='LiveKernelEvent'", selects["Application"])
            self.assertIn("EventID=4101", selects["System"])
            self.assertEqual(task.findtext(".//t:Principal/t:UserId", namespaces=ns), sid)
            for key, value in (("DisallowStartIfOnBatteries", "false"), ("StopIfGoingOnBatteries", "false"),
                               ("MultipleInstancesPolicy", "Queue")):
                self.assertEqual(task.findtext(".//t:" + key, namespaces=ns), value)
            arguments = task.findtext(".//t:Arguments", namespaces=ns)
            self.assertIn('"%s"' % home.root, arguments)
            self.assertTrue(arguments.endswith("bridge run windows-events"))
            if os.name != "nt":
                self.assertIsNone(winevents.installed(Home(tmp)))
                self.assertEqual(winevents.install(Home(tmp)), ["windows-events: not applicable on this OS"])


@unittest.skipIf(os.name == "nt", "uses POSIX shell stand-ins for the agent CLIs")
class AgentDiscovery(TempHome):
    """Installed, signed in, and verified are three separate facts."""

    def make_cli(self, name, body):
        bindir = os.path.join(self.tmp.name, "bin")
        os.makedirs(bindir, exist_ok=True)
        path = os.path.join(bindir, name)
        with open(path, "w") as f:
            f.write("#!/bin/sh\n" + textwrap.dedent(body))
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        return bindir

    def fake_claude(self, logged_in=True, reply=agents.PROBE_TOKEN, version="2.1.325 (Claude Code)"):
        ok = json.dumps({"type": "result", "is_error": False, "result": reply, "session_id": SESSION})
        return self.make_cli("claude", """\
            case "$1" in
              --version) echo '%s';;
              auth) echo '{"loggedIn": %s, "authMethod": "%s", "apiProvider": "firstParty"}';;
              -p) cat >/dev/null; echo '%s';;
              *) echo "interactive $@" >> "%s/interactive.log";;
            esac
            """ % (version, "true" if logged_in else "false", "claude.ai" if logged_in else "none", ok, self.tmp.name))

    def path(self, bindir):
        return mock.patch.dict(os.environ, {"PATH": bindir + os.pathsep + "/usr/bin:/bin"})

    def test_installed_and_signed_in_is_not_verified_until_probed(self):
        with self.path(self.fake_claude()):
            info = agents.inspect(self.home, self.cfg, "claude")
            self.assertTrue(info["installed"])
            self.assertEqual((info["signed_in"], info["auth"], info["verified"]), (True, "claude.ai", False))
            self.assertEqual(agents.inspect(self.home, self.cfg, "codex")["installed"], None)
            res = agents.probe(self.home, self.cfg, "claude")
            self.assertTrue(res["verified"] and res["session_captured"], res)
            self.assertTrue(agents.inspect(self.home, self.cfg, "claude")["verified"])
        # a new version of the agent must be verified again
        with self.path(self.fake_claude(version="3.0.0 (Claude Code)")):
            self.assertFalse(agents.inspect(self.home, self.cfg, "claude")["verified"])

    def test_signed_out_and_wrong_reply_are_not_verified(self):
        with self.path(self.fake_claude(logged_in=False, reply="Sure! How can I help?")):
            info = agents.inspect(self.home, self.cfg, "claude")
            self.assertEqual((info["signed_in"], info["auth"]), (False, "none"))
            self.assertFalse(agents.probe(self.home, self.cfg, "claude")["verified"])

    def test_codex_login_status_text(self):
        bindir = self.make_cli("codex", """\
            case "$1" in
              --version) echo 'codex-cli 0.130.0';;
              login) echo 'Logged in using ChatGPT';;
            esac
            """)
        with self.path(bindir):
            info = agents.inspect(self.home, self.cfg, "codex")
            self.assertEqual((info["signed_in"], info["auth"], info["version"]),
                             (True, "chatgpt account", "codex-cli 0.130.0"))
            self.assertEqual(agents.recommend(self.cfg, agents.inspect_all(self.home, self.cfg)), "codex")

    def cli(self, bindir, *args):
        env = dict(os.environ, PYTHONPATH=SRC, VISUMWAY_HOME=self.tmp.name,
                   PATH=bindir + os.pathsep + os.environ["PATH"])
        return subprocess.run([sys.executable, "-m", "visumway", *args], capture_output=True, text=True,
                              env=env, timeout=60)

    def test_whole_chain_through_the_installed_commands(self):
        """setup -> probe -> runtime running -> crash event -> model message ->
        click -> same session resumed. Only the model itself is a stand-in."""
        reply = "Hey, I noticed Game.exe crashed. Want me to take a look?"
        bindir = self.fake_claude(reply=reply)
        r = self.cli(bindir, "setup", "--agent", "claude", "--no-service", "--no-bridges")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("NOT yet verified", r.stdout)
        self.assertEqual(self.cli(bindir, "wakes", "enable", "--agent", "claude").returncode, 0)
        config_mod.update_user(self.home, {
            "reflex": {"aggregate_window_s": 0}, "notify": {"channels": [{"type": "file"}]},
            "open": {"terminal_argv": ["{command}"]}})

        probe = self.cli(bindir, "agent", "probe")
        self.assertEqual(probe.returncode, 1)  # the stand-in answers the crash line, not the probe token
        self.assertFalse(json.loads(probe.stdout)["verified"])

        env = dict(os.environ, PYTHONPATH=SRC, VISUMWAY_HOME=self.tmp.name,
                   PATH=bindir + os.pathsep + os.environ["PATH"])
        runtime = subprocess.Popen([sys.executable, "-m", "visumway", "run", "--interval", "0.1"], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.assertEqual(self.cli(bindir, "emit", "app.crash", "--subject", "Game.exe",
                                      "--severity", "error").returncode, 0)
            inc = None
            for _ in range(100):
                found = [i for i in incidents.recent(self.home) if i["status"] == "notified"]
                if found:
                    inc = found[0]
                    break
                time.sleep(0.1)
            self.assertIsNotNone(inc, "no notification was produced")
            self.assertEqual((inc["message"], inc["session_id"]), (reply, SESSION))
            sent = [json.loads(l) for l in self.home.outbox.read_text().splitlines()]
            self.assertEqual((sent[-1]["message"], sent[-1]["incident_id"]), (reply, inc["id"]))

            clicked = self.cli(bindir, "open", "visumway://open/" + inc["id"])
            self.assertEqual(clicked.returncode, 0, clicked.stdout + clicked.stderr)
            for _ in range(50):
                if os.path.exists(os.path.join(self.tmp.name, "interactive.log")):
                    break
                time.sleep(0.1)
            with open(os.path.join(self.tmp.name, "interactive.log")) as f:
                self.assertEqual(f.read().strip(), "interactive --resume " + SESSION)
            self.assertEqual(self.cli(bindir, "open", "visumway://open/ffffffffffff").returncode, 1)
            self.assertIn(inc["id"], self.cli(bindir, "incidents").stdout)
        finally:
            runtime.terminate()
            runtime.wait(timeout=10)

        un = self.cli(bindir, "uninstall", "--purge", "--no-service", "--no-bridges")
        self.assertEqual(un.returncode, 0, un.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "config.json")))


if __name__ == "__main__":
    unittest.main()
