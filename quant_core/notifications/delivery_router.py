from __future__ import annotations

from quant_core.llm import explainer
from quant_core.notifications import notification_channels as nch
from quant_core.notifications import notification_config as ncfg


def _notification_body_for_delivery(delivery_type: str, *, subject: str, body: str, config: dict) -> tuple[str, dict]:
    alert_settings = dict(config.get("alert_settings", {}) or {})
    if not bool(alert_settings.get("enable_llm_notification_digest", True)):
        return str(body), {"status": "DISABLED"}
    ok, text, meta = explainer.summarize_notification_message(
        delivery_type=delivery_type,
        subject=subject,
        body=body,
        notification_config=config,
    )
    if ok and str(text or "").strip():
        return str(text).strip(), {"status": "READY", **dict(meta or {})}
    return str(body), {
        "status": "STRUCTURED_FALLBACK",
        "error": str(text or "").strip(),
        **dict(meta or {}),
    }


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
    email = dict(normalized_config.get("email", {}) or {})
    needs_delivery = (
        bool(slack.get("enabled") and slack.get("webhook_url"))
        or bool(email.get("enabled") and list(email.get("to_emails", []) or []))
    )
    if needs_delivery:
        delivery_body, digest_meta = _notification_body_for_delivery(
            delivery_type,
            subject=subject,
            body=body,
            config=normalized_config,
        )
    else:
        delivery_body, digest_meta = str(body), {"status": "SKIPPED_NO_CHANNEL"}

    if slack.get("enabled") and slack.get("webhook_url"):
        ok, message = slack_sender(delivery_body, slack.get("webhook_url"))
        results.append({
            "channel": "slack",
            "ok": ok,
            "message": message,
            "delivery_type": delivery_type,
            "digest": digest_meta,
        })
    else:
        results.append({"channel": "slack", "ok": False, "message": "Slack webhook notifications are not enabled", "delivery_type": delivery_type})

    if email.get("enabled") and list(email.get("to_emails", []) or []):
        ok, message = email_sender(subject, delivery_body, email)
        results.append({
            "channel": "email",
            "ok": ok,
            "message": message,
            "delivery_type": delivery_type,
            "digest": digest_meta,
        })
    else:
        results.append({"channel": "email", "ok": False, "message": "Email notifications are not enabled", "delivery_type": delivery_type})

    return results


def any_success(results) -> bool:
    return any(bool((row or {}).get("ok")) for row in list(results or []))
