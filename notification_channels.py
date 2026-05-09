import json
import smtplib
import urllib.request
from email.message import EmailMessage


def send_slack_message(text, webhook_url, urlopen=urllib.request.urlopen):
    webhook_url = str(webhook_url or "").strip()
    if not webhook_url:
        return False, "Slack webhook URL 为空"
    payload = json.dumps({"text": str(text)}).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            status = getattr(response, "status", None) or getattr(response, "code", None)
            if status and int(status) >= 400:
                return False, f"Slack 返回 HTTP {status}"
        return True, "Slack 测试消息已发送"
    except Exception as exc:
        return False, f"Slack 发送失败: {exc}"


def send_email_message(subject, body, email_config, smtp_factory=smtplib.SMTP):
    config = email_config or {}
    host = str(config.get("smtp_host") or "").strip()
    port = int(config.get("smtp_port") or 587)
    username = str(config.get("username") or "").strip()
    password = str(config.get("password") or "")
    from_email = str(config.get("from_email") or username).strip()
    to_emails = [str(item).strip() for item in config.get("to_emails", []) if str(item).strip()]

    if not host:
        return False, "SMTP host 为空"
    if not from_email:
        return False, "发件人为空"
    if not to_emails:
        return False, "收件人为空"

    message = EmailMessage()
    message["Subject"] = str(subject)
    message["From"] = from_email
    message["To"] = ", ".join(to_emails)
    message.set_content(str(body))

    try:
        with smtp_factory(host, port, timeout=20) as smtp:
            if bool(config.get("use_starttls", True)):
                smtp.starttls()
            if username or password:
                smtp.login(username, password)
            smtp.send_message(message)
        return True, "Email 测试消息已发送"
    except Exception as exc:
        return False, f"Email 发送失败: {exc}"


def build_test_notification_message(channel_name):
    return (
        f"Quant Trade System {channel_name} 测试消息\n\n"
        "如果你收到这条消息，说明通知连接已经配置成功。"
    )
