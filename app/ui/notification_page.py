import streamlit as st


def render_notification_config_page(*, ncfg_module, nch_module, st_module=None):
    st_module = st_module or st
    config = ncfg_module.load_notification_config()
    alert_defaults = dict(getattr(ncfg_module, "DEFAULT_NOTIFICATION_CONFIG", {}).get("alert_settings", {}) or {})
    alert_settings = {**alert_defaults, **dict(config.get("alert_settings", {}) or {})}
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

    with st_module.expander("系统节奏 / 自动分析", expanded=True):
        st_module.caption("这里统一管理小时摘要、夜间报告，以及盘中自动触发全量量化分析的阈值。")
        with st_module.form("alert_settings_form"):
            cooldown_hours = st_module.number_input(
                "告警去重冷却时间（小时）",
                min_value=0.0,
                value=float(alert_settings.get("cooldown_hours", 6) or 0.0),
                step=1.0,
                format="%.1f",
            )
            send_daily_summary = st_module.checkbox(
                "发送夜间日报",
                value=bool(alert_settings.get("send_daily_summary", True)),
            )
            send_hourly_market_summary = st_module.checkbox(
                "发送小时级市场摘要",
                value=bool(alert_settings.get("send_hourly_market_summary", True)),
            )
            send_hourly_market_summary_market_hours_only = st_module.checkbox(
                "小时摘要仅在美股常规交易时段发送",
                value=bool(alert_settings.get("send_hourly_market_summary_market_hours_only", True)),
            )
            send_quant_analysis_change_summary = st_module.checkbox(
                "发送全量量化分析变化摘要",
                value=bool(alert_settings.get("send_quant_analysis_change_summary", True)),
            )
            enable_auto_quant_analysis = st_module.checkbox(
                "启用盘中自动触发全量量化分析",
                value=bool(alert_settings.get("enable_auto_quant_analysis", True)),
            )
            ac1, ac2 = st_module.columns(2)
            auto_quant_analysis_min_interval_minutes = ac1.number_input(
                "自动全量分析最短间隔（分钟）",
                min_value=0,
                value=int(alert_settings.get("auto_quant_analysis_min_interval_seconds", 7200) or 0) // 60,
                step=5,
            )
            auto_quant_analysis_price_jump_pct = ac2.number_input(
                "价格跳变触发阈值 (%)",
                min_value=0.0,
                value=float(alert_settings.get("auto_quant_analysis_price_jump_pct", 0.03) or 0.0) * 100.0,
                step=0.1,
                format="%.1f",
            )
            save_alert_settings = st_module.columns(1)[0].form_submit_button("保存系统/提醒配置")

        if save_alert_settings:
            config["alert_settings"] = {
                "cooldown_hours": float(cooldown_hours),
                "send_daily_summary": bool(send_daily_summary),
                "send_hourly_market_summary": bool(send_hourly_market_summary),
                "send_hourly_market_summary_market_hours_only": bool(send_hourly_market_summary_market_hours_only),
                "send_quant_analysis_change_summary": bool(send_quant_analysis_change_summary),
                "enable_auto_quant_analysis": bool(enable_auto_quant_analysis),
                "auto_quant_analysis_min_interval_seconds": int(auto_quant_analysis_min_interval_minutes) * 60,
                "auto_quant_analysis_price_jump_pct": float(auto_quant_analysis_price_jump_pct) / 100.0,
            }
            config = ncfg_module.save_notification_config(config)
            alert_settings = dict(config.get("alert_settings", {}) or {})
            st_module.success("系统/提醒配置已保存")

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
    auto_quant_enabled = "已启用" if alert_settings.get("enable_auto_quant_analysis", True) else "未启用"
    min_interval_minutes = int(alert_settings.get("auto_quant_analysis_min_interval_seconds", 7200) or 0) // 60
    jump_pct = float(alert_settings.get("auto_quant_analysis_price_jump_pct", 0.03) or 0.0) * 100.0
    st_module.write(
        f"自动全量分析: {auto_quant_enabled} | 最短间隔 {min_interval_minutes} 分钟 | 价格跳变阈值 {jump_pct:.1f}%"
    )
