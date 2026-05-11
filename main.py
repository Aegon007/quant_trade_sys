import streamlit as st
import pandas as pd
from datetime import datetime
import os
from app.orchestration import runtime as rt
from app.ui import dialogs as ud
from app.ui import pages as pg
from app.ui import panels as up
from app.ui import notification_page as unp
from app.ui import components as ui
from quant_core.data import storage as du
from quant_core.ledger import transactions as tx
from quant_core.analytics import quant_analysis as qa
from strategies import ui as su
import ml_strategy as ml_utils
import deep_learning_strategy as dl_utils
from quant_core.events import event_news as en
from quant_core.events import event_fetcher as ef
from quant_core.events import analyst_consensus as ac
from quant_core.notifications import notification_config as ncfg
from quant_core.notifications import notification_channels as nch
from quant_core.portfolio import actions as pactions
from quant_core.snapshots import system_snapshot as ss
import locales as loc
from strategies.registry import create_strategy
from share_utils import format_share_quantity, validate_share_quantity
from quant_core.portfolio.metrics import summarize_holdings
from quant_core.portfolio.position import recommend_position_action, summarize_backtest_guidance
from quant_core.portfolio.risk import analyze_portfolio_risk
from quant_core.portfolio.control_loop import evaluate_allocation_regime
from signal_approval import approve_signal
from signal_scoreboard import build_signal_scoreboard
from quant_core.analytics.strategy_compare import compare_strategies_for_symbol
from quant_core.risk.risk_gate import (
    build_market_risk_snapshot_from_histories,
    evaluate_market_risk_gate,
    merge_risk_gate_decisions,
)
from quant_core.analytics.monte_carlo import simulate_return_distribution

# 引擎
from engine import BacktraderEngine, PyBrokerEngine

st.set_page_config(page_title="Portfolio Tracker", layout="wide")

AUTO_REFRESH_INTERVAL_SECONDS = 300
NEWS_AUTO_REFRESH_INTERVAL_SECONDS = 600


@st.cache_data(ttl=AUTO_REFRESH_INTERVAL_SECONDS, show_spinner=False)
def load_historical_data_cached(symbol, period):
    return qa.get_historical_data(symbol, period=period)


@st.cache_data(ttl=AUTO_REFRESH_INTERVAL_SECONDS, show_spinner=False)
def load_correlation_matrix_cached(symbols, period="6mo"):
    return qa.calculate_correlation_matrix(list(symbols), period=period)


# ---------- 语言设置 ----------
if "lang" not in st.session_state:
    st.session_state.lang = "zh"


def ui_text(zh_text, en_text):
    return zh_text if st.session_state.get("lang", "zh") == "zh" else en_text


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

# ---------- 数据状态 ----------
try:
    rt.bootstrap_app_data(
        st.session_state,
        du,
        refresh_interval_seconds=AUTO_REFRESH_INTERVAL_SECONDS,
    )
except ValueError as e:
    st.error(f"数据文件加载失败: {e}")
    st.stop()
