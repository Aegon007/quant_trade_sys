import json
import os
from copy import deepcopy

from quant_core import paths as qpaths

qpaths.bootstrap_storage_paths()

NOTIFICATION_CONFIG_FILE = qpaths.NOTIFICATION_CONFIG_FILE
NOTIFICATION_SECRETS_FILE = qpaths.NOTIFICATION_SECRETS_FILE
SECRET_FIELDS = (
    ("slack", "webhook_url"),
    ("email", "password"),
    ("llm", "api_key"),
    ("local_slm", "api_key"),
)
DEFAULT_LLM_TIMEOUT_SECONDS = 30
DEFAULT_LLM_MAX_TOKENS = 300
DEFAULT_LLM_CONTEXT_WINDOW_TOKENS = 200000
DEFAULT_DECISION_BRIEF_MAX_OUTPUT_TOKENS = 16000
DEFAULT_DECISION_BRIEF_WALL_TIMEOUT_SECONDS = 90
DEFAULT_LLM_TEMPERATURE = 0.2
DEFAULT_LOCAL_SLM_TIMEOUT_SECONDS = 20
DEFAULT_LOCAL_SLM_MAX_TOKENS = 220
DEFAULT_LOCAL_SLM_TEMPERATURE = 0.1
DEFAULT_WEEKEND_RESEARCH_DAY = "saturday"
DEFAULT_WEEKEND_RESEARCH_HOUR_LOCAL = 10
DEFAULT_WEEKEND_RESEARCH_MINUTE_LOCAL = 0
DEFAULT_WEEKEND_RESEARCH_HISTORY_PERIOD = "5y"

LLM_PRESETS = {
    "openai": {
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5-mini",
        "site_url": "",
        "app_name": "quant-trade-system",
    },
    "openrouter": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openrouter/free",
        "site_url": "",
        "app_name": "quant-trade-system",
    },
}

LOCAL_SLM_PRESET = {
    "provider": "openai",
    "base_url": "http://127.0.0.1:8000/v1",
    "api_key": "EMPTY",
    "model": "Qwen/Qwen3-0.6B",
    "temperature": DEFAULT_LOCAL_SLM_TEMPERATURE,
    "max_tokens": DEFAULT_LOCAL_SLM_MAX_TOKENS,
    "timeout_seconds": DEFAULT_LOCAL_SLM_TIMEOUT_SECONDS,
}

OUTLOOK_SMTP_PRESET = {
    "smtp_host": "smtp-mail.outlook.com",
    "smtp_port": 587,
    "use_starttls": True,
}

DEFAULT_NOTIFICATION_CONFIG = {
    "slack": {
        "enabled": False,
        "webhook_url": "",
    },
    "email": {
        "enabled": False,
        **OUTLOOK_SMTP_PRESET,
        "username": "",
        "password": "",
        "from_email": "",
        "to_emails": [],
    },
    "llm": {
        "enabled": False,
        "provider": "openai",
        "base_url": LLM_PRESETS["openai"]["base_url"],
        "api_key": "",
        "model": LLM_PRESETS["openai"]["model"],
        "temperature": DEFAULT_LLM_TEMPERATURE,
        "max_tokens": DEFAULT_LLM_MAX_TOKENS,
        "context_window_tokens": DEFAULT_LLM_CONTEXT_WINDOW_TOKENS,
        "timeout_seconds": DEFAULT_LLM_TIMEOUT_SECONDS,
        "site_url": "",
        "app_name": "quant-trade-system",
    },
    "local_slm": {
        "enabled": False,
        **LOCAL_SLM_PRESET,
    },
    "alert_settings": {
        "cooldown_hours": 6,
        "send_daily_summary": True,
        "send_premarket_brief": True,
        "send_intraday_alerts": True,
        "send_hourly_market_summary": True,
        "send_hourly_market_summary_market_hours_only": True,
        "send_weekend_research_summary": True,
        "enable_llm_notification_digest": True,
        "enable_llm_decision_brief": True,
        "refresh_llm_brief_on_material_change": True,
        "send_llm_brief_on_material_change": True,
        "decision_brief_max_output_tokens": DEFAULT_DECISION_BRIEF_MAX_OUTPUT_TOKENS,
        "decision_brief_wall_timeout_seconds": DEFAULT_DECISION_BRIEF_WALL_TIMEOUT_SECONDS,
        "enable_weekend_research": True,
        "weekend_research_day_local": DEFAULT_WEEKEND_RESEARCH_DAY,
        "weekend_research_hour_local": DEFAULT_WEEKEND_RESEARCH_HOUR_LOCAL,
        "weekend_research_minute_local": DEFAULT_WEEKEND_RESEARCH_MINUTE_LOCAL,
        "weekend_research_history_period": DEFAULT_WEEKEND_RESEARCH_HISTORY_PERIOD,
    },
}


