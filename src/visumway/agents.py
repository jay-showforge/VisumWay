"""Agent discovery and verification.

Three different facts are kept apart on purpose:

  installed   the agent's command exists on this computer
  signed in   it reports an existing account login (no API key involved)
  verified    one real background invocation succeeded on this machine,
              with this version of the agent

Only "verified" means the computer can actually wake this brain. A desktop
chat app being installed or signed in proves nothing about that.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import proc
from .bridges import codexapp
from .paths import Home

PROBE_TOKEN = "VISUMWAY-OK"
PROBE_PROMPT = "Reply with exactly this text and nothing else: " + PROBE_TOKEN
PREFERENCE = ("claude", "codex", "gemini", "ollama")
CODEX_APP_ADAPTER = {"login_check": ["codex", "login", "status"],
                     "account_methods": ["chatgpt account"],
                     "strip_env": ["OPENAI_API_KEY", "CODEX_API_KEY"]}
_WINDOWS_CODEX_ACCOUNT = ["-c", 'forced_login_method="chatgpt"', "-c", 'model_provider="openai"']

# Desktop chat apps. Detected so the plan can say plainly that they cannot be
# woken in the background, and which command-line sibling shares their sign-in.
DESKTOP_APPS = {
    "ChatGPT desktop app": {
        "sibling": "codex",
        "win": [r"%LOCALAPPDATA%\Packages\OpenAI.Codex_*", r"%LOCALAPPDATA%\Packages\OpenAI.ChatGPT-Desktop_*",
                r"%LOCALAPPDATA%\Programs\ChatGPT"],
        "mac": ["/Applications/ChatGPT.app"],
    },
    "Claude desktop app": {
        "sibling": "claude",
        "win": [r"%LOCALAPPDATA%\AnthropicClaude", r"%LOCALAPPDATA%\Packages\Claude_*", r"%APPDATA%\Claude"],
        "mac": ["/Applications/Claude.app"],
    },
}


@dataclass
class Parsed:
    message: str = ""
    session_id: "str | None" = None
    error: "str | None" = None
    cost_usd: "float | None" = None


def parse_output(kind: str, stdout: str) -> Parsed:
    """Turn an agent CLI's stdout into (message, session id, error)."""
    stdout = stdout or ""
    if kind == "claude-json":
        try:
            obj = json.loads(stdout)
        except ValueError:
            return Parsed(error="agent did not return JSON: %s" % stdout.strip()[:200])
        if isinstance(obj, list):
            obj = next((o for o in reversed(obj) if isinstance(o, dict) and o.get("type") == "result"), {})
        if not isinstance(obj, dict):
            return Parsed(error="unexpected agent output")
        text = str(obj.get("result") or "")
        if obj.get("is_error"):
            # e.g. "Authentication error". Never pass this on as the AI's message.
            return Parsed(session_id=obj.get("session_id"), error=text[:300] or "agent reported an error")
        return Parsed(message=text.strip(), session_id=obj.get("session_id"), cost_usd=obj.get("total_cost_usd"))
    if kind == "codex-jsonl":
        out = Parsed()
        saw_json = False
        for line in stdout.splitlines():
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            saw_json = True
            msg = obj.get("msg") if isinstance(obj.get("msg"), dict) else {}
            item = obj.get("item") if isinstance(obj.get("item"), dict) else {}
            out.session_id = out.session_id or obj.get("thread_id") or obj.get("session_id") or msg.get("session_id")
            kind_ = obj.get("type") or msg.get("type")
            if kind_ in ("error", "turn.failed"):
                err = obj.get("message") or obj.get("error") or msg.get("message") or "agent reported an error"
                out.error = str(err.get("message") if isinstance(err, dict) else err)[:300]
            if item.get("type") in ("agent_message", "assistant_message") and item.get("text"):
                out.message = str(item["text"]).strip()
            elif msg.get("type") == "agent_message" and msg.get("message"):
                out.message = str(msg["message"]).strip()
        if not saw_json:
            out.message = stdout.strip()
        return out
    return Parsed(message=stdout.strip())


def clean_env(adapter: dict, cfg: dict, extra: "dict | None" = None) -> dict:
    """Environment for an agent invocation. By default API-key variables are
    removed so the agent uses the user's existing account sign-in and never
    silently bills a separate API account."""
    env = dict(os.environ)
    env.update(extra or {})
    if adapter.get("account_methods") or cfg.get("agent", {}).get("use_account_login", True):
        for var in adapter.get("strip_env", []):
            env.pop(var, None)
    return env


