"""Desktop notification bridge: the agent's own bubble on the user's screen.

Windows: a native toast shown under the agent's identity, without the AI
desktop app being open. Clicking it (or its buttons) activates the
visumway:// protocol handler, which looks the incident up locally and opens
the agent's interface with that context.

Linux: notify-send (with action buttons where libnotify supports them).
macOS: a basic notification through osascript (no click actions yet).

Nothing here runs while idle. A notification is shown only when a woken agent
has something to say.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import uuid
from xml.sax.saxutils import escape, quoteattr

from .. import proc
from ..paths import Home
from ..incidents import ID_RE
from . import winshortcut

AUMID = winshortcut.AUMID
SCHEME = "visumway"
ACTIONS = (("investigate", "Investigate"), ("later", "Later"))
_REGISTRY_BASE = r"Software\Classes"
_IDENTITY_KEY = _REGISTRY_BASE + "\\AppUserModelId\\" + AUMID

_PS_NOTIFIER = (
    "$ErrorActionPreference='Stop';"
    "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
    "$n=[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:VISUMWAY_AUMID);"
)
_PS_TOAST = _PS_NOTIFIER + (
    "$setting=[string]$n.Setting;"
    "if ($setting -ne 'Enabled') { throw ('Windows toast setting: ' + $setting) };"
    "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]|Out-Null;"
    "$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
    "$x.LoadXml([IO.File]::ReadAllText($env:VISUMWAY_TOAST_XML,[Text.Encoding]::UTF8));"
    "$t=New-Object Windows.UI.Notifications.ToastNotification $x;"
    "$n.Show($t)"
)


def backend() -> "str | None":
    if os.name == "nt":
        return "windows-toast" if shutil.which("powershell.exe") else None
    if sys.platform == "darwin":
        # Optional native notification utility adds click-to-open while the
        # zero-dependency AppleScript fallback remains available.
        if shutil.which("terminal-notifier"):
            return "terminal-notifier"
        return "osascript" if shutil.which("osascript") else None
    has_session = any(os.environ.get(k) for k in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"))
    return "notify-send" if has_session and shutil.which("notify-send") else None


def url(action: str, incident_id: str) -> str:
    return "%s://%s/%s" % (SCHEME, action, incident_id)


def toast_xml(title: str, message: str, incident_id: "str | None" = None) -> str:
    """Windows toast payload. All text is XML-escaped; the only thing a click
    carries is an action name and the incident id."""
    launch = ""
    actions = ""
    if incident_id and ID_RE.fullmatch(str(incident_id)):
        launch = " activationType=\"protocol\" launch=%s" % quoteattr(url("open", incident_id))
        actions = "<actions>%s</actions>" % "".join(
            "<action content=%s activationType=\"protocol\" arguments=%s/>"
            % (quoteattr(label), quoteattr(url(name, incident_id))) for name, label in ACTIONS)
    return ("<toast%s><visual><binding template=\"ToastGeneric\">"
            "<text>%s</text><text>%s</text>"
            "<text placement=\"attribution\">via VisumWay</text>"
            "</binding></visual>%s</toast>"
            % (launch, _xml_text(title), _xml_text(message), actions))


def _xml_text(text: str) -> str:
    return escape("".join(char for char in text if (
        char in "\t\n\r" or 0x20 <= ord(char) <= 0xD7FF or
        0xE000 <= ord(char) <= 0xFFFD or 0x10000 <= ord(char) <= 0x10FFFF)))


def windows_status(home: Home) -> dict:
    if not registered(home):
        return {"ok": False, "error": "Windows notification identity or click handler missing. Run visumway setup."}
    result = proc.run_full(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                            _PS_NOTIFIER + "[string]$n.Setting"],
                           timeout=15, env=dict(os.environ, VISUMWAY_AUMID=AUMID))
    setting = result["stdout"].strip()
    if result["rc"] == 0 and setting == "Enabled":
        return {"ok": True, "setting": setting}
    return {"ok": False, "error": "Windows toast setting: " + setting if setting
            else result["stderr"].strip()[:300] or "Windows toast notifier unavailable"}


def _show_windows(home: Home, title: str, message: str, incident_id) -> dict:
    if not registered(home):
        return {"ok": False, "backend": "windows-toast", "error": "Windows notification or click registration is missing"}
    xml_path = home.state / ("toast-%s.xml" % uuid.uuid4().hex[:8])
    xml_path.write_text(toast_xml(title, message, incident_id), encoding="utf-8")
    try:
        env = dict(os.environ, VISUMWAY_TOAST_XML=str(xml_path), VISUMWAY_AUMID=AUMID)
        # Windows PowerShell 5.1 (powershell.exe) is required: it can load WinRT types.
        res = proc.run_full(["powershell.exe", "-NoProfile", "-NonInteractive",
                             "-Command", _PS_TOAST], timeout=20, env=env)
    finally:
        try:
            xml_path.unlink()
        except OSError:
            pass
    if res["rc"] == 0:
        return {"ok": True, "backend": "windows-toast"}
    return {"ok": False, "backend": "windows-toast", "error": (res["stderr"] or "failed").strip()[:300]}


def notify_send_argv(title: str, message: str, with_actions: bool) -> list:
    argv = ["notify-send", "--app-name", title]
    if with_actions:
        argv += ["--wait", "--action=open=Open"] + ["--action=%s=%s" % a for a in ACTIONS]
    return argv + [title, message]


def wait_and_dispatch(home: Home, cfg: dict, incident_id: str, title: str, message: str,
                      runner=proc.run_full, handler=None) -> dict:
    """Linux: show a notification with buttons, wait for the click, dispatch it.
    Runs as a short-lived helper process that exists only while the bubble does."""
    from .. import opener
    res = runner(notify_send_argv(title, message, True), timeout=900)
    action = (res.get("stdout") or "").strip().splitlines()[-1:] or [""]
    if action[0] in ("open", "investigate", "later"):
        return (handler or opener.handle)(home, cfg, incident_id, action[0])
    return {"ok": True, "action": None}


def show(home: Home, cfg: dict, title: str, message: str, incident_id: "str | None" = None) -> dict:
    kind = backend()
    if kind is None:
        return {"ok": False, "backend": None, "error": "no desktop notification backend in this session"}
    title = (title or "VisumWay")[:120]
    message = message[:1000]
    if kind == "windows-toast":
        return _show_windows(home, title, message, incident_id)
    if kind == "terminal-notifier":
        argv = ["terminal-notifier", "-title", title, "-message", message]
        if incident_id and ID_RE.fullmatch(str(incident_id)):
            # terminal-notifier's -execute is /bin/sh -c. Quote each *fixed*
            # argument independently; never put machine data or model text in
            # the command. The receiving CLI loads the incident from disk.
            cmd = " ".join(shlex.quote(x) for x in
                           [sys.executable, "-m", "visumway", "--home", str(home.root),
                            "open", incident_id])
            argv += ["-execute", cmd]
        res = proc.run_full(argv, timeout=15)
        return {"ok": res["rc"] == 0, "backend": kind,
                "click_action": bool(incident_id and ID_RE.fullmatch(str(incident_id))),
                **({"error": res["stderr"].strip()[:200]} if res["rc"] else {})}
    if kind == "osascript":
        script = "display notification %s with title %s" % (_as_quote(message), _as_quote(title))
        res = proc.run_full(["osascript", "-e", script], timeout=15)
        return {"ok": res["rc"] == 0, "backend": kind, "error": res["stderr"].strip()[:200]} if res["rc"] != 0 \
            else {"ok": True, "backend": kind}
    if incident_id:
        try:  # detached helper waits for the click
            subprocess.Popen([sys.executable, "-m", "visumway", "--home", str(home.root), "notify-wait",
                              incident_id, title, message],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return {"ok": True, "backend": kind}
        except OSError as e:
            return {"ok": False, "backend": kind, "error": str(e)}
    res = proc.run_full(notify_send_argv(title, message, False), timeout=15)
    return {"ok": res["rc"] == 0, "backend": kind, "error": res["stderr"].strip()[:200]} if res["rc"] != 0 \
        else {"ok": True, "backend": kind}


def _as_quote(s: str) -> str:
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


# --- Windows registration: agent identity + click handler --------------------

def handler_command(home: Home) -> str:
    exe = sys.executable
    if os.name == "nt":
        w = os.path.join(os.path.dirname(exe), "pythonw.exe")
        exe = w if os.path.exists(w) else exe
    return '"%s" -m visumway --home "%s" open "%%1"' % (exe, home.root)


def registry_plan(home: Home, cfg: dict) -> list:
    """[(subkey under HKCU, value name, value)] that register() writes."""
    identity = cfg.get("agent", {}).get("identity_name") or cfg.get("agent", {}).get("identity", "VisumWay")
    base = _REGISTRY_BASE
    plan = [
        (_IDENTITY_KEY, "DisplayName", identity[:60]),
        (base + "\\" + SCHEME, "", "URL:VisumWay incident"),
        (base + "\\" + SCHEME, "URL Protocol", ""),
        (base + "\\" + SCHEME + r"\shell\open\command", "", handler_command(home)),
    ]
    icon = cfg.get("agent", {}).get("icon")
    if icon and os.path.exists(icon):
        plan.insert(1, (_IDENTITY_KEY, "IconUri", icon))
    return plan


def register(home: Home, cfg: dict) -> list:
    """Register the notification identity and the visumway:// click handler (per user, no admin)."""
    if os.name != "nt":
        return ["desktop identity: nothing to register on this OS"]
    import winreg
    try:
        owner = _handler_value()
        if owner and owner != handler_command(home) and not _owns_handler(home, owner):
            return ["FAILED: the visumway:// protocol belongs to a different installation"]
        for subkey, name, value in registry_plan(home, cfg):
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, subkey) as k:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    except OSError as error:
        return ["FAILED: Windows notification registry: %s" % error]
    result = winshortcut.install(home)
    if not result["ok"]:
        return ["FAILED: Windows Start Menu notification shortcut: " + result["error"]]
    return ["registered notification identity, AUMID Start Menu shortcut, and %s:// click handler (HKCU)" % SCHEME]