rt.ensure_dialog_state_defaults(st.session_state)

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
tracked_symbols = rt.collect_tracked_symbols(st.session_state.app_data)

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
                st.success(L("manual_tcn_retrain_done"))
            else:
                st.warning(retrain_message)
            st.rerun()

    st.divider()
    st.header(ui_text("账户资金", "Account & Capital"))
    account_config = dict(data.get("account", {}) or {})
    with st.form("account_config_form"):
        cash_available = st.number_input(
            ui_text("可用现金 (USD)", "Cash available (USD)"),
            min_value=0.0,
            value=float(account_config.get("cash_available") or 0.0),
            step=100.0,
            format="%.2f",
        )
        account_col1, account_col2 = st.columns(2)
        min_cash_buffer_pct = account_col1.number_input(
            ui_text("最低现金缓冲 (%)", "Min cash buffer (%)"),
            min_value=0.0,
            max_value=100.0,
            value=float(account_config.get("min_cash_buffer_pct", 0.05) or 0.0) * 100.0,
            step=1.0,
            format="%.1f",
        )
        max_single_position_pct = account_col2.number_input(
            ui_text("单票上限 (%)", "Max single position (%)"),
            min_value=0.0,
            max_value=100.0,
            value=float(account_config.get("max_single_position_pct", 0.20) or 0.0) * 100.0,
            step=1.0,
            format="%.1f",
        )
        max_total_exposure_pct = st.number_input(
            ui_text("总暴露上限 (%)", "Max total exposure (%)"),
            min_value=0.0,
            max_value=100.0,
            value=float(account_config.get("max_total_exposure_pct", 1.0) or 0.0) * 100.0,
            step=1.0,
            format="%.1f",
        )
        if st.form_submit_button(ui_text("保存资金参数", "Save capital settings")):
            data["account"] = {
                "total_capital": None,
                "cash_available": float(cash_available),
                "min_cash_buffer_pct": float(min_cash_buffer_pct) / 100.0,
                "max_single_position_pct": float(max_single_position_pct) / 100.0,
                "max_total_exposure_pct": float(max_total_exposure_pct) / 100.0,
            }
            du.save_data(data)
            st.session_state.app_data = du.load_data()
            st.success(ui_text("资金参数已保存", "Capital settings saved"))
            st.rerun()
    st.caption(
        ui_text(
            "系统会自动按“可用现金 + 持仓市值”计算总资金；这里仅需维护可用现金和风控参数。",
            "Total capital is auto-derived as cash available plus holdings market value; maintain cash and risk limits here.",
        )
    )

    st.header(L("add_holding"))
    with st.form("add_holding"):
        sym = st.text_input(L("stock_code"), placeholder="AAPL, TSM...")
        shares = st.number_input(L("shares"), min_value=0.0, step=0.001, format="%.3f")
        cost = st.number_input(L("cost_price"), min_value=0.0, step=0.01, format="%.2f")
        sector = st.text_input(L("sector"), placeholder="Technology, Healthcare...")
        if st.form_submit_button(L("submit_add_holding")):
            if sym and shares > 0 and cost > 0:
                try:
                    pactions.buy_symbol(sym, shares, price=cost, sector=sector)
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
        st.caption(L("upside_price_hint"))
        if st.form_submit_button(L("submit_add_watch")):
            if w_sym:
                du.add_watch(w_sym, notes)
                st.session_state.app_data = du.load_data()
                st.success(f"{w_sym.upper()} {L('submit_add_watch')} 成功")
                st.rerun()
            else:
                st.warning(L("submit_add_watch") + " 至少输入代码")

    st.divider()
    if st.button(L("refresh_price")):
        with st.spinner("刷新中..."):
            try:
                updated = pactions.refresh_all_market_data()
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
            pactions.clear_all_holdings(notes="ui clear holdings")
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

rt.enable_auto_news_rerun(
    session_state=st.session_state,
    interval_seconds=NEWS_AUTO_REFRESH_INTERVAL_SECONDS,
    st_module=st,
)

ud.render_portfolio_dialogs(
    session_state=st.session_state,
    data=data,
    L=L,
    st_module=st,
    data_utils_module=du,
    portfolio_actions_module=pactions,
    format_share_quantity_fn=format_share_quantity,
    validate_share_quantity_fn=validate_share_quantity,
)