def resolve_executable(command: str) -> "str | None":
    exe = shutil.which(command)
    if exe or os.name != "nt" or command.lower() not in ("codex", "codex.exe"):
        return exe
    # Task Scheduler does not inherit the desktop application's PATH. Resolve
    # the installed package at launch time so an app update can move its CLI.
    package = proc.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
         "(Get-AppxPackage -Name OpenAI.Codex).InstallLocation"],
        timeout=10,
    )
    for directory in package.splitlines():
        candidate = Path(directory.strip()) / "app" / "resources" / "codex.exe"
        if candidate.is_absolute() and candidate.is_file():
            return str(candidate)
    return None


def queued_chat(cfg: dict, name: str) -> str:
    """The optional, previously configured Codex application integration."""
    return cfg["agent"].get("codex_app_thread", "") if name == "codex" else ""


def open_app(cfg: dict, name: str, session: str) -> "str | None":
    """Try the named agent's optional application surface."""
    if name == "codex" and cfg.get("open", {}).get("codex_in_app") is True and codexapp.open_thread(session):
        return "codex-app"
    return None


def _account_ready(adapter: dict, signed_in: "bool | None", method: str) -> bool:
    return signed_in is True and method.casefold() in {
        entry.strip().casefold() for entry in adapter.get("account_methods", ())}


def invoke(home: Home, cfg: dict, name: str, prompt: str, extra_env: "dict | None" = None,
           app_thread: str = "") -> dict:
    """One bounded, non-interactive agent invocation. The single code path
    through which VisumWay can spend model tokens."""
    adapter = cfg.get("agent", {}).get("adapters", {}).get(name)
    started = time.time()
    res = {"agent": name, "ok": False}
    if not adapter:
        res["error"] = "no agent adapter named %r" % name
        return res
    if app_thread:
        adapter = CODEX_APP_ADAPTER
        exe = resolve_executable("codex")
        signed, method = _login_state(adapter, cfg)
        if name != "codex" or not exe or not _account_ready(adapter, signed, method):
            res["error"] = "Codex app queue requires an existing ChatGPT account login"
            return res
        home.workspace.mkdir(parents=True, exist_ok=True)
        try:
            queued = codexapp.enqueue(exe, app_thread, prompt, cwd=str(home.workspace),
                                      env=clean_env(adapter, cfg, extra_env))
        except OSError as e:
            res["error"] = str(e)
        else:
            res.update(ok=True, session_id=app_thread, queue_id=queued)
        res["duration_s"] = round(time.time() - started, 3)
        return res
    if adapter.get("account_methods"):
        signed, method = _login_state(adapter, cfg)
        if not _account_ready(adapter, signed, method):
            res["error"] = ("unattended model call blocked: an existing signed-in account "
                            "was not confirmed (auth method: %s). No API billing fallback." % method)
            return res
    argv = [a.replace("{prompt}", prompt) for a in adapter["argv"]]
    exe = resolve_executable(argv[0])
    if not exe:
        res["error"] = "agent command not found on PATH: %s" % argv[0]
        return res
    argv[0] = exe
    if (os.name == "nt" and name == "codex" and Path(exe).stem.lower() == "codex"
            and argv[1:2] == ["exec"] and adapter.get("account_methods")):
        argv[2:2] = _WINDOWS_CODEX_ACCOUNT
    via_stdin = adapter.get("prompt_via", "arg") == "stdin"
    home.workspace.mkdir(parents=True, exist_ok=True)
    p = proc.run_full(argv, timeout=float(adapter.get("timeout_s", 600)),
                      env=clean_env(adapter, cfg, dict(extra_env or {}, VISUMWAY_HOME=str(home.root))),
                      cwd=str(home.workspace), input=prompt if via_stdin else None)
    parsed = parse_output(adapter.get("output", "text"), p["stdout"])
    res.update(rc=p["rc"], duration_s=round(time.time() - started, 3), message=parsed.message,
               session_id=parsed.session_id, cost_usd=parsed.cost_usd,
               stdout_tail=p["stdout"][-2000:], stderr_tail=p["stderr"][-1000:])
    if p["rc"] is None:
        res["error"] = "agent %s" % (p["stderr"] or "could not be run")
    elif parsed.error:
        res["error"] = parsed.error
    elif p["rc"] != 0:
        res["error"] = "exit code %s: %s" % (p["rc"], (p["stderr"] or p["stdout"]).strip()[-200:])
    else:
        res["ok"] = True
    return res


