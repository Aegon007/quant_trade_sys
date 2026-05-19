import os
import time
from datetime import datetime

import streamlit as st

from app.orchestration import runtime as rt
from app.ui import cockpit as uc
from app.ui import components as ui
from app.ui import notification_page as unp
from app.ui import pages as pg
from app.ui import panels as up
import locales as loc
from quant_core import paths as qpaths
from quant_core.analytics import candidate_pool as cpool
from quant_core.analytics import core_etf_rotation as cer
from quant_core.analytics import portfolio_analysis as qpa
from quant_core.analytics import quant_analysis as qa
from quant_core.data import market_data as md
from quant_core.data import storage as du
from quant_core.events import analyst_consensus as ac
from quant_core.events import event_fetcher as ef
from quant_core.events import event_news as en
from quant_core.execution import nightly_manifest as nman
from quant_core.execution import nightly_planner as nplanner
from quant_core.execution import post_close_review as pclose
from quant_core.ledger import transactions as tx
from quant_core.llm import explainer as lexp
from quant_core.monitoring import intraday_journal as ij
from quant_core.notifications import change_feed as cfeed
from quant_core.notifications import notification_channels as nch
from quant_core.notifications import notification_config as ncfg
from quant_core.notifications import reporting as nr
from quant_core.portfolio import actions as pactions
from quant_core.portfolio import core_etf_engine as cee
from quant_core.portfolio import discipline as qdisc
from quant_core.portfolio.control_loop import evaluate_allocation_regime
from quant_core.portfolio.metrics import summarize_holdings
from quant_core.portfolio.risk import analyze_portfolio_risk
from quant_core.risk.risk_gate import (
    build_market_risk_snapshot_from_histories,
    evaluate_market_risk_gate,
    merge_risk_gate_decisions,
)
from quant_core.snapshots import system_snapshot as ss
from share_utils import format_share_quantity
from signal_scoreboard import build_signal_scoreboard
from strategies import ui as su
from jobs.nightly_alerts import run_nightly_alerts


st.set_page_config(page_title="Portfolio Tracker", layout="wide")

AUTO_REFRESH_INTERVAL_SECONDS = 300
NEWS_AUTO_REFRESH_INTERVAL_SECONDS = 600
DEFER_STARTUP_REFRESH = str(os.environ.get("QUANT_UI_SKIP_STARTUP_REFRESH") or "").strip().lower() in {"1", "true", "yes", "on"}
DEFER_INITIAL_EVENT_FETCH = str(os.environ.get("QUANT_UI_DEFER_INITIAL_EVENT_FETCH") or "").strip().lower() in {"1", "true", "yes", "on"}
RUN_ALL_MODE = str(os.environ.get("QUANT_RUN_ALL_MODE") or "").strip().lower() in {"1", "true", "yes", "on"}


@st.cache_data(ttl=AUTO_REFRESH_INTERVAL_SECONDS, show_spinner=False)
def load_historical_data_cached(symbol, period):
    return qa.get_historical_data(symbol, period=period)


@st.cache_data(ttl=AUTO_REFRESH_INTERVAL_SECONDS, show_spinner=False)
def load_correlation_matrix_cached(symbols, period="6mo"):
    return qa.calculate_correlation_matrix(list(symbols), period=period)


@st.cache_data(ttl=AUTO_REFRESH_INTERVAL_SECONDS, show_spinner=False)
def load_cached_state_payloads(_state_signature):
    quant_analysis_snapshot = qpa.load_quant_analysis_snapshot()
    latest_report_snapshot = quant_analysis_snapshot or nr.load_latest_quant_analysis_snapshot()
    return {
        "analyst_consensus_cache": ac.load_analyst_consensus_cache(),
        "quant_analysis_snapshot": quant_analysis_snapshot,
        "latest_trade_plan": nplanner.load_next_day_trade_plan(),
        "latest_post_close_review": pclose.load_post_close_review(),
        "latest_change_feed": cfeed.load_change_feed(),
        "latest_nightly_manifest": nman.load_nightly_run_manifest(),
        "nightly_snapshot_journal": ss.load_snapshot_journal(limit=62),
        "intraday_event_rows": ij.load_intraday_events(limit=120),
        "core_etf_snapshot": cee.load_core_etf_snapshot(),
        "discipline_snapshot": qdisc.load_discipline_snapshot(),
        "satellite_candidate_snapshot": cpool.load_satellite_candidate_pool_snapshot(),
        "latest_report_snapshot": latest_report_snapshot,
    }


if "lang" not in st.session_state:
    st.session_state.lang = "zh"


def ui_text(zh_text, en_text):
    return zh_text if st.session_state.get("lang", "zh") == "zh" else en_text


def _safe_file_mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _parse_iso_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _state_payload_signature():
    tracked_paths = (
        ac.ANALYST_CONSENSUS_CACHE_FILE,
        qpaths.QUANT_ANALYSIS_SNAPSHOT_FILE,
        qpaths.NEXT_DAY_TRADE_PLAN_FILE,
        qpaths.POST_CLOSE_REVIEW_FILE,
        qpaths.CHANGE_FEED_FILE,
        qpaths.NIGHTLY_RUN_MANIFEST_FILE,
        qpaths.CORE_ETF_SNAPSHOT_FILE,
        qpaths.DISCIPLINE_SNAPSHOT_FILE,
        qpaths.SATELLITE_CANDIDATE_POOL_FILE,
        ss.DEFAULT_NIGHTLY_JOURNAL_FILE,
        qpaths.INTRADAY_EVENT_JOURNAL_FILE,
    )
    return tuple((path, _safe_file_mtime(path)) for path in tracked_paths)


def _data_signature(data):
    data = dict(data or {})
    account = dict(data.get("account", {}) or {})
    holdings_signature = tuple(
        (
            str(row.get("symbol") or "").strip().upper(),
            float(row.get("shares") or 0.0),
            float(row.get("cost") or 0.0),
            None if row.get("current_price") is None else float(row.get("current_price")),
            str(row.get("sector") or "").strip(),
        )
        for row in list(data.get("holdings", []) or [])
    )
    watchlist_signature = tuple(
        (
            str(row.get("symbol") or "").strip().upper(),
            None if row.get("last_price") is None else float(row.get("last_price")),
            str(row.get("notes") or ""),
        )
        for row in list(data.get("watchlist", []) or [])
    )
    account_signature = (
        None if account.get("cash_available") is None else float(account.get("cash_available")),
        None if account.get("total_capital") is None else float(account.get("total_capital")),
        float(account.get("min_cash_buffer_pct") or 0.0),
        float(account.get("max_single_position_pct") or 0.0),
        float(account.get("max_total_exposure_pct") or 0.0),
    )
    return (
        holdings_signature,
        watchlist_signature,
        account_signature,
        str(data.get("last_updated") or ""),
        str(data.get("prices_last_updated") or ""),
    )


