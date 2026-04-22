import streamlit as st
import pandas as pd
from datetime import datetime
import data_utils as du
import ui_components as ui
import transactions as tx
import quant_analysis as qa
import strategy_ui as su

st.set_page_config(page_title="持仓·关注追踪器", layout="wide")
st.title("📊 持仓与关注追踪器")
st.caption("实时行情 · 卖出记录 · 编辑持仓 · 短线量化策略 · 动态信号")

# ---------- 加载数据 ----------
if "app_data" not in st.session_state:
    st.session_state.app_data = du.load_data()
if "sell_dialog_index" not in st.session_state:
    st.session_state.sell_dialog_index = None
if "editing_holding" not in st.session_state:
    st.session_state.editing_holding = None
if "selected_strategy_id" not in st.session_state:
    st.session_state.selected_strategy_id = "ma_crossover"  # 默认策略

data = st.session_state.app_data

# ---------- 加载策略配置 ----------
strategies = su.load_strategies()
strategy_map = {s["id"]: s for s in strategies}
strategy_names = [s["name"] for s in strategies]

# ---------- 侧边栏 ----------
with st.sidebar:
    st.header("➕ 添加持仓")
    with st.form("add_holding"):
        sym = st.text_input("股票代码", placeholder="AAPL, TSM...")
        shares = st.number_input("股数", min_value=0.0, step=1.0)
        cost = st.number_input("成本价 (USD)", min_value=0.0, step=0.01, format="%.2f")
        if st.form_submit_button("添加持仓"):
            if sym and shares > 0 and cost > 0:
                du.add_holding(sym, shares, cost)
                st.session_state.app_data = du.load_data()
                st.success(f"已添加 {sym.upper()}")
                st.rerun()
            else:
                st.warning("请完整填写")

    st.divider()
    st.header("👀 添加关注")
    with st.form("add_watch"):
        w_sym = st.text_input("股票代码", placeholder="NVDA, MSFT...", key="watch_sym")
        notes = st.text_input("备注（可选）", placeholder="等待回调")
        target = st.number_input("目标买入价 (USD)", min_value=0.0, step=0.01, format="%.2f")
        if st.form_submit_button("添加关注"):
            if w_sym:
                du.add_watch(w_sym, notes, target if target > 0 else None)
                st.session_state.app_data = du.load_data()
                st.success(f"已关注 {w_sym.upper()}")
                st.rerun()
            else:
                st.warning("至少输入代码")

    st.divider()
    if st.button("🔄 刷新实时价格", use_container_width=True):
        with st.spinner("正在获取实时价格..."):
            try:
                updated_data = du.update_all_prices(data)
                st.session_state.app_data = updated_data
                du.save_data(updated_data)
                st.success("价格已更新！")
                st.rerun()
            except Exception as e:
                st.error(f"刷新失败: {e}")

    st.divider()
    st.header("🧹 清空操作")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ 清空持仓", use_container_width=True):
            du.clear_holdings()
            st.session_state.app_data = du.load_data()
            st.warning("已清空所有持仓")
            st.rerun()
    with col2:
        if st.button("🗑️ 清空关注", use_container_width=True):
            du.clear_watchlist()
            st.session_state.app_data = du.load_data()
            st.warning("已清空所有关注")
            st.rerun()

    st.divider()
    st.header("📤 导出")
    st.markdown("- **Markdown**：生成持仓表格")
    st.markdown("- **PDF**：使用浏览器打印 (Ctrl+P)")

# ---------- 对话框处理 ----------
def render_dialogs():
    # 卖出对话框
    if st.session_state.sell_dialog_index is not None:
        idx = st.session_state.sell_dialog_index
        if idx < len(data["holdings"]):
            holding = data["holdings"][idx]
            with st.expander(f"💰 卖出 {holding['symbol']}", expanded=True):
                col1, col2 = st.columns(2)
                with col1:
                    sell_price = st.number_input("卖出价 (USD)", min_value=0.0, value=holding.get("current_price") or 0.0, step=0.01, format="%.2f")
                with col2:
                    max_shares = holding["shares"]
                    sell_shares = st.number_input("卖出股数", min_value=0.0, max_value=max_shares, value=max_shares, step=1.0)
                if st.button("确认卖出", type="primary"):
                    if sell_shares > 0:
                        symbol, cost_basis = du.sell_partial_holding(idx, sell_shares, sell_price)
                        tx.add_transaction(symbol, sell_price, sell_shares, cost_basis)
                        st.session_state.app_data = du.load_data()
                        st.success(f"已卖出 {symbol} {sell_shares:,.0f} 股 @ ${sell_price:.2f}")
                        st.session_state.sell_dialog_index = None
                        st.rerun()
                if st.button("取消"):
                    st.session_state.sell_dialog_index = None
                    st.rerun()
        else:
            st.session_state.sell_dialog_index = None
            st.rerun()

    # 编辑对话框
    if st.session_state.editing_holding is not None:
        idx = st.session_state.editing_holding
        if idx < len(data["holdings"]):
            holding = data["holdings"][idx]
            with st.expander(f"✏️ 编辑 {holding['symbol']}", expanded=True):
                with st.form("edit_holding_form"):
                    new_shares = st.number_input("股数", min_value=0.0, value=float(holding["shares"]), step=1.0)
                    new_cost = st.number_input("成本价 (USD)", min_value=0.0, value=float(holding["cost"]), step=0.01, format="%.2f")
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.form_submit_button("保存"):
                            if new_shares > 0:
                                data["holdings"][idx]["shares"] = new_shares
                                data["holdings"][idx]["cost"] = new_cost
                                du.save_data(data)
                                st.session_state.app_data = du.load_data()
                                st.success("持仓已更新")
                                st.session_state.editing_holding = None
                                st.rerun()
                            else:
                                st.error("股数必须大于0")
                    with col2:
                        if st.form_submit_button("取消"):
                            st.session_state.editing_holding = None
                            st.rerun()
        else:
            st.session_state.editing_holding = None
            st.rerun()