def _parse_recipients(value):
    if value is None:
        return []
    if isinstance(value, str):
        raw_values = value.replace(";", ",").split(",")
    elif isinstance(value, (list, tuple)):
        raw_values = value
    else:
        raw_values = [value]
    recipients = []
    for raw in raw_values:
        email = str(raw or "").strip()
        if email and email not in recipients:
            recipients.append(email)
    return recipients


def _coerce_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _coerce_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def normalize_notification_config(config):
    normalized = deepcopy(DEFAULT_NOTIFICATION_CONFIG)
    if not isinstance(config, dict):
        return normalized

    slack = config.get("slack", {})
    if isinstance(slack, dict):
        normalized["slack"]["enabled"] = bool(slack.get("enabled", False))
        normalized["slack"]["webhook_url"] = str(slack.get("webhook_url") or "").strip()

    email = config.get("email", {})
    if isinstance(email, dict):
        normalized["email"]["enabled"] = bool(email.get("enabled", False))
        normalized["email"]["smtp_host"] = str(email.get("smtp_host") or OUTLOOK_SMTP_PRESET["smtp_host"]).strip()
        try:
            normalized["email"]["smtp_port"] = int(email.get("smtp_port", OUTLOOK_SMTP_PRESET["smtp_port"]))
        except (TypeError, ValueError):
            normalized["email"]["smtp_port"] = OUTLOOK_SMTP_PRESET["smtp_port"]
        normalized["email"]["use_starttls"] = bool(email.get("use_starttls", True))
        normalized["email"]["username"] = str(email.get("username") or "").strip()
        normalized["email"]["password"] = str(email.get("password") or "")
        normalized["email"]["from_email"] = str(email.get("from_email") or email.get("username") or "").strip()
        normalized["email"]["to_emails"] = _parse_recipients(email.get("to_emails"))

    llm = config.get("llm", {})
    if isinstance(llm, dict):
        normalized["llm"]["enabled"] = bool(llm.get("enabled", False))
        normalized["llm"]["provider"] = str(llm.get("provider") or "openai").strip().lower() or "openai"
        normalized["llm"]["base_url"] = str(
            llm.get("base_url") or LLM_PRESETS["openai"]["base_url"]
        ).strip()
        normalized["llm"]["api_key"] = str(llm.get("api_key") or "")
        normalized["llm"]["model"] = str(llm.get("model") or LLM_PRESETS["openai"]["model"]).strip()
        normalized["llm"]["temperature"] = max(
            0.0,
            _coerce_float(llm.get("temperature", DEFAULT_LLM_TEMPERATURE), DEFAULT_LLM_TEMPERATURE),
        )
        normalized["llm"]["max_tokens"] = max(
            1,
            _coerce_int(llm.get("max_tokens", DEFAULT_LLM_MAX_TOKENS), DEFAULT_LLM_MAX_TOKENS),
        )
        normalized["llm"]["context_window_tokens"] = max(
            1024,
            _coerce_int(
                llm.get("context_window_tokens", DEFAULT_LLM_CONTEXT_WINDOW_TOKENS),
                DEFAULT_LLM_CONTEXT_WINDOW_TOKENS,
            ),
        )
        normalized["llm"]["timeout_seconds"] = max(
            1,
            _coerce_int(llm.get("timeout_seconds", DEFAULT_LLM_TIMEOUT_SECONDS), DEFAULT_LLM_TIMEOUT_SECONDS),
        )
        normalized["llm"]["site_url"] = str(llm.get("site_url") or "").strip()
        normalized["llm"]["app_name"] = str(llm.get("app_name") or "quant-trade-system").strip()

    local_slm = config.get("local_slm", {})
    if isinstance(local_slm, dict):
        normalized["local_slm"]["enabled"] = bool(local_slm.get("enabled", False))
        normalized["local_slm"]["provider"] = str(local_slm.get("provider") or LOCAL_SLM_PRESET["provider"]).strip().lower() or LOCAL_SLM_PRESET["provider"]
        normalized["local_slm"]["base_url"] = str(local_slm.get("base_url") or LOCAL_SLM_PRESET["base_url"]).strip()
        normalized["local_slm"]["api_key"] = str(local_slm.get("api_key") or LOCAL_SLM_PRESET["api_key"])
        normalized["local_slm"]["model"] = str(local_slm.get("model") or LOCAL_SLM_PRESET["model"]).strip()
        normalized["local_slm"]["temperature"] = max(
            0.0,
            _coerce_float(local_slm.get("temperature", DEFAULT_LOCAL_SLM_TEMPERATURE), DEFAULT_LOCAL_SLM_TEMPERATURE),
        )
        normalized["local_slm"]["max_tokens"] = max(
            1,
            _coerce_int(local_slm.get("max_tokens", DEFAULT_LOCAL_SLM_MAX_TOKENS), DEFAULT_LOCAL_SLM_MAX_TOKENS),
        )
        normalized["local_slm"]["timeout_seconds"] = max(
            1,
            _coerce_int(local_slm.get("timeout_seconds", DEFAULT_LOCAL_SLM_TIMEOUT_SECONDS), DEFAULT_LOCAL_SLM_TIMEOUT_SECONDS),
        )

    alert_settings = config.get("alert_settings", {})
    if isinstance(alert_settings, dict):
        try:
            normalized["alert_settings"]["cooldown_hours"] = float(alert_settings.get("cooldown_hours", 6))
        except (TypeError, ValueError):
            normalized["alert_settings"]["cooldown_hours"] = 6
        normalized["alert_settings"]["send_daily_summary"] = bool(alert_settings.get("send_daily_summary", True))
        normalized["alert_settings"]["send_premarket_brief"] = bool(
            alert_settings.get("send_premarket_brief", True)
        )
        normalized["alert_settings"]["send_intraday_alerts"] = bool(
            alert_settings.get("send_intraday_alerts", True)
        )
        normalized["alert_settings"]["send_hourly_market_summary"] = bool(
            alert_settings.get("send_hourly_market_summary", True)
        )
        normalized["alert_settings"]["send_hourly_market_summary_market_hours_only"] = bool(
            alert_settings.get("send_hourly_market_summary_market_hours_only", True)
        )
        normalized["alert_settings"]["send_weekend_research_summary"] = bool(
            alert_settings.get("send_weekend_research_summary", True)
        )
        normalized["alert_settings"]["enable_llm_notification_digest"] = bool(
            alert_settings.get("enable_llm_notification_digest", True)
        )
        normalized["alert_settings"]["enable_llm_decision_brief"] = bool(
            alert_settings.get("enable_llm_decision_brief", True)
        )
        normalized["alert_settings"]["refresh_llm_brief_on_material_change"] = bool(
            alert_settings.get("refresh_llm_brief_on_material_change", True)
        )
        normalized["alert_settings"]["send_llm_brief_on_material_change"] = bool(
            alert_settings.get("send_llm_brief_on_material_change", True)
        )
        normalized["alert_settings"]["decision_brief_max_output_tokens"] = max(
            512,
            _coerce_int(
                alert_settings.get(
                    "decision_brief_max_output_tokens",
                    DEFAULT_DECISION_BRIEF_MAX_OUTPUT_TOKENS,
                ),
                DEFAULT_DECISION_BRIEF_MAX_OUTPUT_TOKENS,
            ),
        )
        normalized["alert_settings"]["decision_brief_wall_timeout_seconds"] = max(
            10,
            _coerce_int(
                alert_settings.get(
                    "decision_brief_wall_timeout_seconds",
                    DEFAULT_DECISION_BRIEF_WALL_TIMEOUT_SECONDS,
                ),
                DEFAULT_DECISION_BRIEF_WALL_TIMEOUT_SECONDS,
            ),
        )
        normalized["alert_settings"]["enable_weekend_research"] = bool(
            alert_settings.get("enable_weekend_research", True)
        )
        weekend_day = str(
            alert_settings.get("weekend_research_day_local", DEFAULT_WEEKEND_RESEARCH_DAY)
            or DEFAULT_WEEKEND_RESEARCH_DAY
        ).strip().lower()
        if weekend_day not in {"saturday", "sunday"}:
            weekend_day = DEFAULT_WEEKEND_RESEARCH_DAY
        normalized["alert_settings"]["weekend_research_day_local"] = weekend_day
        normalized["alert_settings"]["weekend_research_hour_local"] = min(
            23,
            max(
                0,
                _coerce_int(
                    alert_settings.get("weekend_research_hour_local", DEFAULT_WEEKEND_RESEARCH_HOUR_LOCAL),
                    DEFAULT_WEEKEND_RESEARCH_HOUR_LOCAL,
                ),
            ),
        )
        normalized["alert_settings"]["weekend_research_minute_local"] = min(
            59,
            max(
                0,
                _coerce_int(
                    alert_settings.get("weekend_research_minute_local", DEFAULT_WEEKEND_RESEARCH_MINUTE_LOCAL),
                    DEFAULT_WEEKEND_RESEARCH_MINUTE_LOCAL,
                ),
            ),
        )
        history_period = str(
            alert_settings.get("weekend_research_history_period", DEFAULT_WEEKEND_RESEARCH_HISTORY_PERIOD)
            or DEFAULT_WEEKEND_RESEARCH_HISTORY_PERIOD
        ).strip()
        normalized["alert_settings"]["weekend_research_history_period"] = history_period or DEFAULT_WEEKEND_RESEARCH_HISTORY_PERIOD

    return normalized