def _event_bundle_signature(bundle):
    bundle = dict(bundle or {})
    return (
        str(bundle.get("fetched_at") or ""),
        tuple(str(symbol).strip().upper() for symbol in list(bundle.get("symbols", []) or []) if str(symbol).strip()),
        len(list(bundle.get("events", []) or [])),
        len(list(bundle.get("source_reports", []) or [])),
    )


def _latest_data_timestamp(data):
    timestamps = [
        _parse_iso_datetime((data or {}).get("prices_last_updated")),
        _parse_iso_datetime((data or {}).get("last_updated")),
    ]
    valid = [item for item in timestamps if item is not None]
    if not valid:
        return None
    return max(valid)


def _snapshot_is_current(
    snapshot,
    *,
    data=None,
    history_period=None,
    risk_regime=None,
    allocation_regime=None,
):
    snapshot = dict(snapshot or {})
    generated_at = _parse_iso_datetime(snapshot.get("generated_at"))
    if generated_at is None:
        return False
    if history_period and snapshot.get("history_period") not in (None, "", history_period):
        return False
    if risk_regime and str(snapshot.get("risk_regime") or "").strip().upper() not in ("", str(risk_regime).strip().upper()):
        return False
    if allocation_regime and str(snapshot.get("allocation_regime") or "").strip().upper() not in ("", str(allocation_regime).strip().upper()):
        return False
    data_timestamp = _latest_data_timestamp(data)
    if data_timestamp is not None and generated_at < data_timestamp:
        return False
    return True


def clear_runtime_caches():
    load_historical_data_cached.clear()
    load_correlation_matrix_cached.clear()
    load_cached_state_payloads.clear()
    st.session_state.pop("_derived_ui_context_cache", None)


def _format_ts_for_status(value):
    parsed = _parse_iso_datetime(value)
    if parsed is None:
        return ""
    return parsed.isoformat()


def _background_refresh_status(*, data, event_fetch_bundle):
    now = datetime.now()
    price_last_updated = _format_ts_for_status((data or {}).get("prices_last_updated"))
    event_last_updated = _format_ts_for_status(dict(event_fetch_bundle or {}).get("fetched_at"))
    price_next_due_at = ""
    event_next_due_at = ""

    price_last_dt = _parse_iso_datetime(price_last_updated)
    if price_last_dt is not None:
        price_next_due_at = (price_last_dt.timestamp() + float(AUTO_REFRESH_INTERVAL_SECONDS))
        price_next_due_at = datetime.fromtimestamp(price_next_due_at).isoformat()

    event_last_dt = _parse_iso_datetime(event_last_updated)
    if event_last_dt is not None:
        event_interval = (
            2
            if DEFER_INITIAL_EVENT_FETCH and not event_fetch_bundle
            else NEWS_AUTO_REFRESH_INTERVAL_SECONDS
        )
        event_next_due_at = datetime.fromtimestamp(
            event_last_dt.timestamp() + float(event_interval)
        ).isoformat()
    elif DEFER_INITIAL_EVENT_FETCH:
        event_next_due_at = datetime.fromtimestamp(now.timestamp() + 2.0).isoformat()

    return {
        "run_all_mode": RUN_ALL_MODE,
        "startup_refresh_deferred": DEFER_STARTUP_REFRESH,
        "initial_event_fetch_deferred": DEFER_INITIAL_EVENT_FETCH,
        "price_last_updated": price_last_updated,
        "event_last_updated": event_last_updated,
        "price_refresh_interval_seconds": AUTO_REFRESH_INTERVAL_SECONDS,
        "event_refresh_interval_seconds": NEWS_AUTO_REFRESH_INTERVAL_SECONDS,
        "price_next_due_at": price_next_due_at,
        "event_next_due_at": event_next_due_at,
    }


def _summarize_perf_history(history, *, current_page):
    rows = list(history or [])
    if not rows:
        return {}
    recent = rows[-10:]
    current_page_rows = [row for row in recent if str(row.get("page") or "") == str(current_page or "")]

    def _avg_ms(items, key):
        if not items:
            return None
        values = [float(item.get(key) or 0.0) for item in items]
        if not values:
            return None
        return sum(values) / len(values)

    return {
        "last": dict(rows[-1] or {}),
        "avg_total_ms_last_10": _avg_ms(recent, "total_ms"),
        "avg_context_ms_last_10": _avg_ms(recent, "context_ms"),
        "avg_render_ms_current_page": _avg_ms(current_page_rows, "page_render_ms"),
        "samples": len(recent),
    }


def _record_ui_perf(*, page, bootstrap_ms, context_ms, page_render_ms, total_ms):
    entry = {
        "recorded_at": datetime.now().isoformat(),
        "page": str(page or ""),
        "bootstrap_ms": round(float(bootstrap_ms or 0.0), 1),
        "context_ms": round(float(context_ms or 0.0), 1),
        "page_render_ms": round(float(page_render_ms or 0.0), 1),
        "total_ms": round(float(total_ms or 0.0), 1),
    }
    history = list(st.session_state.get("_ui_perf_history", []) or [])
    history.append(entry)
    history = history[-20:]
    st.session_state["_ui_perf_history"] = history
    st.session_state["_ui_perf_last"] = entry
    st.session_state["_ui_perf_summary"] = _summarize_perf_history(
        history,
        current_page=page,
    )


def render_flash_notice(session_key):
    notice = st.session_state.pop(session_key, None)
    if not isinstance(notice, dict):
        return
    level = str(notice.get("level", "info")).lower()
    message = str(notice.get("message", "") or "").strip()
    if not message:
        return
    if level == "success":
        st.success(message)
    elif level == "warning":
        st.warning(message)
    elif level == "error":
        st.error(message)
    else:
        st.info(message)


def _scoreboard_to_dict(scoreboard):
    if scoreboard is None:
        return {}
    return {
        "completed_trades": int(getattr(scoreboard, "completed_trades", 0) or 0),
        "win_rate": getattr(scoreboard, "win_rate", None),
        "avg_return_pct": getattr(scoreboard, "avg_return_pct", None),
        "avg_win_return_pct": getattr(scoreboard, "avg_win_return_pct", None),
        "avg_loss_return_pct": getattr(scoreboard, "avg_loss_return_pct", None),
        "payoff_ratio": getattr(scoreboard, "payoff_ratio", None),
        "expectancy_return_pct": getattr(scoreboard, "expectancy_return_pct", None),
        "profit_factor": getattr(scoreboard, "profit_factor", None),
        "median_holding_days": getattr(scoreboard, "median_holding_days", None),
        "cumulative_return_pct": getattr(scoreboard, "cumulative_return_pct", None),
        "max_drawdown_pct": getattr(scoreboard, "max_drawdown_pct", None),
        "regime_breakdown": [
            {
                "regime": item.regime,
                "trades": item.trades,
                "win_rate": item.win_rate,
                "avg_return_pct": item.avg_return_pct,
            }
            for item in list(getattr(scoreboard, "regime_breakdown", []) or [])
        ],
    }


