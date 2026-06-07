import streamlit as st


def render_notification_config_page(*, ncfg_module, nch_module, llm_module=None, llm_explainer_module=None, st_module=None, show_header=True):
    st_module = st_module or st
    if llm_module is None:
        from quant_core.llm import openai_compatible as llm_module
    if llm_explainer_module is None:
        from quant_core.llm import explainer as llm_explainer_module
    config = ncfg_module.load_notification_config()
    alert_defaults = dict(getattr(ncfg_module, "DEFAULT_NOTIFICATION_CONFIG", {}).get("alert_settings", {}) or {})
    alert_settings = {**alert_defaults, **dict(config.get("alert_settings", {}) or {})}
    llm_cfg = dict(config.get("llm", {}) or {})
    local_slm_cfg = dict(config.get("local_slm", {}) or {})
    local_status = llm_module.inspect_openai_compatible_endpoint(local_slm_cfg)
    exposed_models = list(local_status.get("models", []) or [])
    cache_summary = llm_explainer_module.summarize_explanation_cache()
    if show_header:
        st_module.header("Settings")
    elif show_header is None:
        st_module.subheader("Slack / Email / LLM / SLM")
    st_module.caption("这里统一管理 Slack、Email、远程 LLM、本地 SLM，以及系统自动化节奏。")
    st_module.caption(f"配置保存在本地 `{ncfg_module.NOTIFICATION_CONFIG_FILE}`，该文件已加入 `.gitignore`。")

    st_module.subheader("连接状态")
    status_cols = st_module.columns(4)
    status_cols[0].metric("Slack", "ENABLED" if config["slack"].get("enabled") else "DISABLED")
    status_cols[1].metric("Email", "ENABLED" if config["email"].get("enabled") else "DISABLED")
    status_cols[2].metric(
        "Remote LLM",
        "ENABLED" if llm_cfg.get("enabled") else "DISABLED",
    )
    status_cols[3].metric("Local SLM", str(local_status.get("label") or "UNKNOWN"))
    st_module.caption(
        " | ".join(
            [
                f"Remote: {llm_cfg.get('provider', 'openai')} / {llm_cfg.get('model', '') or '—'}",
                f"Local: {local_slm_cfg.get('model', '') or '—'}",
            ]
        )
    )
    status_message = str(local_status.get("message") or "").strip()
    if local_status.get("status") == "running":
        st_module.success(status_message)
    elif local_status.get("status") in {"wrong_endpoint", "wrong_model"}:
        st_module.error(status_message)
    elif local_status.get("status") in {"disabled", "not_configured"}:
        st_module.info(status_message)
    else:
        st_module.warning(status_message or "本地 SLM 服务当前不可用。")
    if exposed_models:
        st_module.caption("LM Studio 当前暴露模型: " + " | ".join(exposed_models[:5]))
    cache_cols = st_module.columns(3)
    cache_cols[0].metric("解释缓存", int(cache_summary.get("entry_count") or 0))
    cache_cols[1].metric("本地转述缓存", int(dict(cache_summary.get("by_route", {}) or {}).get("local_slm", 0) or 0))
    cache_cols[2].metric("远程解释缓存", int(dict(cache_summary.get("by_route", {}) or {}).get("llm", 0) or 0))

    quick1, quick2 = st_module.columns(2)
    if quick1.button("写入本地 SLM 默认配置 (LM Studio / Qwen3-0.6B)"):
        config = ncfg_module.apply_local_slm_preset(config)
        config = ncfg_module.save_notification_config(config)
        st_module.success("已写入并启用本地 SLM 默认配置。")
        st_module.rerun()
    if quick2.button("使用 Outlook SMTP 预设"):
        config = ncfg_module.apply_outlook_smtp_preset(config)
        config = ncfg_module.save_notification_config(config)
        st_module.success("已应用 Outlook SMTP 预设")
        st_module.rerun()

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
            send_premarket_brief = st_module.checkbox(
                "发送盘前简报",
                value=bool(alert_settings.get("send_premarket_brief", True)),
            )
            send_intraday_alerts = st_module.checkbox(
                "发送盘中紧急提醒",
                value=bool(alert_settings.get("send_intraday_alerts", True)),
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
            send_weekend_research_summary = st_module.checkbox(
                "发送周末研究摘要",
                value=bool(alert_settings.get("send_weekend_research_summary", True)),
            )
            enable_auto_quant_analysis = st_module.checkbox(
                "启用盘中自动触发全量量化分析",
                value=bool(alert_settings.get("enable_auto_quant_analysis", True)),
            )
            enable_weekend_research = st_module.checkbox(
                "启用周末研究任务",
                value=bool(alert_settings.get("enable_weekend_research", True)),
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
            current_weekend_day = str(alert_settings.get("weekend_research_day_local", "sunday")).strip().lower()
            if hasattr(st_module, "selectbox"):
                weekend_research_day_local = st_module.selectbox(
                    "周末研究日期",
                    ["saturday", "sunday"],
                    index=0 if current_weekend_day == "saturday" else 1,
                )
            else:
                weekend_research_day_local = st_module.text_input(
                    "周末研究日期",
                    value=current_weekend_day or "sunday",
                )
            wc2, wc3 = st_module.columns(2)
            weekend_research_hour_local = wc2.number_input(
                "周末研究小时",
                min_value=0,
                max_value=23,
                value=int(alert_settings.get("weekend_research_hour_local", 11) or 11),
                step=1,
            )
            weekend_research_minute_local = wc3.number_input(
                "周末研究分钟",
                min_value=0,
                max_value=59,
                value=int(alert_settings.get("weekend_research_minute_local", 0) or 0),
                step=5,
            )
            current_weekend_period = str(alert_settings.get("weekend_research_history_period", "5y") or "5y")
            if hasattr(st_module, "selectbox"):
                weekend_research_history_period = st_module.selectbox(
                    "周末研究历史窗口",
                    ["2y", "3y", "5y", "10y"],
                    index=["2y", "3y", "5y", "10y"].index(current_weekend_period)
                    if current_weekend_period in ["2y", "3y", "5y", "10y"]
                    else 2,
                )
            else:
                weekend_research_history_period = st_module.text_input(
                    "周末研究历史窗口",
                    value=current_weekend_period,
                )
            save_alert_settings = st_module.columns(1)[0].form_submit_button("保存系统/提醒配置")

        if save_alert_settings:
            config["alert_settings"] = {
                "cooldown_hours": float(cooldown_hours),
                "send_daily_summary": bool(send_daily_summary),
                "send_premarket_brief": bool(send_premarket_brief),
                "send_intraday_alerts": bool(send_intraday_alerts),
                "send_hourly_market_summary": bool(send_hourly_market_summary),
                "send_hourly_market_summary_market_hours_only": bool(send_hourly_market_summary_market_hours_only),
                "send_quant_analysis_change_summary": bool(send_quant_analysis_change_summary),
                "send_weekend_research_summary": bool(send_weekend_research_summary),
                "enable_auto_quant_analysis": bool(enable_auto_quant_analysis),
                "auto_quant_analysis_min_interval_seconds": int(auto_quant_analysis_min_interval_minutes) * 60,
                "auto_quant_analysis_price_jump_pct": float(auto_quant_analysis_price_jump_pct) / 100.0,
                "enable_weekend_research": bool(enable_weekend_research),
                "weekend_research_day_local": str(weekend_research_day_local or "sunday").strip().lower(),
                "weekend_research_hour_local": int(weekend_research_hour_local),
                "weekend_research_minute_local": int(weekend_research_minute_local),
                "weekend_research_history_period": str(weekend_research_history_period or "5y").strip(),
            }
            config = ncfg_module.save_notification_config(config)
            alert_settings = dict(config.get("alert_settings", {}) or {})
            st_module.success("系统/提醒配置已保存")

    with st_module.expander("Email / SMTP", expanded=True):
        st_module.caption("Outlook 账号可以作为发件人，Gmail 可以作为收件人；实际是否可用取决于该 Outlook 账号是否允许 SMTP 登录。")
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

    with st_module.expander("远程 LLM / OpenAI Compatible API", expanded=False):
        st_module.caption("支持 ChatGPT/OpenAI、OpenRouter，以及任何兼容 `/chat/completions` 的 OpenAI-compatible API。")
        p1, p2 = st_module.columns(2)
        if p1.button("使用 OpenAI 预设"):
            config = ncfg_module.apply_llm_preset(config, "openai")
            config = ncfg_module.save_notification_config(config)
            st_module.success("已应用 OpenAI 预设")
            st_module.rerun()
        if p2.button("使用 OpenRouter 预设"):
            config = ncfg_module.apply_llm_preset(config, "openrouter")
            config = ncfg_module.save_notification_config(config)
            st_module.success("已应用 OpenRouter 预设")
            st_module.rerun()

        with st_module.form("llm_notification_config_form"):
            llm_enabled = st_module.checkbox("启用 LLM 配置", value=bool(llm_cfg.get("enabled", False)))
            provider = st_module.text_input("Provider", value=llm_cfg.get("provider", "openai"), placeholder="openai / openrouter / custom")
            base_url = st_module.text_input("Base URL", value=llm_cfg.get("base_url", ""), placeholder="https://api.openai.com/v1")
            api_key = st_module.text_input("API Key", value=llm_cfg.get("api_key", ""), type="password")
            model = st_module.text_input("Model", value=llm_cfg.get("model", ""), placeholder="gpt-5-mini / openai/gpt-4.1-mini")
            l1, l2, l3 = st_module.columns(3)
            temperature = l1.number_input("Temperature", min_value=0.0, max_value=2.0, value=float(llm_cfg.get("temperature", 0.2) or 0.2), step=0.1, format="%.1f")
            max_tokens = l2.number_input("Max tokens", min_value=1, max_value=4096, value=int(llm_cfg.get("max_tokens", 300) or 300), step=50)
            timeout_seconds = l3.number_input("Timeout (s)", min_value=1, max_value=300, value=int(llm_cfg.get("timeout_seconds", 30) or 30), step=1)
            site_url = st_module.text_input("Site URL (OpenRouter 可选)", value=llm_cfg.get("site_url", ""), placeholder="https://your-site.example")
            app_name = st_module.text_input("App Name (OpenRouter 可选)", value=llm_cfg.get("app_name", "quant-trade-system"), placeholder="quant-trade-system")
            c1, c2 = st_module.columns(2)
            save_llm = c1.form_submit_button("保存 LLM 配置")
            test_llm = c2.form_submit_button("发送 LLM 测试")

        if save_llm or test_llm:
            config["llm"] = {
                "enabled": bool(llm_enabled),
                "provider": str(provider or "").strip().lower(),
                "base_url": str(base_url or "").strip(),
                "api_key": api_key,
                "model": str(model or "").strip(),
                "temperature": float(temperature),
                "max_tokens": int(max_tokens),
                "timeout_seconds": int(timeout_seconds),
                "site_url": str(site_url or "").strip(),
                "app_name": str(app_name or "").strip(),
            }
            config = ncfg_module.save_notification_config(config)
            st_module.success("LLM 配置已保存")
            if test_llm:
                ok, message = llm_module.test_llm_connection(config["llm"])
                if ok:
                    st_module.success(f"LLM 测试成功：{message}")
                else:
                    st_module.error(message)

    with st_module.expander("本地 SLM / LM Studio", expanded=True):
        st_module.caption("推荐使用 LM Studio 的本地 OpenAI-compatible server 来提供本地 SLM。它只负责把结构化原因转述得更自然；复杂解释、调研与综合分析仍然走远程 LLM。")
        st_module.markdown(
            "1. 在 LM Studio 中下载并加载 `Qwen/Qwen3-0.6B`\n"
            "2. 打开 `Developer` 或 `Local Server`\n"
            "3. 启动 OpenAI-compatible server\n"
            "4. 把 Base URL 保持为 `http://127.0.0.1:8000/v1`，或填成你在 LM Studio 里实际看到的地址"
        )
        st_module.caption("如果以后更换本地小模型，通常只需要在 LM Studio 里切换模型，并在这里调整 `Local Model` 或 `Local Base URL`。")

        status_actions = st_module.columns(2)
        refresh_local_slm_status = status_actions[0].button("Refresh Status")
        test_local_narration = status_actions[1].button("Test Narration")
        local_status_cols = st_module.columns(3)
        local_status_cols[0].metric("Local SLM Status", str(local_status.get("label") or "UNKNOWN"))
        local_status_cols[1].metric("Configured Model", str(local_slm_cfg.get("model") or "—"))
        local_status_cols[2].metric("Exposed Models", str(exposed_models[0] if exposed_models else "—"))
        if refresh_local_slm_status:
            st_module.success("本地 SLM 状态已刷新。")
        if test_local_narration:
            ok, message = llm_module.test_local_narration(local_slm_cfg)
            if ok:
                st_module.success("本地 SLM 转述测试成功。")
                st_module.info(message)
            else:
                st_module.error(message)

        with st_module.form("local_slm_notification_config_form"):
            local_slm_enabled = st_module.checkbox("启用本地 SLM", value=bool(local_slm_cfg.get("enabled", False)))
            local_provider = st_module.text_input("Local Provider", value=local_slm_cfg.get("provider", "openai"), placeholder="openai / custom")
            local_base_url = st_module.text_input("Local Base URL", value=local_slm_cfg.get("base_url", ""), placeholder="http://127.0.0.1:8000/v1")
            local_api_key = st_module.text_input("Local API Key", value=local_slm_cfg.get("api_key", "EMPTY"), type="password")
            local_model = st_module.text_input("Local Model (LM Studio model name)", value=local_slm_cfg.get("model", "Qwen/Qwen3-0.6B"), placeholder="Qwen/Qwen3-0.6B")
            l1, l2, l3 = st_module.columns(3)
            local_temperature = l1.number_input("Local Temperature", min_value=0.0, max_value=2.0, value=float(local_slm_cfg.get("temperature", 0.1) or 0.1), step=0.1, format="%.1f")
            local_max_tokens = l2.number_input("Local Max tokens", min_value=1, max_value=4096, value=int(local_slm_cfg.get("max_tokens", 220) or 220), step=20)
            local_timeout_seconds = l3.number_input("Local Timeout (s)", min_value=1, max_value=300, value=int(local_slm_cfg.get("timeout_seconds", 20) or 20), step=1)
            c1, c2 = st_module.columns(2)
            save_local_slm = c1.form_submit_button("保存本地 SLM 配置")
            test_local_slm = c2.form_submit_button("测试本地 SLM")

        if save_local_slm or test_local_slm:
            config["local_slm"] = {
                "enabled": bool(local_slm_enabled),
                "provider": str(local_provider or "").strip().lower(),
                "base_url": str(local_base_url or "").strip(),
                "api_key": local_api_key,
                "model": str(local_model or "").strip(),
                "temperature": float(local_temperature),
                "max_tokens": int(local_max_tokens),
                "timeout_seconds": int(local_timeout_seconds),
            }
            config = ncfg_module.save_notification_config(config)
            st_module.success("本地 SLM 配置已保存")
            if test_local_slm:
                ok, message = llm_module.test_llm_connection(config["local_slm"])
                if ok:
                    st_module.success(f"本地 SLM 测试成功：{message}")
                else:
                    st_module.error(message)
    auto_quant_enabled = "已启用" if alert_settings.get("enable_auto_quant_analysis", True) else "未启用"
    weekend_research_enabled = "已启用" if alert_settings.get("enable_weekend_research", True) else "未启用"
    min_interval_minutes = int(alert_settings.get("auto_quant_analysis_min_interval_seconds", 7200) or 0) // 60
    jump_pct = float(alert_settings.get("auto_quant_analysis_price_jump_pct", 0.03) or 0.0) * 100.0
    st_module.caption(
        f"自动全量分析: {auto_quant_enabled} | 最短间隔 {min_interval_minutes} 分钟 | 价格跳变阈值 {jump_pct:.1f}% | 周末研究: {weekend_research_enabled}"
    )
    cadence_parts = [
        f"夜报 {'开' if alert_settings.get('send_daily_summary', True) else '关'}",
        f"盘前简报 {'开' if alert_settings.get('send_premarket_brief', True) else '关'}",
        f"盘中提醒 {'开' if alert_settings.get('send_intraday_alerts', True) else '关'}",
        f"小时摘要 {'开' if alert_settings.get('send_hourly_market_summary', True) else '关'}",
        f"周末时间 {alert_settings.get('weekend_research_day_local', 'sunday')} {int(alert_settings.get('weekend_research_hour_local', 11) or 11):02d}:{int(alert_settings.get('weekend_research_minute_local', 0) or 0):02d}",
    ]
    st_module.caption("通知节奏: " + " | ".join(cadence_parts))
