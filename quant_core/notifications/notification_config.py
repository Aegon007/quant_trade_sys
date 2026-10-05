from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

from quant_core import paths as qpaths


qpaths.bootstrap_storage_paths()
NOTIFICATION_CONFIG_FILE = qpaths.NOTIFICATION_CONFIG_FILE
NOTIFICATION_SECRETS_FILE = qpaths.NOTIFICATION_SECRETS_FILE
SECRET_FIELDS = (
    ("slack", "webhook_url"), ("slack", "bot_token"), ("slack", "app_token"),
    ("email", "password"), ("llm", "api_key"), ("local_slm", "api_key"),
)
LLM_PRESETS = {
    "openai": {"provider": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-5-mini"},
    "openrouter": {"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1", "model": "openrouter/free"},
}
DEFAULT_NOTIFICATION_CONFIG = {
    "slack": {"enabled": False, "webhook_url": "", "bot_token": "", "app_token": ""},
    "email": {"enabled": False, "smtp_host": "smtp-mail.outlook.com", "smtp_port": 587, "use_starttls": True, "username": "", "password": "", "from_email": "", "to_emails": []},
    "llm": {"enabled": False, "provider": "openai", "base_url": "https://api.openai.com/v1", "api_key": "", "model": "gpt-5-mini", "temperature": 0.2, "max_tokens": 16000, "context_window_tokens": 200000, "timeout_seconds": 90, "site_url": "", "app_name": "valuation-radar"},
    "local_slm": {"enabled": False, "provider": "openai", "base_url": "http://127.0.0.1:8000/v1", "api_key": "EMPTY", "model": "Qwen/Qwen3-0.6B", "temperature": 0.1, "max_tokens": 1000, "timeout_seconds": 20},
    "delivery": {"use_llm_narration": True},
}


def _bool(value, default=False):
    if value is None:
        return default
    return str(value).lower() not in {"0", "false", "no", "off"} if isinstance(value, str) else bool(value)


def _number(value, default, cast=float):
    try:
        return cast(value)
    except (TypeError, ValueError):
        return cast(default)


def _recipients(value) -> list[str]:
    values = value.replace(";", ",").split(",") if isinstance(value, str) else list(value or [])
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def normalize_notification_config(config) -> dict:
    raw = dict(config or {})
    out = deepcopy(DEFAULT_NOTIFICATION_CONFIG)
    for name in ("slack", "email", "llm", "local_slm", "delivery"):
        if isinstance(raw.get(name), dict):
            out[name].update(raw[name])
    out["slack"] = {"enabled": _bool(out["slack"].get("enabled")), **{key: str(out["slack"].get(key) or "").strip() for key in ("webhook_url", "bot_token", "app_token")}}
    email = out["email"]
    email.update({"enabled": _bool(email.get("enabled")), "smtp_port": _number(email.get("smtp_port"), 587, int), "use_starttls": _bool(email.get("use_starttls"), True), "to_emails": _recipients(email.get("to_emails"))})
    for name in ("llm", "local_slm"):
        route = out[name]
        route.update({"enabled": _bool(route.get("enabled")), "temperature": max(_number(route.get("temperature"), 0.2), 0), "max_tokens": max(_number(route.get("max_tokens"), 1000, int), 1), "timeout_seconds": max(_number(route.get("timeout_seconds"), 30, int), 1)})
        for key in ("provider", "base_url", "api_key", "model", "site_url", "app_name"):
            if key in route:
                route[key] = str(route.get(key) or "").strip()
    out["delivery"]["use_llm_narration"] = _bool(out["delivery"].get("use_llm_narration"), True)
    return out


def _read(path) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _secret_path(path) -> str:
    return NOTIFICATION_SECRETS_FILE if os.path.abspath(path) == os.path.abspath(NOTIFICATION_CONFIG_FILE) else str(Path(path).with_name("notification_secrets.local.json"))


def _split(config: dict):
    public, secrets = deepcopy(config), {}
    for section, key in SECRET_FIELDS:
        value = str(public.setdefault(section, {}).get(key) or "")
        public[section][key] = ""
        if value:
            secrets.setdefault(section, {})[key] = value
    return public, secrets


def _merge(config: dict, secrets: dict):
    merged = deepcopy(config)
    for section, key in SECRET_FIELDS:
        value = str(dict(secrets.get(section, {}) or {}).get(key) or "")
        if value:
            merged.setdefault(section, {})[key] = value
    return merged


def load_notification_config(path=NOTIFICATION_CONFIG_FILE) -> dict:
    public = _read(path)
    if not public and os.path.abspath(path) == os.path.abspath(NOTIFICATION_CONFIG_FILE):
        public = _read(qpaths.NOTIFICATION_CONFIG_EXAMPLE_FILE)
    return normalize_notification_config(_merge(public, _read(_secret_path(path))))


def save_notification_config(config, path=NOTIFICATION_CONFIG_FILE) -> dict:
    normalized = normalize_notification_config(config)
    public, secrets = _split(normalized)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    secret_path = Path(_secret_path(path))
    secret_path.write_text(json.dumps(secrets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        secret_path.chmod(0o600)
    except OSError:
        pass
    return normalized


def preserve_unsubmitted_secrets(config, existing):
    merged = deepcopy(dict(config or {}))
    current = normalize_notification_config(existing)
    for section, key in SECRET_FIELDS:
        if not str(merged.setdefault(section, {}).get(key) or ""):
            merged[section][key] = current[section].get(key, "")
    return merged


def apply_environment_overrides(config, environ=None) -> dict:
    env = environ or os.environ
    out = normalize_notification_config(config)
    mapping = {
        "SLACK_WEBHOOK_URL": ("slack", "webhook_url"), "SLACK_BOT_TOKEN": ("slack", "bot_token"), "SLACK_APP_TOKEN": ("slack", "app_token"),
        "SMTP_HOST": ("email", "smtp_host"), "SMTP_USER": ("email", "username"), "SMTP_PASSWORD": ("email", "password"), "SMTP_FROM": ("email", "from_email"),
        "LLM_API_BASE_URL": ("llm", "base_url"), "LLM_API_KEY": ("llm", "api_key"), "LLM_MODEL": ("llm", "model"), "LLM_PROVIDER": ("llm", "provider"),
        "LOCAL_SLM_API_BASE_URL": ("local_slm", "base_url"), "LOCAL_SLM_API_KEY": ("local_slm", "api_key"), "LOCAL_SLM_MODEL": ("local_slm", "model"),
    }
    for env_key, (section, key) in mapping.items():
        if env.get(env_key) not in (None, ""):
            out[section][key] = str(env[env_key]).strip()
    if env.get("SMTP_PORT"):
        out["email"]["smtp_port"] = _number(env["SMTP_PORT"], 587, int)
    if env.get("ALERT_EMAIL_TO"):
        out["email"]["to_emails"] = _recipients(env["ALERT_EMAIL_TO"])
    if env.get("LLM_ENABLED") is not None:
        out["llm"]["enabled"] = _bool(env["LLM_ENABLED"])
    elif out["llm"].get("api_key") and out["llm"].get("model"):
        out["llm"]["enabled"] = True
    if env.get("LOCAL_SLM_ENABLED") is not None:
        out["local_slm"]["enabled"] = _bool(env["LOCAL_SLM_ENABLED"])
    if out["slack"].get("webhook_url"):
        out["slack"]["enabled"] = True
    if out["email"].get("smtp_host") and out["email"].get("to_emails"):
        out["email"]["enabled"] = True
    return normalize_notification_config(out)


def apply_llm_preset(config, preset_name):
    out = normalize_notification_config(config)
    out["llm"].update(LLM_PRESETS.get(str(preset_name).lower(), {}))
    return out


def apply_outlook_smtp_preset(config):
    out = normalize_notification_config(config)
    out["email"].update({"smtp_host": "smtp-mail.outlook.com", "smtp_port": 587, "use_starttls": True})
    return out


def apply_local_slm_preset(config):
    out = normalize_notification_config(config)
    out["local_slm"].update(DEFAULT_NOTIFICATION_CONFIG["local_slm"])
    out["local_slm"]["enabled"] = True
    return out


def redact_secret(value, visible=4):
    value = str(value or "")
    return "" if not value else "*" * max(len(value) - visible, 0) + value[-visible:]