def handle_force_market_refresh():
    with st.spinner(ui_text("正在强制刷新行情...", "Forcing a fresh market-data refresh...")):
        md.reset_market_data_status()
        updated = pactions.refresh_all_market_data(force_source_refresh=True)
        clear_runtime_caches()
        refresh_status = md.get_market_data_status_snapshot()
        refresh_notice = ui.build_manual_refresh_notice(
            refresh_status,
            tracked_symbol_count=len(rt.collect_tracked_symbols(updated)),
            lang=st.session_state.get("lang", "zh"),
        )
        st.session_state["manual_refresh_notice"] = refresh_notice
        st.session_state.app_data = updated
        du.save_data(updated)
        st.rerun()


def handle_refresh_news():
    with st.spinner(ui_text("正在刷新新闻与事件...", "Refreshing news and event sources...")):
        symbols_for_news = rt.collect_tracked_symbols(st.session_state.app_data)
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
        st.success(
            ui_text(
                f"新闻刷新完成，共抓取 {len(events)} 条事件。",
                f"News refresh completed with {len(events)} events.",
            )
        )
        st.rerun()


def _noop_slack_sender(message, webhook_url):
    return True, "suppressed"


def _noop_email_sender(subject, body, email_cfg):
    return True, "suppressed"


def _noop_message_router(delivery_type, subject, body, *, config=None, environ=None):
    return [{"channel": "noop", "ok": True, "message": "suppressed", "delivery_type": delivery_type}]


def handle_force_full_system_refresh():
    with st.spinner(ui_text("正在强制补齐整套系统数据...", "Running a full system backfill now...")):
        refreshed_data = pactions.refresh_all_market_data(force_source_refresh=True)
        st.session_state.app_data = refreshed_data
        du.save_data(refreshed_data)
        run_nightly_alerts(
            now=datetime.now(),
            force=True,
            dry_run=False,
            history_period=st.session_state.get("history_period", "2y"),
            with_strategy_comparison=True,
            slack_sender=_noop_slack_sender,
            email_sender=_noop_email_sender,
            message_router=_noop_message_router,
        )
        clear_runtime_caches()
        st.session_state.pop("event_fetch_bundle", None)
        st.session_state.app_data = du.load_data()
        st.session_state["manual_refresh_notice"] = {
            "level": "success",
            "message": ui_text(
                "已完成一次无通知的全量补齐运行。nightly 快照、候选池、报告和计划单都已更新。",
                "A no-delivery full backfill run is complete. Nightly snapshots, candidate pools, reports, and trade plans have been refreshed.",
            ),
        }
        st.rerun()


def handle_reload_editable_data():
    if not du.editable_data_file_exists():
        st.warning(ui_text("未检测到可编辑数据文件。", "Editable data file was not found."))
        return
    try:
        clear_runtime_caches()
        st.session_state.app_data = du.load_data(force_editable_sync=True)
        st.success(ui_text("已从可编辑数据文件重新载入。", "Reloaded from the editable data file."))
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))


def handle_manual_tcn_retrain(deep_tcn_strategy):
    if not deep_tcn_strategy:
        st.info(ui_text("当前没有启用 TCN 默认策略。", "No default TCN strategy is configured right now."))
        return
    import deep_learning_strategy as dl_utils

    with st.spinner(ui_text("正在手动重训 TCN...", "Running manual TCN retraining...")):
        refreshed_data = du.refresh_market_data(st.session_state.app_data)
        st.session_state.app_data = refreshed_data
        du.save_data(refreshed_data)
        clear_runtime_caches()
        symbols_for_retrain = rt.collect_tracked_symbols(st.session_state.app_data)
        manual_params = dict(deep_tcn_strategy.get("params", {}))
        manual_params["period"] = st.session_state.history_period
        ok, retrain_message = dl_utils.run_nightly_retraining_for_symbols(
            symbols_for_retrain,
            params=manual_params,
            force=True,
        )
        st.session_state.nightly_retrain_status = retrain_message
        if ok:
            st.success(ui_text("TCN 手动重训已完成。", "Manual TCN retraining completed."))
        else:
            st.warning(retrain_message)
        st.rerun()


def save_account_config(current_data, *, cash_available, min_cash_buffer_pct, max_single_position_pct, max_total_exposure_pct):
    current_data["account"] = {
        "total_capital": None,
        "cash_available": float(cash_available),
        "min_cash_buffer_pct": float(min_cash_buffer_pct) / 100.0,
        "max_single_position_pct": float(max_single_position_pct) / 100.0,
        "max_total_exposure_pct": float(max_total_exposure_pct) / 100.0,
    }
    du.save_data(current_data)
    clear_runtime_caches()
    st.session_state.app_data = du.load_data()
    st.success(ui_text("资金参数已保存。", "Capital settings saved."))
    st.rerun()


def rebuild_latest_quant_report(*, data, strategy_runtime, market_risk_gate_decision, allocation_regime_decision):
    with st.spinner(ui_text("正在生成组合级量化报告...", "Generating the portfolio-level quant report...")):
        try:
            from engine import BacktraderEngine

            report_snapshot = qpa.build_portfolio_quant_analysis_snapshot(
                data,
                strategy=strategy_runtime,
                history_period=st.session_state.get("history_period", "2y"),
                engine_name="backtrader",
                engine_factory_fn=lambda: BacktraderEngine(initial_cash=100000),
                risk_gate=market_risk_gate_decision,
                allocation_regime=allocation_regime_decision,
                now=datetime.now(),
            )
            report_text = nr.build_quant_analysis_report(report_snapshot)
            report_files = nr.save_quant_analysis_report_files(
                report_snapshot,
                report_text=report_text,
            )
            qpa.save_quant_analysis_snapshot(report_snapshot)
            st.session_state.latest_quant_analysis_report = {
                "snapshot": report_snapshot,
                "files": report_files,
            }
            clear_runtime_caches()
            st.success(ui_text("组合量化报告已生成。", "The portfolio quant report has been generated."))
            st.rerun()
        except Exception as exc:
            st.error(f"{ui_text('生成报告失败', 'Report generation failed')}: {exc}")


