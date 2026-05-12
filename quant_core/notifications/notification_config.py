import json
import os
from copy import deepcopy

from quant_core import paths as qpaths

qpaths.bootstrap_storage_paths()

NOTIFICATION_CONFIG_FILE = qpaths.NOTIFICATION_CONFIG_FILE
DEFAULT_AUTO_QUANT_ANALYSIS_MIN_INTERVAL_SECONDS = 7200
DEFAULT_AUTO_QUANT_ANALYSIS_PRICE_JUMP_PCT = 0.03

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
    "alert_settings": {
        "cooldown_hours": 6,
        "send_daily_summary": True,
        "send_hourly_market_summary": True,
        "send_hourly_market_summary_market_hours_only": True,
        "send_quant_analysis_change_summary": True,
        "enable_auto_quant_analysis": True,
        "auto_quant_analysis_min_interval_seconds": DEFAULT_AUTO_QUANT_ANALYSIS_MIN_INTERVAL_SECONDS,
        "auto_quant_analysis_price_jump_pct": DEFAULT_AUTO_QUANT_ANALYSIS_PRICE_JUMP_PCT,
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

    alert_settings = config.get("alert_settings", {})
    if isinstance(alert_settings, dict):
        try:
            normalized["alert_settings"]["cooldown_hours"] = float(alert_settings.get("cooldown_hours", 6))
        except (TypeError, ValueError):
            normalized["alert_settings"]["cooldown_hours"] = 6
        normalized["alert_settings"]["send_daily_summary"] = bool(alert_settings.get("send_daily_summary", True))
        normalized["alert_settings"]["send_hourly_market_summary"] = bool(
            alert_settings.get("send_hourly_market_summary", True)
        )
        normalized["alert_settings"]["send_hourly_market_summary_market_hours_only"] = bool(
            alert_settings.get("send_hourly_market_summary_market_hours_only", True)
        )
        normalized["alert_settings"]["send_quant_analysis_change_summary"] = bool(
            alert_settings.get("send_quant_analysis_change_summary", True)
        )
        normalized["alert_settings"]["enable_auto_quant_analysis"] = bool(
            alert_settings.get("enable_auto_quant_analysis", True)
        )
        normalized["alert_settings"]["auto_quant_analysis_min_interval_seconds"] = max(
            0,
            _coerce_int(
                alert_settings.get(
                    "auto_quant_analysis_min_interval_seconds",
                    DEFAULT_AUTO_QUANT_ANALYSIS_MIN_INTERVAL_SECONDS,
                ),
                DEFAULT_AUTO_QUANT_ANALYSIS_MIN_INTERVAL_SECONDS,
            ),
        )
        normalized["alert_settings"]["auto_quant_analysis_price_jump_pct"] = max(
            0.0,
            _coerce_float(
                alert_settings.get(
                    "auto_quant_analysis_price_jump_pct",
                    DEFAULT_AUTO_QUANT_ANALYSIS_PRICE_JUMP_PCT,
                ),
                DEFAULT_AUTO_QUANT_ANALYSIS_PRICE_JUMP_PCT,
            ),
        )

    return normalized


def load_notification_config(path=NOTIFICATION_CONFIG_FILE):
    if not path or not os.path.exists(path):
        return deepcopy(DEFAULT_NOTIFICATION_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
    except Exception:
        return deepcopy(DEFAULT_NOTIFICATION_CONFIG)
    return normalize_notification_config(config)


def save_notification_config(config, path=NOTIFICATION_CONFIG_FILE):
    normalized = normalize_notification_config(config)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(normalized, handle, ensure_ascii=False, indent=2)
    return normalized


def apply_outlook_smtp_preset(config):
    normalized = normalize_notification_config(config)
    normalized["email"].update(OUTLOOK_SMTP_PRESET)
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

    return normalized


def redact_secret(value, visible=4):
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= visible:
        return "*" * len(text)
    return "*" * (len(text) - visible) + text[-visible:]
