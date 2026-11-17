"""Configuration: reflex rules, agent adapters, sources, notification channels.

JSON on purpose: every agent and every language can read and write it with no
dependencies.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
from uuid import UUID

from .filelock import exclusive
from .paths import Home

ACTIONS = ("ignore", "log", "wake")
_ANY_AGENT = object()

DEFAULT_CONFIG = {
    "version": 1,
    "agent": {
        # Name the woken model answers to (e.g. "Vinci"). Identity lives here,
        # not in a running process.
        "identity": "this computer's AI assistant",
        "default": "claude",
        "codex_app_thread": "",
        "instructions": "",
        # Use the agent's existing account sign-in. API-key environment
        # variables are removed from wake invocations so nothing is ever
        # billed to a separate API account by accident.
        "use_account_login": True,
        "adapters": {
            # argv: the non-interactive command. {prompt} is substituted, or the
            #   prompt is written to stdin (prompt_via: "stdin").
            # output: how to read the reply: "text", "claude-json", "codex-jsonl".
            # deliver_stdout: the model's reply is its message to the user.
            # open_argv / investigate_argv: interactive command that resumes the
            #   same session when the user clicks the notification.
            # fresh_argv: interactive command when there is no session to resume.
            # login_check: token-free command that reports sign-in state.
            "claude": {
                "label": "Claude Code (your Claude account sign-in)",
                "argv": ["claude", "-p", "--output-format", "json"],
                "prompt_via": "stdin", "output": "claude-json", "deliver_stdout": True,
                "open_argv": ["claude", "--resume", "{session_id}"],
                "investigate_argv": ["claude", "--resume", "{session_id}", "{investigate_prompt}"],
                "fresh_argv": ["claude", "{context_prompt}"],
                "login_check": ["claude", "auth", "status"],
                "account_methods": ["claude.ai"],
                "account_provider": "firstParty",
                "strip_env": ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                              "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
                              "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"],
                "timeout_s": 300,
            },
            "codex": {
                "label": "Codex CLI (your ChatGPT account sign-in)",
                "argv": ["codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--json", "-"],
                "prompt_via": "stdin", "output": "codex-jsonl", "deliver_stdout": True,
                "open_argv": ["codex", "resume", "{session_id}"],
                "investigate_argv": ["codex", "resume", "{session_id}", "{investigate_prompt}"],
                "fresh_argv": ["codex", "{context_prompt}"],
                "login_check": ["codex", "login", "status"],
                "account_methods": ["chatgpt", "chatgpt account"],
                "strip_env": ["OPENAI_API_KEY", "CODEX_API_KEY"],
                "timeout_s": 300,
            },
            "ollama": {
                "label": "Ollama (local model, no account)",
                "argv": ["ollama", "run", "MODEL_NAME"],
                "prompt_via": "stdin", "output": "text", "deliver_stdout": True,
                "fresh_argv": ["ollama", "run", "MODEL_NAME"],
                "timeout_s": 600,
            },
        },
    },
    "reflex": {
        "wakes_enabled": True,  # compatibility for existing installations
        "default_action": "log",
        "aggregate_window_s": 5,
        "default_cooldown_s": 300,
        "budget": {"max_wakes_per_hour": 4, "max_wakes_per_day": 20},
        "notify_on_wake_failure": True,
        "snooze_minutes": 30,  # the "Later" button
        # First matching rule wins. "match" and "subject" are shell-style globs.
        "rules": [
            {"match": "app.crash", "action": "wake", "cooldown_s": 300},
            {"match": "app.hang", "action": "wake", "cooldown_s": 300},
            {"match": "gpu.error", "action": "wake", "cooldown_s": 600},
            {"match": "disk.low_space", "action": "wake", "cooldown_s": 21600},
            {"match": "disk.health", "action": "wake", "cooldown_s": 21600},
            {"match": "process.exited", "action": "log"},
            {"match": "update.*", "action": "log"},
            {"match": "window.*", "action": "ignore"},
            {"match": "input.*", "action": "ignore"},
        ],
    },
    "sources": {
        "process_watch": {"enabled": False, "names": [], "interval_s": 5},
        "disk": {"enabled": True, "paths": [], "min_free_pct": 5, "interval_s": 300},
    },
    "notify": {
        # {"type": "desktop"} native notification bubble under the agent's name.
        # {"type": "file"} always works (writes to outbox/messages.jsonl).
        # {"type": "ntfy", "url": "https://ntfy.sh/<your-secret-topic>"}
        # {"type": "webhook", "url": "https://..."}
        "channels": [{"type": "desktop"}, {"type": "file"}],
    },
}


class ConfigError(ValueError):
    pass


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)  # lists (e.g. rules) replace wholesale
    return out


def validate(cfg: dict) -> dict:
    thread = cfg.get("agent", {}).get("codex_app_thread", "")
    if thread != "":
        try:
            valid = isinstance(thread, str) and str(UUID(thread)) == thread
        except ValueError:
            valid = False
        if not valid:
            raise ConfigError("agent.codex_app_thread must be a canonical Codex chat UUID")
    reflex = cfg.get("reflex", {})
    if type(reflex.get("wakes_enabled")) is not bool:
        raise ConfigError("reflex.wakes_enabled must be true or false")
    if reflex.get("default_action") not in ACTIONS:
        raise ConfigError("reflex.default_action must be one of %s" % (ACTIONS,))
    for i, rule in enumerate(reflex.get("rules", [])):
        if not isinstance(rule, dict) or "match" not in rule:
            raise ConfigError("reflex.rules[%d] needs a 'match'" % i)
        if rule.get("action") not in ACTIONS:
            raise ConfigError("reflex.rules[%d].action must be one of %s" % (i, ACTIONS))
        if (os.name == "nt" and rule.get("action") == "wake" and rule.get("agent")
                and rule["agent"] != cfg["agent"].get("default")):
            raise ConfigError("reflex.rules[%d] selects another agent. Windows uses agent.default for every wake." % i)
    adapters = cfg.get("agent", {}).get("adapters", {})
    for name, a in adapters.items():
        if not isinstance(a.get("argv"), list) or not a["argv"]:
            raise ConfigError("agent.adapters.%s.argv must be a non-empty list" % name)
        if "account_methods" in a:
            methods = a["account_methods"]
            if not isinstance(methods, list) or not methods or not all(isinstance(value, str) and value.strip()
                                                                      for value in methods):
                raise ConfigError("agent.adapters.%s.account_methods must list accepted login methods" % name)
            if not isinstance(a.get("login_check"), list) or not a["login_check"]:
                raise ConfigError("agent.adapters.%s.login_check must check account status" % name)
    for ch in cfg.get("notify", {}).get("channels", []):
        if ch.get("type") not in ("desktop", "file", "ntfy", "webhook"):
            raise ConfigError("unknown notify channel type: %r" % ch.get("type"))
        if ch["type"] in ("ntfy", "webhook") and not str(ch.get("url", "")).startswith(("http://", "https://")):
            raise ConfigError("notify channel %s needs an http(s) url" % ch["type"])
    return cfg


def load(home: Home) -> dict:
    user = read_user(home)
    cfg = _merge(DEFAULT_CONFIG, user)
    cfg["agent"]["installer"] = installing_agent(user)
    cfg["agent"]["bound"] = bool(user.get("agent", {}).get("default"))
    if not cfg["agent"]["bound"]:
        cfg["reflex"]["wakes_enabled"] = False
    return validate(cfg)


def installing_agent(user: dict) -> "str | None":
    settings = user.get("agent", {})
    return settings.get("installer") or settings.get("default")


def is_notification_owner(cfg: dict, name: "str | None") -> bool:
    binding = cfg["agent"]
    return bool(binding["bound"] and name == binding["default"])


# What a fresh config.json contains. Deliberately small: everything else comes
# from DEFAULT_CONFIG, so shipped defaults (adapter commands, rules) can improve
# in later versions without being frozen into the user's file.
STARTER_CONFIG = {
    "version": 1,
    "agent": {"identity": DEFAULT_CONFIG["agent"]["identity"]},
    "reflex": {"wakes_enabled": False, "budget": dict(DEFAULT_CONFIG["reflex"]["budget"])},
    "notify": {"channels": list(DEFAULT_CONFIG["notify"]["channels"])},
}


def read_user(home: Home) -> dict:
    try:
        user = json.loads(home.config.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        raise ConfigError("config.json is not valid JSON: %s" % e)
    if not isinstance(user, dict):
        raise ConfigError("config.json must contain an object")
    return user


def update_user(home: Home, patch: dict, *, expected_agent=_ANY_AGENT, expected_installer=_ANY_AGENT) -> dict:
    """Merge a change into the user's config.json (validated before writing)."""
    with exclusive(home.root / ".config.lock"):
        existing = read_user(home)
        if expected_agent is not _ANY_AGENT and existing.get("agent", {}).get("default") != expected_agent:
            raise ConfigError("The notification agent changed. Run `visumway agent list` and try again.")
        if expected_installer is not _ANY_AGENT and installing_agent(existing) != expected_installer:
            raise ConfigError("Another agent set up VisumWay. Run setup again to reuse the installation.")
        merged = _merge(existing, patch)
        validate(_merge(DEFAULT_CONFIG, merged))
        if merged != existing or not home.config.is_file():
            merged.setdefault("version", DEFAULT_CONFIG["version"])
            _write_user(home, merged)
        return merged


def _write_user(home: Home, data: dict) -> None:
    fd, path = tempfile.mkstemp(dir=home.root, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)
            file.write("\n")
        os.replace(path, home.config)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def write_default(home: Home, overwrite: bool = False) -> bool:
    with exclusive(home.root / ".config.lock"):
        if home.config.exists() and not overwrite:
            return False
        _write_user(home, STARTER_CONFIG)
        return True