def explain_core_etf_row(row, *, discipline_snapshot, latest_change_feed):
    config = ncfg.load_notification_config()
    ok, message, meta = lexp.explain_core_etf_decision(
        symbol_row=row,
        notification_config=config,
        discipline_snapshot=discipline_snapshot,
        change_feed=latest_change_feed,
        complexity="explanation",
    )
    symbol = str(dict(row or {}).get("symbol") or "").strip().upper()
    if ok and symbol:
        explanations = dict(st.session_state.get("core_etf_llm_explanations", {}) or {})
        route_name = str((meta or {}).get("route_name") or "").strip()
        model_name = str((meta or {}).get("model") or "").strip()
        label_bits = [item for item in [route_name, model_name] if item]
        if (meta or {}).get("cached"):
            label_bits.append("cached")
        explanations[symbol] = {
            "text": str(message or "").strip(),
            "label": " | ".join(label_bits),
        }
        st.session_state["core_etf_llm_explanations"] = explanations
    return ok, message, meta


def _build_llm_route_label(meta):
    route_name = str((meta or {}).get("route_name") or "").strip()
    model_name = str((meta or {}).get("model") or "").strip()
    label_bits = [item for item in [route_name, model_name] if item]
    if (meta or {}).get("cached"):
        label_bits.append("cached")
    return " | ".join(label_bits)


def narrate_change_feed(*, latest_change_feed, monthly_discipline_review):
    config = ncfg.load_notification_config()
    ok, message, meta = lexp.narrate_change_feed(
        change_feed=latest_change_feed,
        monthly_discipline_review=monthly_discipline_review,
        notification_config=config,
    )
    if ok:
        st.session_state["change_feed_llm_narration"] = {
            "text": str(message or "").strip(),
            "label": _build_llm_route_label(meta),
        }
    return ok, message, meta


def explain_change_feed(*, latest_change_feed, monthly_discipline_review):
    config = ncfg.load_notification_config()
    ok, message, meta = lexp.explain_change_feed(
        change_feed=latest_change_feed,
        monthly_discipline_review=monthly_discipline_review,
        notification_config=config,
    )
    if ok:
        st.session_state["change_feed_llm_explanation"] = {
            "text": str(message or "").strip(),
            "label": _build_llm_route_label(meta),
        }
    return ok, message, meta


def narrate_discipline_review(*, monthly_discipline_review, discipline_snapshot, latest_post_close_review):
    config = ncfg.load_notification_config()
    ok, message, meta = lexp.narrate_discipline_review(
        review=monthly_discipline_review,
        discipline_snapshot=discipline_snapshot,
        latest_post_close_review=latest_post_close_review,
        notification_config=config,
    )
    if ok:
        st.session_state["discipline_review_llm_narration"] = {
            "text": str(message or "").strip(),
            "label": _build_llm_route_label(meta),
        }
    return ok, message, meta


def explain_discipline_review(*, monthly_discipline_review, discipline_snapshot, latest_post_close_review):
    config = ncfg.load_notification_config()
    ok, message, meta = lexp.explain_discipline_review(
        review=monthly_discipline_review,
        discipline_snapshot=discipline_snapshot,
        latest_post_close_review=latest_post_close_review,
        notification_config=config,
    )
    if ok:
        st.session_state["discipline_review_llm_explanation"] = {
            "text": str(message or "").strip(),
            "label": _build_llm_route_label(meta),
        }
    return ok, message, meta