def _secret_path_for(path):
    path = os.fspath(path)
    if os.path.abspath(path) == os.path.abspath(NOTIFICATION_CONFIG_FILE):
        return NOTIFICATION_SECRETS_FILE
    return os.path.join(os.path.dirname(path), "notification_secrets.local.json")


def _read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _split_secret_fields(config):
    public_config = deepcopy(config)
    secrets = {}
    for section, key in SECRET_FIELDS:
        section_payload = public_config.setdefault(section, {})
        value = str(section_payload.get(key) or "")
        section_payload[key] = ""
        if value:
            secrets.setdefault(section, {})[key] = value
    return public_config, secrets


def _merge_secret_fields(config, secrets):
    merged = deepcopy(config if isinstance(config, dict) else {})
    for section, key in SECRET_FIELDS:
        value = str(dict(secrets.get(section, {}) or {}).get(key) or "")
        if value:
            merged.setdefault(section, {})[key] = value
    return merged


def load_notification_config(path=NOTIFICATION_CONFIG_FILE):
    if not path or not os.path.exists(path):
        return deepcopy(DEFAULT_NOTIFICATION_CONFIG)
    config = _read_json_file(path)
    secrets = _read_json_file(_secret_path_for(path))
    normalized = normalize_notification_config(_merge_secret_fields(config, secrets))
    if any(str(dict(config.get(section, {}) or {}).get(key) or "") for section, key in SECRET_FIELDS):
        save_notification_config(normalized, path)
    return normalized


