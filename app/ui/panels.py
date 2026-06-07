import pandas as pd
import streamlit as st

from quant_core.events import news_summary as ns
from quant_core.notifications import change_feed as cfeed
from quant_core.portfolio import discipline as qdisc


def render_compact_table(dataframe, *, st_module=None):
    st_module = st_module or st
    if dataframe is None:
        return
    if not isinstance(dataframe, pd.DataFrame):
        dataframe = pd.DataFrame(dataframe)
    if dataframe.empty:
        return
    if not hasattr(st_module, "table"):
        st_module.dataframe(dataframe, hide_index=True, width="stretch")
        return
    try:
        st_module.table(dataframe.style.hide(axis="index"))
    except Exception:
        fallback_df = dataframe.copy()
        fallback_df.index = [""] * len(fallback_df)
        st_module.table(fallback_df)


def _collapsed_expander(st_module, label):
    try:
        return st_module.expander(label, expanded=False)
    except TypeError:
        return st_module.expander(label)


def render_account_snapshot_panel(account_snapshot, *, ui_text, st_module=None):
    st_module = st_module or st
    total_capital = account_snapshot.get("total_capital")
    cash_available = account_snapshot.get("cash_available")
    deployable_cash = float(account_snapshot.get("deployable_cash") or 0.0)
    exposure_pct = float(account_snapshot.get("exposure_pct") or 0.0)

    st_module.subheader(ui_text("账户概览", "Account Overview"))
    if total_capital is None:
        st_module.info(
            ui_text(
                "尚未配置可用现金且暂无持仓市值，系统还无法给出完整的资金分配建议。",
                "Cash available is not configured and holdings have no market value yet, so full allocation guidance is not available.",
            )
        )
        return

    top_cols = st_module.columns(2)
    bottom_cols = st_module.columns(2)
    top_cols[0].metric(ui_text("总资产", "Total Capital"), f"${float(total_capital):,.2f}")
    top_cols[1].metric(
        ui_text("现金", "Cash Available"),
        "—" if cash_available is None else f"${float(cash_available):,.2f}",
    )
    bottom_cols[0].metric(ui_text("可部署", "Deployable Cash"), f"${deployable_cash:,.2f}")
    bottom_cols[1].metric(ui_text("暴露", "Current Exposure"), f"{exposure_pct:.1f}%")
    st_module.caption(
        ui_text(
            "现金缓冲 "
            f"${float(account_snapshot.get('cash_buffer_dollars') or 0.0):,.2f} | "
            f"单票上限 {float(account_snapshot.get('max_single_position_pct') or 0.0):.1f}% | "
            f"总暴露上限 {float(account_snapshot.get('max_total_exposure_pct') or 0.0):.1f}%",
            "Cash buffer "
            f"${float(account_snapshot.get('cash_buffer_dollars') or 0.0):,.2f} | "
            f"Single-position cap {float(account_snapshot.get('max_single_position_pct') or 0.0):.1f}% | "
            f"Total exposure cap {float(account_snapshot.get('max_total_exposure_pct') or 0.0):.1f}%",
        )
    )


def render_data_source_status_panel(data_source_status, *, ui_text, st_module=None):
    st_module = st_module or st
    st_module.subheader(ui_text("数据源", "Data Sources"))
    if not data_source_status:
        st_module.info(ui_text("暂无数据源状态。", "Data source status is not available yet."))
        return

    history = dict(data_source_status.get("history", {}) or {})
    prices = dict(data_source_status.get("prices", {}) or {})

    def _friendly_source_name(source_value):
        source = str(source_value or "").strip().lower()
        if source == "yfinance":
            return "Yahoo"
        if source == "stooq":
            return "Stooq"
        if not source:
            return ui_text("未知", "Unknown")
        return source

    def _source_label(source_value, *, primary_source=None):
        source = str(source_value or "").strip().lower()
        primary = str(primary_source or "").strip().lower()
        friendly = _friendly_source_name(source_value)
        if not source:
            return ui_text("暂无请求", "No requests yet")
        if primary and source == primary:
            return ui_text(f"主源 {friendly}", f"Primary {friendly}")
        if primary:
            return ui_text(f"备用源 {friendly}", f"Fallback {friendly}")
        return friendly

    history_primary = str(history.get("primary_source") or "yfinance").strip().lower()
    price_primary = str(prices.get("primary_source") or "").strip().lower()
    history_source = _source_label(history.get("last_source"), primary_source=history_primary)
    price_source = _source_label(prices.get("last_source"), primary_source=price_primary)
    history_fallbacks = int(history.get("fallback_requests") or 0)
    price_fallbacks = int(prices.get("fallback_symbols") or 0)

    top_cols = st_module.columns(2)
    bottom_cols = st_module.columns(2)
    top_cols[0].metric(ui_text("历史源", "History Source"), history_source)
    top_cols[1].metric(ui_text("历史回退", "History Fallbacks"), f"{history_fallbacks}")
    bottom_cols[0].metric(ui_text("现价源", "Price Source"), price_source)
    bottom_cols[1].metric(ui_text("现价回退", "Price Fallbacks"), f"{price_fallbacks}")

    history_error = str(history.get("last_error") or "").strip()
    prices_error = str(prices.get("last_error") or "").strip()
    history_symbol = str(history.get("last_symbol") or "").strip()
    price_symbols = list(prices.get("last_symbols", []) or [])

    details = []
    if history_symbol:
        details.append(
            ui_text(
                f"最近历史请求: {history_symbol} -> {history_source}",
                f"Latest history request: {history_symbol} -> {history_source}",
            )
        )
    if price_symbols:
        details.append(
            ui_text(
                f"最近现价请求: {', '.join(price_symbols[:5])} -> {price_source}",
                f"Latest price request: {', '.join(price_symbols[:5])} -> {price_source}",
            )
        )

    fallback_used = history_fallbacks > 0 or price_fallbacks > 0
    if not fallback_used and price_primary and str(prices.get("last_source") or "").strip().lower() not in {"", price_primary}:
        fallback_used = True
    if not fallback_used and history_primary and str(history.get("last_source") or "").strip().lower() not in {"", history_primary}:
        fallback_used = True
    if fallback_used:
        st_module.warning(
            ui_text(
                "检测到备用源已介入，当前系统仍可运行，但价格/历史数据的时效性可能低于主源。",
                "Fallback data source is active. The system can keep running, but freshness may be lower than the primary source.",
            )
        )
    else:
        st_module.success(
            ui_text(
                "当前数据请求仍在使用主源。",
                "Current data requests are using the primary source.",
            )
        )

    if details:
        st_module.caption(" | ".join(details))
    if history_error:
        st_module.caption(ui_text(f"历史主源错误: {history_error}", f"History primary-source error: {history_error}"))
    if prices_error:
        st_module.caption(ui_text(f"现价主源错误: {prices_error}", f"Price primary-source error: {prices_error}"))