def get_or_build_derived_ui_context(
    *,
    data,
    history_period,
    strategies,
    selected_strategy_id,
    default_strategy_id,
    include_holdings_records=False,
    include_watchlist_records=False,
    include_core_holdings_df=False,
    include_satellite_holdings_df=False,
    include_latest_report=False,
    allow_expensive_rebuilds=True,
):
    now = datetime.now()
    tracked_symbols = rt.collect_tracked_symbols(data)
    fetched_events, fetched_reports, _ = rt.fetch_news_events_with_cache(
        session_state=st.session_state,
        fetcher_module=ef,
        symbols=tracked_symbols,
        interval_seconds=NEWS_AUTO_REFRESH_INTERVAL_SECONDS,
        allow_initial_fetch=not DEFER_INITIAL_EVENT_FETCH,
        now=now,
    )
    state_signature = _state_payload_signature()
    cache_key = (
        _data_signature(data),
        str(history_period or ""),
        str(selected_strategy_id or ""),
        str(default_strategy_id or ""),
        bool(include_holdings_records),
        bool(include_watchlist_records),
        bool(include_core_holdings_df),
        bool(include_satellite_holdings_df),
        bool(include_latest_report),
        str(
            (
                dict(st.session_state.get("latest_quant_analysis_report", {}) or {}).get("snapshot", {}) or {}
            ).get("generated_at")
            or ""
        ),
        _event_bundle_signature(st.session_state.get("event_fetch_bundle")),
        state_signature,
    )
    cached = st.session_state.get("_derived_ui_context_cache")
    if isinstance(cached, dict) and cached.get("key") == cache_key:
        return cached.get("context", {})

    state_payloads = load_cached_state_payloads(state_signature)
    analyst_consensus_cache = state_payloads.get("analyst_consensus_cache") or {}
    quant_analysis_snapshot = state_payloads.get("quant_analysis_snapshot")
    latest_trade_plan = state_payloads.get("latest_trade_plan") or {}
    latest_post_close_review = state_payloads.get("latest_post_close_review") or {}
    latest_change_feed = state_payloads.get("latest_change_feed") or {}
    latest_nightly_manifest = state_payloads.get("latest_nightly_manifest") or {}
    nightly_snapshot_journal = list(state_payloads.get("nightly_snapshot_journal") or [])
    intraday_event_rows = list(state_payloads.get("intraday_event_rows") or [])
    intraday_event_summary = ij.summarize_intraday_events(intraday_event_rows)

    market_risk_gate_decision = None
    market_risk_snapshot = None
    portfolio_risk_advice = None
    portfolio_corr_matrix = None
    active_market_events = []
    event_risk_decision = None
    event_source_reports = []
    if data.get("holdings"):
        try:
            (
                market_risk_gate_decision,
                market_risk_snapshot,
                portfolio_risk_advice,
                portfolio_corr_matrix,
                active_market_events,
                event_risk_decision,
                event_source_reports,
            ) = rt.evaluate_market_risk_for_portfolio(
                holdings=data["holdings"],
                history_period=history_period,
                load_historical_data_fn=load_historical_data_cached,
                load_correlation_matrix_fn=load_correlation_matrix_cached,
                analyze_portfolio_risk_fn=analyze_portfolio_risk,
                build_market_risk_snapshot_fn=build_market_risk_snapshot_from_histories,
                evaluate_market_risk_gate_fn=evaluate_market_risk_gate,
                select_active_events_fn=en.select_active_events,
                evaluate_event_risk_switch_fn=en.evaluate_event_risk_switch,
                merge_risk_gate_decisions_fn=merge_risk_gate_decisions,
                fetch_events_from_sources_fn=ef.fetch_events_from_sources,
                event_symbols=tracked_symbols,
                now=now,
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

    transaction_rows = tx.normalize_transactions(tx.load_transactions())
    try:
        scoreboard_benchmark_history = load_historical_data_cached("SPY", period=history_period)
    except Exception:
        scoreboard_benchmark_history = None
    live_scoreboard = build_signal_scoreboard(
        transaction_rows,
        benchmark_history=scoreboard_benchmark_history,
    )
    account_snapshot = ss.build_account_snapshot(data)
    allocation_regime_decision = evaluate_allocation_regime(
        live_scoreboard,
        risk_gate=market_risk_gate_decision,
        account_snapshot=account_snapshot,
    )
    current_risk_regime = str(getattr(market_risk_gate_decision, "regime", "NORMAL") or "NORMAL").upper() if market_risk_gate_decision is not None else "NORMAL"
    current_allocation_regime = str(getattr(allocation_regime_decision, "regime", "NORMAL") or "NORMAL").upper() if allocation_regime_decision is not None else "NORMAL"
    analysis_freshness_alert = ui.build_holdings_analysis_freshness_alert(
        data.get("holdings", []),
        quant_analysis_snapshot,
        now=now,
    )

    core_etf_universe = cer.load_core_etf_universe()
    core_etf_symbols = [
        str(row.get("symbol") or "").strip().upper()
        for row in list(core_etf_universe.get("etfs", []) or [])
        if bool(row.get("enabled", True))
    ]

    loaded_core_etf_snapshot = state_payloads.get("core_etf_snapshot")
    if loaded_core_etf_snapshot and (
        _snapshot_is_current(
            loaded_core_etf_snapshot,
            data=data,
            risk_regime=current_risk_regime,
            allocation_regime=current_allocation_regime,
        )
        or not allow_expensive_rebuilds
    ):
        core_etf_rotation_snapshot = None
        core_etf_snapshot = loaded_core_etf_snapshot
    else:
        core_etf_rotation_snapshot = cer.build_core_etf_rotation_snapshot(
            data=data,
            history_period=history_period,
            load_historical_data_fn=load_historical_data_cached,
            universe=core_etf_universe,
            risk_gate=market_risk_gate_decision,
            allocation_regime=allocation_regime_decision,
            now=now,
        )
        core_etf_snapshot = cee.build_core_etf_snapshot(
            data=data,
            account_snapshot=account_snapshot,
            rotation_snapshot=core_etf_rotation_snapshot,
            risk_gate=market_risk_gate_decision,
            allocation_regime=allocation_regime_decision,
            previous_snapshot=loaded_core_etf_snapshot,
            now=now,
        )

    loaded_discipline_snapshot = state_payloads.get("discipline_snapshot")
    if loaded_discipline_snapshot and (
        _snapshot_is_current(
            loaded_discipline_snapshot,
            data=data,
            risk_regime=current_risk_regime,
            allocation_regime=current_allocation_regime,
        )
        or not allow_expensive_rebuilds
    ):
        discipline_snapshot = loaded_discipline_snapshot
    else:
        discipline_snapshot = qdisc.build_discipline_snapshot(
            account_snapshot=account_snapshot,
            risk_gate=market_risk_gate_decision,
            allocation_regime=allocation_regime_decision,
            analysis_freshness_alert=analysis_freshness_alert,
            core_etf_snapshot=core_etf_snapshot,
            now=now,
        )

    monthly_discipline_review = qdisc.build_monthly_discipline_review(
        discipline_snapshot=discipline_snapshot,
        scoreboard=live_scoreboard,
        latest_post_close_review=latest_post_close_review,
        snapshot_journal=nightly_snapshot_journal,
        now=now,
    )

    strategy_map = {strategy["id"]: strategy for strategy in strategies}
    dashboard_strategy = strategy_map.get(selected_strategy_id, strategies[0])
    dashboard_strategy_runtime = rt.apply_runtime_strategy_params(
        dashboard_strategy,
        history_period=history_period,
    )

    loaded_satellite_candidate_snapshot = state_payloads.get("satellite_candidate_snapshot")
    use_saved_satellite_snapshot = bool(loaded_satellite_candidate_snapshot) and selected_strategy_id == default_strategy_id and (
        _snapshot_is_current(
            loaded_satellite_candidate_snapshot,
            data=data,
            history_period=history_period,
        )
        or not allow_expensive_rebuilds
    )
    if use_saved_satellite_snapshot:
        satellite_candidate_snapshot = loaded_satellite_candidate_snapshot
    elif dashboard_strategy_runtime:
        satellite_candidate_snapshot = cpool.build_satellite_candidate_pool_snapshot(
            data=data,
            strategy=dashboard_strategy_runtime,
            history_period=history_period,
            load_historical_data_fn=load_historical_data_cached,
            universe=cpool.load_satellite_universe(),
            core_symbols=set(core_etf_symbols),
            discipline_snapshot=discipline_snapshot,
            policy=cer.load_engine_policy(),
            risk_gate=market_risk_gate_decision,
            allocation_regime=allocation_regime_decision,
            now=now,
        )
    else:
        satellite_candidate_snapshot = loaded_satellite_candidate_snapshot

    dashboard_portfolio_summary = summarize_holdings(data["holdings"])
    holding_records = []
    watchlist_records = []
    core_holdings_df = None
    satellite_holdings_df = None
    if include_holdings_records or include_watchlist_records or include_core_holdings_df or include_satellite_holdings_df:
        holding_records = ui.build_holding_records(
            data.get("holdings", []),
            dashboard_strategy_runtime,
            dashboard_portfolio_summary.total_value,
            risk_gate=market_risk_gate_decision,
            analyst_consensus_cache=analyst_consensus_cache,
            allocation_regime=allocation_regime_decision,
            analysis_snapshot=quant_analysis_snapshot,
            analysis_now=now,
        )
    if include_watchlist_records:
        watchlist_records = ui.build_watchlist_records(
            data.get("watchlist", []),
            strategy=dashboard_strategy_runtime,
            analyst_consensus_cache=analyst_consensus_cache,
            account=data.get("account", {}),
            risk_gate=market_risk_gate_decision,
            allocation_regime=allocation_regime_decision,
            current_invested_dollars=dashboard_portfolio_summary.total_value,
            analysis_snapshot=quant_analysis_snapshot,
            analysis_now=now,
            active_events=active_market_events,
        )
    if include_core_holdings_df:
        core_holdings_df = pg.build_holdings_focus_dataframe(
            holding_records,
            include_symbols=core_etf_symbols,
        )
    if include_satellite_holdings_df:
        satellite_holdings_df = pg.build_holdings_focus_dataframe(
            holding_records,
            exclude_symbols=core_etf_symbols,
        )

    latest_report_snapshot = None
    latest_report_files = {}
    if include_latest_report:
        latest_report_bundle = st.session_state.get("latest_quant_analysis_report", {})
        latest_report_snapshot = (
            latest_report_bundle.get("snapshot")
            if isinstance(latest_report_bundle, dict)
            else None
        ) or state_payloads.get("latest_report_snapshot")
        latest_report_files = {
            **nr.get_quant_analysis_report_latest_paths(),
            **(
                dict(latest_report_bundle.get("files", {}) or {})
                if isinstance(latest_report_bundle, dict)
                else {}
            ),
        }

    context = {
        "now": now,
        "tracked_symbols": tracked_symbols,
        "analyst_consensus_cache": analyst_consensus_cache,
        "quant_analysis_snapshot": quant_analysis_snapshot,
        "latest_trade_plan": latest_trade_plan,
        "latest_post_close_review": latest_post_close_review,
        "latest_change_feed": latest_change_feed,
        "latest_nightly_manifest": latest_nightly_manifest,
        "nightly_snapshot_journal": nightly_snapshot_journal,
        "intraday_event_rows": intraday_event_rows,
        "intraday_event_summary": intraday_event_summary,
        "market_risk_gate_decision": market_risk_gate_decision,
        "market_risk_snapshot": market_risk_snapshot,
        "portfolio_risk_advice": portfolio_risk_advice,
        "portfolio_corr_matrix": portfolio_corr_matrix,
        "active_market_events": active_market_events,
        "event_risk_decision": event_risk_decision,
        "event_source_reports": event_source_reports,
        "transaction_rows": transaction_rows,
        "live_scoreboard": live_scoreboard,
        "account_snapshot": account_snapshot,
        "allocation_regime_decision": allocation_regime_decision,
        "analysis_freshness_alert": analysis_freshness_alert,
        "core_etf_universe": core_etf_universe,
        "core_etf_symbols": core_etf_symbols,
        "core_etf_rotation_snapshot": core_etf_rotation_snapshot,
        "core_etf_snapshot": core_etf_snapshot,
        "discipline_snapshot": discipline_snapshot,
        "monthly_discipline_review": monthly_discipline_review,
        "dashboard_strategy_runtime": dashboard_strategy_runtime,
        "satellite_candidate_snapshot": satellite_candidate_snapshot,
        "dashboard_portfolio_summary": dashboard_portfolio_summary,
        "holding_records": holding_records,
        "watchlist_records": watchlist_records,
        "core_holdings_df": core_holdings_df,
        "satellite_holdings_df": satellite_holdings_df,
        "latest_report_snapshot": latest_report_snapshot,
        "latest_report_files": latest_report_files,
    }
    st.session_state["_derived_ui_context_cache"] = {
        "key": cache_key,
        "context": context,
    }
    return context


script_started_at = time.perf_counter()
bootstrap_started_at = time.perf_counter()
try:
    rt.bootstrap_app_data(
        st.session_state,
        du,
        refresh_interval_seconds=AUTO_REFRESH_INTERVAL_SECONDS,
        allow_startup_refresh=not DEFER_STARTUP_REFRESH,
    )
except ValueError as exc:
    st.error(f"数据文件加载失败: {exc}")
    st.stop()
bootstrap_elapsed_ms = (time.perf_counter() - bootstrap_started_at) * 1000.0

data = st.session_state.app_data
market_events_bootstrapped = en.ensure_market_events_file()

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

if deep_tcn_strategy:
    st.session_state.nightly_retrain_status = ui_text(
        "前台仅做推理与展示；夜间重训交给 nightly / run_all，或使用手动重训按钮。",
        "The UI only handles inference and display; nightly retraining is handled by nightly / run_all, or by the manual retrain button.",
    )

st.session_state.analyst_consensus_status = ui_text(
    "前台仅读取夜间分析师缓存；分析师更新交给 nightly / run_all。",
    "The UI reads the nightly analyst cache only; analyst refresh is handled by nightly / run_all.",
)

data = st.session_state.app_data

L = lambda key, **kwargs: loc.get_text(st.session_state.lang, key, **kwargs)

news_rerun_interval_seconds = (
    2
    if DEFER_INITIAL_EVENT_FETCH and "event_fetch_bundle" not in st.session_state
    else NEWS_AUTO_REFRESH_INTERVAL_SECONDS
)

rt.enable_auto_news_rerun(
    session_state=st.session_state,
    interval_seconds=news_rerun_interval_seconds,
    st_module=st,
)

uc.inject_cockpit_styles(st_module=st)
st.title(ui_text("量化交易驾驶舱", "Quant Trading Cockpit"))
st.caption(
    ui_text(
        "夜间生成次日计划，盘中只看紧急风险与计划触发，收盘后再用 Robinhood CSV 回流复盘。",
        "The system plans at night, watches only urgent risk and planned triggers intraday, and reviews against Robinhood CSV after the close.",
    )
)
render_flash_notice("manual_refresh_notice")
page_options = {
    "dashboard": ui_text("🏠 Dashboard", "🏠 Dashboard"),
    "core": ui_text("🧭 Core ETFs", "🧭 Core ETFs"),
    "satellite": ui_text("🚀 Satellite Radar", "🚀 Satellite Radar"),
    "risk": ui_text("🛡️ Risk & Discipline", "🛡️ Risk & Discipline"),
    "ops": ui_text("🧰 Operations", "🧰 Operations"),
    "settings": ui_text("⚙️ Settings", "⚙️ Settings"),
}
if "active_page" not in st.session_state or st.session_state.active_page not in page_options:
    st.session_state.active_page = "dashboard"
selected_page_label = st.radio(
    ui_text("导航", "Navigation"),
    options=list(page_options.values()),
    index=list(page_options.keys()).index(st.session_state.active_page),
    horizontal=True,
    label_visibility="collapsed",
)
active_page = next(
    (page_key for page_key, page_label in page_options.items() if page_label == selected_page_label),
    "dashboard",
)
st.session_state.active_page = active_page

context_started_at = time.perf_counter()
derived_context = get_or_build_derived_ui_context(
    data=data,
    history_period=st.session_state.history_period,
    strategies=strategies,
    selected_strategy_id=st.session_state.selected_strategy_id,
    default_strategy_id=default_strategy_id,
    include_holdings_records=active_page in {"core", "satellite"},
    include_watchlist_records=False,
    include_core_holdings_df=active_page == "core",
    include_satellite_holdings_df=active_page == "satellite",
    include_latest_report=active_page == "ops",
    allow_expensive_rebuilds=active_page in {"core", "satellite", "risk"},
)
context_elapsed_ms = (time.perf_counter() - context_started_at) * 1000.0
analyst_consensus_cache = derived_context["analyst_consensus_cache"]
quant_analysis_snapshot = derived_context["quant_analysis_snapshot"]
latest_trade_plan = derived_context["latest_trade_plan"]
latest_post_close_review = derived_context["latest_post_close_review"]
latest_change_feed = derived_context["latest_change_feed"]
latest_nightly_manifest = derived_context["latest_nightly_manifest"]
nightly_snapshot_journal = derived_context["nightly_snapshot_journal"]
intraday_event_summary = derived_context["intraday_event_summary"]
market_risk_gate_decision = derived_context["market_risk_gate_decision"]
market_risk_snapshot = derived_context["market_risk_snapshot"]
active_market_events = derived_context["active_market_events"]
event_risk_decision = derived_context["event_risk_decision"]
event_source_reports = derived_context["event_source_reports"]
live_scoreboard = derived_context["live_scoreboard"]
account_snapshot = derived_context["account_snapshot"]
allocation_regime_decision = derived_context["allocation_regime_decision"]
analysis_freshness_alert = derived_context["analysis_freshness_alert"]
core_etf_symbols = derived_context["core_etf_symbols"]
core_etf_snapshot = derived_context["core_etf_snapshot"]
discipline_snapshot = derived_context["discipline_snapshot"]
monthly_discipline_review = derived_context["monthly_discipline_review"]
dashboard_strategy_runtime = derived_context["dashboard_strategy_runtime"]
satellite_candidate_snapshot = derived_context["satellite_candidate_snapshot"]
holding_records = derived_context["holding_records"]
watchlist_records = derived_context["watchlist_records"]
core_holdings_df = derived_context["core_holdings_df"]
satellite_holdings_df = derived_context["satellite_holdings_df"]
latest_report_snapshot = derived_context["latest_report_snapshot"]
latest_report_files = derived_context["latest_report_files"]
trade_plan_banner = ui.build_trade_plan_banner(
    latest_trade_plan,
    lang=st.session_state.get("lang", "zh"),
)
refresh_runtime_status = _background_refresh_status(
    data=data,
    event_fetch_bundle=st.session_state.get("event_fetch_bundle"),
)

page_render_started_at = time.perf_counter()
if active_page == "dashboard":
    uc.render_dashboard_page(
        ui_text=ui_text,
        latest_trade_plan=latest_trade_plan,
        latest_post_close_review=latest_post_close_review,
        trade_plan_banner=trade_plan_banner,
        latest_change_feed=latest_change_feed,
        change_feed_narration=str(dict(st.session_state.get("change_feed_llm_narration", {}) or {}).get("text") or "").strip(),
        change_feed_explanation=str(dict(st.session_state.get("change_feed_llm_explanation", {}) or {}).get("text") or "").strip(),
        narrate_change_feed_fn=lambda: narrate_change_feed(
            latest_change_feed=latest_change_feed,
            monthly_discipline_review=monthly_discipline_review,
        ),
        explain_change_feed_fn=lambda: explain_change_feed(
            latest_change_feed=latest_change_feed,
            monthly_discipline_review=monthly_discipline_review,
        ),
        latest_nightly_manifest=latest_nightly_manifest,
        account_snapshot=account_snapshot,
        data_source_status=md.get_market_data_status_snapshot(),
        refresh_runtime_status=refresh_runtime_status,
        ui_performance_snapshot=st.session_state.get("_ui_perf_summary", {}),
        allocation_regime_decision=allocation_regime_decision,
        discipline_snapshot=discipline_snapshot,
        monthly_discipline_review=monthly_discipline_review,
        live_scoreboard=live_scoreboard,
        market_risk_gate_decision=market_risk_gate_decision,
        market_risk_snapshot=market_risk_snapshot,
        analysis_freshness_alert=analysis_freshness_alert,
        active_market_events=active_market_events,
        event_risk_decision=event_risk_decision,
        event_source_reports=event_source_reports,
        intraday_event_summary=intraday_event_summary,
        L=L,
        core_etf_snapshot=core_etf_snapshot,
        satellite_candidate_snapshot=satellite_candidate_snapshot,
        st_module=st,
        lang=st.session_state.get("lang", "zh"),
    )
elif active_page == "core":
    st.header(ui_text("核心 ETF 引擎", "Core ETF Engine"))
    st.caption(
        ui_text(
            "这一页只处理核心仓，展示候选 ETF、轮动结论、目标权重和价位区间。",
            "This page is core-book only, showing the ETF universe, rotation conclusion, target weights, and price zones.",
        )
    )
    uc.render_core_etfs_page(
        core_etf_snapshot=core_etf_snapshot,
        core_holdings_df=core_holdings_df,
        llm_explanations=st.session_state.get("core_etf_llm_explanations", {}),
        explain_core_etf_fn=lambda row: explain_core_etf_row(
            row,
            discipline_snapshot=discipline_snapshot,
            latest_change_feed=latest_change_feed,
        ),
        ui_text=ui_text,
        st_module=st,
    )
elif active_page == "satellite":
    st.header(ui_text("卫星仓雷达", "Satellite Radar"))
    st.caption(
        ui_text(
            "这一页聚焦 Top 3 候选、候选池 Top 10 和当前卫星仓，由 nightly 快照统一驱动。",
            "This page focuses on the Top 3 names, the Top 10 candidate pool, and current satellite positions, all driven by the nightly snapshot.",
        )
    )
    uc.render_satellite_radar_page(
        satellite_candidate_snapshot=satellite_candidate_snapshot,
        satellite_holdings_df=satellite_holdings_df,
        ui_text=ui_text,
        active_market_events=active_market_events,
        event_risk_decision=event_risk_decision,
        event_source_reports=event_source_reports,
        L=L,
        st_module=st,
        lang=st.session_state.get("lang", "zh"),
    )
elif active_page == "risk":
    st.header(ui_text("纪律与风险", "Risk & Discipline"))
    st.caption(
        ui_text(
            "这页专门回答两件事：为什么不能重仓，为什么今天不该追价。所有阻断条件、分析过期和风险状态都在这里集中展示。",
            "This page answers two questions: why you should not go heavy right now, and why you should not chase. All blocking reasons, stale analysis, and risk states are centralized here.",
        )
    )
    uc.render_risk_page(
        ui_text=ui_text,
        discipline_snapshot=discipline_snapshot,
        monthly_discipline_review=monthly_discipline_review,
        discipline_review_narration=str(dict(st.session_state.get("discipline_review_llm_narration", {}) or {}).get("text") or "").strip(),
        discipline_review_explanation=str(dict(st.session_state.get("discipline_review_llm_explanation", {}) or {}).get("text") or "").strip(),
        narrate_discipline_review_fn=lambda: narrate_discipline_review(
            monthly_discipline_review=monthly_discipline_review,
            discipline_snapshot=discipline_snapshot,
            latest_post_close_review=latest_post_close_review,
        ),
        explain_discipline_review_fn=lambda: explain_discipline_review(
            monthly_discipline_review=monthly_discipline_review,
            discipline_snapshot=discipline_snapshot,
            latest_post_close_review=latest_post_close_review,
        ),
        market_risk_gate_decision=market_risk_gate_decision,
        market_risk_snapshot=market_risk_snapshot,
        analysis_freshness_alert=analysis_freshness_alert,
        account_snapshot=account_snapshot,
        data_source_status=md.get_market_data_status_snapshot(),
        live_scoreboard=live_scoreboard,
        latest_change_feed=latest_change_feed,
        change_feed_narration=str(dict(st.session_state.get("change_feed_llm_narration", {}) or {}).get("text") or "").strip(),
        change_feed_explanation=str(dict(st.session_state.get("change_feed_llm_explanation", {}) or {}).get("text") or "").strip(),
        narrate_change_feed_fn=lambda: narrate_change_feed(
            latest_change_feed=latest_change_feed,
            monthly_discipline_review=monthly_discipline_review,
        ),
        explain_change_feed_fn=lambda: explain_change_feed(
            latest_change_feed=latest_change_feed,
            monthly_discipline_review=monthly_discipline_review,
        ),
        latest_post_close_review=latest_post_close_review,
        snapshot_journal=nightly_snapshot_journal,
        intraday_event_summary=intraday_event_summary,
        L=L,
        st_module=st,
    )
elif active_page == "ops":
    uc.render_control_center_page(
        ui_text=ui_text,
        latest_nightly_manifest=latest_nightly_manifest,
        latest_change_feed=latest_change_feed,
        change_feed_narration=str(dict(st.session_state.get("change_feed_llm_narration", {}) or {}).get("text") or "").strip(),
        change_feed_explanation=str(dict(st.session_state.get("change_feed_llm_explanation", {}) or {}).get("text") or "").strip(),
        narrate_change_feed_fn=lambda: narrate_change_feed(
            latest_change_feed=latest_change_feed,
            monthly_discipline_review=monthly_discipline_review,
        ),
        explain_change_feed_fn=lambda: explain_change_feed(
            latest_change_feed=latest_change_feed,
            monthly_discipline_review=monthly_discipline_review,
        ),
        latest_report_snapshot=latest_report_snapshot,
        latest_report_files=latest_report_files,
        market_events_bootstrapped=market_events_bootstrapped,
        market_events_file=en.MARKET_EVENTS_FILE,
        event_sources_config_path=ef.EVENT_SOURCES_CONFIG_PATH,
        analyst_consensus_cache_file=ac.ANALYST_CONSENSUS_CACHE_FILE,
        editable_data_file=du.EDITABLE_DATA_FILE,
        manual_portfolio_editor=uc.render_manual_portfolio_editor,
        transactions_renderer=pg.render_transactions_tab,
        tx_module=tx,
        L=L,
        format_share_quantity_fn=format_share_quantity,
        portfolio_actions_module=pactions,
        data_utils_module=du,
        session_state=st.session_state,
        report_rebuilder=lambda: rebuild_latest_quant_report(
            data=data,
            strategy_runtime=dashboard_strategy_runtime,
            market_risk_gate_decision=market_risk_gate_decision,
            allocation_regime_decision=allocation_regime_decision,
        ),
        st_module=st,
    )
else:
    cached_event_bundle = st.session_state.get("event_fetch_bundle", {})
    uc.render_settings_page(
        ui_text=ui_text,
        data=data,
        market_events_bootstrapped=market_events_bootstrapped,
        market_events_file=en.MARKET_EVENTS_FILE,
        event_sources_config_path=ef.EVENT_SOURCES_CONFIG_PATH,
        analyst_consensus_cache_file=ac.ANALYST_CONSENSUS_CACHE_FILE,
        editable_data_file=du.EDITABLE_DATA_FILE,
        account_config_saver=save_account_config,
        notification_renderer=unp.render_notification_config_page,
        ncfg_module=ncfg,
        nch_module=nch,
        session_state=st.session_state,
        history_period_options=HISTORY_PERIOD_OPTIONS,
        strategies=strategies,
        run_full_system_refresh_fn=handle_force_full_system_refresh,
        force_price_refresh_fn=handle_force_market_refresh,
        refresh_news_fn=handle_refresh_news,
        reload_editable_data_fn=handle_reload_editable_data,
        manual_tcn_retrain_fn=(lambda: handle_manual_tcn_retrain(deep_tcn_strategy)) if deep_tcn_strategy else None,
        nightly_retrain_status=st.session_state.get("nightly_retrain_status"),
        analyst_consensus_status=st.session_state.get("analyst_consensus_status"),
        last_price_refresh=data.get("prices_last_updated") or ui_text("尚未刷新", "Not refreshed yet"),
        last_news_refresh=(cached_event_bundle.get("fetched_at") if isinstance(cached_event_bundle, dict) else None),
        st_module=st,
    )

page_render_elapsed_ms = (time.perf_counter() - page_render_started_at) * 1000.0
total_elapsed_ms = (time.perf_counter() - script_started_at) * 1000.0
_record_ui_perf(
    page=active_page,
    bootstrap_ms=bootstrap_elapsed_ms,
    context_ms=context_elapsed_ms,
    page_render_ms=page_render_elapsed_ms,
    total_ms=total_elapsed_ms,
)

snapshot_alerts = pg.build_snapshot_alerts(active_market_events)
st.session_state.latest_system_snapshot = ss.build_system_snapshot(
    data=st.session_state.app_data,
    holding_records=holding_records,
    watchlist_records=watchlist_records,
    risk_gate=market_risk_gate_decision,
    alerts=snapshot_alerts,
    data_sources=md.get_market_data_status_snapshot(),
    performance={
        "live_scoreboard": _scoreboard_to_dict(live_scoreboard),
        "ui_performance": st.session_state.get("_ui_perf_last", {}),
    },
    allocation_regime=allocation_regime_decision.to_dict() if allocation_regime_decision is not None else {},
    trade_plan=latest_trade_plan,
    execution_review=latest_post_close_review,
    core_etf_snapshot=core_etf_snapshot,
    satellite_candidate_snapshot=satellite_candidate_snapshot,
    discipline_snapshot=discipline_snapshot,
    monthly_discipline_review=monthly_discipline_review,
    intraday_event_summary=intraday_event_summary,
    change_feed=latest_change_feed,
    nightly_manifest=latest_nightly_manifest,
)
