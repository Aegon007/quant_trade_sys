import streamlit as st
import pandas as pd
from datetime import datetime
import os
import data_utils as du
import ui_components as ui
import transactions as tx
import quant_analysis as qa
import strategy_ui as su
import ml_strategy as ml_utils
import deep_learning_strategy as dl_utils
import event_news as en
import event_fetcher as ef
import news_summary as ns
import analyst_consensus as ac
import locales as loc
from strategy_registry import create_strategy
from share_utils import format_share_quantity, validate_share_quantity
from portfolio_metrics import summarize_holdings
from position_advisor import recommend_position_action, summarize_backtest_guidance
from portfolio_advisor import analyze_portfolio_risk
from risk_gate import (
    build_market_risk_snapshot_from_histories,
    evaluate_market_risk_gate,
    merge_risk_gate_decisions,
)
from monte_carlo import simulate_return_distribution

# 引擎
from engine import BacktraderEngine, PyBrokerEngine

st.set_page_config(page_title="Portfolio Tracker", layout="wide")

AUTO_REFRESH_INTERVAL_SECONDS = 300
NEWS_AUTO_REFRESH_INTERVAL_SECONDS = 600

# ---------- 语言设置 ----------
if "lang" not in st.session_state:
    st.session_state.lang = "zh"

# ---------- 数据状态 ----------
try:
    if "app_data" not in st.session_state or du.has_newer_editable_data():
        st.session_state.app_data = du.load_data()
    refreshed_data, auto_refreshed = du.auto_refresh_market_data(
        st.session_state.app_data,
        refresh_interval_seconds=AUTO_REFRESH_INTERVAL_SECONDS,
    )
    if auto_refreshed:
        st.session_state.app_data = refreshed_data
        du.save_data(refreshed_data)
except ValueError as e:
    st.error(f"数据文件加载失败: {e}")
    st.stop()
if "sell_dialog_index" not in st.session_state:
    st.session_state.sell_dialog_index = None
if "editing_holding" not in st.session_state:
    st.session_state.editing_holding = None

data = st.session_state.app_data
market_events_bootstrapped = en.ensure_market_events_file()

# ---------- 策略配置 ----------
strategies = su.load_strategies()
if not strategies:
    st.error("策略配置文件加载失败，请检查 config/strategies.json")
    st.stop()

HISTORY_PERIOD_OPTIONS = ["6mo", "1y", "2y", "3y", "5y", "10y"]
deep_tcn_strategy = next((strategy for strategy in strategies if strategy.get("id") == "deep_tcn"), None)
default_history_period = "2y"
if deep_tcn_strategy:
    default_history_period = deep_tcn_strategy.get("params", {}).get("period", "2y")
if default_history_period not in HISTORY_PERIOD_OPTIONS:
    default_history_period = "2y"
if "history_period" not in st.session_state:
    st.session_state.history_period = default_history_period
if st.session_state.history_period not in HISTORY_PERIOD_OPTIONS:
    st.session_state.history_period = default_history_period

default_strategy_id = su.get_default_strategy_id(strategies)
if "selected_strategy_id" not in st.session_state:
    st.session_state.selected_strategy_id = default_strategy_id

valid_strategy_ids = {strategy["id"] for strategy in strategies}
if st.session_state.selected_strategy_id not in valid_strategy_ids:
    st.session_state.selected_strategy_id = default_strategy_id

strategy_map = {s["id"]: s for s in strategies}
strategy_names = [s["name"] for s in strategies]
tracked_symbols = sorted(
    {
        str(item.get("symbol", "")).strip().upper()
        for item in (st.session_state.app_data.get("holdings", []) + st.session_state.app_data.get("watchlist", []))
        if item.get("symbol")
    }
)

if deep_tcn_strategy:
    deep_tcn_params = dict(deep_tcn_strategy.get("params", {}))
    deep_tcn_params["period"] = st.session_state.history_period
    if dl_utils.should_run_nightly_retraining():
        refreshed_data = du.refresh_market_data(st.session_state.app_data)
        st.session_state.app_data = refreshed_data
        du.save_data(refreshed_data)
        _, retrain_message = dl_utils.run_nightly_retraining_for_symbols(
            tracked_symbols,
            params=deep_tcn_params,
        )
        st.session_state.nightly_retrain_status = retrain_message
    elif "nightly_retrain_status" not in st.session_state:
        st.session_state.nightly_retrain_status = "白天推理模式：仅推理，不训练"

if ac.should_run_nightly_consensus_update(now=datetime.now()):
    _, analyst_message = ac.refresh_analyst_consensus_cache(
        tracked_symbols,
        now=datetime.now(),
    )
    st.session_state.analyst_consensus_status = analyst_message
elif "analyst_consensus_status" not in st.session_state:
    st.session_state.analyst_consensus_status = "白天缓存模式：仅读取夜间分析师共识缓存"

data = st.session_state.app_data
analyst_consensus_cache = ac.load_analyst_consensus_cache()