def _login_state(adapter: dict, cfg: dict) -> "tuple":
    """(signed_in: True/False/None, method: str). Costs no tokens."""
    check = adapter.get("login_check")
    command = (adapter.get("argv") or [""])[0]
    executable = check[0] if check else ""
    # A configured absolute CLI path should use that same installation for auth.
    if command and executable and Path(command).stem.casefold() == Path(executable).stem.casefold():
        executable = command
    exe = resolve_executable(executable) if executable else None
    if not exe:
        return None, "unknown"
    p = proc.run_full([exe] + check[1:], timeout=20, env=clean_env(adapter, cfg))
    text = (p["stdout"] + "\n" + p["stderr"]).strip()
    try:
        obj = json.loads(p["stdout"])
        if isinstance(obj, dict) and isinstance(obj.get("loggedIn"), bool):
            if not obj["loggedIn"]:
                return False, "none"
            if p["rc"] != 0:
                return None, "unknown"
            expected = adapter.get("account_provider")
            provider = str(obj.get("apiProvider") or "")
            if expected and provider.casefold() != expected.casefold():
                return True, "unexpected provider: " + (provider[:60] or "unknown")
            return True, str(obj.get("authMethod") or "unknown")[:80]
    except ValueError:
        pass
    low = text.lower()
    if "not logged in" in low or "logged out" in low:
        return False, "none"
    if p["rc"] == 0 and not adapter.get("account_provider") and "logged in" in low:
        return True, "chatgpt account" if "chatgpt" in low else "api key" if "api key" in low else "account"
    return None, "unknown"


def load_state(home: Home) -> dict:
    try:
        return json.loads(home.agents.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def inspect(home: Home, cfg: dict, name: str) -> dict:
    adapter = cfg.get("agent", {}).get("adapters", {}).get(name, {})
    exe = resolve_executable(adapter["argv"][0]) if adapter else None
    info = {"name": name, "label": adapter.get("label", name), "installed": exe, "version": None,
            "signed_in": None, "auth": "unknown", "verified": False, "verified_at": None,
            "billing_safe": False, "requires_account": bool(adapter.get("account_methods")),
            "resumable": bool(adapter.get("open_argv")),
            "api_key_env_ignored": [v for v in adapter.get("strip_env", []) if os.environ.get(v)]}
    if not exe:
        return info
    info["version"] = (proc.run([exe, "--version"], timeout=20).strip().splitlines() or [None])[0]
    info["signed_in"], info["auth"] = _login_state(adapter, cfg)
    info["billing_safe"] = _account_ready(adapter, info["signed_in"], info["auth"])
    rec = load_state(home).get(name, {})
    if (rec.get("verified") and rec.get("version") == info["version"] and rec.get("argv") == adapter.get("argv")
            and (not info["requires_account"] or info["billing_safe"])):
        info["verified"], info["verified_at"] = True, rec.get("at")
    return info


def inspect_all(home: Home, cfg: dict) -> list:
    names = list(cfg.get("agent", {}).get("adapters", {}))
    names.sort(key=lambda n: PREFERENCE.index(n) if n in PREFERENCE else len(PREFERENCE))
    return [inspect(home, cfg, n) for n in names]


def recommend(cfg: dict, infos: list) -> "str | None":
    """Recommend one confirmed account, allowing an installed preference to win."""
    by_name = {i["name"]: i for i in infos}
    default = cfg.get("agent", {}).get("default")
    if by_name.get(default, {}).get("installed"):
        return default
    safe = [i for i in infos if i["installed"] and i["billing_safe"]]
    best = [i for i in safe if i["verified"]] or safe
    return best[0]["name"] if len(best) == 1 else None


def probe(home: Home, cfg: dict, name: str) -> dict:
    """Verify background invocation with one tiny real call. Spends a few tokens."""
    info = inspect(home, cfg, name)
    if not info["installed"]:
        return {"agent": name, "verified": False, "detail": "not installed"}
    res = invoke(home, cfg, name, PROBE_PROMPT)
    verified = bool(res["ok"] and PROBE_TOKEN in (res.get("message") or ""))
    detail = "background invocation works" if verified else (
        res.get("error") or "unexpected reply: %s" % (res.get("message") or "")[:120])
    adapter = cfg["agent"]["adapters"][name]
    state = load_state(home)
    state[name] = {"verified": verified, "at": time.time(), "version": info["version"],
                   "argv": adapter.get("argv"), "detail": detail,
                   "session_captured": bool(res.get("session_id")), "duration_s": res.get("duration_s")}
    home.state.mkdir(parents=True, exist_ok=True)
    home.agents.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return {"agent": name, "verified": verified, "detail": detail,
            "session_captured": bool(res.get("session_id")), "duration_s": res.get("duration_s")}


def desktop_apps() -> list:
    """Chat apps found on this machine (heuristic path check)."""
    import glob
    key = "win" if os.name == "nt" else "mac" if sys.platform == "darwin" else None
    found = []
    for label, spec in DESKTOP_APPS.items():
        for pattern in spec.get(key, []) if key else []:
            if glob.glob(os.path.expandvars(pattern)) or Path(os.path.expandvars(pattern)).exists():
                found.append({"label": label, "sibling": spec["sibling"]})
                break
    return found
