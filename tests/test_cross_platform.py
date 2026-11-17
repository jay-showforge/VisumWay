"""Platform adapters: parse/build/unit exercise without claiming host verification."""
import json
import os
import plistlib
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from visumway import agents, config as config_mod, plan, service
from visumway.bridges import codexapp, desktop, linuxevents, macevents, winshortcut
from visumway.events import drain_inbox
from visumway.paths import Home


class MacReports(unittest.TestCase):
    def test_new_report_is_emitted_once_and_old_reports_are_baselined(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Home(Path(temp) / "home").ensure()
            directory = Path(temp) / "DiagnosticReports"
            directory.mkdir()
            old = directory / "Old.crash"
            old.write_text("Process: OldApp [123]\nException Type: EXC_BAD_ACCESS")
            self.assertEqual(macevents.collect(home, directory), [])
            new = directory / "New.ips"
            new.write_text('{"procName": "TheEditor", "bug_type": "309"}\n{}')
            evs = macevents.collect(home, directory)
            self.assertEqual([(e.type, e.subject) for e in evs], [("app.crash", "TheEditor")])
            self.assertEqual(len(drain_inbox(home)), 1)
            self.assertEqual(macevents.collect(home, directory), [])
            hang = directory / "Window.hang"
            hang.write_text("Process: Calendar [123]")
            self.assertEqual(macevents.collect(home, directory)[0].type, "app.hang")

    def test_report_symlinks_are_ignored_and_plist_is_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "logs"
            directory.mkdir()
            outside = Path(temp) / "private.ips"
            outside.write_text('abc')
            link = directory / "link.ips"
            try:
                link.symlink_to(outside)
            except OSError:  # Windows CI runners may lack symlink privileges
                pass
            else:
                self.assertIsNone(macevents.report_event(link, directory, 123))
            name = "home with & spaces" if os.name == "nt" else "home with & <> spaces"
            home = Home(Path(temp) / name).ensure()
            spec = macevents.describe(home, directory)
            data = plistlib.loads(spec["content"])
            self.assertEqual(data["ProgramArguments"][4], str(home.root))
            self.assertEqual(data["WatchPaths"], [str(directory)])


class LinuxJournal(unittest.TestCase):
    def test_parse_crashes_but_not_ordinary_errors(self):
        lines = [
            {"__CURSOR": "a", "MESSAGE": "Disk is full", "_COMM": "app"},
            {"__CURSOR": "b", "MESSAGE": "Main process exited, code=dumped, status=11/SEGV",
             "_COMM": "editor", "__REALTIME_TIMESTAMP": "1794776400000000"},
            {"__CURSOR": "c", "MESSAGE_ID": linuxevents.COREDUMP_ID,
             "MESSAGE": "Process dumped core", "COREDUMP_COMM": "gimp",
             "__REALTIME_TIMESTAMP": "1794776400000000"},
        ]
        evs = linuxevents.parse_records("\n".join(map(json.dumps, lines)))
        self.assertEqual([(e.subject, e.type) for _, e in evs],
                         [("editor", "app.crash"), ("gimp", "app.crash")])
        self.assertTrue(all(isinstance(e.ts, float) for _, e in evs))

    def test_first_scan_baselines_then_writes_events_once(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Home(temp).ensure()
            records = [{"__CURSOR": "a", "MESSAGE": "Unimportant"}]
            def run(cmd, timeout):
                if "--after-cursor" in cmd:
                    cursor = cmd[cmd.index("--after-cursor") + 1]
                    emitted = [r for r in records if r["__CURSOR"] > cursor]
                else:
                    emitted = records[:]
                return {"rc": 0, "stdout": "\n".join(map(json.dumps, emitted)), "stderr": ""}
            self.assertEqual(linuxevents.collect(home, runner=run), [])
            records.append({"__CURSOR": "b", "MESSAGE": "Main process exited, code=dumped, status=11/SEGV",
                            "_COMM": "inkscape"})
            self.assertEqual(linuxevents.collect(home, runner=run)[0].subject, "inkscape")
            self.assertEqual(linuxevents.collect(home, runner=run), [])
            self.assertEqual(drain_inbox(home)[0].source, "linux-journal")

    def test_timer_definition_is_a_user_scoped_one_shot(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Home(temp)
            specs = linuxevents.describe(home)
            self.assertEqual(len(specs), 2)
            self.assertIn("OnUnitActiveSec=1min", next(v for k,v in specs.items() if k.suffix == ".timer"))
            self.assertIn("Type=oneshot", next(v for k,v in specs.items() if k.suffix == ".service"))


class NativeNotifications(unittest.TestCase):
    def test_macos_notifier_uses_quoted_fixed_incident_command(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Home(Path(temp) / 'home has spaces').ensure()
            fake = {"rc": 0, "stdout": "", "stderr": ""}
            with mock.patch.object(desktop, "backend", return_value="terminal-notifier"), \
                 mock.patch.object(desktop.proc, "run_full", return_value=fake) as run:
                r = desktop.show(home, {}, "Vinci", "Are you okay?", "0123456789ab")
                self.assertTrue(r["ok"])
                argv = run.call_args.args[0]
                self.assertEqual(argv[0], "terminal-notifier")
                self.assertEqual(argv[argv.index("-message") + 1], "Are you okay?")
                self.assertIn('0123456789ab', argv[argv.index("-execute") + 1])
                desktop.show(home, {}, "Vinci", "Hi", "bad;rm -rf /")
                self.assertNotIn("-execute", run.call_args.args[0])

    def test_windows_shortcut_uses_documented_shell_property(self):
        self.assertIn('9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3', winshortcut.SCRIPT)
        self.assertIn('Marshal.StringToCoTaskMemUni', winshortcut.SCRIPT)
        self.assertIn('IPropertyStore', winshortcut.SCRIPT)
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(winshortcut.shortcut_path(temp).name, winshortcut.SHORTCUT_NAME)


class PlatformPlans(unittest.TestCase):
    def test_cross_platform_startup_definitions(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Home(Path(temp)/'home & space')
            mac = service.describe(home, "macos")
            macplist = plistlib.loads(next(iter(mac['files'].values())).encode('utf-8'))
            self.assertEqual(macplist['EnvironmentVariables']['VISUMWAY_HOME'], str(home.root))
            xdg = service.describe(home, "linux-xdg")
            self.assertEqual(xdg['kind'], "xdg-autostart")
            self.assertIn('Exec=', next(iter(xdg['files'].values())))
            self.assertTrue(all('visumway' in path for path in xdg['files']))
            sid = "S-1-5-21-1001"
            windows = service.describe(home, "windows", user_sid=sid)
            task = ET.fromstring(next(iter(windows["files"].values())))
            ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
            self.assertEqual(task.findtext(".//t:LogonTrigger/t:UserId", namespaces=ns), sid)
            self.assertEqual(task.findtext(".//t:LogonType", namespaces=ns), "InteractiveToken")
            self.assertEqual(task.findtext(".//t:ExecutionTimeLimit", namespaces=ns), "PT0S")
            self.assertEqual(task.findtext(".//t:TimeTrigger/t:Repetition/t:Interval", namespaces=ns), "PT1M")
            self.assertIsNotNone(task.find(".//t:TimeTrigger/t:StartBoundary", namespaces=ns))

    def test_system_specific_plans_have_native_event_bridges(self):
        bp = {"display": {"server": "macos-quartz", "capture_backends": []},
              "service_manager": "launchd", "gpus": [], "os": {"system": "Darwin"},
              "agent_runtimes": {}}
        rows = plan.build_plan(bp, config_mod.DEFAULT_CONFIG, [], [])
        self.assertTrue(any("macos-reports" in r["action"] for r in rows))
        bp['display']['server'] = 'wayland'
        bp['service_manager'] = 'systemd'
        bp['os']['system'] = 'Linux'
        rows = plan.build_plan(bp, config_mod.DEFAULT_CONFIG, [], [])
        self.assertTrue(any("linux-journal" in r["action"] for r in rows))


class AccountBillingSafeguards(unittest.TestCase):
    def test_api_only_sign_in_is_rejected_before_model_call(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Home(temp).ensure()
            cfg = json.loads(json.dumps(config_mod.DEFAULT_CONFIG))
            result = {"rc": 0, "stdout": "", "stderr": ""}
            with mock.patch.object(agents, "_login_state", return_value=(True, "api_key")), \
                 mock.patch.object(agents.proc, "run_full", return_value=result) as runner:
                res = agents.invoke(home, cfg, "codex", "Please look")
                self.assertFalse(res["ok"])
                self.assertIn("No API billing fallback", res["error"])
                runner.assert_not_called()
            with mock.patch.object(agents, "_login_state", return_value=(True, "chatgpt account")), \
                 mock.patch.object(agents.shutil, "which", return_value="/usr/bin/codex"), \
                 mock.patch.object(agents.proc, "run_full", return_value={"rc": 0, "stdout": "OK", "stderr": ""}) as runner:
                res = agents.invoke(home, cfg, "codex", "Please look")
                self.assertTrue(res["ok"])
                self.assertEqual(runner.call_count, 1)

    def test_unknown_auth_is_not_auto_approved(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Home(temp).ensure()
            cfg = json.loads(json.dumps(config_mod.DEFAULT_CONFIG))
            with mock.patch.object(agents, "_login_state", return_value=(None, "unknown")):
                self.assertFalse(agents.invoke(home, cfg, "claude", "ping")["ok"])


class CodexAppQueue(unittest.TestCase):
    def test_submits_only_after_initialize_and_sends_report_on_stdin(self):
        script = """
import json
import sys

initialize = json.loads(sys.stdin.readline())
assert initialize["method"] == "initialize"
assert initialize["params"]["capabilities"]["experimentalApi"]
print(json.dumps({"id": initialize["id"], "result": {}}), flush=True)
assert json.loads(sys.stdin.readline())["method"] == "initialized"
call = json.loads(sys.stdin.readline())
assert call["method"] == "thread/queue/add"
assert call["params"]["threadId"] == "chat-id"
assert call["params"]["input"][0]["text"] == 'event: café & "<"'
print(json.dumps({"method": "unrelated/notification"}), flush=True)
print(json.dumps({"id": call["id"], "result": {"queuedSubmission": {"id": "queued-test"}}}), flush=True)
"""
        popen = codexapp.subprocess.Popen
        with mock.patch.object(codexapp.subprocess, "Popen", side_effect=lambda argv, **kw:
                               popen([argv[0], "-c", script], **kw)) as spawn:
            self.assertEqual(codexapp.enqueue(sys.executable, "chat-id", 'event: café & "<"',
                                              cwd=None, env=None), "queued-test")
        self.assertEqual(spawn.call_args.args[0], [sys.executable, "app-server", "--stdio"])


if __name__ == '__main__':
    unittest.main()
