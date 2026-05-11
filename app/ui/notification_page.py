import streamlit as st


def render_notification_config_page(*, ncfg_module, nch_module, st_module=None):
    st_module = st_module or st
    config = ncfg_module.load_notification_config()
    st_module.header("通知配置")
    st_module.caption(f"配置保存在本地 `{ncfg_module.NOTIFICATION_CONFIG_FILE}`，该文件已加入 `.gitignore`。")

    with st_module.expander("Slack", expanded=True):
        slack = config["slack"]
        with st_module.form("slack_notification_config_form"):
            slack_enabled = st_module.checkbox("启用 Slack 通知", value=bool(slack.get("enabled")))
            slack_webhook_url = st_module.text_input(
                "Incoming Webhook URL",
                value=slack.get("webhook_url", ""),
                type="password",
                placeholder="https://hooks.slack.com/services/...",
            )
            c1, c2 = st_module.columns(2)
            save_slack = c1.form_submit_button("保存 Slack 配置")
            test_slack = c2.form_submit_button("发送 Slack 测试")

        if save_slack or test_slack:
            config["slack"] = {
                "enabled": slack_enabled,
                "webhook_url": slack_webhook_url.strip(),
            }
            config = ncfg_module.save_notification_config(config)
            st_module.success("Slack 配置已保存")
            if test_slack:
                ok, message = nch_module.send_slack_message(
                    nch_module.build_test_notification_message("Slack"),
                    config["slack"]["webhook_url"],
                )
                if ok:
                    st_module.success(message)
                else:
                    st_module.error(message)

    with st_module.expander("Email / SMTP", expanded=True):
        st_module.caption("Outlook 账号可以作为发件人，Gmail 可以作为收件人；实际是否可用取决于该 Outlook 账号是否允许 SMTP 登录。")
        if st_module.button("使用 Outlook SMTP 预设"):
            config = ncfg_module.apply_outlook_smtp_preset(config)
            config = ncfg_module.save_notification_config(config)
            st_module.success("已应用 Outlook SMTP 预设")
            st_module.rerun()

        email_cfg = config["email"]
        with st_module.form("email_notification_config_form"):
            email_enabled = st_module.checkbox("启用 Email 通知", value=bool(email_cfg.get("enabled")))
            ec1, ec2, ec3 = st_module.columns([2, 1, 1])
            smtp_host = ec1.text_input("SMTP Host", value=email_cfg.get("smtp_host", "smtp-mail.outlook.com"))
            smtp_port = ec2.number_input("SMTP Port", min_value=1, max_value=65535, value=int(email_cfg.get("smtp_port", 587)))
            use_starttls = ec3.checkbox("STARTTLS", value=bool(email_cfg.get("use_starttls", True)))
            username = st_module.text_input("SMTP 用户名", value=email_cfg.get("username", ""), placeholder="your_account@outlook.com")
            password = st_module.text_input("SMTP 密码 / App Password", value=email_cfg.get("password", ""), type="password")
            from_email = st_module.text_input(
                "发件人",
                value=email_cfg.get("from_email") or email_cfg.get("username", ""),
                placeholder="your_account@outlook.com",
            )
            to_emails = st_module.text_input(
                "收件人",
                value=", ".join(email_cfg.get("to_emails", [])),
                placeholder="your_gmail@gmail.com",
            )
            c1, c2 = st_module.columns(2)
            save_email = c1.form_submit_button("保存 Email 配置")
            test_email = c2.form_submit_button("发送 Email 测试")

        if save_email or test_email:
            config["email"] = {
                "enabled": email_enabled,
                "smtp_host": smtp_host.strip(),
                "smtp_port": int(smtp_port),
                "use_starttls": bool(use_starttls),
                "username": username.strip(),
                "password": password,
                "from_email": from_email.strip(),
                "to_emails": to_emails,
            }
            config = ncfg_module.save_notification_config(config)
            st_module.success("Email 配置已保存")
            if test_email:
                ok, message = nch_module.send_email_message(
                    "Quant Trade System Email 测试",
                    nch_module.build_test_notification_message("Email"),
                    config["email"],
                )
                if ok:
                    st_module.success(message)
                else:
                    st_module.error(message)

    st_module.subheader("当前状态")
    slack_status = "已启用" if config["slack"].get("enabled") else "未启用"
    email_status = "已启用" if config["email"].get("enabled") else "未启用"
    st_module.write(f"Slack: {slack_status}")
    st_module.write(
        "Email: "
        f"{email_status} | {config['email'].get('smtp_host')}:{config['email'].get('smtp_port')} "
        f"| 收件人 {len(config['email'].get('to_emails', []))} 个"
    )