def render_refresh_runtime_panel(refresh_runtime_status, *, ui_text, st_module=None):
    st_module = st_module or st
    status = dict(refresh_runtime_status or {})
    st_module.subheader(ui_text("后台刷新", "Background Refresh"))

    run_all_mode = bool(status.get("run_all_mode"))
    price_last_updated = str(status.get("price_last_updated") or "").strip()
    event_last_updated = str(status.get("event_last_updated") or "").strip()
    price_next_due_at = str(status.get("price_next_due_at") or "").strip()
    event_next_due_at = str(status.get("event_next_due_at") or "").strip()
    price_interval_seconds = int(status.get("price_refresh_interval_seconds") or 0)
    event_interval_seconds = int(status.get("event_refresh_interval_seconds") or 0)

    cols = st_module.columns(3)
    cols[0].metric(
        ui_text("自动刷新", "Auto Refresh"),
        ui_text("开启", "ON") if run_all_mode else ui_text("未检测", "OFF"),
    )
    cols[1].metric(
        ui_text("行情刷新", "Last Price Refresh"),
        price_last_updated.replace("T", " ")[:16] if price_last_updated else "—",
    )
    cols[2].metric(
        ui_text("事件刷新", "Last Event Refresh"),
        event_last_updated.replace("T", " ")[:16] if event_last_updated else "—",
    )

    cadence_parts = []
    if price_interval_seconds > 0:
        cadence_parts.append(
            ui_text(
                f"行情刷新节奏：约每 {int(price_interval_seconds // 60)} 分钟",
                f"Price refresh cadence: about every {int(price_interval_seconds // 60)} min",
            )
        )
    if event_interval_seconds > 0:
        cadence_parts.append(
            ui_text(
                f"事件检查节奏：约每 {int(event_interval_seconds // 60)} 分钟",
                f"Event refresh cadence: about every {int(event_interval_seconds // 60)} min",
            )
        )
    if cadence_parts:
        st_module.caption(" | ".join(cadence_parts))

    next_parts = []
    if price_next_due_at:
        next_parts.append(
            ui_text(
                f"下一次行情刷新不早于：{price_next_due_at.replace('T', ' ')[:16]}",
                f"Next price refresh no earlier than: {price_next_due_at.replace('T', ' ')[:16]}",
            )
        )
    if event_next_due_at:
        next_parts.append(
            ui_text(
                f"下一次事件检查不早于：{event_next_due_at.replace('T', ' ')[:16]}",
                f"Next event check no earlier than: {event_next_due_at.replace('T', ' ')[:16]}",
            )
        )
    if next_parts:
        st_module.caption(" | ".join(next_parts))

    if run_all_mode:
        st_module.success(
            ui_text(
                "当前由 jobs.run_all 后台线程负责自动刷新；首页优先显示最近一致快照，后台随后补最新数据。",
                "Background threads from jobs.run_all are active; the UI shows the latest consistent snapshot first, then refreshes in the background.",
            )
        )
    else:
        st_module.info(
            ui_text(
                "当前未检测到 run_all 后台模式；若需要自动刷新，请使用 jobs.run_all 启动整套系统。",
                "run_all background mode was not detected; use jobs.run_all if you want the full auto-refresh supervisor.",
            )
        )


def render_ui_performance_panel(performance_snapshot, *, ui_text, st_module=None):
    st_module = st_module or st
    perf = dict(performance_snapshot or {})
    last = dict(perf.get("last", {}) or {})
    if not perf or not last:
        st_module.info(ui_text("暂无页面性能数据。", "No page-performance data is available yet."))
        return

    st_module.subheader(ui_text("页面性能打点", "Page Performance"))
    cols = st_module.columns(4)
    cols[0].metric(ui_text("最近页面", "Last Page"), str(last.get("page") or "—"))
    cols[1].metric(ui_text("最近总耗时", "Last Total"), f"{float(last.get('total_ms') or 0.0):.0f} ms")
    cols[2].metric(ui_text("最近上下文", "Last Context"), f"{float(last.get('context_ms') or 0.0):.0f} ms")
    cols[3].metric(ui_text("最近渲染", "Last Render"), f"{float(last.get('page_render_ms') or 0.0):.0f} ms")

    average_total = perf.get("avg_total_ms_last_10")
    average_context = perf.get("avg_context_ms_last_10")
    average_page_render = perf.get("avg_render_ms_current_page")
    samples = int(perf.get("samples") or 0)
    st_module.caption(
        ui_text(
            f"最近 {samples} 次平均：总耗时 {average_total:.0f} ms | 上下文 {average_context:.0f} ms | 当前页渲染 {average_page_render:.0f} ms"
            if average_total is not None and average_context is not None and average_page_render is not None
            else f"最近 {samples} 次平均数据仍在积累中。",
            f"Last {samples} samples: total {average_total:.0f} ms | context {average_context:.0f} ms | current-page render {average_page_render:.0f} ms"
            if average_total is not None and average_context is not None and average_page_render is not None
            else f"Performance averages are still warming up over the last {samples} samples.",
        )
    )