market_risk_gate_decision = None
market_risk_snapshot = None
portfolio_risk_advice = None
portfolio_corr_matrix = None
active_market_events = []
event_risk_decision = None
event_source_reports = []
if data["holdings"]:
    try:
        event_symbols = rt.collect_tracked_symbols(data)
        fetched_events, fetched_reports, _ = rt.fetch_news_events_with_cache(
            session_state=st.session_state,
            fetcher_module=ef,
            symbols=event_symbols,
            interval_seconds=NEWS_AUTO_REFRESH_INTERVAL_SECONDS,
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
        ) = rt.evaluate_market_risk_for_portfolio(
            holdings=data["holdings"],
            history_period=st.session_state.history_period,
            load_historical_data_fn=load_historical_data_cached,
            load_correlation_matrix_fn=load_correlation_matrix_cached,
            analyze_portfolio_risk_fn=analyze_portfolio_risk,
            build_market_risk_snapshot_fn=build_market_risk_snapshot_from_histories,
            evaluate_market_risk_gate_fn=evaluate_market_risk_gate,
            select_active_events_fn=en.select_active_events,
            evaluate_event_risk_switch_fn=en.evaluate_event_risk_switch,
            merge_risk_gate_decisions_fn=merge_risk_gate_decisions,
            fetch_events_from_sources_fn=ef.fetch_events_from_sources,
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

transaction_rows = tx.normalize_transactions(tx.load_transactions())
scoreboard_benchmark_history = None
try:
    scoreboard_benchmark_history = load_historical_data_cached("SPY", period=st.session_state.get("history_period", "2y"))
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

# ---------- 主区域 ----------
st.title(L("app_title"))
st.caption(L("app_caption"))

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    L("holdings_tab"), L("watchlist_tab"),
    L("transactions_tab"), L("quant_tab"), "通知配置"
])
holding_records = []
watchlist_records = []

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
    selected_strategy_runtime = rt.apply_runtime_strategy_params(
        selected_strategy,
        history_period=st.session_state.get("history_period", "2y"),
    )
    st.session_state.selected_strategy_id = selected_strategy["id"]
    with st.expander(L("strategy_desc")):
        st.markdown(selected_strategy.get("description", "无说明"))

    def handle_sell(idx):
        st.session_state.sell_dialog_index = idx

    def handle_buy(idx):
        st.session_state.buy_dialog_index = idx

    def handle_delete_holding(idx):
        try:
            symbol = data["holdings"][idx]["symbol"]
            pactions.remove_holding_record(symbol, notes="ui delete holding")
            st.session_state.app_data = du.load_data()
        except ValueError as e:
            st.error(str(e))
            return False

    def handle_move_holding_to_watch(idx):
        try:
            symbol = data["holdings"][idx]["symbol"]
            pactions.move_holding_to_watch(symbol)
            st.session_state.app_data = du.load_data()
        except ValueError as e:
            st.error(str(e))
            return False

    if data["holdings"]:
        up.render_market_risk_gate_banner(market_risk_gate_decision, market_risk_snapshot, L)
    summary, holding_records = ui.render_holdings_table(
        data,
        on_price_change=du.update_holding_price,
        on_delete=handle_delete_holding,
        on_buy=handle_buy,
        on_sell=handle_sell,
        on_move_to_watch=handle_move_holding_to_watch,
        strategy=selected_strategy_runtime,
        risk_gate=market_risk_gate_decision,
        analyst_consensus_cache=analyst_consensus_cache,
        allocation_regime=allocation_regime_decision,
    )
    up.render_account_snapshot_panel(account_snapshot, ui_text=ui_text)
    up.render_allocation_regime_panel(allocation_regime_decision, ui_text=ui_text)
    up.render_signal_scoreboard_panel(live_scoreboard, ui_text=ui_text)
    if data["holdings"]:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(L("total_cost"), f"${summary.total_cost:,.2f}")
        c2.metric(L("total_value"), f"${summary.total_value:,.2f}")
        c3.metric(L("total_pl"), f"${summary.total_pl:+,.2f}", delta=f"{summary.total_pl_pct:+.2f}%")
        c4.metric(L("holdings_count"), f"{len(data['holdings'])}")

        if st.button(L("gen_md")):
            md_text = pg.build_holdings_markdown(
                holding_records,
                summary,
                format_share_quantity_fn=format_share_quantity,
                labels={
                    "total_cost": L("total_cost"),
                    "total_value": L("total_value"),
                    "total_pl": L("total_pl"),
                },
            )
            st.code(md_text, language="markdown")
            st.download_button("⬇️ 下载 Markdown", data=md_text, file_name=f"holdings_{datetime.now().strftime('%Y%m%d')}.md")

# ----- Tab2 关注列表 -----
with tab2:
    selected_strategy_for_watch = strategy_map.get(st.session_state.selected_strategy_id, strategies[0])
    selected_strategy_for_watch_runtime = rt.apply_runtime_strategy_params(
        selected_strategy_for_watch,
        history_period=st.session_state.get("history_period", "2y"),
    )
    up.render_account_snapshot_panel(account_snapshot, ui_text=ui_text)
    up.render_allocation_regime_panel(allocation_regime_decision, ui_text=ui_text)

    def handle_delete_watch_batch(indices):
        du.delete_watch_batch(indices)
        st.session_state.app_data = du.load_data()

    def handle_move_watch_to_holding(idx):
        st.session_state.move_watch_dialog_index = idx

    watchlist_records = ui.render_watchlist_table(
        data,
        on_delete_batch=handle_delete_watch_batch,
        on_move_to_holding=handle_move_watch_to_holding,
        strategy=selected_strategy_for_watch_runtime,
        analyst_consensus_cache=analyst_consensus_cache,
        risk_gate=market_risk_gate_decision,
        allocation_regime=allocation_regime_decision,
    )

