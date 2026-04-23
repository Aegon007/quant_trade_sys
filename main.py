import streamlit as st
import pandas as pd
from datetime import datetime
import data_utils as du
import ui_components as ui
import transactions as tx
import quant_analysis as qa
import strategy_ui as su
import ml_strategy as ml_utils
import locales as loc

# 引擎
from engine import BacktraderEngine, PyBrokerEngine, BacktestResult
# 策略类
from strategies import (
    MACrossoverStrategy, BollingerStrategy, MACDStrategy, RSIStrategy,
    LightGBMStrategy, EnsembleVotingStrategy
)

st.set_page_config(page_title="Portfolio Tracker", layout="wide")

# ---------- 语言设置 ----------
if "lang" not in st.session_state:
    st.session_state.lang = "zh"

# ---------- 数据状态 ----------
if "app_data" not in st.session_state:
    st.session_state.app_data = du.load_data()
if "sell_dialog_index" not in st.session_state:
    st.session_state.sell_dialog_index = None
if "editing_holding" not in st.session_state:
    st.session_state.editing_holding = None
if "selected_strategy_id" not in st.session_state:
    st.session_state.selected_strategy_id = "ma_crossover"

data = st.session_state.app_data

# ---------- 策略配置 ----------
strategies = su.load_strategies()
if not strategies:
    st.error("策略配置文件加载失败，请检查 config/strategies.json")
    st.stop()

strategy_map = {s["id"]: s for s in strategies}
strategy_names = [s["name"] for s in strategies]

# ========== 侧边栏 ==========
with st.sidebar:
    # 语言切换
    lang_choice = st.selectbox("🌐 Language / 语言", ["中文", "English"],
                               index=0 if st.session_state.lang == "zh" else 1)
    st.session_state.lang = "zh" if lang_choice == "中文" else "en"
    L = lambda key, **kwargs: loc.get_text(st.session_state.lang, key, **kwargs)

    st.header(L("add_holding"))
    with st.form("add_holding"):
        sym = st.text_input(L("stock_code"), placeholder="AAPL, TSM...")
        shares = st.number_input(L("shares"), min_value=0.0, step=1.0)
        cost = st.number_input(L("cost_price"), min_value=0.0, step=0.01, format="%.2f")
        if st.form_submit_button(L("submit_add_holding")):
            if sym and shares > 0 and cost > 0:
                du.add_holding(sym, shares, cost)
                st.session_state.app_data = du.load_data()
                st.success(f"{sym.upper()} {L('submit_add_holding')} 成功")
                st.rerun()
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
                updated = du.update_all_prices(data)
                st.session_state.app_data = updated
                du.save_data(updated)
                st.success(L("refresh_price") + " 完成！")
                st.rerun()
            except Exception as e:
                st.error(f"刷新失败: {e}")

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
                                                 max_value=max_s, value=max_s, step=1.0)
                if st.button(L("confirm_sell")):
                    if sell_shares > 0:
                        sym, cb = du.sell_partial_holding(idx, sell_shares, sell_price)
                        tx.add_transaction(sym, sell_price, sell_shares, cb)
                        st.session_state.app_data = du.load_data()
                        st.success(f"已卖出 {sym} {sell_shares:,.0f} 股 @ ${sell_price:.2f}")
                        st.session_state.sell_dialog_index = None
                        st.rerun()
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
                    new_shares = st.number_input(L("shares"), min_value=0.0, value=float(h["shares"]), step=1.0)
                    new_cost = st.number_input(L("cost_price"), min_value=0.0, value=float(h["cost"]), step=0.01, format="%.2f")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.form_submit_button(L("save")):
                            if new_shares > 0:
                                data["holdings"][idx]["shares"] = new_shares
                                data["holdings"][idx]["cost"] = new_cost
                                du.save_data(data)
                                st.session_state.app_data = du.load_data()
                                st.success(L("save") + " 成功")
                                st.session_state.editing_holding = None
                                st.rerun()
                            else:
                                st.error(L("shares") + " 必须大于0")
                    with c2:
                        if st.form_submit_button(L("cancel")):
                            st.session_state.editing_holding = None
                            st.rerun()
        else:
            st.session_state.editing_holding = None
            st.rerun()