def render_strategy_validation_panel(snapshot, *, journal_rows=None, ui_text, st_module=None):
    st_module = st_module or st
    snapshot = dict(snapshot or {})
    summary = dict(snapshot.get("summary", {}) or {})
    if not snapshot or not summary:
        st_module.info(ui_text("尚未生成策略验证快照。", "No strategy-validation snapshot is available yet."))
        return

    st_module.subheader(ui_text("策略验证", "Strategy Validation"))
    cols = st_module.columns(4)
    cols[0].metric(ui_text("状态", "Status"), str(summary.get("status") or "—"))
    cols[1].metric(ui_text("覆盖", "Coverage"), f"{int(summary.get('symbol_count', 0) or 0)}")
    cols[2].metric(ui_text("通过", "Validated"), f"{int(summary.get('validated_count', 0) or 0)}")
    cols[3].metric(ui_text("预警", "Warnings"), f"{len(list(summary.get('warning_symbols', []) or []))}")

    message = str(summary.get("message") or "").strip()
    status = str(summary.get("status") or "").strip().upper()
    if message:
        if status == "READY":
            st_module.success(message)
        elif status == "CAUTION":
            st_module.warning(message)
        else:
            st_module.info(message)

    rows = []
    for row in list(snapshot.get("symbols", []) or [])[:8]:
        rows.append(
            {
                ui_text("代码", "Symbol"): str(row.get("symbol") or "—"),
                ui_text("角色", "Role"): ui_text("核心", "Core")
                if str(row.get("focus_role") or "").strip().lower() == "core"
                else ui_text("卫星", "Satellite"),
                ui_text("状态", "Status"): str(row.get("status") or "—"),
                ui_text("默认名次", "Default Rank"): "—"
                if row.get("default_rank") is None
                else int(row.get("default_rank") or 0),
                ui_text("领先策略", "Best Strategy"): str(row.get("best_strategy_name") or "—"),
                ui_text("分差", "Gap"): "—"
                if row.get("score_gap_vs_best") is None
                else f"{float(row.get('score_gap_vs_best') or 0.0):+.2f}",
                ui_text("样本", "Trades"): int(row.get("completed_trades") or 0),
            }
        )
    if rows:
        render_compact_table(pd.DataFrame(rows), st_module=st_module)

    avg_rank = summary.get("avg_default_rank")
    avg_gap = summary.get("avg_score_gap")
    footer_bits = []
    if avg_rank is not None:
        footer_bits.append(ui_text(f"平均默认名次 {float(avg_rank):.2f}", f"Average default rank {float(avg_rank):.2f}"))
    if avg_gap is not None:
        footer_bits.append(ui_text(f"平均分差 {float(avg_gap):+.2f}", f"Average score gap {float(avg_gap):+.2f}"))
    if footer_bits:
        st_module.caption(" | ".join(footer_bits))

    journal_rows = list(journal_rows or [])
    if journal_rows:
        with _collapsed_expander(st_module, ui_text("最近研究轨迹", "Recent Research Trail")):
            compact_rows = []
            for row in journal_rows[-5:][::-1]:
                compact_rows.append(
                    {
                        ui_text("时间", "Time"): str(row.get("generated_at") or "").replace("T", " ")[:16] or "—",
                        ui_text("状态", "Status"): str(row.get("status") or "—"),
                        ui_text("覆盖", "Coverage"): int(row.get("symbol_count") or 0),
                        ui_text("通过", "Validated"): int(row.get("validated_count") or 0),
                        ui_text("预警", "Warnings"): len(list(row.get("warning_symbols", []) or [])),
                    }
                )
            render_compact_table(pd.DataFrame(compact_rows), st_module=st_module)


def render_market_risk_gate_banner(decision, snapshot, L, *, st_module=None):
    st_module = st_module or st
    if decision is None or snapshot is None:
        st_module.info(L("market_risk_gate_unavailable"))
        return

    metrics = [
        f"{L('risk_score')}: {decision.risk_score}",
        f"{L('max_position_weight')}: {decision.max_position_weight * 100:.1f}%",
    ]
    if snapshot.vix is not None:
        metrics.append(f"VIX: {snapshot.vix:.1f}")
    if snapshot.benchmark_drawdown is not None:
        metrics.append(f"SPY DD: {snapshot.benchmark_drawdown:.1%}")
    if snapshot.benchmark_volatility is not None:
        metrics.append(f"SPY Vol: {snapshot.benchmark_volatility:.1%}")

    risk_regime_map = {
        "NORMAL": L("risk_regime_normal"),
        "CAUTION": L("risk_regime_caution"),
        "RISK_OFF": L("risk_regime_off"),
    }
    regime_label = risk_regime_map.get(decision.regime, decision.regime)
    message = f"{L('market_risk_gate')}: {regime_label} | {' | '.join(metrics)}"
    if decision.reasons:
        message = f"{message}\n{L('risk_factors')}: {' '.join(decision.reasons)}"

    if decision.regime == "RISK_OFF":
        st_module.error(message)
    elif decision.regime == "CAUTION":
        st_module.warning(message)
    else:
        st_module.success(message)