render_dialogs()

# ---------- 主区域 Tab ----------
tab1, tab2, tab3, tab4 = st.tabs(["📋 持仓", "👀 关注列表", "📜 交易记录", "📈 量化分析"])

with tab1:
    # 策略选择器（放置在持仓表格上方）
    st.caption("选择应用于持仓信号的短线策略")
    selected_strategy_name = st.selectbox(
        "策略信号",
        strategy_names,
        index=[s["id"] for s in strategies].index(st.session_state.selected_strategy_id)
    )
    selected_strategy = next((s for s in strategies if s["name"] == selected_strategy_name), strategies[0])
    st.session_state.selected_strategy_id = selected_strategy["id"]
    # 显示策略简短说明
    with st.expander("📌 策略说明"):
        st.markdown(selected_strategy["description"])

    def handle_sell(idx):
        st.session_state.sell_dialog_index = idx

    total_cost, total_value, total_pl, total_pl_pct = ui.render_holdings_table(
        data,
        on_price_change=du.update_holding_price,
        on_delete=du.delete_holding,
        on_sell=handle_sell,
        strategy=selected_strategy   # 传入策略对象，用于计算信号
    )
    if data["holdings"]:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("总成本", f"${total_cost:,.2f}")
        col2.metric("总市值", f"${total_value:,.2f}")
        col3.metric("总盈亏", f"${total_pl:+,.2f}", delta=f"{total_pl_pct:+.2f}%")
        col4.metric("持仓数量", f"{len(data['holdings'])} 只")

        if st.button("📝 生成持仓 Markdown"):
            lines = ["| 代码 | 股数 | 成本价 | 现价 | 市值 | 盈亏 ($) | 盈亏 (%) | 信号 |"]
            lines.append("|------|------|--------|------|------|----------|----------|------|")
            for h in data["holdings"]:
                shares = h["shares"]
                cost = h["cost"]
                price = h.get("current_price")
                mkt = shares * price if price else None
                pl = mkt - shares * cost if mkt else None
                pl_pct = (pl / (shares * cost) * 100) if pl and shares*cost else None
                signal, reason = qa.get_signal_for_strategy(h["symbol"], selected_strategy)
                lines.append(
                    f"| {h['symbol']} | {shares:,.0f} | ${cost:,.2f} | "
                    f"{'$'+f'{price:,.2f}' if price else '—'} | "
                    f"{'$'+f'{mkt:,.2f}' if mkt else '—'} | "
                    f"{'$'+f'{pl:+,.2f}' if pl is not None else '—'} | "
                    f"{f'{pl_pct:+.2f}%' if pl_pct is not None else '—'} | "
                    f"{signal} |"
                )
            lines.append(f"\n**总成本**: ${total_cost:,.2f}  \n**总市值**: ${total_value:,.2f}  \n**总盈亏**: ${total_pl:+,.2f} ({total_pl_pct:+.2f}%)")
            md_text = "\n".join(lines)
            st.code(md_text, language="markdown")
            st.download_button("⬇️ 下载 Markdown", data=md_text, file_name=f"holdings_{datetime.now().strftime('%Y%m%d')}.md")

with tab2:
    ui.render_watchlist_table(data, on_delete_batch=du.delete_watch_batch)