render_dialogs()

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
    selected_strategy_name = st.selectbox(
        L("strategy_signal"),
        strategy_names,
        index=[s["id"] for s in strategies].index(st.session_state.selected_strategy_id)
    )
    selected_strategy = next((s for s in strategies if s["name"] == selected_strategy_name), strategies[0])
    st.session_state.selected_strategy_id = selected_strategy["id"]
    with st.expander(L("strategy_desc")):
        st.markdown(selected_strategy.get("description", "无说明"))

    def handle_sell(idx):
        st.session_state.sell_dialog_index = idx

    total_cost, total_value, total_pl, total_pl_pct = ui.render_holdings_table(
        data,
        on_price_change=du.update_holding_price,
        on_delete=du.delete_holding,
        on_sell=handle_sell,
        strategy=selected_strategy
    )
    if data["holdings"]:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(L("total_cost"), f"${total_cost:,.2f}")
        c2.metric(L("total_value"), f"${total_value:,.2f}")
        c3.metric(L("total_pl"), f"${total_pl:+,.2f}", delta=f"{total_pl_pct:+.2f}%")
        c4.metric(L("holdings_count"), f"{len(data['holdings'])}")

        if st.button(L("gen_md")):
            lines = ["| 代码 | 股数 | 成本价 | 现价 | 市值 | 盈亏 ($) | 盈亏 (%) | 信号 |"]
            lines.append("|------|------|--------|------|------|----------|----------|------|")
            for h in data["holdings"]:
                shares = h["shares"]
                cost = h["cost"]
                price = h.get("current_price")
                mkt = shares * price if price else None
                pl = mkt - shares * cost if mkt else None
                pl_pct = (pl / (shares * cost) * 100) if pl and shares*cost else None
                signal, reason = su.get_signal(selected_strategy, h["symbol"])
                lines.append(
                    f"| {h['symbol']} | {shares:,.0f} | ${cost:,.2f} | "
                    f"{'$'+f'{price:,.2f}' if price else '—'} | "
                    f"{'$'+f'{mkt:,.2f}' if mkt else '—'} | "
                    f"{'$'+f'{pl:+,.2f}' if pl is not None else '—'} | "
                    f"{f'{pl_pct:+.2f}%' if pl_pct is not None else '—'} | "
                    f"{signal} |"
                )
            lines.append(f"\n**{L('total_cost')}**: ${total_cost:,.2f}  \n**{L('total_value')}**: ${total_value:,.2f}  \n**{L('total_pl')}**: ${total_pl:+,.2f} ({total_pl_pct:+.2f}%)")
            md_text = "\n".join(lines)
            st.code(md_text, language="markdown")
            st.download_button("⬇️ 下载 Markdown", data=md_text, file_name=f"holdings_{datetime.now().strftime('%Y%m%d')}.md")

# ----- Tab2 关注列表 -----
with tab2:
    ui.render_watchlist_table(data, on_delete_batch=du.delete_watch_batch)

# ----- Tab3 交易记录 -----
with tab3:
    transactions = tx.load_transactions()
    if not transactions:
        st.info(L("no_transactions"))
    else:
        df = pd.DataFrame(transactions)
        df_display = df.copy()
        df_display["盈亏 ($)"] = df_display["pl"].apply(lambda x: f"${x:+,.2f}")
        df_display["盈亏 (%)"] = df_display["pl_pct"].apply(lambda x: f"{x:+.2f}%")
        df_display = df_display[["date", "symbol", "shares", "sell_price", "cost_basis", "proceeds", "盈亏 ($)", "盈亏 (%)"]]
        df_display.columns = ["日期", "代码", "股数", "卖出价", "成本价", "收入", "盈亏 ($)", "盈亏 (%)"]
        st.dataframe(df_display, hide_index=True, use_container_width=True)
        total_proceeds = sum(t["proceeds"] for t in transactions)
        total_pl_trans = sum(t["pl"] for t in transactions)
        c1, c2 = st.columns(2)
        c1.metric(L("total_income"), f"${total_proceeds:,.2f}")
        c2.metric(L("total_pl_trans"), f"${total_pl_trans:+,.2f}")