def render_analysis_freshness_banner(alert, *, ui_text, st_module=None):
    st_module = st_module or st
    if not alert or not bool(alert.get("needs_warning")):
        return

    expired_symbols = list(alert.get("expired_symbols", []) or [])
    missing_symbols = list(alert.get("missing_symbols", []) or [])

    fragments = []
    if expired_symbols:
        fragments.append(
            ui_text(
                f"以下持仓的全量分析已过期：{', '.join(expired_symbols[:6])}",
                f"Full analysis is expired for: {', '.join(expired_symbols[:6])}",
            )
        )
    if missing_symbols:
        fragments.append(
            ui_text(
                f"以下持仓尚未生成全量分析：{', '.join(missing_symbols[:6])}",
                f"Full analysis is missing for: {', '.join(missing_symbols[:6])}",
            )
        )

    guidance = ui_text(
        "建议先重跑全量分析，再参考仓位建议和退出参考。",
        "Run a fresh full analysis before relying on position sizing or exit guidance.",
    )
    st_module.warning(" | ".join(fragments + [guidance]))


def render_signal_scoreboard_panel(scoreboard, *, ui_text, st_module=None):
    st_module = st_module or st
    if scoreboard is None:
        st_module.info(ui_text("暂无信号评分数据。", "Signal scoreboard is not available yet."))
        return

    st_module.subheader(ui_text("信号评分看板", "Signal Scoreboard"))
    row1 = st_module.columns(3)
    row2 = st_module.columns(3)
    row1[0].metric(ui_text("完成交易", "Closed Trades"), f"{int(getattr(scoreboard, 'completed_trades', 0) or 0)}")
    win_rate = getattr(scoreboard, "win_rate", None)
    expectancy = getattr(scoreboard, "expectancy_return_pct", None)
    payoff = getattr(scoreboard, "payoff_ratio", None)
    profit_factor = getattr(scoreboard, "profit_factor", None)
    max_dd = getattr(scoreboard, "max_drawdown_pct", None)
    row1[1].metric(ui_text("胜率", "Signal Win Rate"), f"{float(win_rate):.2%}" if win_rate is not None else "—")
    row1[2].metric(ui_text("期望", "Expectancy/Trade"), f"{float(expectancy):.2%}" if expectancy is not None else "—")
    row2[0].metric(ui_text("盈亏比", "Payoff Ratio"), f"{float(payoff):.2f}" if payoff is not None else "—")
    row2[1].metric(ui_text("利润因子", "Profit Factor"), f"{float(profit_factor):.2f}" if profit_factor is not None else "—")
    row2[2].metric(ui_text("回撤", "Max Drawdown"), f"{float(max_dd):.2%}" if max_dd is not None else "—")

    regime_breakdown = list(getattr(scoreboard, "regime_breakdown", []) or [])
    if regime_breakdown:
        regime_df = pd.DataFrame(
            [
                {
                    ui_text("波动状态", "Volatility Regime"): item.regime,
                    ui_text("交易数", "Trades"): item.trades,
                    ui_text("胜率", "Win Rate"): f"{item.win_rate:.2%}" if item.win_rate is not None else "—",
                    ui_text("平均收益", "Avg Return"): f"{item.avg_return_pct:.2%}" if item.avg_return_pct is not None else "—",
                }
                for item in regime_breakdown
            ]
        )
        st_module.dataframe(regime_df, hide_index=True, width="stretch")


def render_allocation_regime_panel(decision, *, ui_text, st_module=None):
    st_module = st_module or st
    if decision is None:
        return

    regime = str(getattr(decision, "regime", "NORMAL") or "NORMAL").upper()
    multiplier = float(getattr(decision, "risk_multiplier", 1.0) or 1.0)
    min_exp = float(getattr(decision, "target_exposure_min_pct", 0.0) or 0.0)
    max_exp = float(getattr(decision, "target_exposure_max_pct", 100.0) or 100.0)
    reasons = list(getattr(decision, "reasons", []) or [])

    header = (
        f"{ui_text('仓位节奏', 'Allocation Regime')}: {regime} | "
        f"{ui_text('风险倍数', 'Risk Multiplier')}: x{multiplier:.2f} | "
        f"{ui_text('目标暴露', 'Target Exposure')}: {min_exp:.0f}% ~ {max_exp:.0f}%"
    )
    details = " ".join(reasons) if reasons else ui_text("暂无补充说明。", "No extra rationale.")

    if regime == "STOP":
        st_module.error(f"{header}\n{details}")
    elif regime == "LIGHT":
        st_module.warning(f"{header}\n{details}")
    elif regime == "HEAVY":
        st_module.success(f"{header}\n{details}")
    else:
        st_module.info(f"{header}\n{details}")