with tab3:
    transactions = tx.load_transactions()
    if not transactions:
        st.info("暂无交易记录。")
    else:
        df = pd.DataFrame(transactions)
        df_display = df.copy()
        df_display["盈亏 ($)"] = df_display["pl"].apply(lambda x: f"${x:+,.2f}")
        df_display["盈亏 (%)"] = df_display["pl_pct"].apply(lambda x: f"{x:+.2f}%")
        df_display = df_display[["date", "symbol", "shares", "sell_price", "cost_basis", "proceeds", "盈亏 ($)", "盈亏 (%)"]]
        df_display.columns = ["日期", "代码", "股数", "卖出价", "成本价", "收入", "盈亏 ($)", "盈亏 (%)"]
        st.dataframe(df_display, hide_index=True, use_container_width=True)
        total_proceeds = sum(t["proceeds"] for t in transactions)
        total_pl = sum(t["pl"] for t in transactions)
        col1, col2 = st.columns(2)
        col1.metric("累计收入", f"${total_proceeds:,.2f}")
        col2.metric("累计盈亏", f"${total_pl:+,.2f}")

with tab4:
    st.header("量化分析工具")
    st.markdown("基于持仓和关注列表的技术指标、风险度量和短线策略回测")

    all_symbols = list(set([h["symbol"] for h in data["holdings"]] + [w["symbol"] for w in data["watchlist"]]))
    if not all_symbols:
        st.warning("暂无持仓或关注标的，请先添加。")
    else:
        selected_symbol = st.selectbox("选择股票代码", all_symbols)

        # 策略选择（独立于股票）
        st.subheader("📊 策略选择与说明")
        selected_strategy_tab4 = su.render_strategy_selector(strategies)
        su.display_strategy_description(selected_strategy_tab4)

        if selected_symbol:
            with st.spinner("加载历史数据..."):
                hist = qa.get_historical_data(selected_symbol, period="6mo")
                if hist.empty:
                    st.error("无法获取历史数据")
                else:
                    st.subheader(f"{selected_symbol} 技术指标")
                    df_ma = qa.calculate_ma(hist)
                    rsi = qa.calculate_rsi(hist)

                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("最新价", f"${hist['Close'].iloc[-1]:.2f}")
                        st.metric("20日均线", f"${df_ma['MA20'].iloc[-1]:.2f}")
                        st.metric("50日均线", f"${df_ma['MA50'].iloc[-1]:.2f}")
                    with col2:
                        st.metric("RSI (14)", f"{rsi.iloc[-1]:.2f}")
                        st.metric("年化波动率", f"{qa.calculate_volatility(hist):.2%}")
                        st.metric("最大回撤", f"{qa.calculate_max_drawdown(hist):.2%}")

                    chart_data = df_ma[["Close", "MA20", "MA50"]].tail(100)
                    st.line_chart(chart_data)

                    # 显示当前信号
                    signal, reason = qa.get_signal_for_strategy(selected_symbol, selected_strategy_tab4)
                    if signal == "BUY":
                        st.success(f"📈 当前信号：买入 — {reason}")
                    elif signal == "SELL":
                        st.error(f"📉 当前信号：卖出 — {reason}")
                    else:
                        st.info(f"⏸️ 当前信号：持有 — {reason}")

                    # 回测
                    st.subheader("策略回测")
                    bt_df = su.run_backtest(selected_strategy_tab4, selected_symbol)
                    if bt_df is not None and not bt_df.empty:
                        cum_ret = (1 + bt_df["Strategy"]).cumprod()
                        st.line_chart(cum_ret.tail(100))
                        total_return = (1 + bt_df["Strategy"]).prod() - 1
                        sharpe = qa.calculate_sharpe_ratio(bt_df["Strategy"].dropna())
                        st.metric("策略累计收益", f"{total_return:.2%}")
                        st.metric("年化夏普比率", f"{sharpe:.2f}")

                    # MACD 图表
                    macd, signal_line, hist_macd = qa.calculate_macd(hist)
                    macd_df = pd.DataFrame({"MACD": macd, "Signal": signal_line, "Histogram": hist_macd}).tail(100)
                    st.subheader("MACD 指标")
                    st.line_chart(macd_df[["MACD", "Signal"]])
                    st.bar_chart(macd_df["Histogram"])

        # 组合风险分析
        st.divider()
        st.subheader("📊 组合风险分析")
        if data["holdings"]:
            if st.button("计算组合 Beta 与相关性"):
                with st.spinner("计算中..."):
                    try:
                        beta, betas = qa.calculate_portfolio_beta(data["holdings"])
                        st.metric("组合 Beta (vs SPY)", f"{beta:.2f}")
                        beta_df = pd.DataFrame(list(betas.items()), columns=["代码", "Beta"])
                        st.dataframe(beta_df, hide_index=True)
                        symbols = [h["symbol"] for h in data["holdings"] if h.get("current_price")]
                        if len(symbols) > 1:
                            corr = qa.calculate_correlation_matrix(symbols)
                            st.write("持仓相关性矩阵")
                            st.dataframe(corr.style.format("{:.2f}"))
                    except Exception as e:
                        st.error(f"计算失败: {e}")
        else:
            st.info("暂无持仓数据，无法进行组合分析。")