# ----- Tab4 量化分析 -----
with tab4:
    st.header(L("quant_title"))
    st.markdown(L("quant_desc"))

    all_symbols = list(set([h["symbol"] for h in data["holdings"]] + [w["symbol"] for w in data["watchlist"]]))
    if not all_symbols:
        st.warning("暂无数据")
    else:
        st.subheader(L("engine_setting"))
        engine_option = st.selectbox(L("select_engine"), ["Backtrader (推荐)", "PyBroker"])
        use_backtrader = (engine_option == "Backtrader (推荐)")

        st.subheader(L("strategy_select"))
        selected_strategy_tab4 = su.render_strategy_selector(strategies)
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
                                params = selected_strategy_tab4.get("params", {})
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

        if selected_symbol and selected_strategy_tab4:
            with st.spinner("加载历史数据..."):
                hist = qa.get_historical_data(selected_symbol, period="6mo")
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

                    # 当前信号
                    try:
                        signal, reason = su.get_signal(selected_strategy_tab4, selected_symbol)
                        if signal == "BUY":
                            st.success(f"📈 {L('current_signal')}: {L('buy')} — {reason}")
                        elif signal == "SELL":
                            st.error(f"📉 {L('current_signal')}: {L('sell')} — {reason}")
                        else:
                            st.info(f"⏸️ {L('current_signal')}: {L('hold')} — {reason}")
                    except Exception as e:
                        st.warning(f"无法获取信号: {e}")

                    # 回测按钮
                    st.subheader(L("backtest_title") + f" (引擎: {engine_option})")
                    if st.button(L("run_backtest"), key="run_backtest"):
                        with st.spinner("回测中..."):
                            try:
                                strategy_id = selected_strategy_tab4["id"]
                                params = selected_strategy_tab4.get("params", {})
                                if strategy_id == "ma_crossover":
                                    strategy_obj = MACrossoverStrategy(**params)
                                elif strategy_id == "bollinger":
                                    strategy_obj = BollingerStrategy(**params)
                                elif strategy_id == "macd":
                                    strategy_obj = MACDStrategy(**params)
                                elif strategy_id == "rsi":
                                    strategy_obj = RSIStrategy(**params)
                                elif strategy_id == "ml_lightgbm":
                                    strategy_obj = LightGBMStrategy(params)
                                elif strategy_id == "ensemble_voting":
                                    strategy_obj = EnsembleVotingStrategy(params)
                                else:
                                    st.error("未知策略")
                                    strategy_obj = None

                                if strategy_obj:
                                    engine = BacktraderEngine(initial_cash=100000) if use_backtrader else PyBrokerEngine(initial_cash=100000)
                                    engine.set_data(hist)
                                    engine.set_strategy(strategy_obj)
                                    result = engine.run()

                                    st.success("回测完成！")
                                    c1, c2, c3, c4 = st.columns(4)
                                    c1.metric(L("cum_return"), f"{result.total_return:.2%}")
                                    c2.metric(L("sharpe"), f"{result.sharpe_ratio:.2f}")
                                    c3.metric(L("max_drawdown"), f"{result.max_drawdown:.2%}")
                                    c4.metric(L("win_rate"), f"{result.win_rate:.2%}")
                                    if result.equity_curve:
                                        st.line_chart(pd.Series(result.equity_curve))
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
                        symbols = [h["symbol"] for h in data["holdings"] if h.get("current_price")]
                        if len(symbols) > 1:
                            corr = qa.calculate_correlation_matrix(symbols)
                            st.write(L("corr_matrix"))
                            st.dataframe(corr.style.format("{:.2f}"))
                    except Exception as e:
                        st.error(f"计算失败: {e}")
        else:
            st.info("无持仓数据")