# ----- Tab3 交易记录 -----
with tab3:
    pg.render_transactions_tab(
        tx_module=tx,
        L=L,
        format_share_quantity_fn=format_share_quantity,
        st_module=st,
    )

# ----- Tab4 量化分析 -----
with tab4:
    st.header(L("quant_title"))
    st.markdown(L("quant_desc"))
    if data["holdings"]:
        up.render_market_risk_gate_banner(market_risk_gate_decision, market_risk_snapshot, L)
        up.render_active_events_panel(
            active_market_events,
            event_risk_decision,
            event_source_reports,
            L,
            lang=st.session_state.get("lang", "zh"),
        )
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
            rt.apply_runtime_strategy_params(
                selected_strategy_tab4,
                history_period=st.session_state.get("history_period", "2y"),
            )
            if selected_strategy_tab4
            else None
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
                hist = load_historical_data_cached(selected_symbol, period=history_period)
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
                        signal_approval = approve_signal(current_signal, risk_gate=market_risk_gate_decision)
                        current_signal = signal_approval.approved_signal
                        if signal_approval.blocked and signal_approval.reason:
                            current_reason = f"{current_reason} | {signal_approval.reason}"
                        if current_signal in {"BUY", "STRONG_BUY"}:
                            st.success(f"📈 {L('current_signal')}: {L('buy')} — {current_reason}")
                        elif current_signal in {"SELL", "STRONG_SELL"}:
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

                                    scoreboard = build_signal_scoreboard(
                                        result.trade_log,
                                        equity_curve=result.equity_curve,
                                        benchmark_history=hist,
                                    )
                                    st.subheader(ui_text("信号评分看板", "Signal Scoreboard"))
                                    s1, s2, s3, s4, s5, s6 = st.columns(6)
                                    s1.metric(ui_text("完成交易", "Closed Trades"), f"{scoreboard.completed_trades}")
                                    s2.metric(
                                        ui_text("信号胜率", "Signal Win Rate"),
                                        f"{scoreboard.win_rate:.2%}" if scoreboard.win_rate is not None else "—",
                                    )
                                    s3.metric(
                                        ui_text("期望收益/笔", "Expectancy/Trade"),
                                        f"{scoreboard.expectancy_return_pct:.2%}" if scoreboard.expectancy_return_pct is not None else "—",
                                    )
                                    s4.metric(
                                        ui_text("盈亏比", "Payoff Ratio"),
                                        f"{scoreboard.payoff_ratio:.2f}" if scoreboard.payoff_ratio is not None else "—",
                                    )
                                    s5.metric(
                                        ui_text("利润因子", "Profit Factor"),
                                        f"{scoreboard.profit_factor:.2f}" if scoreboard.profit_factor is not None else "—",
                                    )
                                    s6.metric(
                                        ui_text("看板最大回撤", "Scoreboard Max DD"),
                                        f"{scoreboard.max_drawdown_pct:.2%}" if scoreboard.max_drawdown_pct is not None else "—",
                                    )

                                    if scoreboard.regime_breakdown:
                                        regime_df = pd.DataFrame(
                                            [
                                                {
                                                    ui_text("波动状态", "Volatility Regime"): item.regime,
                                                    ui_text("交易数", "Trades"): item.trades,
                                                    ui_text("胜率", "Win Rate"): f"{item.win_rate:.2%}" if item.win_rate is not None else "—",
                                                    ui_text("平均收益", "Avg Return"): f"{item.avg_return_pct:.2%}" if item.avg_return_pct is not None else "—",
                                                }
                                                for item in scoreboard.regime_breakdown
                                            ]
                                        )
                                        st.dataframe(regime_df, hide_index=True, width="stretch")

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
                                            allocation_regime=allocation_regime_decision,
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

                    st.subheader(ui_text("策略比较（同标的）", "Strategy Comparison (Same Symbol)"))
                    compare_bundle = st.session_state.get("latest_strategy_comparison", {})
                    if st.button(ui_text("运行策略比较", "Run Strategy Comparison"), key="run_strategy_compare"):
                        with st.spinner(ui_text("策略比较中...", "Comparing strategies...")):
                            try:
                                comparison_rows = compare_strategies_for_symbol(
                                    symbol=selected_symbol,
                                    strategies=strategies,
                                    load_historical_data_fn=load_historical_data_cached,
                                    create_strategy_fn=create_strategy,
                                    engine_factory_fn=(
                                        (lambda: BacktraderEngine(initial_cash=100000))
                                        if use_backtrader
                                        else (lambda: PyBrokerEngine(initial_cash=100000))
                                    ),
                                    history_period=history_period,
                                    runtime_param_fn=lambda strategy: rt.apply_runtime_strategy_params(
                                        strategy,
                                        history_period=st.session_state.get("history_period", "2y"),
                                    ),
                                )
                                compare_bundle = {
                                    "symbol": selected_symbol,
                                    "history_period": history_period,
                                    "engine": "backtrader" if use_backtrader else "pybroker",
                                    "rows": comparison_rows,
                                    "generated_at": datetime.now().isoformat(),
                                }
                                st.session_state.latest_strategy_comparison = compare_bundle
                            except Exception as e:
                                st.error(f"策略比较失败: {e}")

                    compare_rows = list(compare_bundle.get("rows", []) or [])
                    if compare_bundle.get("symbol") == selected_symbol and compare_rows:
                        comparison_df = pd.DataFrame(
                            [
                                {
                                    "策略": row.get("strategy_name", row.get("strategy_id")),
                                    "综合分": f"{float(row.get('composite_score', 0.0)):.2f}",
                                    "收益率": f"{float(row.get('total_return', 0.0)):.2%}" if row.get("total_return") is not None else "—",
                                    "夏普": f"{float(row.get('sharpe_ratio', 0.0)):.2f}" if row.get("sharpe_ratio") is not None else "—",
                                    "胜率": f"{float(row.get('win_rate', 0.0)):.2%}" if row.get("win_rate") is not None else "—",
                                    "期望收益/笔": (
                                        f"{float(row.get('expectancy_return_pct')):.2%}"
                                        if row.get("expectancy_return_pct") is not None
                                        else "—"
                                    ),
                                    "利润因子": (
                                        f"{float(row.get('profit_factor')):.2f}"
                                        if row.get("profit_factor") is not None
                                        else "—"
                                    ),
                                }
                                for row in compare_rows
                            ]
                        )
                        st.dataframe(comparison_df, hide_index=True, width="stretch")
                        st.caption(
                            ui_text(
                                f"最后比较时间: {compare_bundle.get('generated_at', '—')}",
                                f"Last comparison at: {compare_bundle.get('generated_at', '—')}",
                            )
                        )
                    elif compare_bundle.get("symbol") == selected_symbol:
                        st.info(ui_text("策略比较暂无可用结果。", "No strategy comparison result yet."))

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
                            corr = load_correlation_matrix_cached(tuple(sorted(symbols)))
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

snapshot_alerts = pg.build_snapshot_alerts(active_market_events)
latest_strategy_comparison = st.session_state.get("latest_strategy_comparison", {})
st.session_state.latest_system_snapshot = ss.build_system_snapshot(
    data=st.session_state.app_data,
    holding_records=holding_records,
    watchlist_records=watchlist_records,
    risk_gate=market_risk_gate_decision,
    alerts=snapshot_alerts,
    performance={
        "live_scoreboard": _scoreboard_to_dict(live_scoreboard),
        "strategy_comparison": dict(latest_strategy_comparison or {}),
    },
    allocation_regime=allocation_regime_decision.to_dict() if allocation_regime_decision is not None else {},
)

# ----- Tab5 通知配置 -----
with tab5:
    unp.render_notification_config_page(
        ncfg_module=ncfg,
        nch_module=nch,
    )