def _handler_value() -> "str | None":
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            "Software\\Classes\\" + SCHEME + r"\shell\open\command") as key:
            return winreg.QueryValueEx(key, "")[0]
    except FileNotFoundError:
        return None


def _owns_handler(home: Home, command: str) -> bool:
    # Allow interpreter upgrades while requiring the same VisumWay home and action.
    return isinstance(command, str) and command.startswith('"') and command.partition('" -m visumway ')[2] == (
        '--home "%s" open "%%1"' % home.root)


def registered(home: Home) -> "bool | None":
    if os.name != "nt":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _IDENTITY_KEY) as key:
            name, _ = winreg.QueryValueEx(key, "DisplayName")
        return bool(name and _handler_value() == handler_command(home) and winshortcut.registered(home))
    except OSError:
        return False


def unregister(home: "Home | None" = None) -> list:
    if os.name != "nt":
        return []
    import winreg
    home = home or Home()
    try:
        owner = _handler_value()
        if owner and not _owns_handler(home, owner):
            return ["FAILED: the visumway:// protocol belongs to a different installation"]
        if not owner and not (home.state / "windows-shortcut.json").is_file():
            return []
    except OSError as error:
        return ["FAILED: could not inspect Windows notification registry: %s" % error]
    log = winshortcut.remove(home)
    base = _REGISTRY_BASE
    for subkey in (base + "\\" + SCHEME + r"\shell\open\command", base + "\\" + SCHEME + r"\shell\open",
                   base + "\\" + SCHEME + r"\shell", base + "\\" + SCHEME,
                   _IDENTITY_KEY):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
        except FileNotFoundError:
            continue
        except OSError as error:
            log.append("FAILED: could not remove %s: %s" % (subkey, error))
    return log + ["removed notification identity and click handler"]