def render_discipline_snapshot_panel(snapshot, *, ui_text, st_module=None):
    st_module = st_module or st
    snapshot = dict(snapshot or {})
    if not snapshot:
        st_module.info(ui_text("暂无纪律层快照。", "Discipline snapshot is not available yet."))
        return

    st_module.subheader(ui_text("纪律总控", "Discipline"))
    top_cols = st_module.columns(2)
    bottom_cols = st_module.columns(2)
    top_cols[0].metric(ui_text("纪律", "Discipline"), snapshot.get("regime", "UNKNOWN"))
    top_cols[1].metric(ui_text("风险", "Risk Regime"), snapshot.get("risk_regime", "UNKNOWN"))
    bottom_cols[0].metric(
        ui_text("核心新仓", "Core New"),
        ui_text("是", "Yes") if snapshot.get("can_open_new_core_positions") else ui_text("否", "No"),
    )
    bottom_cols[1].metric(
        ui_text("卫星新仓", "Satellite New"),
        ui_text("是", "Yes") if snapshot.get("can_open_new_satellite_positions") else ui_text("否", "No"),
    )

    summary = str(snapshot.get("summary") or "").strip()
    if summary:
        regime = str(snapshot.get("regime") or "").upper()
        if regime == "STOP":
            st_module.error(summary)
        elif regime == "LIGHT":
            st_module.warning(summary)
        elif regime == "HEAVY":
            st_module.success(summary)
        else:
            st_module.info(summary)

    warnings = list(snapshot.get("warnings", []) or [])
    reasons = list(snapshot.get("reasons", []) or [])
    if warnings:
        st_module.warning(" | ".join(warnings[:3]))
    if reasons:
        st_module.caption(" | ".join(reasons[:3]))


def render_monthly_discipline_review_panel(
    *,
    discipline_snapshot,
    scoreboard,
    latest_post_close_review=None,
    review=None,
    review_narration=None,
    review_explanation=None,
    narrate_review_fn=None,
    explain_review_fn=None,
    key_prefix="discipline_review",
    ui_text,
    st_module=None,
    snapshot_journal=None,
    now=None,
):
    st_module = st_module or st
    review = dict(review or {})
    if not review:
        review = qdisc.build_monthly_discipline_review(
            discipline_snapshot=discipline_snapshot,
            scoreboard=scoreboard,
            latest_post_close_review=latest_post_close_review,
            snapshot_journal=snapshot_journal,
            now=now,
        )

    st_module.subheader(ui_text("纪律层月度自评", "Monthly Discipline Review"))
    top_cols = st_module.columns(2)
    bottom_cols = st_module.columns(2)
    top_cols[0].metric(ui_text("复盘月份", "Review Month"), review["month"])
    top_cols[1].metric(ui_text("FOLLOW / IGNORE", "FOLLOW / IGNORE"), f"{review['follow_days']} / {review['ignore_days']}")
    bottom_cols[0].metric(ui_text("FOLLOW 盈亏", "FOLLOW P/L"), f"${float(review['follow_realized_pl']):+,.2f}")
    bottom_cols[1].metric(ui_text("纪律状态", "Discipline Check"), review["status"])

    if review["status"] == "ALIGNED":
        st_module.success(review["summary"])
    elif review["status"] == "CAUTION":
        st_module.warning(review["summary"])
    else:
        st_module.info(review["summary"])

    if review["notes"]:
        st_module.caption(" | ".join(review["notes"][:3]))
    show_actions = callable(narrate_review_fn) or callable(explain_review_fn)
    if show_actions:
        action_cols = st_module.columns(2)
        if callable(narrate_review_fn) and hasattr(action_cols[0], "button"):
            result = action_cols[0].button(
                ui_text("本地转述", "Local Narration"),
                key=f"{key_prefix}_narrate",
            )
            if result:
                ok, message, _meta = narrate_review_fn()
                if ok:
                    review_narration = str(message or "").strip()
                else:
                    st_module.error(message)
        if callable(explain_review_fn) and hasattr(action_cols[1], "button"):
            result = action_cols[1].button(
                ui_text("远程解释", "Remote Explanation"),
                key=f"{key_prefix}_explain",
            )
            if result:
                ok, message, _meta = explain_review_fn()
                if ok:
                    review_explanation = str(message or "").strip()
                else:
                    st_module.error(message)
    if str(review_narration or "").strip():
        st_module.info(str(review_narration or "").strip())
    if str(review_explanation or "").strip():
        st_module.caption(str(review_explanation or "").strip())
    st_module.dataframe(pd.DataFrame(review["rows"]), hide_index=True, width="stretch")