# ========== 侧边栏 ==========
with st.sidebar:
    # 语言切换
    lang_choice = st.selectbox("🌐 Language / 语言", ["中文", "English"],
                               index=0 if st.session_state.lang == "zh" else 1)
    st.session_state.lang = "zh" if lang_choice == "中文" else "en"
    L = lambda key, **kwargs: loc.get_text(st.session_state.lang, key, **kwargs)

    history_period_index = HISTORY_PERIOD_OPTIONS.index(st.session_state.history_period)
    st.session_state.history_period = st.selectbox(
        L("history_window"),
        HISTORY_PERIOD_OPTIONS,
        index=history_period_index,
    )
    st.caption(L("history_window_hint", period=st.session_state.history_period))
    if "nightly_retrain_status" in st.session_state:
        st.caption(f"{L('nightly_retrain_status')}: {st.session_state.nightly_retrain_status}")
    if "analyst_consensus_status" in st.session_state:
        st.caption(f"分析师共识状态: {st.session_state.analyst_consensus_status}")
    if deep_tcn_strategy and st.button(L("manual_tcn_retrain")):
        with st.spinner(L("manual_tcn_retrain_running")):
            refreshed_data = du.refresh_market_data(st.session_state.app_data)
            st.session_state.app_data = refreshed_data
            du.save_data(refreshed_data)
            symbols_for_retrain = sorted(
                {
                    str(item.get("symbol", "")).strip().upper()
                    for item in (
                        st.session_state.app_data.get("holdings", [])
                        + st.session_state.app_data.get("watchlist", [])
                    )
                    if item.get("symbol")
                }
            )
            manual_params = dict(deep_tcn_strategy.get("params", {}))
            manual_params["period"] = st.session_state.history_period
            ok, retrain_message = dl_utils.run_nightly_retraining_for_symbols(
                symbols_for_retrain,
                params=manual_params,
                force=True,
            )
            st.session_state.nightly_retrain_status = retrain_message
            if ok:
                st.success(L("manual_tcn_retrain_done"))
            else:
                st.warning(retrain_message)
            st.rerun()

    st.header(L("add_holding"))
    with st.form("add_holding"):
        sym = st.text_input(L("stock_code"), placeholder="AAPL, TSM...")
        shares = st.number_input(L("shares"), min_value=0.0, step=0.001, format="%.3f")
        cost = st.number_input(L("cost_price"), min_value=0.0, step=0.01, format="%.2f")
        sector = st.text_input(L("sector"), placeholder="Technology, Healthcare...")
        if st.form_submit_button(L("submit_add_holding")):
            if sym and shares > 0 and cost > 0:
                try:
                    du.add_holding(sym, shares, cost, sector)
                    st.session_state.app_data = du.load_data()
                    st.success(f"{sym.upper()} {L('submit_add_holding')} 成功")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
            else:
                st.warning(L("submit_add_holding") + " 请完整填写")

    st.divider()
    st.header(L("add_watch"))
    with st.form("add_watch"):
        w_sym = st.text_input(L("stock_code"), key="watch_sym", placeholder="NVDA, MSFT...")
        notes = st.text_input(L("notes"), placeholder="等待回调")
        target = st.number_input(L("target_buy_price"), min_value=0.0, step=0.01, format="%.2f")
        if st.form_submit_button(L("submit_add_watch")):
            if w_sym:
                du.add_watch(w_sym, notes, target if target > 0 else None)
                st.session_state.app_data = du.load_data()
                st.success(f"{w_sym.upper()} {L('submit_add_watch')} 成功")
                st.rerun()
            else:
                st.warning(L("submit_add_watch") + " 至少输入代码")

    st.divider()
    if st.button(L("refresh_price")):
        with st.spinner("刷新中..."):
            try:
                updated = du.refresh_market_data(data)
                st.session_state.app_data = updated
                du.save_data(updated)
                st.success(L("refresh_price") + " 完成！")
                st.rerun()
            except Exception as e:
                st.error(f"刷新失败: {e}")
    if data.get("prices_last_updated"):
        st.caption(f"{L('last_price_refresh')}: {data['prices_last_updated']}")
    else:
        st.caption(L("last_price_refresh_empty"))

    st.divider()
    st.header(L("data_files"))
    st.caption(L("editable_data_file", path=du.EDITABLE_DATA_FILE))
    st.caption(L("market_events_file", path=en.MARKET_EVENTS_FILE))
    st.caption(L("event_sources_file", path=ef.EVENT_SOURCES_CONFIG_PATH))
    st.caption(f"分析师共识缓存：`{ac.ANALYST_CONSENSUS_CACHE_FILE}`")
    st.caption(L("news_auto_refresh_interval", minutes=NEWS_AUTO_REFRESH_INTERVAL_SECONDS // 60))
    if market_events_bootstrapped:
        st.success(L("market_events_bootstrapped", path=en.MARKET_EVENTS_FILE))
    if not os.path.exists(en.MARKET_EVENTS_FILE):
        st.info(L("market_events_missing", path=en.MARKET_EVENTS_FILE))
    cached_event_bundle = st.session_state.get("event_fetch_bundle", {})
    if isinstance(cached_event_bundle, dict) and cached_event_bundle.get("fetched_at"):
        st.caption(L("news_last_fetched_at", ts=str(cached_event_bundle.get("fetched_at"))))
    if st.button(L("refresh_news")):
        with st.spinner(L("refresh_news_running")):
            symbols_for_news = sorted(
                {
                    str(item.get("symbol", "")).strip().upper()
                    for item in (
                        st.session_state.app_data.get("holdings", [])
                        + st.session_state.app_data.get("watchlist", [])
                    )
                    if item.get("symbol")
                }
            )
            events, reports = ef.fetch_events_from_sources(
                symbols=symbols_for_news,
                now=datetime.now(),
            )
            st.session_state.event_fetch_bundle = {
                "events": events,
                "source_reports": reports,
                "symbols": symbols_for_news,
                "fetched_at": datetime.now().isoformat(),
            }
            st.success(L("refresh_news_done", count=len(events)))
            st.rerun()
    if du.has_newer_editable_data():
        st.info(L("editable_data_pending"))
    if st.button(L("reload_data_file")):
        if not du.editable_data_file_exists():
            st.warning(L("editable_data_missing", path=du.EDITABLE_DATA_FILE))
        else:
            try:
                st.session_state.app_data = du.load_data(force_editable_sync=True)
                st.success(L("reload_data_file_done"))
                st.rerun()
            except ValueError as e:
                st.error(f"{L('reload_data_file_failed')}: {e}")

    st.divider()
    st.header(L("clear_ops"))
    c1, c2 = st.columns(2)
    with c1:
        if st.button(L("clear_holdings")):
            du.clear_holdings()
            st.session_state.app_data = du.load_data()
            st.warning(L("clear_holdings") + " 完成")
            st.rerun()
    with c2:
        if st.button(L("clear_watchlist")):
            du.clear_watchlist()
            st.session_state.app_data = du.load_data()
            st.warning(L("clear_watchlist") + " 完成")
            st.rerun()

    st.divider()
    st.header(L("export"))
    st.markdown(f"- {L('export_md')}")
    st.markdown(f"- {L('export_pdf')}")

# ---------- 辅助函数 ----------
def apply_runtime_strategy_params(strategy):
    runtime_strategy = dict(strategy)
    runtime_params = dict(strategy.get("params", {}))
    runtime_params["period"] = st.session_state.get("history_period", runtime_params.get("period", "2y"))
    runtime_strategy["params"] = runtime_params
    return runtime_strategy


def _normalize_symbols(symbols):
    return sorted(
        {
            str(symbol).strip().upper()
            for symbol in (symbols or [])
            if symbol and str(symbol).strip()
        }
    )


def fetch_news_events_with_cache(symbols, force=False, now=None):
    now = now or datetime.now()
    normalized_symbols = _normalize_symbols(symbols)
    cached_bundle = st.session_state.get("event_fetch_bundle")
    previous_symbols = cached_bundle.get("symbols", []) if isinstance(cached_bundle, dict) else []
    last_fetched_at = cached_bundle.get("fetched_at") if isinstance(cached_bundle, dict) else None
    should_refresh = ef.should_refresh_events_cache(
        last_fetched_at=last_fetched_at,
        previous_symbols=previous_symbols,
        current_symbols=normalized_symbols,
        interval_seconds=NEWS_AUTO_REFRESH_INTERVAL_SECONDS,
        now=now,
        force=force,
    )
    if should_refresh:
        events, source_reports = ef.fetch_events_from_sources(
            symbols=normalized_symbols,
            now=now,
        )
        cached_bundle = {
            "events": events,
            "source_reports": source_reports,
            "symbols": normalized_symbols,
            "fetched_at": now.isoformat(),
        }
        st.session_state.event_fetch_bundle = cached_bundle
        return events, source_reports, True

    if not isinstance(cached_bundle, dict):
        return [], [], False
    return (
        list(cached_bundle.get("events", []) or []),
        list(cached_bundle.get("source_reports", []) or []),
        False,
    )


def enable_auto_news_rerun(interval_seconds=NEWS_AUTO_REFRESH_INTERVAL_SECONDS):
    fragment_decorator = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)
    rerun_fn = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
    if fragment_decorator is None or rerun_fn is None:
        return False

    if "_news_auto_rerun_last" not in st.session_state:
        st.session_state["_news_auto_rerun_last"] = datetime.now().timestamp()

    @fragment_decorator(run_every=int(interval_seconds))
    def _news_refresh_heartbeat():
        now_ts = datetime.now().timestamp()
        last_ts = float(st.session_state.get("_news_auto_rerun_last", now_ts))
        # Avoid immediate rerun on first render; rerun only on interval ticks.
        if now_ts - last_ts < max(2.0, float(interval_seconds) * 0.8):
            return
        st.session_state["_news_auto_rerun_last"] = now_ts
        rerun_fn()

    _news_refresh_heartbeat()
    return True


def evaluate_market_risk_for_portfolio(
    holdings,
    history_period,
    event_symbols=None,
    now=None,
    fetched_events=None,
    source_reports=None,
):
    if not holdings:
        return None, None, None, None, [], None, []

    symbols = list(dict.fromkeys([h["symbol"] for h in holdings if h.get("current_price") is not None]))
    correlation_matrix = None
    if len(symbols) > 1:
        try:
            correlation_matrix = qa.calculate_correlation_matrix(symbols, period="6mo")
        except Exception:
            correlation_matrix = None

    portfolio_risk = analyze_portfolio_risk(
        holdings,
        correlation_matrix=correlation_matrix,
    )

    benchmark_history = qa.get_historical_data("SPY", period=history_period)
    vix_history = qa.get_historical_data("^VIX", period="6mo")
    snapshot = build_market_risk_snapshot_from_histories(
        benchmark_history=benchmark_history,
        vix_history=vix_history,
        sector_alert_count=len(portfolio_risk.sector_alerts),
        correlation_alert_count=len(portfolio_risk.correlation_alerts),
    )
    base_decision = evaluate_market_risk_gate(snapshot)

    if fetched_events is None or source_reports is None:
        fetched_events, source_reports = ef.fetch_events_from_sources(
            symbols=event_symbols or symbols,
            now=now or datetime.now(),
        )
    active_events = en.select_active_events(
        fetched_events,
        symbols=event_symbols or symbols,
        now=now,
        verified_only=False,
    )
    event_decision = en.evaluate_event_risk_switch(
        active_events,
        vix=snapshot.vix,
        verified_only=True,
        now=now,
    )
    decision = merge_risk_gate_decisions(base_decision, event_decision)
    return decision, snapshot, portfolio_risk, correlation_matrix, active_events, event_decision, source_reports


def render_market_risk_gate_banner(decision, snapshot, L):
    if decision is None or snapshot is None:
        st.info(L("market_risk_gate_unavailable"))
        return

    metrics = [f"{L('risk_score')}: {decision.risk_score}", f"{L('max_position_weight')}: {decision.max_position_weight * 100:.1f}%"]
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
        st.error(message)
    elif decision.regime == "CAUTION":
        st.warning(message)
    else:
        st.success(message)


def render_active_events_panel(active_events, event_decision, source_reports, L):
    st.subheader(L("event_risk_panel"))
    summary = ns.summarize_news_events(
        active_events,
        lang="zh" if st.session_state.get("lang", "zh") == "zh" else "en",
        max_headlines=3,
    )
    st.markdown(f"**{L('event_news_summary_title')}**")
    st.info(summary.overview)
    if summary.top_headline_details:
        for idx, detail in enumerate(summary.top_headline_details, start=1):
            st.caption(f"{idx}. {detail.headline}")
            with st.expander(f"{L('event_news_expand_label')} #{idx}"):
                metric_col = "指标" if st.session_state.get("lang", "zh") == "zh" else "Metric"
                score_col = "分数" if st.session_state.get("lang", "zh") == "zh" else "Score"
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
                st.dataframe(score_df, hide_index=True, width="stretch")
                explanation = detail.explanation_zh if st.session_state.get("lang", "zh") == "zh" else detail.explanation_en
                st.caption(explanation)
    elif summary.top_headlines:
        for idx, headline in enumerate(summary.top_headlines, start=1):
            st.caption(f"{idx}. {headline}")

    if event_decision is not None:
        regime_map = {
            "NORMAL": L("risk_regime_normal"),
            "CAUTION": L("risk_regime_caution"),
            "RISK_OFF": L("risk_regime_off"),
        }
        regime_label = regime_map.get(event_decision.regime, event_decision.regime)
        st.caption(
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
                report_lines.append(f"[{status}] {report.get('source_id')} {L('event_fetch_count')}: {fetched}, {L('event_fetch_error')}: {error}")
            else:
                report_lines.append(f"[{status}] {report.get('source_id')} {L('event_fetch_count')}: {fetched}")
        st.caption(" | ".join(report_lines))
    if not active_events:
        st.info(L("event_risk_none"))
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
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def render_dialogs():
    if st.session_state.sell_dialog_index is not None:
        idx = st.session_state.sell_dialog_index
        if idx < len(data["holdings"]):
            h = data["holdings"][idx]
            with st.expander(f"{L('sell_dialog_title')} {h['symbol']}", expanded=True):
                col1, col2 = st.columns(2)
                with col1:
                    sell_price = st.number_input(L("sell_price"), min_value=0.0,
                                                value=h.get("current_price") or 0.0, step=0.01, format="%.2f")
                with col2:
                    max_s = h["shares"]
                    sell_shares = st.number_input(L("sell_shares"), min_value=0.0,
                                                 max_value=float(max_s), value=float(max_s), step=0.001, format="%.3f")
                if st.button(L("confirm_sell")):
                    if sell_shares > 0:
                        try:
                            sym, cb = du.sell_partial_holding(idx, sell_shares, sell_price)
                            tx.add_transaction(sym, sell_price, sell_shares, cb)
                            st.session_state.app_data = du.load_data()
                            st.success(f"已卖出 {sym} {format_share_quantity(sell_shares)} 股 @ ${sell_price:.2f}")
                            st.session_state.sell_dialog_index = None
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
                if st.button(L("cancel")):
                    st.session_state.sell_dialog_index = None
                    st.rerun()
        else:
            st.session_state.sell_dialog_index = None
            st.rerun()

    if st.session_state.editing_holding is not None:
        idx = st.session_state.editing_holding
        if idx < len(data["holdings"]):
            h = data["holdings"][idx]
            with st.expander(f"{L('edit_dialog_title')} {h['symbol']}", expanded=True):
                with st.form("edit_holding_form"):
                    new_shares = st.number_input(L("shares"), min_value=0.0, value=float(h["shares"]), step=0.001, format="%.3f")
                    new_cost = st.number_input(L("cost_price"), min_value=0.0, value=float(h["cost"]), step=0.01, format="%.2f")
                    new_sector = st.text_input(L("sector"), value=h.get("sector", ""))
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.form_submit_button(L("save")):
                            if new_shares > 0:
                                try:
                                    data["holdings"][idx]["shares"] = validate_share_quantity(new_shares, field_name="shares")
                                    data["holdings"][idx]["cost"] = new_cost
                                    data["holdings"][idx]["sector"] = new_sector.strip()
                                    du.save_data(data)
                                    st.session_state.app_data = du.load_data()
                                    st.success(L("save") + " 成功")
                                    st.session_state.editing_holding = None
                                    st.rerun()
                                except ValueError as e:
                                    st.error(str(e))
                            else:
                                st.error(L("shares") + " 必须大于0")
                    with c2:
                        if st.form_submit_button(L("cancel")):
                            st.session_state.editing_holding = None
                            st.rerun()
        else:
            st.session_state.editing_holding = None
            st.rerun()


enable_auto_news_rerun(interval_seconds=NEWS_AUTO_REFRESH_INTERVAL_SECONDS)

render_dialogs()

market_risk_gate_decision = None
market_risk_snapshot = None
portfolio_risk_advice = None
portfolio_corr_matrix = None
active_market_events = []
event_risk_decision = None
event_source_reports = []
if data["holdings"]:
    try:
        event_symbols = list(
            dict.fromkeys(
                [h["symbol"] for h in data["holdings"] if h.get("symbol")]
                + [w["symbol"] for w in data.get("watchlist", []) if w.get("symbol")]
            )
        )
        fetched_events, fetched_reports, _ = fetch_news_events_with_cache(
            event_symbols,
            now=datetime.now(),
        )
        (
            market_risk_gate_decision,
            market_risk_snapshot,
            portfolio_risk_advice,
            portfolio_corr_matrix,
            active_market_events,
            event_risk_decision,
            event_source_reports,
        ) = evaluate_market_risk_for_portfolio(
            data["holdings"],
            history_period=st.session_state.history_period,
            event_symbols=event_symbols,
            now=datetime.now(),
            fetched_events=fetched_events,
            source_reports=fetched_reports,
        )
    except Exception:
        market_risk_gate_decision = None
        market_risk_snapshot = None
        portfolio_risk_advice = None
        portfolio_corr_matrix = None
        active_market_events = []
        event_risk_decision = None
        event_source_reports = []

# ---------- 主区域 ----------
st.title(L("app_title"))
st.caption(L("app_caption"))

tab1, tab2, tab3, tab4 = st.tabs([
    L("holdings_tab"), L("watchlist_tab"),
    L("transactions_tab"), L("quant_tab")
])

# ----- Tab1 持仓 -----
with tab1:
    st.caption(L("strategy_signal"))
    selected_index = [s["id"] for s in strategies].index(st.session_state.selected_strategy_id)
    selected_strategy_name = st.selectbox(
        L("strategy_signal"),
        strategy_names,
        index=selected_index
    )
    selected_strategy = next((s for s in strategies if s["name"] == selected_strategy_name), strategies[0])
    selected_strategy_runtime = apply_runtime_strategy_params(selected_strategy)
    st.session_state.selected_strategy_id = selected_strategy["id"]
    with st.expander(L("strategy_desc")):
        st.markdown(selected_strategy.get("description", "无说明"))

    def handle_sell(idx):
        st.session_state.sell_dialog_index = idx

    def handle_delete_holding(idx):
        du.delete_holding(idx)
        st.session_state.app_data = du.load_data()

    def handle_move_holding_to_watch(idx):
        du.move_holding_to_watchlist(idx)
        st.session_state.app_data = du.load_data()

    if data["holdings"]:
        render_market_risk_gate_banner(market_risk_gate_decision, market_risk_snapshot, L)
    summary, holding_records = ui.render_holdings_table(
        data,
        on_price_change=du.update_holding_price,
        on_delete=handle_delete_holding,
        on_sell=handle_sell,
        on_move_to_watch=handle_move_holding_to_watch,
        strategy=selected_strategy_runtime,
        risk_gate=market_risk_gate_decision,
    )
    if data["holdings"]:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(L("total_cost"), f"${summary.total_cost:,.2f}")
        c2.metric(L("total_value"), f"${summary.total_value:,.2f}")
        c3.metric(L("total_pl"), f"${summary.total_pl:+,.2f}", delta=f"{summary.total_pl_pct:+.2f}%")
        c4.metric(L("holdings_count"), f"{len(data['holdings'])}")

        if st.button(L("gen_md")):
            lines = ["| 代码 | 股数 | 成本价 | 现价 | 市值 | 盈亏 ($) | 盈亏 (%) | 信号 |"]
            lines.append("|------|------|--------|------|------|----------|----------|------|")
            for row in holding_records:
                price_text = f"${row['现价']:,.2f}" if row["现价"] is not None else "—"
                value_text = f"${row['市值']:,.2f}" if row["市值"] is not None else "—"
                pl_text = f"${row['盈亏 ($)']:+,.2f}" if row["盈亏 ($)"] is not None else "—"
                pl_pct_text = f"{row['盈亏 (%)']:+.2f}%" if row["盈亏 (%)"] is not None else "—"
                lines.append(
                    f"| {row['代码']} | {format_share_quantity(row['股数'])} | ${row['成本价']:,.2f} | "
                    f"{price_text} | "
                    f"{value_text} | "
                    f"{pl_text} | "
                    f"{pl_pct_text} | "
                    f"{row['信号']} |"
                )
            lines.append(
                f"\n**{L('total_cost')}**: ${summary.total_cost:,.2f}  "
                f"\n**{L('total_value')}**: ${summary.total_value:,.2f}  "
                f"\n**{L('total_pl')}**: ${summary.total_pl:+,.2f} ({summary.total_pl_pct:+.2f}%)"
            )
            md_text = "\n".join(lines)
            st.code(md_text, language="markdown")
            st.download_button("⬇️ 下载 Markdown", data=md_text, file_name=f"holdings_{datetime.now().strftime('%Y%m%d')}.md")

# ----- Tab2 关注列表 -----
with tab2:
    selected_strategy_for_watch = strategy_map.get(st.session_state.selected_strategy_id, strategies[0])
    selected_strategy_for_watch_runtime = apply_runtime_strategy_params(selected_strategy_for_watch)

    def handle_delete_watch_batch(indices):
        du.delete_watch_batch(indices)
        st.session_state.app_data = du.load_data()

    def handle_move_watch_to_holding(idx):
        du.move_watch_to_holding(idx, shares=1.0)
        st.session_state.app_data = du.load_data()

    ui.render_watchlist_table(
        data,
        on_delete_batch=handle_delete_watch_batch,
        on_move_to_holding=handle_move_watch_to_holding,
        strategy=selected_strategy_for_watch_runtime,
        analyst_consensus_cache=analyst_consensus_cache,
    )

# ----- Tab3 交易记录 -----
with tab3:
    transactions = tx.load_transactions()
    if not transactions:
        st.info(L("no_transactions"))
    else:
        df = pd.DataFrame(transactions)
        df_display = df.copy()
        df_display["shares"] = df_display["shares"].apply(format_share_quantity)
        df_display["盈亏 ($)"] = df_display["pl"].apply(lambda x: f"${x:+,.2f}")
        df_display["盈亏 (%)"] = df_display["pl_pct"].apply(lambda x: f"{x:+.2f}%")
        df_display = df_display[["date", "symbol", "shares", "sell_price", "cost_basis", "proceeds", "盈亏 ($)", "盈亏 (%)"]]
        df_display.columns = ["日期", "代码", "股数", "卖出价", "成本价", "收入", "盈亏 ($)", "盈亏 (%)"]
        st.dataframe(df_display, hide_index=True, width="stretch")
        total_proceeds = sum(t["proceeds"] for t in transactions)
        total_pl_trans = sum(t["pl"] for t in transactions)
        c1, c2 = st.columns(2)
        c1.metric(L("total_income"), f"${total_proceeds:,.2f}")
        c2.metric(L("total_pl_trans"), f"${total_pl_trans:+,.2f}")

# ----- Tab4 量化分析 -----
with tab4:
    st.header(L("quant_title"))
    st.markdown(L("quant_desc"))
    if data["holdings"]:
        render_market_risk_gate_banner(market_risk_gate_decision, market_risk_snapshot, L)
        render_active_events_panel(active_market_events, event_risk_decision, event_source_reports, L)
    portfolio_summary = summarize_holdings(data["holdings"])

    all_symbols = list(set([h["symbol"] for h in data["holdings"]] + [w["symbol"] for w in data["watchlist"]]))
    if not all_symbols:
        st.warning("暂无数据")
    else:
        st.subheader(L("engine_setting"))
        engine_option = st.selectbox(L("select_engine"), ["Backtrader (推荐)", "PyBroker"])
        use_backtrader = (engine_option == "Backtrader (推荐)")

        st.subheader(L("strategy_select"))
        selected_strategy_tab4 = su.render_strategy_selector(
            strategies,
            default_strategy_id=st.session_state.selected_strategy_id,
        )
        selected_strategy_tab4_runtime = (
            apply_runtime_strategy_params(selected_strategy_tab4) if selected_strategy_tab4 else None
        )
        if selected_strategy_tab4:
            su.display_strategy_description(selected_strategy_tab4)

        selected_symbol = st.selectbox(L("select_stock"), all_symbols)

        # ---- 模型重训练（仅ML/集成策略）----
        if selected_strategy_tab4 and selected_strategy_tab4["id"] in ("ml_lightgbm", "ensemble_voting"):
            st.subheader(L("model_management"))
            if selected_symbol:
                train_period = st.selectbox(L("select_train_period"), ["1y", "2y", "3y", "5y", "10y"], index=1)
                if st.button(L("retrain_btn")):
                    with st.spinner("训练中..."):
                        try:
                            train_hist = qa.get_historical_data(selected_symbol, period=train_period)
                            if train_hist.empty:
                                st.error("无法获取足够数据。")
                            else:
                                params = selected_strategy_tab4_runtime.get("params", {})
                                status = ml_utils.retrain_and_save_model(selected_symbol, train_hist, params)
                                if "✅" in status:
                                    st.success(status)
                                    st.cache_data.clear()
                                else:
                                    st.warning(status)
                        except Exception as e:
                            st.error(f"训练失败: {e}")
            else:
                st.info(L("need_select_stock"))

        if selected_symbol and selected_strategy_tab4_runtime:
            with st.spinner("加载历史数据..."):
                history_period = selected_strategy_tab4_runtime.get("params", {}).get("period", "2y")
                hist = qa.get_historical_data(selected_symbol, period=history_period)
                if hist.empty:
                    st.error("无历史数据")
                else:
                    st.subheader(f"{selected_symbol} 技术指标")
                    df_ma = qa.calculate_ma(hist)
                    rsi = qa.calculate_rsi(hist)
                    c1, c2 = st.columns(2)
                    with c1:
                        st.metric(L("latest_price"), f"${hist['Close'].iloc[-1]:.2f}")
                        st.metric(L("ma20"), f"${df_ma['MA20'].iloc[-1]:.2f}")
                        st.metric(L("ma50"), f"${df_ma['MA50'].iloc[-1]:.2f}")
                    with c2:
                        st.metric(L("rsi14"), f"{rsi.iloc[-1]:.2f}")
                        st.metric(L("annual_vol"), f"{qa.calculate_volatility(hist):.2%}")
                        st.metric(L("max_dd"), f"{qa.calculate_max_drawdown(hist):.2%}")

                    st.line_chart(df_ma[["Close", "MA20", "MA50"]].tail(100))

                    st.subheader(L("mc_title"))
                    mc_col1, mc_col2 = st.columns(2)
                    with mc_col1:
                        mc_horizon = st.slider(L("mc_horizon_days"), min_value=5, max_value=90, value=20, step=5)
                    with mc_col2:
                        mc_simulations = st.selectbox(L("mc_simulations"), [500, 1000, 2000, 5000], index=2)
                    mc_dist = simulate_return_distribution(
                        hist,
                        horizon_days=mc_horizon,
                        simulations=int(mc_simulations),
                        seed=42,
                    )
                    if mc_dist is None:
                        st.info(L("mc_unavailable"))
                    else:
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric(L("mc_expected_return"), f"{mc_dist.expected_return:.2%}")
                        m2.metric(L("mc_positive_prob"), f"{mc_dist.positive_probability:.1%}")
                        m3.metric(L("mc_var95"), f"{mc_dist.var_95:.2%}")
                        m4.metric(L("mc_cvar95"), f"{mc_dist.cvar_95:.2%}")
                        p1, p2, p3 = st.columns(3)
                        p1.metric(L("mc_expected_price"), f"${mc_dist.expected_price:.2f}")
                        p2.metric(L("mc_p05_price"), f"${mc_dist.p05_price:.2f}")
                        p3.metric(L("mc_p95_price"), f"${mc_dist.p95_price:.2f}")

                    # 当前信号
                    current_signal = "HOLD"
                    current_reason = "暂无信号"
                    try:
                        current_signal, current_reason = su.get_signal(selected_strategy_tab4_runtime, selected_symbol)
                        if current_signal == "BUY":
                            st.success(f"📈 {L('current_signal')}: {L('buy')} — {current_reason}")
                        elif current_signal == "SELL":
                            st.error(f"📉 {L('current_signal')}: {L('sell')} — {current_reason}")
                        else:
                            st.info(f"⏸️ {L('current_signal')}: {L('hold')} — {current_reason}")
                    except Exception as e:
                        st.warning(f"无法获取信号: {e}")

                    if selected_strategy_tab4_runtime.get("id") == "deep_tcn":
                        profile = dl_utils.get_deep_tcn_signal_profile(
                            selected_symbol,
                            **selected_strategy_tab4_runtime.get("params", {}),
                        )
                        st.subheader(L("tcn_profile_title"))
                        if profile.probability is not None:
                            p1, p2, p3, p4 = st.columns(4)
                            p1.metric(L("tcn_up_prob"), f"{profile.probability:.1%}")
                            p2.metric(L("tcn_expected_return"), f"{profile.expected_return_pct:.2%}" if profile.expected_return_pct is not None else "—")
                            p3.metric(L("tcn_confidence"), f"{profile.confidence:.1%}" if profile.confidence is not None else "—")
                            p4.metric(L("tcn_weight_cap"), f"{profile.recommended_max_weight_pct:.1f}%" if profile.recommended_max_weight_pct is not None else "—")

                            q1, q2, q3 = st.columns(3)
                            q1.metric(L("tcn_take_profit"), f"${profile.take_profit_price:.2f}" if profile.take_profit_price is not None else "—")
                            q2.metric(L("tcn_stop_loss"), f"${profile.stop_loss_price:.2f}" if profile.stop_loss_price is not None else "—")
                            q3.metric(L("tcn_trained_at"), profile.trained_at or "—")
                        else:
                            st.info(profile.reason)

                    # 回测按钮
                    st.subheader(L("backtest_title") + f" (引擎: {engine_option})")
                    if st.button(L("run_backtest"), key="run_backtest"):
                        with st.spinner("回测中..."):
                            try:
                                strategy_obj = create_strategy(selected_strategy_tab4_runtime)

                                if strategy_obj:
                                    engine = BacktraderEngine(initial_cash=100000) if use_backtrader else PyBrokerEngine(initial_cash=100000)
                                    engine.set_data(hist)
                                    engine.set_strategy(strategy_obj)
                                    result = engine.run()
                                    guidance = summarize_backtest_guidance(
                                        result.trade_log,
                                        current_price=float(hist["Close"].iloc[-1]),
                                    )

                                    st.success("回测完成！")
                                    c1, c2, c3, c4 = st.columns(4)
                                    c1.metric(L("cum_return"), f"{result.total_return:.2%}")
                                    c2.metric(L("sharpe"), f"{result.sharpe_ratio:.2f}")
                                    c3.metric(L("max_drawdown"), f"{result.max_drawdown:.2%}")
                                    c4.metric(L("win_rate"), f"{result.win_rate:.2%}")
                                    if result.equity_curve:
                                        st.line_chart(pd.Series(result.equity_curve))

                                    st.subheader("仓位与退出参考")
                                    if guidance.completed_trades:
                                        g1, g2, g3, g4 = st.columns(4)
                                        g1.metric("单笔期望收益", f"{guidance.expected_return_pct:.2%}" if guidance.expected_return_pct is not None else "—")
                                        g2.metric("平均持有天数", f"{guidance.expected_holding_days} 天" if guidance.expected_holding_days is not None else "—")
                                        g3.metric("参考卖出价", f"${guidance.suggested_exit_price:.2f}" if guidance.suggested_exit_price is not None else "—")
                                        g4.metric("完成交易数", f"{guidance.completed_trades}")
                                    else:
                                        st.info("当前回测没有形成完整买卖对，暂时无法估计持有周期和参考卖出价。")

                                    current_holding = next((h for h in data["holdings"] if h["symbol"] == selected_symbol), None)
                                    if current_holding and current_holding.get("current_price") is not None and portfolio_summary.total_value > 0:
                                        advice = recommend_position_action(
                                            holding=current_holding,
                                            portfolio_value=portfolio_summary.total_value,
                                            signal=current_signal,
                                            signal_reason=current_reason,
                                            guidance=guidance,
                                            risk_gate=market_risk_gate_decision,
                                        )
                                        delta_text = (
                                            format_share_quantity(abs(advice.delta_shares))
                                            if advice.delta_shares is not None
                                            else "—"
                                        )
                                        if advice.action == "ADD":
                                            st.info(
                                                f"当前持仓建议：加仓约 {delta_text} 股，目标仓位 {advice.target_weight_pct:.1f}%。"
                                                f" {advice.reason}"
                                            )
                                        elif advice.action == "TRIM":
                                            st.warning(
                                                f"当前持仓建议：减仓约 {delta_text} 股，目标仓位 {advice.target_weight_pct:.1f}%。"
                                                f" {advice.reason}"
                                            )
                                        elif advice.action == "EXIT":
                                            st.error(f"当前持仓建议：考虑逐步卖出该仓位。 {advice.reason}")
                                        else:
                                            st.success(f"当前持仓建议：继续持有。 {advice.reason}")
                            except Exception as e:
                                st.error(f"回测失败: {e}")

                    # MACD 图表
                    macd, signal_line, hist_macd = qa.calculate_macd(hist)
                    macd_df = pd.DataFrame({"MACD": macd, "Signal": signal_line, "Histogram": hist_macd}).tail(100)
                    st.subheader(L("macd_indicator"))
                    st.line_chart(macd_df[["MACD", "Signal"]])
                    st.bar_chart(macd_df["Histogram"])

        # 组合风险
        st.divider()
        st.subheader(L("portfolio_risk"))
        if data["holdings"]:
            if st.button(L("calc_beta")):
                with st.spinner("计算中..."):
                    try:
                        beta, betas = qa.calculate_portfolio_beta(data["holdings"])
                        st.metric(L("portfolio_beta"), f"{beta:.2f}")
                        st.dataframe(pd.DataFrame(list(betas.items()), columns=["代码", "Beta"]), hide_index=True)
                        symbols = list(dict.fromkeys([h["symbol"] for h in data["holdings"] if h.get("current_price")]))
                        corr = None
                        if len(symbols) > 1:
                            corr = qa.calculate_correlation_matrix(symbols)
                            st.write(L("corr_matrix"))
                            st.dataframe(corr.style.format("{:.2f}"))

                        portfolio_advice = analyze_portfolio_risk(
                            data["holdings"],
                            correlation_matrix=corr,
                        )
                        st.subheader(L("portfolio_advice"))
                        if portfolio_advice.sector_exposures:
                            sector_df = pd.DataFrame([
                                {
                                    "Sector": exposure.sector,
                                    "Value": exposure.value,
                                    "Weight": f"{exposure.weight_pct:.1f}%",
                                }
                                for exposure in portfolio_advice.sector_exposures
                            ])
                            st.dataframe(sector_df, hide_index=True, width="stretch")

                        if portfolio_advice.recommendations:
                            for recommendation in portfolio_advice.recommendations:
                                st.warning(recommendation)
                        else:
                            st.success(L("portfolio_advice_ok"))
                    except Exception as e:
                        st.error(f"计算失败: {e}")
        else:
            st.info("无持仓数据")
