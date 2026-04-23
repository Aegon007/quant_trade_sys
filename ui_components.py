import streamlit as st
import pandas as pd
import strategy_ui as su

def render_holdings_table(data, on_price_change, on_delete, on_sell, strategy):
    if not data["holdings"]:
        st.info("暂无持仓，请在侧边栏添加。")
        return 0, 0, 0, 0

    records = []
    for i, h in enumerate(data["holdings"]):
        cost = h["cost"]
        shares = h["shares"]
        price = h.get("current_price")
        market_value = shares * price if price is not None else None
        pl = market_value - shares * cost if market_value is not None else None
        pl_pct = (pl / (shares * cost) * 100) if pl is not None and shares*cost != 0 else None

        # 计算策略信号
        try:
            signal, reason = su.get_signal(strategy, h["symbol"])
        except Exception as e:
            signal, reason = "HOLD", f"信号计算失败: {e}"

        records.append({
            "序号": i,
            "代码": h["symbol"],
            "股数": shares,
            "成本价": cost,
            "现价": price,
            "市值": market_value,
            "盈亏 ($)": pl,
            "盈亏 (%)": pl_pct,
            "数据来源": "自动" if price is not None else "待刷新",
            "信号": signal,
            "信号说明": reason
        })

    df = pd.DataFrame(records)

    edited_df = st.data_editor(
        df,
        column_config={
            "序号": None,
            "现价": st.column_config.NumberColumn("现价 (USD)", min_value=0.0, step=0.01, format="%.2f"),
            "市值": st.column_config.NumberColumn("市值 (USD)", format="%.2f"),
            "盈亏 ($)": st.column_config.NumberColumn("盈亏 ($)", format="%.2f"),
            "盈亏 (%)": st.column_config.NumberColumn("盈亏 (%)", format="%.2f"),
            "数据来源": None,
            "信号": None,
            "信号说明": None,
        },
        disabled=["序号", "代码", "股数", "成本价", "市值", "盈亏 ($)", "盈亏 (%)", "数据来源", "信号", "信号说明"],
        hide_index=True,
        use_container_width=True,
        key="holdings_editor"
    )

    for idx, row in edited_df.iterrows():
        new_price = row["现价"]
        if not pd.isna(new_price):
            old_price = data["holdings"][idx].get("current_price")
            if old_price != new_price:
                on_price_change(idx, new_price)

    # 渲染表格头部
    cols = st.columns([1.2, 1, 1, 1, 1.2, 1.2, 1, 0.8, 0.8, 0.7, 0.7, 0.7])
    headers = ["代码", "股数", "成本价", "现价", "市值", "盈亏 ($)", "盈亏 (%)", "来源", "信号", "卖出", "编辑", "删除"]
    for col, h in zip(cols, headers):
        col.markdown(f"**{h}**")

    for i, row in enumerate(records):
        c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11, c12 = st.columns([1.2, 1, 1, 1, 1.2, 1.2, 1, 0.8, 0.8, 0.7, 0.7, 0.7])
        c1.write(row["代码"])
        c2.write(f"{row['股数']:,.0f}")
        c3.write(f"${row['成本价']:,.2f}")
        c4.write(f"${row['现价']:,.2f}" if row["现价"] else "—")
        c5.write(f"${row['市值']:,.2f}" if row["市值"] else "—")
        pl_val = row["盈亏 ($)"]
        if pl_val is not None:
            color = "#0b7b44" if pl_val >= 0 else "#c2410c"
            c6.markdown(f"<span style='color:{color};'>${pl_val:+,.2f}</span>", unsafe_allow_html=True)
        else:
            c6.write("—")
        pl_pct_val = row["盈亏 (%)"]
        if pl_pct_val is not None:
            color = "#0b7b44" if pl_pct_val >= 0 else "#c2410c"
            c7.markdown(f"<span style='color:{color};'>{pl_pct_val:+.2f}%</span>", unsafe_allow_html=True)
        else:
            c7.write("—")
        c8.write(row["数据来源"])

        # 信号列
        signal = row["信号"]
        if signal == "BUY":
            c9.markdown(f"<span style='color:#0b7b44; font-weight:bold;' title='{row['信号说明']}'>买入</span>", unsafe_allow_html=True)
        elif signal == "SELL":
            c9.markdown(f"<span style='color:#c2410c; font-weight:bold;' title='{row['信号说明']}'>卖出</span>", unsafe_allow_html=True)
        else:
            c9.markdown(f"<span style='color:#6b7280;' title='{row['信号说明']}'>持有</span>", unsafe_allow_html=True)

        if c10.button("💰", key=f"sell_{i}", help="卖出"):
            on_sell(i)
            st.rerun()

        if c11.button("✏️", key=f"edit_{i}", help="编辑"):
            st.session_state.editing_holding = i
            st.rerun()

        if c12.button("🗑️", key=f"del_{i}"):
            on_delete(i)
            st.rerun()

    total_cost = sum(h["shares"] * h["cost"] for h in data["holdings"])
    total_value = sum(h["shares"] * h.get("current_price", 0) for h in data["holdings"] if h.get("current_price"))
    total_pl = total_value - total_cost
    total_pl_pct = (total_pl / total_cost * 100) if total_cost != 0 else 0
    return total_cost, total_value, total_pl, total_pl_pct


def render_watchlist_table(data, on_delete_batch):
    if not data["watchlist"]:
        st.info("暂无关注标的，请在侧边栏添加。")
        return

    records = []
    for i, w in enumerate(data["watchlist"]):
        last_price = w.get("last_price")
        target_buy = w.get("target_buy")
        diff = None
        if last_price and target_buy:
            diff = last_price - target_buy
        records.append({
            "选择": False,
            "序号": i,
            "代码": w["symbol"],
            "备注": w.get("notes", ""),
            "目标买入价": f"${target_buy:,.2f}" if target_buy else "—",
            "最新价": f"${last_price:,.2f}" if last_price else "—",
            "距目标": f"${diff:+,.2f}" if diff is not None else "—"
        })

    df = pd.DataFrame(records)
    edited_df = st.data_editor(
        df,
        column_config={
            "选择": st.column_config.CheckboxColumn("选择", default=False),
            "序号": None,
        },
        disabled=["序号", "代码", "备注", "目标买入价", "最新价", "距目标"],
        hide_index=True,
        use_container_width=True,
        key="watchlist_editor"
    )

    selected_indices = [i for i, row in edited_df.iterrows() if row["选择"]]
    if selected_indices:
        if st.button(f"🗑️ 批量删除选中 ({len(selected_indices)})", type="secondary"):
            on_delete_batch(selected_indices)
            st.rerun()