def render_change_feed_panel(
    change_feed,
    *,
    change_feed_narration=None,
    change_feed_explanation=None,
    narrate_change_feed_fn=None,
    explain_change_feed_fn=None,
    key_prefix="change_feed",
    ui_text,
    st_module=None,
):
    st_module = st_module or st
    change_feed = dict(change_feed or {})
    summary = dict(change_feed.get("summary", {}) or {})
    high_items = list(change_feed.get("high_items", []) or [])
    medium_items = list(change_feed.get("medium_items", []) or [])
    if not (high_items or medium_items):
        st_module.info(ui_text("当前没有高优先级变化。", "There are no high-priority changes right now."))
        return

    st_module.subheader(ui_text("变化总览", "Change Feed"))
    cols = st_module.columns(3)
    cols[0].metric(ui_text("高优先级", "High"), f"{int(summary.get('high_count', 0) or 0)}")
    cols[1].metric(ui_text("中优先级", "Medium"), f"{int(summary.get('medium_count', 0) or 0)}")
    cols[2].metric(ui_text("低优先级", "Low"), f"{int(summary.get('low_count', 0) or 0)}")
    show_actions = callable(narrate_change_feed_fn) or callable(explain_change_feed_fn)
    if show_actions:
        action_cols = st_module.columns(2)
        if callable(narrate_change_feed_fn) and hasattr(action_cols[0], "button"):
            result = action_cols[0].button(
                ui_text("本地转述", "Local Narration"),
                key=f"{key_prefix}_narrate",
            )
            if result:
                ok, message, _meta = narrate_change_feed_fn()
                if ok:
                    change_feed_narration = str(message or "").strip()
                else:
                    st_module.error(message)
        if callable(explain_change_feed_fn) and hasattr(action_cols[1], "button"):
            result = action_cols[1].button(
                ui_text("远程解释", "Remote Explanation"),
                key=f"{key_prefix}_explain",
            )
            if result:
                ok, message, _meta = explain_change_feed_fn()
                if ok:
                    change_feed_explanation = str(message or "").strip()
                else:
                    st_module.error(message)
    if str(change_feed_narration or "").strip():
        st_module.info(str(change_feed_narration or "").strip())
    if str(change_feed_explanation or "").strip():
        st_module.caption(str(change_feed_explanation or "").strip())

    for item in high_items[:6]:
        symbol_prefix = f"[{item.get('symbol')}] " if item.get("symbol") else ""
        st_module.warning(f"{symbol_prefix}{item.get('title', '')}: {item.get('explanation_summary') or item.get('message', '')}")
        bullets = list(item.get("explanation_bullets", []) or [])
        details = dict(item.get("details", {}) or {})
        if bullets or any(value not in (None, "", []) for value in details.values()):
            with st_module.expander(ui_text("查看变化原因", "View Change Reasons")):
                if bullets:
                    for bullet in bullets[:4]:
                        st_module.caption(f"- {bullet}")
                detail_rows = []
                if details.get("before_value") not in (None, ""):
                    detail_rows.append({ui_text("字段", "Field"): ui_text("昨日", "Yesterday"), ui_text("值", "Value"): details.get("before_value")})
                if details.get("after_value") not in (None, ""):
                    detail_rows.append({ui_text("字段", "Field"): ui_text("今日", "Today"), ui_text("值", "Value"): details.get("after_value")})
                if detail_rows:
                    render_compact_table(pd.DataFrame(detail_rows), st_module=st_module)

    if medium_items:
        with st_module.expander(ui_text("查看中优先级变化", "Show Medium-Priority Changes")):
            for item in medium_items[:12]:
                symbol_prefix = f"[{item.get('symbol')}] " if item.get("symbol") else ""
                st_module.caption(f"{symbol_prefix}{item.get('title', '')}: {item.get('explanation_summary') or item.get('message', '')}")


def render_change_feed_priority_banner(change_feed, *, st_module=None):
    st_module = st_module or st
    change_feed = dict(change_feed or {})
    high_items = cfeed.select_priority_items(change_feed, priority="HIGH", limit=2)
    if not high_items:
        return

    message = cfeed.build_priority_summary_text(change_feed, priority="HIGH", limit=2)
    categories = {str(row.get("category") or "").strip().lower() for row in high_items}
    if categories & {"discipline_month", "discipline", "risk"}:
        st_module.error(message)
    else:
        st_module.warning(message)


def render_nightly_manifest_panel(manifest, *, ui_text, st_module=None):
    st_module = st_module or st
    manifest = dict(manifest or {})
    if not manifest:
        st_module.info(ui_text("尚未生成 nightly manifest。", "No nightly manifest is available yet."))
        return

    st_module.subheader(ui_text("夜间运行状态", "Nightly Run Status"))
    cols = st_module.columns(4)
    cols[0].metric(ui_text("运行 ID", "Run ID"), str(manifest.get("run_id") or "—"))
    cols[1].metric(ui_text("状态", "Status"), str(manifest.get("status") or "unknown"))
    cols[2].metric(ui_text("步骤数", "Steps"), f"{len(dict(manifest.get('steps', {}) or {}))}")
    cols[3].metric(ui_text("恢复时间", "Resumed At"), str(manifest.get("resumed_at") or "—"))
    steps = dict(manifest.get("steps", {}) or {})
    if steps:
        rows = []
        for step_name, step in steps.items():
            rows.append(
                {
                    ui_text("步骤", "Step"): step_name,
                    ui_text("状态", "Status"): step.get("status"),
                    ui_text("是否复用", "Reused"): ui_text("是", "Yes") if step.get("reused") else ui_text("否", "No"),
                    ui_text("输出文件", "Output"): step.get("output_file") or "—",
                    ui_text("错误", "Error"): step.get("error_message") or "—",
                }
            )
        render_compact_table(pd.DataFrame(rows), st_module=st_module)


def render_intraday_event_panel(summary, *, ui_text, st_module=None):
    st_module = st_module or st
    summary = dict(summary or {})
    if not summary:
        st_module.info(ui_text("暂无盘中事件样本。", "No intraday event samples are available yet."))
        return

    st_module.subheader(ui_text("盘中事件监控", "Intraday Event Monitor"))
    cols = st_module.columns(5)
    cols[0].metric(ui_text("事件数", "Events"), f"{int(summary.get('total_count', 0) or 0)}")
    cols[1].metric(ui_text("已发送", "Alerts Sent"), f"{int(summary.get('sent_count', 0) or 0)}")
    cols[2].metric(ui_text("有利结果", "Favorable"), f"{int(summary.get('favorable_count', 0) or 0)}")
    cols[3].metric(ui_text("不利结果", "Unfavorable"), f"{int(summary.get('unfavorable_count', 0) or 0)}")
    cols[4].metric(ui_text("最新时间", "Latest"), str(summary.get("latest_timestamp") or "—").replace("T", " ")[:16])

    recent_rows = list(summary.get("recent_rows", []) or [])
    if recent_rows:
        display_rows = []
        for row in recent_rows[-6:]:
            payload = dict(row.get("payload", {}) or {})
            display_rows.append(
                {
                    ui_text("时间", "Time"): str(row.get("timestamp") or "").replace("T", " ")[:16],
                    ui_text("代码", "Symbol"): row.get("symbol") or "ALL",
                    ui_text("事件", "Event"): row.get("event_type"),
                    ui_text("结果", "Outcome"): row.get("outcome_label") or "—",
                    ui_text("说明", "Reason"): row.get("trigger_reason") or payload.get("alert_message") or "—",
                }
            )
        render_compact_table(pd.DataFrame(display_rows), st_module=st_module)


