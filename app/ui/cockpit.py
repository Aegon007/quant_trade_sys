import os

import pandas as pd
import streamlit as st

from app.ui import components as ui
from app.ui import pages as pg
from app.ui import panels as up
from quant_core.analytics import candidate_pool as cpool
from quant_core.analytics import core_etf_rotation as cer
from quant_core.monitoring import intraday_tactical as itac


def _card_container(st_module):
    try:
        return st_module.container(border=True)
    except TypeError:
        return st_module.container()


def _format_timestamp(value, fallback="—"):
    text = str(value or "").strip()
    if not text:
        return fallback
    return text.replace("T", " ")[:16]


def inject_cockpit_styles(*, st_module=None):
    st_module = st_module or st
    st_module.markdown(
        """
        <style>
        .stApp .block-container {
            padding-top: 1.4rem;
            padding-bottom: 2.0rem;
            max-width: 1400px;
        }
        div[data-testid="stMetric"] {
            background: rgba(250, 250, 252, 0.55);
            border: 1px solid rgba(148, 163, 184, 0.22);
            border-radius: 16px;
            padding: 0.8rem 0.95rem;
        }
        div[data-testid="stMetricLabel"] {
            white-space: normal !important;
            line-height: 1.2;
        }
        div[data-testid="stMetricValue"] {
            line-height: 1.15;
        }
        div[data-testid="stCaptionContainer"] {
            line-height: 1.35;
        }
        div[data-testid="stTable"] table {
            width: 100%;
            table-layout: fixed;
        }
        div[data-testid="stTable"] th,
        div[data-testid="stTable"] td {
            white-space: normal !important;
            word-break: break-word;
            vertical-align: top;
        }
        .qt-card-tight p {
            margin-bottom: 0.35rem;
        }
        .qt-shell-note {
            border-left: 4px solid #0f766e;
            padding: 0.8rem 1rem;
            background: rgba(15, 118, 110, 0.08);
            border-radius: 0.75rem;
            margin: 0.25rem 0 1rem 0;
        }
        .qt-section-kicker {
            color: #64748b;
            font-size: 0.9rem;
            margin-bottom: 0.35rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_shell_header(
    *,
    latest_trade_plan,
    latest_nightly_manifest,
    change_feed,
    discipline_snapshot,
    monthly_discipline_review,
    strategy_validation_snapshot,
    data_source_status,
    refresh_runtime_status,
    ui_text,
    st_module=None,
):
    st_module = st_module or st
    summary = dict((change_feed or {}).get("summary", {}) or {})
    manifest = dict(latest_nightly_manifest or {})
    discipline_snapshot = dict(discipline_snapshot or {})
    monthly_discipline_review = dict(monthly_discipline_review or {})
    strategy_validation_snapshot = dict(strategy_validation_snapshot or {})

    with _card_container(st_module):
        st_module.markdown(
            f"<div class='qt-shell-note'><strong>{ui_text('交易驾驶舱已启用', 'Trading cockpit is active')}</strong><br>"
            f"{ui_text('主界面现在聚焦夜间计划、盘中监控、收盘复盘，以及核心仓 / 卫星仓 / 风险三条主线。', 'The primary surface is now centered on nightly planning, intraday monitoring, post-close review, and the three main lanes: core book, satellite radar, and risk discipline.')}</div>",
            unsafe_allow_html=True,
        )
        top_cols = st_module.columns(3)
        bottom_cols = st_module.columns(3)
        top_cols[0].metric(
            ui_text("夜间运行", "Latest Nightly"),
            _format_timestamp(manifest.get("completed_at") or manifest.get("started_at")),
        )
        top_cols[1].metric(
            ui_text("明日计划", "Next-Day Plan"),
            ui_text("有动作", "Action")
            if bool((latest_trade_plan or {}).get("has_actions"))
            else ui_text("无动作", "No Action"),
        )
        top_cols[2].metric(
            ui_text("纪律", "Discipline"),
            str(discipline_snapshot.get("regime") or "UNKNOWN"),
        )
        bottom_cols[0].metric(
            ui_text("月度纪律", "Monthly Discipline"),
            str(monthly_discipline_review.get("status") or "MONITOR"),
        )
        bottom_cols[1].metric(
            ui_text("高变化", "High Changes"),
            f"{int(summary.get('high_count', 0) or 0)}",
        )
        last_price_refresh = ((data_source_status or {}).get("prices", {}) or {}).get("last_updated")
        bottom_cols[2].metric(
            ui_text("行情刷新", "Price Refresh"),
            _format_timestamp(last_price_refresh),
        )
        refresh_runtime_status = dict(refresh_runtime_status or {})
        refresh_mode = (
            ui_text("run_all 自动刷新中", "run_all auto-refresh")
            if bool(refresh_runtime_status.get("run_all_mode"))
            else ui_text("仅前台会话", "UI session only")
        )
        event_last_updated = _format_timestamp(refresh_runtime_status.get("event_last_updated"))
        st_module.caption(
            ui_text(
                f"后台刷新：{refresh_mode} | 事件上次刷新：{event_last_updated} | 首页优先显示最近一致快照，后台随后补最新数据。",
                f"Background refresh: {refresh_mode} | Last event refresh: {event_last_updated} | The homepage shows the latest consistent snapshot first, then background updates fill in fresher data.",
            )
        )
        monthly_summary = str(monthly_discipline_review.get("summary") or "").strip()
        if monthly_summary:
            st_module.caption(
                ui_text(
                    f"月度纪律提示：{monthly_summary}",
                    f"Monthly discipline: {monthly_summary}",
                )
            )
        validation_summary = dict(strategy_validation_snapshot.get("summary", {}) or {})
        if validation_summary:
            st_module.caption(
                ui_text(
                    f"策略验证：{validation_summary.get('status') or '—'} | 覆盖 {int(validation_summary.get('symbol_count', 0) or 0)} | 预警 {len(list(validation_summary.get('warning_symbols', []) or []))}",
                    f"Strategy validation: {validation_summary.get('status') or '—'} | coverage {int(validation_summary.get('symbol_count', 0) or 0)} | warnings {len(list(validation_summary.get('warning_symbols', []) or []))}",
                )
            )


def render_progress_panel(*, ui_text, st_module=None):
    st_module = st_module or st
    live_items = [
        ui_text("夜间计划 / 盘前简报 / 收盘复盘闭环", "Nightly plan / pre-market brief / post-close review loop"),
        ui_text("核心 ETF 候选池与轮动快照", "Core ETF universe and rotation snapshot"),
        ui_text("卫星候选池 + Top 3 正式评分", "Satellite candidate pool + formal Top 3 scoring"),
        ui_text("Robinhood CSV 导入与对账", "Robinhood CSV import and reconciliation"),
        ui_text("Slack / Email 通知路由", "Slack / Email delivery routing"),
        ui_text("控制中心 ETF / 候选池配置面板", "Control-center ETF / candidate configuration panels"),
        ui_text("控制中心手工持仓编辑器", "Control-center manual portfolio editor"),
        ui_text("盘中紧急事件分类与日志采集", "Intraday emergency classification and journal capture"),
        ui_text("Core ETF 按需 LLM / 本地 SLM 解释", "On-demand Core ETF explanations via LLM / local SLM"),
    ]
    stabilizing_items = [
        ui_text("Nightly manifest / 断点恢复", "Nightly manifest / resume support"),
        ui_text("Dashboard Change Feed 分级", "Dashboard change-feed prioritization"),
        ui_text("新驾驶舱信息架构与页面拆分", "New cockpit information architecture"),
        ui_text("盘中事件 outcome 标注与纪律复盘联动", "Intraday outcome labeling linked to discipline review"),
    ]
    optimization_items = [
        ui_text("持续压缩噪声提醒，只保留真正打断你的信号", "Continue suppressing noisy alerts and keep only interruption-worthy signals"),
        ui_text("扩展本地 SLM / 远程 LLM 的解释缓存复用", "Expand cached reuse for local-SLM / remote-LLM explanations"),
        ui_text("随着样本积累训练更好的盘中提醒价值模型", "Train better intraday alert-value models as more samples accumulate"),
    ]

    st_module.subheader(ui_text("系统进度与方向", "System Progress & Direction"))
    c1, c2, c3 = st_module.columns(3)
    with c1:
        with _card_container(st_module):
            st_module.markdown(f"**{ui_text('已上线', 'Live now')}**")
            for item in live_items:
                st_module.markdown(f"- {item}")
    with c2:
        with _card_container(st_module):
            st_module.markdown(f"**{ui_text('正在收口', 'Stabilizing')}**")
            for item in stabilizing_items:
                st_module.markdown(f"- {item}")
    with c3:
        with _card_container(st_module):
            st_module.markdown(f"**{ui_text('持续优化方向', 'Ongoing Optimization')}**")
            for item in optimization_items:
                st_module.markdown(f"- {item}")


def _coerce_editor_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value


def _clean_editor_records(frame, *, fields, numeric_fields=None):
    numeric_fields = set(numeric_fields or [])
    rows = []
    for row in list((frame if frame is not None else pd.DataFrame()).to_dict("records")):
        normalized = {}
        has_payload = False
        for field in fields:
            value = _coerce_editor_value(row.get(field))
            if field == "symbol" and isinstance(value, str):
                value = value.upper()
            if field in numeric_fields and value is not None:
                value = float(value)
            normalized[field] = value
            if field != "symbol" and value not in (None, ""):
                has_payload = True
        if normalized.get("symbol") is None and not has_payload:
            continue
        rows.append(normalized)
    return rows


def render_manual_portfolio_editor(
    *,
    data_utils_module,
    ui_text,
    st_module=None,
    session_state=None,
):
    st_module = st_module or st
    editable_payload = data_utils_module.load_editable_data()
    account = dict(editable_payload.get("account", {}) or {})
    holdings_df = pd.DataFrame(list(editable_payload.get("holdings", []) or []))
    watchlist_df = pd.DataFrame(list(editable_payload.get("watchlist", []) or []))
    if holdings_df.empty:
        holdings_df = pd.DataFrame(columns=["symbol", "shares", "cost", "sector"])
    if watchlist_df.empty:
        watchlist_df = pd.DataFrame(columns=["symbol", "notes"])

    st_module.subheader(ui_text("手工持仓编辑器", "Manual Portfolio Editor"))
    st_module.caption(
        ui_text(
            f"这里直接维护 `{data_utils_module.EDITABLE_DATA_FILE}`，保存后会同步更新运行时持仓数据。",
            f"This editor writes directly to `{data_utils_module.EDITABLE_DATA_FILE}` and synchronizes the runtime portfolio after saving.",
        )
    )

    c1, c2, c3, c4 = st_module.columns(4)
    cash_available = c1.number_input(
        ui_text("可用现金", "Cash Available"),
        min_value=0.0,
        value=float(account.get("cash_available") or 0.0),
        step=100.0,
        key="manual_portfolio_cash_available",
    )
    min_cash_buffer_pct = c2.number_input(
        ui_text("最小现金缓冲 (%)", "Min Cash Buffer (%)"),
        min_value=0.0,
        max_value=100.0,
        value=float(account.get("min_cash_buffer_pct", 0.05) or 0.05) * 100.0,
        step=1.0,
        key="manual_portfolio_cash_buffer",
    )
    max_single_position_pct = c3.number_input(
        ui_text("单仓上限 (%)", "Single Position Cap (%)"),
        min_value=0.0,
        max_value=100.0,
        value=float(account.get("max_single_position_pct", 0.20) or 0.20) * 100.0,
        step=1.0,
        key="manual_portfolio_single_cap",
    )
    max_total_exposure_pct = c4.number_input(
        ui_text("总暴露上限 (%)", "Total Exposure Cap (%)"),
        min_value=0.0,
        max_value=100.0,
        value=float(account.get("max_total_exposure_pct", 1.0) or 1.0) * 100.0,
        step=1.0,
        key="manual_portfolio_total_cap",
    )

    st_module.markdown(f"**{ui_text('持仓', 'Holdings')}**")
    edited_holdings = st_module.data_editor(
        holdings_df,
        hide_index=True,
        num_rows="dynamic",
        width="stretch",
        key="manual_portfolio_holdings_editor",
    )
    st_module.markdown(f"**{ui_text('候选观察池', 'Watchlist')}**")
    edited_watchlist = st_module.data_editor(
        watchlist_df,
        hide_index=True,
        num_rows="dynamic",
        width="stretch",
        key="manual_portfolio_watchlist_editor",
    )

    action_col1, action_col2 = st_module.columns(2)
    if action_col1.button(ui_text("保存并同步持仓", "Save & Sync Portfolio"), key="manual_portfolio_save"):
        payload = {
            "account": {
                "cash_available": float(cash_available),
                "min_cash_buffer_pct": float(min_cash_buffer_pct) / 100.0,
                "max_single_position_pct": float(max_single_position_pct) / 100.0,
                "max_total_exposure_pct": float(max_total_exposure_pct) / 100.0,
            },
            "holdings": _clean_editor_records(
                edited_holdings,
                fields=["symbol", "shares", "cost", "sector"],
                numeric_fields={"shares", "cost"},
            ),
            "watchlist": _clean_editor_records(
                edited_watchlist,
                fields=["symbol", "notes"],
            ),
        }
        try:
            data_utils_module.save_editable_data(payload, sync_runtime=True)
            if session_state is not None:
                session_state.app_data = data_utils_module.load_data(force_editable_sync=True)
            st_module.success(ui_text("手工持仓模板已保存并同步。", "Manual portfolio template saved and synchronized."))
            st_module.rerun()
        except ValueError as exc:
            st_module.error(str(exc))
    if action_col2.button(ui_text("从文件重新载入", "Reload From File"), key="manual_portfolio_reload"):
        try:
            reloaded_data = data_utils_module.load_data(force_editable_sync=True)
            if session_state is not None:
                session_state.app_data = reloaded_data
            st_module.success(ui_text("已从可编辑数据文件重新载入。", "Reloaded from the editable data file."))
            st_module.rerun()
        except ValueError as exc:
            st_module.error(str(exc))


def render_core_etf_config_editor(*, core_etf_universe, ui_text, st_module=None):
    st_module = st_module or st
    policy = cer.load_engine_policy()
    st_module.subheader(ui_text("核心 ETF 池配置", "Core ETF Universe Config"))
    st_module.caption(
        ui_text(
            "这里可以直接维护核心 ETF 候选池和轮动策略的基础门槛。保存后，新的 nightly / Dashboard 会自动读取这些配置。",
            "You can maintain the core ETF universe and baseline rotation thresholds here. New nightly runs and the Dashboard will read these settings automatically after saving.",
        )
    )
    editor_df = pd.DataFrame(list((core_etf_universe or {}).get("etfs", []) or []))
    if editor_df.empty:
        editor_df = pd.DataFrame(
            columns=["symbol", "enabled", "role", "priority", "long_term_core"]
        )
    edited_df = st_module.data_editor(
        editor_df,
        hide_index=True,
        num_rows="dynamic",
        width="stretch",
        key="core_etf_universe_editor",
        column_config={
            "symbol": st.column_config.TextColumn("symbol"),
            "enabled": st.column_config.CheckboxColumn("enabled", default=True),
            "role": st.column_config.TextColumn("role"),
            "priority": st.column_config.NumberColumn("priority", min_value=1, step=1, format="%d"),
            "long_term_core": st.column_config.CheckboxColumn("long_term_core", default=True),
        },
    )
    p1, p2, p3 = st_module.columns(3)
    min_weight_change_pct = p1.number_input(
        ui_text("最小权重变化阈值 (%)", "Min weight-change threshold (%)"),
        min_value=0.0,
        value=float(policy.get("min_weight_change_pct", 3.0) or 3.0),
        step=0.5,
        format="%.1f",
        key="core_etf_policy_min_weight_change",
    )
    action_confirmation_days = p2.number_input(
        ui_text("动作确认天数", "Action confirmation days"),
        min_value=1,
        value=int(policy.get("action_confirmation_days", 2) or 2),
        step=1,
        key="core_etf_policy_confirmation_days",
    )
    minimum_trade_value = p3.number_input(
        ui_text("最小交易金额 (USD)", "Minimum trade value (USD)"),
        min_value=0.0,
        value=float(policy.get("minimum_trade_value", 250.0) or 250.0),
        step=50.0,
        format="%.0f",
        key="core_etf_policy_min_trade_value",
    )
    if st_module.button(ui_text("保存核心 ETF 配置", "Save Core ETF Config"), key="save_core_etf_config"):
        cer.save_core_etf_universe({"etfs": edited_df.to_dict("records")})
        updated_policy = dict(policy or {})
        updated_policy["min_weight_change_pct"] = float(min_weight_change_pct)
        updated_policy["action_confirmation_days"] = int(action_confirmation_days)
        updated_policy["minimum_trade_value"] = float(minimum_trade_value)
        cer.save_engine_policy(updated_policy)
        st_module.success(ui_text("核心 ETF 配置已保存。", "Core ETF configuration saved."))
        st_module.rerun()


def render_satellite_config_editor(*, ui_text, st_module=None):
    st_module = st_module or st
    universe = cpool.load_satellite_universe()
    st_module.subheader(ui_text("卫星候选池配置", "Satellite Candidate Pool Config"))
    st_module.caption(
        ui_text(
            "这里直接控制 nightly 候选池规模、深度分析数量和手工补充股票池。它已经替代了旧 watchlist 驱动的配置方式。",
            "This directly controls the nightly candidate-pool size, deep-analysis count, and manual satellite-universe overrides. It replaces the old watchlist-driven setup.",
        )
    )
    source_indexes = ", ".join(list(universe.get("source_indexes", []) or []))
    manual_include = ", ".join(list(universe.get("manual_include", []) or []))
    manual_exclude = ", ".join(list(universe.get("manual_exclude", []) or []))
    source_indexes_text = st_module.text_input(
        ui_text("来源索引（逗号分隔）", "Source indexes (comma-separated)"),
        value=source_indexes,
        key="satellite_source_indexes_editor",
    )
    manual_include_text = st_module.text_area(
        ui_text("手工纳入股票（逗号或空格分隔）", "Manual include symbols (comma or space separated)"),
        value=manual_include,
        key="satellite_manual_include_editor",
    )
    manual_exclude_text = st_module.text_area(
        ui_text("手工排除股票（逗号或空格分隔）", "Manual exclude symbols (comma or space separated)"),
        value=manual_exclude,
        key="satellite_manual_exclude_editor",
    )
    c1, c2, c3, c4 = st_module.columns(4)
    max_candidate_pool_size = c1.number_input(
        ui_text("候选池上限", "Candidate pool cap"),
        min_value=1,
        value=int(universe.get("max_candidate_pool_size", 100) or 100),
        step=1,
        key="satellite_max_pool_editor",
    )
    max_deep_analysis_size = c2.number_input(
        ui_text("深度分析数", "Deep analysis count"),
        min_value=1,
        value=int(universe.get("max_deep_analysis_size", 20) or 20),
        step=1,
        key="satellite_max_deep_editor",
    )
    max_recommendations = c3.number_input(
        ui_text("Top 推荐数", "Top recommendation count"),
        min_value=1,
        value=int(universe.get("max_recommendations", 3) or 3),
        step=1,
        key="satellite_max_reco_editor",
    )
    candidate_persistence_days = c4.number_input(
        ui_text("入池确认天数", "Candidate persistence days"),
        min_value=1,
        value=int(universe.get("candidate_persistence_days", 2) or 2),
        step=1,
        key="satellite_persistence_editor",
    )
    if st_module.button(ui_text("保存卫星候选池配置", "Save Satellite Config"), key="save_satellite_config"):
        normalized_payload = {
            "source_indexes": [item.strip() for item in source_indexes_text.replace(" ", "").split(",") if item.strip()],
            "manual_include": [
                item.strip().upper()
                for item in manual_include_text.replace("\n", ",").replace(" ", ",").split(",")
                if item.strip()
            ],
            "manual_exclude": [
                item.strip().upper()
                for item in manual_exclude_text.replace("\n", ",").replace(" ", ",").split(",")
                if item.strip()
            ],
            "max_candidate_pool_size": int(max_candidate_pool_size),
            "max_deep_analysis_size": int(max_deep_analysis_size),
            "max_recommendations": int(max_recommendations),
            "candidate_persistence_days": int(candidate_persistence_days),
        }
        cpool.save_satellite_universe(normalized_payload)
        st_module.success(ui_text("卫星候选池配置已保存。", "Satellite candidate-pool configuration saved."))
        st_module.rerun()


def render_intraday_tactical_config_editor(*, ui_text, st_module=None):
    st_module = st_module or st
    config = itac.load_intraday_tactical_config()
    st_module.subheader(ui_text("盘中战术层配置", "Intraday Tactical Overlay Config"))
    st_module.caption(
        ui_text(
            "这里控制盘中战术工具池和触发阈值。它只服务于盘中风险升级与反向对冲，不参与核心仓或普通卫星仓配置。",
            "This controls the intraday tactical tool pool and trigger thresholds. It is only for intraday risk escalation and tactical hedging, not for the core or normal satellite books.",
        )
    )
    enabled = st_module.checkbox(
        ui_text("启用盘中战术层", "Enable Intraday Tactical Overlay"),
        value=bool(config.get("enabled", True)),
        key="intraday_tactical_enabled",
    )
    benchmark_symbols_text = st_module.text_input(
        ui_text("基准标的（逗号分隔）", "Benchmark symbols (comma-separated)"),
        value=", ".join(list(config.get("benchmark_symbols", []) or [])),
        key="intraday_tactical_benchmarks",
    )
    tactical_df = pd.DataFrame(list(config.get("tactical_symbols", []) or []))
    if tactical_df.empty:
        tactical_df = pd.DataFrame(columns=["symbol", "role", "max_weight_pct"])
    edited_df = st_module.data_editor(
        tactical_df,
        hide_index=True,
        num_rows="dynamic",
        width="stretch",
        key="intraday_tactical_symbols_editor",
        column_config={
            "symbol": st.column_config.TextColumn("symbol"),
            "role": st.column_config.TextColumn("role"),
            "max_weight_pct": st.column_config.NumberColumn("max_weight_pct", min_value=0.0, step=0.5, format="%.1f"),
        },
    )
    thresholds = dict(config.get("thresholds", {}) or {})
    t1, t2 = st_module.columns(2)
    qqq_stress = t1.number_input(
        ui_text("QQQ 压力阈值 (%)", "QQQ stress threshold (%)"),
        value=float(thresholds.get("qqq_stress_drop_pct", -0.02) or 0.0) * 100.0,
        step=0.1,
        format="%.1f",
        key="intraday_tactical_qqq_stress",
    )
    qqq_panic = t2.number_input(
        ui_text("QQQ 恐慌阈值 (%)", "QQQ panic threshold (%)"),
        value=float(thresholds.get("qqq_panic_drop_pct", -0.03) or 0.0) * 100.0,
        step=0.1,
        format="%.1f",
        key="intraday_tactical_qqq_panic",
    )
    t3, t4 = st_module.columns(2)
    spy_stress = t3.number_input(
        ui_text("SPY 压力阈值 (%)", "SPY stress threshold (%)"),
        value=float(thresholds.get("spy_stress_drop_pct", -0.015) or 0.0) * 100.0,
        step=0.1,
        format="%.1f",
        key="intraday_tactical_spy_stress",
    )
    spy_panic = t4.number_input(
        ui_text("SPY 恐慌阈值 (%)", "SPY panic threshold (%)"),
        value=float(thresholds.get("spy_panic_drop_pct", -0.025) or 0.0) * 100.0,
        step=0.1,
        format="%.1f",
        key="intraday_tactical_spy_panic",
    )
    t5, t6 = st_module.columns(2)
    tactical_chase_gain = t5.number_input(
        ui_text("不追高阈值 (%)", "Do-not-chase threshold (%)"),
        value=float(thresholds.get("tactical_chase_gain_pct", 0.08) or 0.0) * 100.0,
        step=0.5,
        format="%.1f",
        key="intraday_tactical_chase_gain",
    )
    max_tactical_total_weight_pct = t6.number_input(
        ui_text("战术总仓位上限 (%)", "Max tactical total weight (%)"),
        min_value=0.0,
        value=float(config.get("max_tactical_total_weight_pct", 5.0) or 0.0),
        step=0.5,
        format="%.1f",
        key="intraday_tactical_total_cap",
    )
    allow_overnight = st_module.checkbox(
        ui_text("允许隔夜", "Allow overnight holding"),
        value=bool(config.get("allow_overnight", False)),
        key="intraday_tactical_allow_overnight",
    )
    if st_module.button(ui_text("保存盘中战术层配置", "Save Intraday Tactical Config"), key="save_intraday_tactical_config"):
        payload = {
            "enabled": bool(enabled),
            "benchmark_symbols": [
                item.strip().upper()
                for item in benchmark_symbols_text.replace(" ", "").split(",")
                if item.strip()
            ],
            "tactical_symbols": [
                {
                    "symbol": str(row.get("symbol") or "").strip().upper(),
                    "role": str(row.get("role") or "").strip(),
                    "max_weight_pct": float(row.get("max_weight_pct") or 0.0),
                }
                for row in edited_df.to_dict("records")
                if str(row.get("symbol") or "").strip()
            ],
            "thresholds": {
                "qqq_stress_drop_pct": float(qqq_stress) / 100.0,
                "qqq_panic_drop_pct": float(qqq_panic) / 100.0,
                "spy_stress_drop_pct": float(spy_stress) / 100.0,
                "spy_panic_drop_pct": float(spy_panic) / 100.0,
                "tactical_chase_gain_pct": float(tactical_chase_gain) / 100.0,
            },
            "allow_overnight": bool(allow_overnight),
            "max_tactical_total_weight_pct": float(max_tactical_total_weight_pct),
        }
        itac.save_intraday_tactical_config(payload)
        st_module.success(ui_text("盘中战术层配置已保存。", "Intraday tactical overlay configuration saved."))
        st_module.rerun()


def render_core_etf_cards(
    snapshot,
    *,
    ui_text,
    st_module=None,
    enable_llm_explanations: bool = False,
    llm_explanations=None,
    explain_core_etf_fn=None,
    button_namespace: str = "core_etf",
):
    st_module = st_module or st
    rows = list((snapshot or {}).get("symbols", []) or [])
    llm_explanations = dict(llm_explanations or {})
    if not rows:
        st_module.info(ui_text("尚未生成核心 ETF 快照。", "Core ETF snapshot is not available yet."))
        return

    columns = st_module.columns(2)
    for idx, row in enumerate(rows):
        col = columns[idx % len(columns)]
        with col:
            with _card_container(st_module):
                st_module.markdown("<div class='qt-card-tight'>", unsafe_allow_html=True)
                st_module.markdown(f"**{row.get('symbol', '—')} · {row.get('role', 'other')}**")
                st_module.caption(str(row.get("signal_reason") or "").strip() or ui_text("暂无摘要。", "No summary yet."))
                m1, m2 = st_module.columns(2)
                m1.metric(ui_text("动作", "Action"), str(row.get("action") or "HOLD"))
                m2.metric(
                    ui_text("轮动评分", "Rotation Score"),
                    f"{float(row.get('rotation_score') or 0.0):.1f}",
                )
                m3, m4 = st_module.columns(2)
                m3.metric(
                    ui_text("当前仓位", "Current"),
                    f"{float(row.get('current_weight_pct') or 0.0):.1f}%",
                )
                m4.metric(
                    ui_text("目标仓位", "Target"),
                    f"{float(row.get('target_weight_pct') or 0.0):.1f}%",
                )
                st_module.caption(
                    ui_text(
                        f"目标区间 {float(row.get('target_weight_range_low_pct') or 0.0):.1f}% ~ {float(row.get('target_weight_range_high_pct') or 0.0):.1f}%",
                        f"Target range {float(row.get('target_weight_range_low_pct') or 0.0):.1f}% ~ {float(row.get('target_weight_range_high_pct') or 0.0):.1f}%",
                    )
                )
                stability_score = row.get("signal_stability_score")
                same_action_days = int(float(row.get("days_in_same_action") or 0.0) or 0)
                regime_change_days = int(float(row.get("days_since_regime_change") or 0.0) or 0)
                if stability_score is not None:
                    st_module.caption(
                        ui_text(
                            f"稳定度 {float(stability_score):.0f}/100 | 同动作 {same_action_days} 天 | 距 regime 切换 {regime_change_days} 天",
                            f"Stability {float(stability_score):.0f}/100 | Same action {same_action_days}d | Since regime change {regime_change_days}d",
                        )
                    )
                buy_low = row.get("recommended_buy_zone_low")
                buy_high = row.get("recommended_buy_zone_high")
                trim_low = row.get("trim_zone_low")
                trim_high = row.get("trim_zone_high")
                risk_break = row.get("risk_break_level")
                buy_zone_text = (
                    ('$%.2f ~ $%.2f' % (buy_low, buy_high))
                    if buy_low is not None and buy_high is not None
                    else "—"
                )
                trim_zone_text = (
                    ('$%.2f ~ $%.2f' % (trim_low, trim_high))
                    if trim_low is not None and trim_high is not None
                    else "—"
                )
                risk_break_text = ('$%.2f' % risk_break) if risk_break is not None else "—"
                st_module.caption(
                    ui_text(
                        f"买 {buy_zone_text} | 减 {trim_zone_text} | 破位 {risk_break_text}",
                        f"Buy {buy_zone_text} | Trim {trim_zone_text} | Break {risk_break_text}",
                    )
                )
                symbol = str(row.get("symbol") or "").strip().upper()
                explanation_record = dict(llm_explanations.get(symbol, {}) or {})
                explanation_text = str(explanation_record.get("text") or "").strip()
                explanation_label = str(explanation_record.get("label") or "").strip()
                if enable_llm_explanations and explain_core_etf_fn is not None:
                    if st_module.button(
                        ui_text("LLM 解释", "LLM Explain"),
                        key=f"{button_namespace}_llm_explain_{symbol}_{idx}",
                    ):
                        ok, message, meta = explain_core_etf_fn(row)
                        if ok:
                            explanation_text = str(message or "").strip()
                            route_name = str((meta or {}).get("route_name") or "").strip()
                            model_name = str((meta or {}).get("model") or "").strip()
                            cached = bool((meta or {}).get("cached"))
                            detail_bits = []
                            if route_name:
                                detail_bits.append(route_name)
                            if model_name:
                                detail_bits.append(model_name)
                            if cached:
                                detail_bits.append("cached")
                            explanation_label = " | ".join(detail_bits)
                        else:
                            st_module.error(message)
                if explanation_text:
                    with st_module.expander(ui_text("查看解释", "View Explanation"), expanded=False):
                        if explanation_label:
                            st_module.caption(explanation_label)
                        st_module.write(explanation_text)
                st_module.markdown("</div>", unsafe_allow_html=True)


def render_satellite_top_cards(
    snapshot,
    *,
    ui_text,
    st_module=None,
    enable_llm_explanations: bool = False,
    llm_explanations=None,
    explain_satellite_fn=None,
    button_namespace: str = "satellite_top",
):
    st_module = st_module or st
    top_rows = list((snapshot or {}).get("top_recommendations", []) or [])
    llm_explanations = dict(llm_explanations or {})
    if not top_rows:
        st_module.info(ui_text("当前没有 Top 3 候选。", "Top 3 candidates are not available yet."))
        return
    columns = st_module.columns(3)
    for idx, row in enumerate(top_rows[:3]):
        with columns[idx]:
            with _card_container(st_module):
                st_module.markdown("<div class='qt-card-tight'>", unsafe_allow_html=True)
                st_module.markdown(f"**{row.get('symbol', '—')}**")
                st_module.caption(str(row.get("recommendation_reason") or row.get("signal_reason") or "").strip() or ui_text("暂无摘要。", "No summary yet."))
                m1, m2 = st_module.columns(2)
                m1.metric(ui_text("阶段", "Stage"), str(row.get("recommendation_status") or row.get("candidate_state") or "WATCH"))
                m2.metric(
                    ui_text("建议仓位", "Target"),
                    f"{float(row.get('suggested_weight_pct') or 0.0):.1f}%",
                )
                m3, m4 = st_module.columns(2)
                m3.metric(ui_text("综合分", "Score"), f"{float(row.get('satellite_score') or 0.0):.1f}")
                mc = dict(row.get("monte_carlo", {}) or {})
                m4.metric(
                    ui_text("MC预期", "MC Exp"),
                    f"{float(mc.get('expected_return')):+.2%}" if mc.get("expected_return") is not None else "—",
                )
                membership_state = str(row.get("top3_membership_state") or "").strip().upper()
                residency_days = int(float(row.get("top3_residency_days") or 0.0) or 0)
                if membership_state:
                    st_module.caption(
                        ui_text(
                            f"Top3 状态 {membership_state} | 已驻留 {residency_days} 天",
                            f"Top3 state {membership_state} | Residency {residency_days}d",
                        )
                    )
                risk_note = str(row.get("risk_note") or row.get("exit_reason") or "").strip()
                if risk_note:
                    st_module.caption(risk_note)
                symbol = str(row.get("symbol") or "").strip().upper()
                explanation_record = dict(llm_explanations.get(symbol, {}) or {})
                explanation_text = str(explanation_record.get("text") or "").strip()
                explanation_label = str(explanation_record.get("label") or "").strip()
                if enable_llm_explanations and explain_satellite_fn is not None:
                    if st_module.button(
                        ui_text("LLM 解释", "LLM Explain"),
                        key=f"{button_namespace}_llm_explain_{symbol}_{idx}",
                    ):
                        ok, message, meta = explain_satellite_fn(row)
                        if ok:
                            explanation_text = str(message or "").strip()
                            route_name = str((meta or {}).get("route_name") or "").strip()
                            model_name = str((meta or {}).get("model") or "").strip()
                            detail_bits = []
                            if route_name:
                                detail_bits.append(route_name)
                            if model_name:
                                detail_bits.append(model_name)
                            if (meta or {}).get("cached"):
                                detail_bits.append("cached")
                            explanation_label = " | ".join(detail_bits)
                        else:
                            st_module.error(message)
                if explanation_text:
                    with st_module.expander(ui_text("查看解释", "View Explanation"), expanded=False):
                        if explanation_label:
                            st_module.caption(explanation_label)
                        st_module.write(explanation_text)
                st_module.markdown("</div>", unsafe_allow_html=True)


def render_quant_report_summary(snapshot, files, *, ui_text, st_module=None):
    st_module = st_module or st
    snapshot = dict(snapshot or {})
    files = dict(files or {})
    if not snapshot:
        st_module.info(ui_text("尚未生成组合级量化报告。", "No portfolio-level quant report is available yet."))
        return

    summary = dict(snapshot.get("summary", {}) or {})
    with _card_container(st_module):
        st_module.markdown(f"**{ui_text('最新组合量化报告', 'Latest Portfolio Quant Report')}**")
        st_module.caption(
            ui_text(
                f"生成时间：{snapshot.get('generated_at', '—')}",
                f"Generated at: {snapshot.get('generated_at', '—')}",
            )
        )
        top_cols = st_module.columns(2)
        bottom_cols = st_module.columns(2)
        top_cols[0].metric(ui_text("覆盖标的", "Tracked"), f"{int(summary.get('total_symbols', 0) or 0)}")
        top_cols[1].metric(ui_text("买入信号", "BUY"), f"{int(summary.get('buy_count', 0) or 0)}")
        bottom_cols[0].metric(ui_text("卖出信号", "SELL"), f"{int(summary.get('sell_count', 0) or 0)}")
        bottom_cols[1].metric(ui_text("观望信号", "HOLD"), f"{int(summary.get('hold_count', 0) or 0)}")
        top_buys = ", ".join(list(summary.get("top_buy_symbols", []) or []))
        if top_buys:
            st_module.caption(ui_text(f"优先关注：{top_buys}", f"Top candidates: {top_buys}"))

        download_cols = st_module.columns(3)
        latest_pdf_path = files.get("latest_pdf_path")
        latest_markdown_path = files.get("latest_markdown_path")
        latest_json_path = files.get("latest_json_path")
        if latest_pdf_path and os.path.exists(latest_pdf_path):
            with open(latest_pdf_path, "rb") as handle:
                download_cols[0].download_button(
                    ui_text("下载 PDF", "Download PDF"),
                    data=handle.read(),
                    file_name=os.path.basename(latest_pdf_path),
                    mime="application/pdf",
                )
        if latest_markdown_path and os.path.exists(latest_markdown_path):
            with open(latest_markdown_path, "rb") as handle:
                download_cols[1].download_button(
                    ui_text("下载 Markdown", "Download Markdown"),
                    data=handle.read(),
                    file_name=os.path.basename(latest_markdown_path),
                    mime="text/markdown",
                )
        if latest_json_path and os.path.exists(latest_json_path):
            with open(latest_json_path, "rb") as handle:
                download_cols[2].download_button(
                    ui_text("下载 JSON", "Download JSON"),
                    data=handle.read(),
                    file_name=os.path.basename(latest_json_path),
                    mime="application/json",
                )


def render_control_center_page(
    *,
    ui_text,
    latest_nightly_manifest,
    latest_change_feed,
    change_feed_narration=None,
    change_feed_explanation=None,
    narrate_change_feed_fn=None,
    explain_change_feed_fn=None,
    latest_report_snapshot,
    latest_report_files,
    market_events_bootstrapped,
    market_events_file,
    event_sources_config_path,
    analyst_consensus_cache_file,
    editable_data_file,
    manual_portfolio_editor,
    transactions_renderer,
    tx_module,
    L,
    format_share_quantity_fn,
    portfolio_actions_module,
    data_utils_module,
    session_state,
    report_rebuilder,
    latest_weekend_research_snapshot=None,
    latest_strategy_validation_snapshot=None,
    latest_strategy_experiment_journal=None,
    run_weekend_research_fn=None,
    st_module=None,
):
    st_module = st_module or st

    st_module.header(ui_text("运营中心", "Operations"))
    st_module.caption(
        ui_text(
            "这里统一处理交易同步、手工数据维护、nightly 结果查看和报告重建。",
            "This page centralizes trade sync, manual data maintenance, nightly inspection, and report rebuild tasks.",
        )
    )

    sync_tab, report_tab = st_module.tabs(
        [
            ui_text("同步与模板", "Sync & Templates"),
            ui_text("报告与通知", "Reports & Notifications"),
        ]
    )

    with sync_tab:
        st_module.subheader(ui_text("Robinhood 交易同步", "Robinhood Trade Sync"))
        transactions_renderer(
            tx_module=tx_module,
            L=L,
            format_share_quantity_fn=format_share_quantity_fn,
            st_module=st_module,
            session_state=session_state,
            portfolio_actions_module=portfolio_actions_module,
            data_utils_module=data_utils_module,
        )
        st_module.divider()
        manual_portfolio_editor(
            data_utils_module=data_utils_module,
            ui_text=ui_text,
            st_module=st_module,
            session_state=session_state,
        )

    with report_tab:
        st_module.subheader(ui_text("组合量化报告", "Portfolio Quant Report"))
        if st_module.button(ui_text("重建最新组合量化报告", "Rebuild Latest Portfolio Quant Report")):
            report_rebuilder()
        render_quant_report_summary(
            latest_report_snapshot,
            latest_report_files,
            ui_text=ui_text,
            st_module=st_module,
        )

        st_module.divider()
        st_module.subheader(ui_text("周末研究", "Weekend Research"))
        if callable(run_weekend_research_fn) and st_module.button(ui_text("立即运行周末研究", "Run Weekend Research Now")):
            run_weekend_research_fn()
        weekend_snapshot = dict(latest_weekend_research_snapshot or {})
        weekend_summary = dict(weekend_snapshot.get("summary", {}) or {})
        if weekend_snapshot:
            w1, w2 = st_module.columns(2)
            w3, w4 = st_module.columns(2)
            w1.metric(ui_text("周偏向", "Bias"), str(weekend_summary.get("next_week_bias") or "—"))
            w2.metric(ui_text("风控状态", "Risk"), str(weekend_summary.get("risk_regime") or "—"))
            w3.metric(ui_text("核心焦点", "Core Focus"), f"{int(weekend_summary.get('core_focus_count', 0) or 0)}")
            w4.metric(ui_text("卫星Top", "Satellite Top"), f"{int(weekend_summary.get('satellite_top_count', 0) or 0)}")
            message = str(weekend_summary.get("message") or "").strip()
            if message:
                st_module.info(message)
            recommendation_rows = [
                {ui_text("研究结论", "Research takeaway"): str(item).strip()}
                for item in list(weekend_snapshot.get("recommendations", []) or [])[:5]
                if str(item).strip()
            ]
            if recommendation_rows:
                up.render_compact_table(pd.DataFrame(recommendation_rows), st_module=st_module)
            strategy_rows = []
            for row in list(weekend_snapshot.get("strategy_research_rows", []) or [])[:5]:
                strategy_rows.append(
                    {
                        ui_text("代码", "Symbol"): row.get("symbol") or "—",
                        ui_text("领先策略", "Best Strategy"): row.get("best_strategy_name") or "—",
                        ui_text("分数", "Score"): f"{float(row.get('best_strategy_score') or 0.0):.2f}",
                    }
                )
            if strategy_rows:
                st_module.caption(ui_text("周末策略对比亮点", "Weekend strategy-compare highlights"))
                up.render_compact_table(pd.DataFrame(strategy_rows), st_module=st_module)
        else:
            st_module.info(ui_text("尚未生成周末研究快照。", "No weekend research snapshot is available yet."))

        st_module.divider()
        up.render_strategy_validation_panel(
            latest_strategy_validation_snapshot,
            journal_rows=latest_strategy_experiment_journal,
            ui_text=ui_text,
            st_module=st_module,
        )

        with st_module.expander(ui_text("Nightly 管线与变化日志", "Nightly Pipeline & Change Log"), expanded=False):
            up.render_nightly_manifest_panel(latest_nightly_manifest, ui_text=ui_text, st_module=st_module)
            up.render_change_feed_panel(
                latest_change_feed,
                change_feed_narration=change_feed_narration,
                change_feed_explanation=change_feed_explanation,
                narrate_change_feed_fn=narrate_change_feed_fn,
                explain_change_feed_fn=explain_change_feed_fn,
                key_prefix="control_change_feed",
                ui_text=ui_text,
                st_module=st_module,
            )

        with st_module.expander(ui_text("运行文件与状态", "Runtime Files & Status"), expanded=False):
            st_module.caption(ui_text(f"可编辑数据文件：`{editable_data_file}`", f"Editable data file: `{editable_data_file}`"))
            st_module.caption(ui_text(f"市场事件文件：`{market_events_file}`", f"Market events file: `{market_events_file}`"))
            st_module.caption(ui_text(f"事件源配置：`{event_sources_config_path}`", f"Event source config: `{event_sources_config_path}`"))
            st_module.caption(ui_text(f"分析师共识缓存：`{analyst_consensus_cache_file}`", f"Analyst-consensus cache: `{analyst_consensus_cache_file}`"))
            if market_events_bootstrapped:
                st_module.success(ui_text("市场事件样例文件已就绪。", "The market-events bootstrap file is ready."))

        with st_module.expander(ui_text("系统路线图", "System Roadmap"), expanded=False):
            render_progress_panel(ui_text=ui_text, st_module=st_module)


def render_settings_page(
    *,
    ui_text,
    data,
    market_events_bootstrapped,
    market_events_file,
    event_sources_config_path,
    analyst_consensus_cache_file,
    editable_data_file,
    account_config_saver,
    notification_renderer,
    ncfg_module,
    nch_module,
    session_state,
    history_period_options,
    strategies,
    run_full_system_refresh_fn=None,
    force_price_refresh_fn=None,
    refresh_news_fn=None,
    reload_editable_data_fn=None,
    manual_tcn_retrain_fn=None,
    run_weekend_research_fn=None,
    nightly_retrain_status=None,
    analyst_consensus_status=None,
    last_price_refresh=None,
    last_news_refresh=None,
    last_weekend_research=None,
    st_module=None,
):
    st_module = st_module or st
    account_config = dict(data.get("account", {}) or {})

    st_module.header(ui_text("设置", "Settings"))
    st_module.caption(
        ui_text(
            "这里统一管理所有低频配置：资金参数、核心 ETF 池、卫星候选池、Slack / Email、远程 LLM 和本地 SLM。",
            "This page centralizes all low-frequency configuration: capital settings, the core ETF universe, the satellite universe, Slack / Email, the remote LLM, and the local SLM.",
        )
    )
    st_module.caption(
        ui_text(
            "交易同步、Robinhood CSV 导入和手工持仓维护放在 Operations 页；这里只保留统一配置。",
            "Trade sync, Robinhood CSV import, and manual portfolio maintenance live in Operations; this page is reserved for shared configuration.",
        )
    )

    quick_tab, portfolio_tab, universe_tab, delivery_tab, advanced_tab = st_module.tabs(
        [
            ui_text("快速操作", "Quick Actions"),
            ui_text("账户与风险", "Portfolio & Risk"),
            ui_text("ETF / 候选池", "Universe & Strategy"),
            ui_text("通知 / 模型", "Notifications & Models"),
            ui_text("高级", "Advanced"),
        ]
    )

    with quick_tab:
        st_module.subheader(ui_text("界面与运行上下文", "UI & Runtime Context"))
        ctx1, ctx2, ctx3 = st_module.columns(3)
        selected_lang = ctx1.selectbox(
            ui_text("界面语言", "Interface Language"),
            ["中文", "English"],
            index=0 if session_state.get("lang", "zh") == "zh" else 1,
            key="settings_language_select",
        )
        session_state.lang = "zh" if selected_lang == "中文" else "en"

        current_history_period = str(session_state.get("history_period", history_period_options[0]))
        history_index = history_period_options.index(current_history_period) if current_history_period in history_period_options else 0
        session_state.history_period = ctx2.selectbox(
            ui_text("历史窗口", "History Window"),
            history_period_options,
            index=history_index,
            key="settings_history_period_select",
        )

        strategy_names = [str(item.get("name") or "") for item in strategies]
        strategy_ids = [str(item.get("id") or "") for item in strategies]
        current_strategy_id = str(session_state.get("selected_strategy_id") or strategy_ids[0])
        strategy_index = strategy_ids.index(current_strategy_id) if current_strategy_id in strategy_ids else 0
        selected_strategy_name = ctx3.selectbox(
            ui_text("当前决策策略", "Decision Strategy"),
            strategy_names,
            index=strategy_index,
            key="settings_strategy_select",
        )
        selected_strategy = next((item for item in strategies if str(item.get("name") or "") == selected_strategy_name), strategies[0])
        session_state.selected_strategy_id = str(selected_strategy.get("id") or strategy_ids[0])

        st_module.divider()
        st_module.subheader(ui_text("一键补齐 / 刷新", "Bootstrap & Refresh"))
        q1, q2, q3, q4 = st_module.columns(4)
        if callable(run_full_system_refresh_fn) and q1.button(ui_text("立即强制补齐整套系统数据", "Force Full System Update Now")):
            run_full_system_refresh_fn()
        if callable(force_price_refresh_fn) and q2.button(ui_text("仅强制刷新行情", "Force Price Refresh Only")):
            force_price_refresh_fn()
        if callable(refresh_news_fn) and q3.button(ui_text("刷新新闻 / 事件", "Refresh News / Events")):
            refresh_news_fn()
        if callable(reload_editable_data_fn) and q4.button(ui_text("从可编辑数据文件重载", "Reload Editable Data")):
            reload_editable_data_fn()
        if callable(manual_tcn_retrain_fn) and st_module.button(ui_text("手动重训 TCN", "Manual TCN Retrain")):
            manual_tcn_retrain_fn()
        if callable(run_weekend_research_fn) and st_module.button(ui_text("立即运行周末研究", "Run Weekend Research Now")):
            run_weekend_research_fn()
        st_module.caption(
            ui_text(
                "“强制补齐整套系统数据”会立即跑一次无通知版 nightly 流程，用来在白天首次启动时补齐快照、候选池、报告和计划单。",
                "\"Force Full System Update Now\" runs a no-delivery nightly refresh immediately so daytime first launches can backfill snapshots, candidate pools, reports, and trade plans.",
            )
        )
        runtime_bits = []
        if nightly_retrain_status:
            runtime_bits.append(ui_text(f"TCN 状态: {nightly_retrain_status}", f"TCN status: {nightly_retrain_status}"))
        if analyst_consensus_status:
            runtime_bits.append(
                ui_text(
                    f"分析师共识: {analyst_consensus_status}",
                    f"Analyst consensus: {analyst_consensus_status}",
                )
            )
        if last_price_refresh:
            runtime_bits.append(
                ui_text(
                    f"最近价格刷新: {last_price_refresh}",
                    f"Latest price refresh: {last_price_refresh}",
                )
            )
        if last_news_refresh:
            runtime_bits.append(
                ui_text(
                    f"最近新闻刷新: {last_news_refresh}",
                    f"Latest news refresh: {last_news_refresh}",
                )
            )
        if last_weekend_research:
            runtime_bits.append(
                ui_text(
                    f"最近周末研究: {last_weekend_research}",
                    f"Latest weekend research: {last_weekend_research}",
                )
            )
        if runtime_bits:
            st_module.caption(" | ".join(runtime_bits))

    with portfolio_tab:
        st_module.subheader(ui_text("账户资金与风险参数", "Capital & Risk Settings"))
        with st_module.form("settings_account_config_form"):
            cash_available = st_module.number_input(
                ui_text("可用现金 (USD)", "Cash available (USD)"),
                min_value=0.0,
                value=float(account_config.get("cash_available") or 0.0),
                step=100.0,
                format="%.2f",
            )
            c1, c2 = st_module.columns(2)
            min_cash_buffer_pct = c1.number_input(
                ui_text("最低现金缓冲 (%)", "Min cash buffer (%)"),
                min_value=0.0,
                max_value=100.0,
                value=float(account_config.get("min_cash_buffer_pct", 0.05) or 0.0) * 100.0,
                step=1.0,
                format="%.1f",
            )
            max_single_position_pct = c2.number_input(
                ui_text("单票上限 (%)", "Max single position (%)"),
                min_value=0.0,
                max_value=100.0,
                value=float(account_config.get("max_single_position_pct", 0.20) or 0.0) * 100.0,
                step=1.0,
                format="%.1f",
            )
            max_total_exposure_pct = st_module.number_input(
                ui_text("总暴露上限 (%)", "Max total exposure (%)"),
                min_value=0.0,
                max_value=100.0,
                value=float(account_config.get("max_total_exposure_pct", 1.0) or 0.0) * 100.0,
                step=1.0,
                format="%.1f",
            )
            if st_module.form_submit_button(ui_text("保存资金参数", "Save capital settings")):
                account_config_saver(
                    data,
                    cash_available=cash_available,
                    min_cash_buffer_pct=min_cash_buffer_pct,
                    max_single_position_pct=max_single_position_pct,
                    max_total_exposure_pct=max_total_exposure_pct,
                )

    with universe_tab:
        render_core_etf_config_editor(
            core_etf_universe=cer.load_core_etf_universe(),
            ui_text=ui_text,
            st_module=st_module,
        )
        st_module.divider()
        render_satellite_config_editor(
            ui_text=ui_text,
            st_module=st_module,
        )
        st_module.divider()
        render_intraday_tactical_config_editor(
            ui_text=ui_text,
            st_module=st_module,
        )

    with delivery_tab:
        notification_renderer(
            ncfg_module=ncfg_module,
            nch_module=nch_module,
            st_module=st_module,
            show_header=False,
        )

    with advanced_tab:
        st_module.caption(ui_text(f"可编辑数据文件：`{editable_data_file}`", f"Editable data file: `{editable_data_file}`"))
        st_module.caption(ui_text(f"市场事件文件：`{market_events_file}`", f"Market events file: `{market_events_file}`"))
        st_module.caption(ui_text(f"事件源配置：`{event_sources_config_path}`", f"Event source config: `{event_sources_config_path}`"))
        st_module.caption(ui_text(f"分析师共识缓存：`{analyst_consensus_cache_file}`", f"Analyst-consensus cache: `{analyst_consensus_cache_file}`"))
        if market_events_bootstrapped:
            st_module.success(ui_text("市场事件样例文件已就绪。", "The market-events bootstrap file is ready."))


def render_dashboard_page(
    *,
    ui_text,
    latest_trade_plan,
    latest_post_close_review,
    trade_plan_banner=None,
    latest_change_feed,
    change_feed_narration=None,
    change_feed_explanation=None,
    narrate_change_feed_fn=None,
    explain_change_feed_fn=None,
    latest_nightly_manifest,
    account_snapshot,
    data_source_status,
    refresh_runtime_status,
    ui_performance_snapshot,
    allocation_regime_decision,
    discipline_snapshot,
    monthly_discipline_review,
    strategy_validation_snapshot,
    live_scoreboard,
    market_risk_gate_decision,
    market_risk_snapshot,
    analysis_freshness_alert,
    active_market_events,
    event_risk_decision,
    event_source_reports,
    news_summary_narration=None,
    narrate_news_summary_fn=None,
    intraday_event_summary,
    intraday_tactical_snapshot,
    L,
    core_etf_snapshot,
    satellite_candidate_snapshot,
    st_module=None,
    lang="zh",
):
    st_module = st_module or st
    trade_plan_banner = dict(trade_plan_banner or {})
    trade_plan_level = str(trade_plan_banner.get("level", "info") or "info").lower()
    trade_plan_message = str(trade_plan_banner.get("message", "") or "").strip()
    if trade_plan_message:
        if trade_plan_level == "success":
            st_module.success(trade_plan_message)
        elif trade_plan_level == "warning":
            st_module.warning(trade_plan_message)
        elif trade_plan_level == "error":
            st_module.error(trade_plan_message)
        else:
            st_module.info(trade_plan_message)

    render_shell_header(
        latest_trade_plan=latest_trade_plan,
        latest_nightly_manifest=latest_nightly_manifest,
        change_feed=latest_change_feed,
        discipline_snapshot=discipline_snapshot,
        monthly_discipline_review=monthly_discipline_review,
        strategy_validation_snapshot=strategy_validation_snapshot,
        data_source_status=data_source_status,
        refresh_runtime_status=refresh_runtime_status,
        ui_text=ui_text,
        st_module=st_module,
    )
    up.render_change_feed_priority_banner(latest_change_feed, st_module=st_module)
    up.render_analysis_freshness_banner(
        analysis_freshness_alert,
        ui_text=ui_text,
        st_module=st_module,
    )
    if latest_nightly_manifest and str(latest_nightly_manifest.get("status") or "").strip().lower() != "completed":
        up.render_nightly_manifest_panel(latest_nightly_manifest, ui_text=ui_text, st_module=st_module)

    top_left, top_right = st_module.columns((1.15, 1.0))
    with top_left:
        up.render_account_snapshot_panel(account_snapshot, ui_text=ui_text, st_module=st_module)
    with top_right:
        up.render_allocation_regime_panel(allocation_regime_decision, ui_text=ui_text, st_module=st_module)
        up.render_discipline_snapshot_panel(discipline_snapshot, ui_text=ui_text, st_module=st_module)

    if market_risk_gate_decision is not None and market_risk_snapshot is not None:
        up.render_market_risk_gate_banner(market_risk_gate_decision, market_risk_snapshot, L, st_module=st_module)

    bottom_left, bottom_right = st_module.columns((1.0, 1.0))
    with bottom_left:
        up.render_data_source_status_panel(data_source_status, ui_text=ui_text, st_module=st_module)
    with bottom_right:
        up.render_refresh_runtime_panel(refresh_runtime_status, ui_text=ui_text, st_module=st_module)
    up.render_intraday_tactical_panel(intraday_tactical_snapshot, ui_text=ui_text, st_module=st_module)

    st_module.subheader(ui_text("今日动作板", "Today Action Board"))
    action_col1, action_col2 = st_module.columns(2)
    with action_col1:
        with _card_container(st_module):
            st_module.markdown(f"**{ui_text('次日交易计划', 'Next-Day Trade Plan')}**")
            if latest_trade_plan:
                st_module.caption(str(latest_trade_plan.get("summary_reason") or "").strip() or "—")
                trade_plan_records = ui.build_trade_plan_records(latest_trade_plan)
                if trade_plan_records:
                    up.render_compact_table(pd.DataFrame(trade_plan_records), st_module=st_module)
                else:
                    st_module.info(ui_text("当前没有需要执行的计划单。", "There are no actionable items for the next session."))
            else:
                st_module.info(ui_text("尚未生成次日交易计划。", "No next-day plan is available yet."))
    with action_col2:
        with _card_container(st_module):
            st_module.markdown(f"**{ui_text('收盘执行复盘', 'Post-Close Review')}**")
            if latest_post_close_review:
                st_module.caption(
                    ui_text(
                        f"执行 {int(float(latest_post_close_review.get('executed_count') or 0.0) or 0)} | "
                        f"触达未做 {int(float(latest_post_close_review.get('missed_reachable_count') or 0.0) or 0)} | "
                        f"价位失效 {int(float(latest_post_close_review.get('price_failure_count') or 0.0) or 0)}",
                        f"Executed {int(float(latest_post_close_review.get('executed_count') or 0.0) or 0)} | "
                        f"Missed but reachable {int(float(latest_post_close_review.get('missed_reachable_count') or 0.0) or 0)} | "
                        f"Price failures {int(float(latest_post_close_review.get('price_failure_count') or 0.0) or 0)}",
                    )
                )
                review_records = ui.build_execution_review_records(latest_post_close_review)
                if review_records:
                    up.render_compact_table(pd.DataFrame(review_records), st_module=st_module)
                else:
                    st_module.info(ui_text("最近一个交易日没有可复盘的执行记录。", "The latest session has no matched execution review records."))
            else:
                st_module.info(ui_text("尚未生成收盘复盘。", "No post-close review is available yet."))

    st_module.subheader(ui_text("核心仓与卫星仓焦点", "Core & Satellite Focus"))
    focus_col1, focus_col2 = st_module.columns(2)
    with focus_col1:
        render_core_etf_cards(core_etf_snapshot, ui_text=ui_text, st_module=st_module)
    with focus_col2:
        render_satellite_top_cards(satellite_candidate_snapshot, ui_text=ui_text, st_module=st_module)

    up.render_strategy_validation_panel(
        strategy_validation_snapshot,
        ui_text=ui_text,
        st_module=st_module,
    )

    if active_market_events:
        up.render_active_events_panel(
            active_market_events,
            event_risk_decision,
            event_source_reports,
            L,
            lang=lang,
            st_module=st_module,
            news_summary_narration=news_summary_narration,
            narrate_news_summary_fn=narrate_news_summary_fn,
        )

    with st_module.expander(ui_text("更多变化与盘中提醒", "More changes & intraday watch"), expanded=False):
        up.render_change_feed_panel(
            latest_change_feed,
            change_feed_narration=change_feed_narration,
            change_feed_explanation=change_feed_explanation,
            narrate_change_feed_fn=narrate_change_feed_fn,
            explain_change_feed_fn=explain_change_feed_fn,
            key_prefix="dashboard_change_feed",
            ui_text=ui_text,
            st_module=st_module,
        )
        up.render_intraday_event_panel(intraday_event_summary, ui_text=ui_text, st_module=st_module)
        up.render_signal_scoreboard_panel(live_scoreboard, ui_text=ui_text, st_module=st_module)
        up.render_ui_performance_panel(ui_performance_snapshot, ui_text=ui_text, st_module=st_module)

def render_core_etfs_page(
    *,
    core_etf_snapshot,
    core_holdings_df,
    llm_explanations=None,
    explain_core_etf_fn=None,
    ui_text,
    st_module=None,
):
    st_module = st_module or st
    summary = dict((core_etf_snapshot or {}).get("summary", {}) or {})
    top_cols = st_module.columns(2)
    bottom_cols = st_module.columns(2)
    top_cols[0].metric(ui_text("候选数", "Universe"), f"{int(summary.get('total_symbols', 0) or 0)}")
    top_cols[1].metric(ui_text("可增配", "Accumulate"), f"{int(summary.get('accumulate_count', 0) or 0)}")
    bottom_cols[0].metric(ui_text("需减配", "Trim"), f"{int(summary.get('trim_count', 0) or 0)}")
    bottom_cols[1].metric(ui_text("暂停追价", "Pause Buy"), f"{int(summary.get('pause_buy_count', 0) or 0)}")

    render_core_etf_cards(
        core_etf_snapshot,
        ui_text=ui_text,
        st_module=st_module,
        enable_llm_explanations=True,
        llm_explanations=llm_explanations,
        explain_core_etf_fn=explain_core_etf_fn,
        button_namespace="core_page",
    )

    st_module.subheader(ui_text("当前核心 ETF 持仓", "Current Core ETF Holdings"))
    st_module.caption(
        ui_text(
            "点单个 ETF 的“LLM 解释”可看更深说明。",
            "Click “LLM Explain” on an ETF for deeper context.",
        )
    )
    st_module.caption(
        ui_text(
            "ETF 池和轮动阈值统一在 Settings → ETF / 候选池。",
            "ETF universe and rotation thresholds live in Settings → Universe & Strategy.",
        )
    )
    if core_holdings_df is not None and not core_holdings_df.empty:
        up.render_compact_table(core_holdings_df, st_module=st_module)
    else:
        st_module.info(ui_text("当前没有核心 ETF 持仓。", "There are no current core ETF holdings."))


def render_satellite_radar_page(
    *,
    satellite_candidate_snapshot,
    satellite_holdings_df,
    ui_text,
    discipline_snapshot=None,
    latest_change_feed=None,
    llm_explanations=None,
    explain_satellite_fn=None,
    active_market_events,
    event_risk_decision,
    event_source_reports,
    news_summary_narration=None,
    narrate_news_summary_fn=None,
    L,
    st_module=None,
    lang="zh",
):
    st_module = st_module or st
    summary = dict((satellite_candidate_snapshot or {}).get("summary", {}) or {})
    top_cols = st_module.columns(2)
    bottom_cols = st_module.columns(2)
    top_cols[0].metric(ui_text("扫描数", "Scanned"), f"{int(summary.get('scanned_symbols', 0) or 0)}")
    top_cols[1].metric(ui_text("候选池", "Pool Size"), f"{int(summary.get('candidate_count', 0) or 0)}")
    bottom_cols[0].metric(ui_text("深度分析", "Deep Analysis"), f"{int(summary.get('deep_analysis_count', 0) or 0)}")
    bottom_cols[1].metric(ui_text("Top 推荐", "Top Picks"), f"{int(summary.get('recommendation_count', 0) or 0)}")

    st_module.subheader(ui_text("当前卫星仓", "Current Satellite Positions"))
    if satellite_holdings_df is not None and not satellite_holdings_df.empty:
        up.render_compact_table(satellite_holdings_df, st_module=st_module)
    else:
        st_module.info(ui_text("当前没有卫星仓持仓。", "There are no satellite holdings right now."))

    st_module.subheader(ui_text("Top 3 推荐", "Top 3 Recommendations"))
    render_satellite_top_cards(
        satellite_candidate_snapshot,
        ui_text=ui_text,
        st_module=st_module,
        enable_llm_explanations=True,
        llm_explanations=llm_explanations,
        explain_satellite_fn=explain_satellite_fn,
        button_namespace="satellite_page",
    )

    st_module.subheader(ui_text("候选池 Top 10", "Candidate Pool Top 10"))
    top10_df = pg.build_satellite_candidate_dataframe(satellite_candidate_snapshot, limit=10)
    if not top10_df.empty:
        up.render_compact_table(top10_df, st_module=st_module)
    else:
        st_module.info(ui_text("当前没有候选池快照。", "No satellite candidate snapshot is available yet."))
    st_module.caption(
        ui_text(
            "候选池来源、容量和 Top 3 规则统一在 Settings → ETF / 候选池。",
            "Pool sources, size, and Top 3 rules live in Settings → Universe & Strategy.",
        )
    )

    if active_market_events:
        up.render_active_events_panel(
            active_market_events,
            event_risk_decision,
            event_source_reports,
            L,
            lang=lang,
            st_module=st_module,
            news_summary_narration=news_summary_narration,
            narrate_news_summary_fn=narrate_news_summary_fn,
        )


def render_risk_page(
    *,
    ui_text,
    discipline_snapshot,
    monthly_discipline_review,
    discipline_review_narration=None,
    discipline_review_explanation=None,
    narrate_discipline_review_fn=None,
    explain_discipline_review_fn=None,
    market_risk_gate_decision,
    market_risk_snapshot,
    analysis_freshness_alert,
    account_snapshot,
    data_source_status,
    live_scoreboard,
    latest_change_feed,
    change_feed_narration=None,
    change_feed_explanation=None,
    narrate_change_feed_fn=None,
    explain_change_feed_fn=None,
    latest_post_close_review,
    snapshot_journal,
    intraday_event_summary,
    intraday_tactical_snapshot,
    L,
    st_module=None,
):
    st_module = st_module or st
    up.render_discipline_snapshot_panel(discipline_snapshot, ui_text=ui_text, st_module=st_module)
    if market_risk_gate_decision is not None and market_risk_snapshot is not None:
        up.render_market_risk_gate_banner(market_risk_gate_decision, market_risk_snapshot, L, st_module=st_module)
    up.render_analysis_freshness_banner(analysis_freshness_alert, ui_text=ui_text, st_module=st_module)
    up.render_signal_scoreboard_panel(live_scoreboard, ui_text=ui_text, st_module=st_module)

    c1, c2 = st_module.columns(2)
    with c1:
        st_module.subheader(ui_text("纪律约束清单", "Discipline Constraints"))
        st_module.dataframe(pg.build_discipline_constraints_dataframe(discipline_snapshot), hide_index=True, width="stretch")
    with c2:
        st_module.subheader(ui_text("最近关键变化", "Recent Critical Changes"))
        up.render_change_feed_panel(
            latest_change_feed,
            change_feed_narration=change_feed_narration,
            change_feed_explanation=change_feed_explanation,
            narrate_change_feed_fn=narrate_change_feed_fn,
            explain_change_feed_fn=explain_change_feed_fn,
            key_prefix="risk_change_feed",
            ui_text=ui_text,
            st_module=st_module,
        )

    st_module.subheader(ui_text("账户与数据状态", "Account & Data State"))
    s1, s2 = st_module.columns(2)
    with s1:
        up.render_account_snapshot_panel(account_snapshot, ui_text=ui_text, st_module=st_module)
    with s2:
        up.render_data_source_status_panel(data_source_status, ui_text=ui_text, st_module=st_module)
    up.render_intraday_tactical_panel(intraday_tactical_snapshot, ui_text=ui_text, st_module=st_module)
    up.render_monthly_discipline_review_panel(
        discipline_snapshot=discipline_snapshot,
        scoreboard=live_scoreboard,
        latest_post_close_review=latest_post_close_review,
        review=monthly_discipline_review,
        review_narration=discipline_review_narration,
        review_explanation=discipline_review_explanation,
        narrate_review_fn=narrate_discipline_review_fn,
        explain_review_fn=explain_discipline_review_fn,
        key_prefix="risk_discipline_review",
        snapshot_journal=snapshot_journal,
        ui_text=ui_text,
        st_module=st_module,
    )
    up.render_intraday_event_panel(intraday_event_summary, ui_text=ui_text, st_module=st_module)