def save_notification_config(config, path=NOTIFICATION_CONFIG_FILE):
    normalized = normalize_notification_config(config)
    public_config, secrets = _split_secret_fields(normalized)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(public_config, handle, ensure_ascii=False, indent=2)
    secret_path = _secret_path_for(path)
    with open(secret_path, "w", encoding="utf-8") as handle:
        json.dump(secrets, handle, ensure_ascii=False, indent=2)
    try:
        os.chmod(secret_path, 0o600)
    except OSError:
        pass
    return normalized


def preserve_unsubmitted_secrets(config, existing):
    """Keep stored credentials when the settings UI submits an empty secret field."""
    merged = deepcopy(config if isinstance(config, dict) else {})
    current = normalize_notification_config(existing)
    for section, key in SECRET_FIELDS:
        incoming_section = merged.setdefault(section, {})
        if not isinstance(incoming_section, dict):
            incoming_section = {}
            merged[section] = incoming_section
        if not str(incoming_section.get(key) or ""):
            incoming_section[key] = current[section].get(key, "")
    return merged


def apply_outlook_smtp_preset(config):
    normalized = normalize_notification_config(config)
    normalized["email"].update(OUTLOOK_SMTP_PRESET)
    return normalized


def apply_llm_preset(config, preset_name):
    normalized = normalize_notification_config(config)
    preset = dict(LLM_PRESETS.get(str(preset_name or "").strip().lower()) or {})
    if not preset:
        return normalized
    normalized["llm"].update(preset)
    return normalized