def render_intraday_tactical_panel(snapshot, *, ui_text, st_module=None):
    st_module = st_module or st
    snapshot = dict(snapshot or {})
    if not snapshot:
        st_module.info(ui_text("暂无盘中战术快照。", "No intraday tactical snapshot is available yet."))
        return

    st_module.subheader(ui_text("盘中战术层", "Intraday Tactical Overlay"))
    top_cols = st_module.columns(2)
    bottom_cols = st_module.columns(2)
    top_cols[0].metric(ui_text("状态", "State"), str(snapshot.get("state") or "UNKNOWN"))
    top_cols[1].metric(ui_text("动作", "Action"), str(snapshot.get("recommended_action") or "NONE"))
    bottom_cols[0].metric(ui_text("工具", "Tool"), str(snapshot.get("recommended_symbol") or "—"))
    suggested_weight = snapshot.get("suggested_weight_pct")
    bottom_cols[1].metric(
        ui_text("建议仓位", "Suggested Weight"),
        f"{float(suggested_weight):.1f}%" if suggested_weight is not None else "—",
    )

    message = str(snapshot.get("message") or "").strip()
    state = str(snapshot.get("state") or "").strip().upper()
    if message:
        if state in {"PANIC", "CAPITULATION"}:
            st_module.warning(message)
        elif state == "STRESS_BUILDING":
            st_module.info(message)
        else:
            st_module.caption(message)

    benchmark_rows = []
    for row in list(snapshot.get("benchmark_rows", []) or []):
        change_pct = row.get("change_pct")
        benchmark_rows.append(
            {
                ui_text("基准", "Benchmark"): row.get("symbol") or "—",
                ui_text("现价", "Live"): f"${float(row.get('current_price')):,.2f}" if row.get("current_price") is not None else "—",
                ui_text("昨收", "Prev Close"): f"${float(row.get('previous_close')):,.2f}" if row.get("previous_close") is not None else "—",
                ui_text("变动", "Move"): f"{float(change_pct):+.2%}" if change_pct is not None else "—",
            }
        )
    if benchmark_rows:
        render_compact_table(pd.DataFrame(benchmark_rows), st_module=st_module)

    bullets = [str(item).strip() for item in list(snapshot.get("explanation_bullets", []) or []) if str(item).strip()]
    if bullets:
        st_module.caption(" | ".join(bullets[:3]))


