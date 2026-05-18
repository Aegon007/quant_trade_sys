from __future__ import annotations

from quant_core.notifications import notification_channels as nch
from quant_core.notifications import notification_config as ncfg


def deliver_message(
    delivery_type: str,
    *,
    subject: str,
    body: str,
    config=None,
    environ=None,
    slack_sender=None,
    email_sender=None,
):
    normalized_config = ncfg.apply_environment_overrides(config or ncfg.load_notification_config(), environ=environ)
    slack_sender = slack_sender or nch.send_slack_message
    email_sender = email_sender or nch.send_email_message
    delivery_type = str(delivery_type or "").strip().lower() or "generic"
    results = []

    slack = dict(normalized_config.get("slack", {}) or {})
    if slack.get("enabled") and slack.get("webhook_url"):
        ok, message = slack_sender(body, slack.get("webhook_url"))
        results.append({"channel": "slack", "ok": ok, "message": message, "delivery_type": delivery_type})
    else:
        results.append({"channel": "slack", "ok": False, "message": "Slack webhook notifications are not enabled", "delivery_type": delivery_type})

    email = dict(normalized_config.get("email", {}) or {})
    if email.get("enabled") and list(email.get("to_emails", []) or []):
        ok, message = email_sender(subject, body, email)
        results.append({"channel": "email", "ok": ok, "message": message, "delivery_type": delivery_type})
    else:
        results.append({"channel": "email", "ok": False, "message": "Email notifications are not enabled", "delivery_type": delivery_type})

    return results


def any_success(results) -> bool:
    return any(bool((row or {}).get("ok")) for row in list(results or []))