def apply_local_slm_preset(config):
    normalized = normalize_notification_config(config)
    normalized["local_slm"].update(LOCAL_SLM_PRESET)
    normalized["local_slm"]["enabled"] = True
    return normalized


def _env_bool(value, default=True):
    if value is None:
        return default
    return str(value).strip().lower() not in ("0", "false", "no", "off")


def apply_environment_overrides(config, environ=None):
    environ = environ or os.environ
    normalized = normalize_notification_config(config)

    slack_webhook = str(environ.get("SLACK_WEBHOOK_URL") or "").strip()
    if slack_webhook:
        normalized["slack"]["enabled"] = True
        normalized["slack"]["webhook_url"] = slack_webhook

    smtp_host = str(environ.get("SMTP_HOST") or "").strip()
    smtp_port = str(environ.get("SMTP_PORT") or "").strip()
    smtp_user = str(environ.get("SMTP_USER") or "").strip()
    smtp_password = str(environ.get("SMTP_PASSWORD") or "")
    smtp_from = str(environ.get("SMTP_FROM") or "").strip()
    alert_email_to = str(environ.get("ALERT_EMAIL_TO") or "").strip()
    smtp_starttls = environ.get("SMTP_STARTTLS")

    if smtp_host:
        normalized["email"]["smtp_host"] = smtp_host
    if smtp_port:
        try:
            normalized["email"]["smtp_port"] = int(smtp_port)
        except ValueError:
            pass
    if smtp_user:
        normalized["email"]["username"] = smtp_user
    if smtp_password:
        normalized["email"]["password"] = smtp_password
    if smtp_from:
        normalized["email"]["from_email"] = smtp_from
    elif smtp_user and not normalized["email"].get("from_email"):
        normalized["email"]["from_email"] = smtp_user
    if alert_email_to:
        normalized["email"]["to_emails"] = _parse_recipients(alert_email_to)
    if smtp_starttls is not None:
        normalized["email"]["use_starttls"] = _env_bool(smtp_starttls, default=True)

    if normalized["email"].get("smtp_host") and normalized["email"].get("to_emails"):
        normalized["email"]["enabled"] = True

    llm_enabled = environ.get("LLM_ENABLED")
    llm_provider = str(environ.get("LLM_PROVIDER") or "").strip()
    llm_base_url = str(environ.get("LLM_API_BASE_URL") or "").strip()
    llm_api_key = str(environ.get("LLM_API_KEY") or "")
    llm_model = str(environ.get("LLM_MODEL") or "").strip()
    llm_temperature = environ.get("LLM_TEMPERATURE")
    llm_max_tokens = environ.get("LLM_MAX_TOKENS")
    llm_timeout = environ.get("LLM_TIMEOUT_SECONDS")
    llm_site_url = str(environ.get("LLM_SITE_URL") or "").strip()
    llm_app_name = str(environ.get("LLM_APP_NAME") or "").strip()
    local_slm_enabled = environ.get("LOCAL_SLM_ENABLED")
    local_slm_provider = str(environ.get("LOCAL_SLM_PROVIDER") or "").strip()
    local_slm_base_url = str(environ.get("LOCAL_SLM_API_BASE_URL") or "").strip()
    local_slm_api_key = str(environ.get("LOCAL_SLM_API_KEY") or "")
    local_slm_model = str(environ.get("LOCAL_SLM_MODEL") or "").strip()
    local_slm_temperature = environ.get("LOCAL_SLM_TEMPERATURE")
    local_slm_max_tokens = environ.get("LOCAL_SLM_MAX_TOKENS")
    local_slm_timeout = environ.get("LOCAL_SLM_TIMEOUT_SECONDS")

    if llm_enabled is not None:
        normalized["llm"]["enabled"] = _env_bool(llm_enabled, default=True)
    if llm_provider:
        normalized["llm"]["provider"] = llm_provider.lower()
    if llm_base_url:
        normalized["llm"]["base_url"] = llm_base_url
    if llm_api_key:
        normalized["llm"]["api_key"] = llm_api_key
    if llm_model:
        normalized["llm"]["model"] = llm_model
    if llm_temperature is not None:
        normalized["llm"]["temperature"] = max(
            0.0,
            _coerce_float(llm_temperature, DEFAULT_LLM_TEMPERATURE),
        )
    if llm_max_tokens is not None:
        normalized["llm"]["max_tokens"] = max(
            1,
            _coerce_int(llm_max_tokens, DEFAULT_LLM_MAX_TOKENS),
        )
    if llm_timeout is not None:
        normalized["llm"]["timeout_seconds"] = max(
            1,
            _coerce_int(llm_timeout, DEFAULT_LLM_TIMEOUT_SECONDS),
        )
    if llm_site_url:
        normalized["llm"]["site_url"] = llm_site_url
    if llm_app_name:
        normalized["llm"]["app_name"] = llm_app_name

    if llm_enabled is None and normalized["llm"].get("api_key") and normalized["llm"].get("model"):
        normalized["llm"]["enabled"] = True

    if local_slm_enabled is not None:
        normalized["local_slm"]["enabled"] = _env_bool(local_slm_enabled, default=True)
    if local_slm_provider:
        normalized["local_slm"]["provider"] = local_slm_provider.lower()
    if local_slm_base_url:
        normalized["local_slm"]["base_url"] = local_slm_base_url
    if local_slm_api_key:
        normalized["local_slm"]["api_key"] = local_slm_api_key
    if local_slm_model:
        normalized["local_slm"]["model"] = local_slm_model
    if local_slm_temperature is not None:
        normalized["local_slm"]["temperature"] = max(
            0.0,
            _coerce_float(local_slm_temperature, DEFAULT_LOCAL_SLM_TEMPERATURE),
        )
    if local_slm_max_tokens is not None:
        normalized["local_slm"]["max_tokens"] = max(
            1,
            _coerce_int(local_slm_max_tokens, DEFAULT_LOCAL_SLM_MAX_TOKENS),
        )
    if local_slm_timeout is not None:
        normalized["local_slm"]["timeout_seconds"] = max(
            1,
            _coerce_int(local_slm_timeout, DEFAULT_LOCAL_SLM_TIMEOUT_SECONDS),
        )
    return normalized


def redact_secret(value, visible=4):
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= visible:
        return "*" * len(text)
    return "*" * (len(text) - visible) + text[-visible:]