def render_active_events_panel(
    active_events,
    event_decision,
    source_reports,
    L,
    *,
    lang="zh",
    st_module=None,
    summarize_news_events=None,
    news_summary_narration=None,
    narrate_news_summary_fn=None,
):
    st_module = st_module or st
    summarize_news_events = summarize_news_events or ns.summarize_news_events
    st_module.subheader(L("event_risk_panel"))
    summary = summarize_news_events(
        active_events,
        lang="zh" if lang == "zh" else "en",
        max_headlines=3,
    )
    event_count = int(getattr(summary, "event_count", 0) or 0)
    high_severity_count = int(getattr(summary, "high_severity_count", 0) or 0)
    verified_count = int(getattr(summary, "verified_count", 0) or 0)
    dominant_sentiment = str(getattr(summary, "dominant_sentiment", "neutral") or "neutral").lower()
    top_headline_details = list(getattr(summary, "top_headline_details", []) or [])
    top_headlines = list(getattr(summary, "top_headlines", []) or [])
    theme_focuses = list(getattr(summary, "theme_focuses", []) or [])
    focus_points = [str(item).strip() for item in list(getattr(summary, "focus_points", []) or []) if str(item).strip()]
    summary_signature = ns.build_news_summary_signature(summary)
    narration = dict(news_summary_narration or {})
    narration_text = ""
    narration_label = ""
    if str(narration.get("signature") or "").strip() == summary_signature:
        narration_text = str(narration.get("text") or "").strip()
        narration_label = str(narration.get("label") or "").strip()

    st_module.markdown(f"**{L('event_news_summary_title')}**")
    if narration_text:
        st_module.info(narration_text)
        if narration_label:
            st_module.caption(narration_label)
    else:
        st_module.info(str(getattr(summary, "overview", "") or ""))

    dominant_label = {
        "negative": "偏负面" if lang == "zh" else "Negative",
        "neutral": "中性" if lang == "zh" else "Neutral",
        "positive": "偏正面" if lang == "zh" else "Positive",
    }.get(dominant_sentiment, "—")
    st_module.caption(
        " | ".join(
            [
                f"{'事件数' if lang == 'zh' else 'Events'} {event_count}",
                f"{'高强度' if lang == 'zh' else 'High Severity'} {high_severity_count}",
                f"{'已核验' if lang == 'zh' else 'Verified'} {verified_count}",
                f"{'主情绪' if lang == 'zh' else 'Tone'} {dominant_label}",
            ]
        )
    )

    if callable(narrate_news_summary_fn) and hasattr(st_module, "button"):
        if st_module.button("本地聚合" if lang == "zh" else "Local Narration", key="news_summary_narrate"):
            ok, message, _meta = narrate_news_summary_fn()
            if ok:
                narration_text = str(message or "").strip()
            else:
                st_module.error(message)

    if focus_points:
        st_module.markdown(f"**{'今日重点' if lang == 'zh' else 'Key Focus'}**")
        for idx, point in enumerate(focus_points[:3], start=1):
            st_module.caption(f"{idx}. {point}")

    if theme_focuses:
        st_module.markdown(f"**{'主题排序' if lang == 'zh' else 'Priority Themes'}**")
        for idx, item in enumerate(theme_focuses[:4], start=1):
            label = getattr(item, "label_zh", "") if lang == "zh" else getattr(item, "label_en", "")
            sentiment_text = {
                "negative": "偏负面" if lang == "zh" else "Negative",
                "neutral": "中性" if lang == "zh" else "Neutral",
                "positive": "偏正面" if lang == "zh" else "Positive",
            }.get(str(getattr(item, "dominant_sentiment", "neutral") or "neutral").lower(), "—")
            symbols = list(getattr(item, "top_symbols", []) or [])
            symbol_text = " / ".join(symbols[:3]) if symbols else ("广泛市场" if lang == "zh" else "Broad Market")
            summary_text = getattr(item, "summary_zh", "") if lang == "zh" else getattr(item, "summary_en", "")
            st_module.markdown(
                f"{idx}. **{label}**  "
                f"`{sentiment_text}`  "
                f"`{symbol_text}`\n\n"
                f"{summary_text}"
            )

    if event_decision is not None:
        regime_map = {
            "NORMAL": L("risk_regime_normal"),
            "CAUTION": L("risk_regime_caution"),
            "RISK_OFF": L("risk_regime_off"),
        }
        regime_label = regime_map.get(event_decision.regime, event_decision.regime)
        st_module.caption(
            f"{L('event_risk_summary')}: {regime_label} | "
            f"{L('risk_score')}: {event_decision.risk_score} | "
            f"{L('event_count')}: {event_decision.active_event_count}"
        )
    if not active_events:
        st_module.info(L("event_risk_none"))
        if source_reports:
            with _collapsed_expander(st_module, "抓取状态" if lang == "zh" else "Fetch Status"):
                report_lines = []
                for report in source_reports:
                    status = "OK" if report.get("ok") else "ERR"
                    fetched = int(report.get("fetched", 0))
                    error = str(report.get("error") or "").strip()
                    if error:
                        report_lines.append(
                            f"[{status}] {report.get('source_id')} {L('event_fetch_count')}: {fetched}, "
                            f"{L('event_fetch_error')}: {error}"
                        )
                    else:
                        report_lines.append(f"[{status}] {report.get('source_id')} {L('event_fetch_count')}: {fetched}")
                for line in report_lines:
                    st_module.caption(line)
        return

    with _collapsed_expander(st_module, "原始新闻明细" if lang == "zh" else "Raw Headlines"):
        if top_headline_details:
            for idx, detail in enumerate(top_headline_details, start=1):
                st_module.caption(f"{idx}. {detail.headline}")
                with st_module.expander(f"{L('event_news_expand_label')} #{idx}"):
                    metric_col = "指标" if lang == "zh" else "Metric"
                    score_col = "分数" if lang == "zh" else "Score"
                    score_df = pd.DataFrame(
                        [
                            {metric_col: L("event_news_score_total"), score_col: round(detail.total_score, 2)},
                            {metric_col: L("event_news_score_severity"), score_col: round(detail.severity_component, 2)},
                            {metric_col: L("event_news_score_sentiment"), score_col: round(detail.sentiment_component, 2)},
                            {metric_col: L("event_news_score_confidence"), score_col: round(detail.confidence_component, 2)},
                            {metric_col: L("event_news_score_verified"), score_col: round(detail.verified_component, 2)},
                            {metric_col: L("event_news_score_type"), score_col: round(detail.event_type_component, 2)},
                        ]
                    )
                    render_compact_table(score_df, st_module=st_module)
                    explanation = detail.explanation_zh if lang == "zh" else detail.explanation_en
                    st_module.caption(explanation)
        rows = []
        for event in active_events:
            window_text = "—"
            if event.starts_at is not None or event.ends_at is not None:
                start_text = event.starts_at.isoformat(timespec="minutes") if event.starts_at else "?"
                end_text = event.ends_at.isoformat(timespec="minutes") if event.ends_at else "?"
                window_text = f"{start_text} ~ {end_text}"
            rows.append(
                {
                    L("event_title"): event.title,
                    L("event_severity"): event.severity,
                    L("event_symbols"): ", ".join(event.symbols) if event.symbols else "ALL",
                    L("event_window"): window_text,
                    L("event_source"): event.source or "—",
                }
            )
        render_compact_table(pd.DataFrame(rows), st_module=st_module)
        if source_reports:
            st_module.markdown(f"**{'抓取状态' if lang == 'zh' else 'Fetch Status'}**")
            for report in source_reports:
                status = "OK" if report.get("ok") else "ERR"
                fetched = int(report.get("fetched", 0))
                error = str(report.get("error") or "").strip()
                if error:
                    st_module.caption(
                        f"[{status}] {report.get('source_id')} {L('event_fetch_count')}: {fetched}, "
                        f"{L('event_fetch_error')}: {error}"
                    )
                else:
                    st_module.caption(f"[{status}] {report.get('source_id')} {L('event_fetch_count')}: {fetched}")
