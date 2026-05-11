import pandas as pd
import streamlit as st

from quant_core.events import news_summary as ns


def render_account_snapshot_panel(account_snapshot, *, ui_text, st_module=None):
    st_module = st_module or st
    total_capital = account_snapshot.get("total_capital")
    cash_available = account_snapshot.get("cash_available")
    deployable_cash = float(account_snapshot.get("deployable_cash") or 0.0)
    exposure_pct = float(account_snapshot.get("exposure_pct") or 0.0)

    st_module.subheader(ui_text("账户资金概览", "Account Overview"))
    if total_capital is None:
        st_module.info(
            ui_text(
                "尚未配置可用现金且暂无持仓市值，系统还无法给出完整的资金分配建议。",
                "Cash available is not configured and holdings have no market value yet, so full allocation guidance is not available.",
            )
        )
        return

    cols = st_module.columns(4)
    cols[0].metric(ui_text("总资金", "Total Capital"), f"${float(total_capital):,.2f}")
    cols[1].metric(
        ui_text("可用现金", "Cash Available"),
        "—" if cash_available is None else f"${float(cash_available):,.2f}",
    )
    cols[2].metric(ui_text("可部署现金", "Deployable Cash"), f"${deployable_cash:,.2f}")
    cols[3].metric(ui_text("当前暴露", "Current Exposure"), f"{exposure_pct:.1f}%")
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


def render_signal_scoreboard_panel(scoreboard, *, ui_text, st_module=None):
    st_module = st_module or st
    if scoreboard is None:
        st_module.info(ui_text("暂无信号评分数据。", "Signal scoreboard is not available yet."))
        return

    st_module.subheader(ui_text("信号评分看板", "Signal Scoreboard"))
    s1, s2, s3, s4, s5, s6 = st_module.columns(6)
    s1.metric(ui_text("完成交易", "Closed Trades"), f"{int(getattr(scoreboard, 'completed_trades', 0) or 0)}")
    win_rate = getattr(scoreboard, "win_rate", None)
    expectancy = getattr(scoreboard, "expectancy_return_pct", None)
    payoff = getattr(scoreboard, "payoff_ratio", None)
    profit_factor = getattr(scoreboard, "profit_factor", None)
    max_dd = getattr(scoreboard, "max_drawdown_pct", None)
    s2.metric(ui_text("信号胜率", "Signal Win Rate"), f"{float(win_rate):.2%}" if win_rate is not None else "—")
    s3.metric(ui_text("期望收益/笔", "Expectancy/Trade"), f"{float(expectancy):.2%}" if expectancy is not None else "—")
    s4.metric(ui_text("盈亏比", "Payoff Ratio"), f"{float(payoff):.2f}" if payoff is not None else "—")
    s5.metric(ui_text("利润因子", "Profit Factor"), f"{float(profit_factor):.2f}" if profit_factor is not None else "—")
    s6.metric(ui_text("最大回撤", "Max Drawdown"), f"{float(max_dd):.2%}" if max_dd is not None else "—")

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


def render_active_events_panel(
    active_events,
    event_decision,
    source_reports,
    L,
    *,
    lang="zh",
    st_module=None,
    summarize_news_events=None,
):
    st_module = st_module or st
    summarize_news_events = summarize_news_events or ns.summarize_news_events
    st_module.subheader(L("event_risk_panel"))
    summary = summarize_news_events(
        active_events,
        lang="zh" if lang == "zh" else "en",
        max_headlines=3,
    )
    st_module.markdown(f"**{L('event_news_summary_title')}**")
    st_module.info(summary.overview)
    if summary.top_headline_details:
        for idx, detail in enumerate(summary.top_headline_details, start=1):
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
                st_module.dataframe(score_df, hide_index=True, width="stretch")
                explanation = detail.explanation_zh if lang == "zh" else detail.explanation_en
                st_module.caption(explanation)
    elif summary.top_headlines:
        for idx, headline in enumerate(summary.top_headlines, start=1):
            st_module.caption(f"{idx}. {headline}")

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
    if source_reports:
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
        st_module.caption(" | ".join(report_lines))
    if not active_events:
        st_module.info(L("event_risk_none"))
        return

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
                L("event_type"): event.event_type,
                L("event_severity"): event.severity,
                L("event_verified"): "Yes" if event.verified else "No",
                L("event_confidence"): f"{event.confidence_level} ({(event.confidence_score or 0.0):.2f})",
                L("event_sentiment"): (
                    f"{event.sentiment}"
                    + (
                        f" ({event.sentiment_score:.2f}, {event.sentiment_model or 'n/a'})"
                        if event.sentiment_score is not None
                        else ""
                    )
                ),
                L("event_symbols"): ", ".join(event.symbols) if event.symbols else "ALL",
                L("event_window"): window_text,
                L("event_source"): event.source or "—",
            }
        )
    st_module.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
