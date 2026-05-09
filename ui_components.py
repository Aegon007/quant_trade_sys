import streamlit as st
import pandas as pd
import html
import strategy_ui as su
import analyst_consensus as ac
from portfolio_metrics import PortfolioSummary, summarize_holdings
from share_utils import format_share_quantity
from position_advisor import recommend_position_action


def build_holding_records(holdings, strategy, portfolio_value, risk_gate=None):
    records = []
    for i, h in enumerate(holdings):
        cost = h["cost"]
        shares = h["shares"]
        price = h.get("current_price")
        market_value = shares * price if price is not None else None
        pl = market_value - shares * cost if market_value is not None else None
        pl_pct = (pl / (shares * cost) * 100) if pl is not None and shares * cost != 0 else None

        try:
            signal, reason = su.get_signal(strategy, h["symbol"])
        except Exception as e:
            signal, reason = "HOLD", f"信号计算失败: {e}"

        advice = recommend_position_action(
            holding=h,
            portfolio_value=portfolio_value,
            signal=signal,
            signal_reason=reason,
            risk_gate=risk_gate,
        )

        advice_text = "持有"
        if advice.action == "ADD" and advice.delta_shares:
            advice_text = f"加仓 +{format_share_quantity(advice.delta_shares)}"
        elif advice.action == "TRIM" and advice.delta_shares:
            advice_text = f"减仓 -{format_share_quantity(abs(advice.delta_shares))}"
        elif advice.action == "EXIT" and advice.delta_shares is not None:
            advice_text = f"清仓 -{format_share_quantity(abs(advice.delta_shares))}"

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
            "信号说明": reason,
            "当前仓位": advice.current_weight_pct,
            "目标仓位": advice.target_weight_pct,
            "仓位建议": advice_text,
            "仓位说明": advice.reason,
        })
    return records

def render_holdings_table(
    data,
    on_price_change,
    on_delete,
    on_sell,
    on_move_to_watch,
    strategy,
    risk_gate=None,
):
    if not data["holdings"]:
        st.info("暂无持仓，请在侧边栏添加。")
        return PortfolioSummary(), []

    summary = summarize_holdings(data["holdings"])
    records = build_holding_records(data["holdings"], strategy, summary.total_value, risk_gate=risk_gate)
    df = pd.DataFrame(records)

    edited_df = st.data_editor(
        df,
        column_config={
            "序号": None,
            "股数": st.column_config.NumberColumn("股数", min_value=0.0, step=0.001, format="%.3f"),
            "现价": st.column_config.NumberColumn("现价 (USD)", min_value=0.0, step=0.01, format="%.2f"),
            "市值": st.column_config.NumberColumn("市值 (USD)", format="%.2f"),
            "盈亏 ($)": st.column_config.NumberColumn("盈亏 ($)", format="%.2f"),
            "盈亏 (%)": st.column_config.NumberColumn("盈亏 (%)", format="%.2f"),
            "数据来源": None,
            "信号": None,
            "信号说明": None,
            "当前仓位": None,
            "目标仓位": None,
            "仓位建议": None,
            "仓位说明": None,
        },
        disabled=["序号", "代码", "股数", "成本价", "市值", "盈亏 ($)", "盈亏 (%)", "数据来源", "信号", "信号说明", "当前仓位", "目标仓位", "仓位建议", "仓位说明"],
        hide_index=True,
        width="stretch",
        key="holdings_editor"
    )

    price_updated = False
    for idx, row in edited_df.iterrows():
        new_price = row["现价"]
        if not pd.isna(new_price):
            old_price = data["holdings"][idx].get("current_price")
            if old_price != new_price:
                on_price_change(idx, new_price)
                price_updated = True

    if price_updated:
        st.rerun()

    # 渲染表格头部
    cols = st.columns([1.2, 1, 1, 1, 1.2, 1.2, 1, 1.4, 0.8, 0.7, 0.7, 0.7, 1.2])
    headers = ["代码", "股数", "成本价", "现价", "市值", "盈亏 ($)", "盈亏 (%)", "仓位建议", "信号", "卖出", "编辑", "删除", "转到关注"]
    for col, h in zip(cols, headers):
        col.markdown(f"**{h}**")

    for i, row in enumerate(records):
        c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11, c12, c13 = st.columns(
            [1.2, 1, 1, 1, 1.2, 1.2, 1, 1.4, 0.8, 0.7, 0.7, 0.7, 1.2]
        )
        signal_reason = html.escape(str(row["信号说明"]))
        advice_reason = html.escape(str(row["仓位说明"]))
        advice_text = html.escape(str(row["仓位建议"]))
        c1.write(row["代码"])
        c2.write(format_share_quantity(row["股数"]))
        c3.write(f"${row['成本价']:,.2f}")
        c4.write(f"${row['现价']:,.2f}" if row["现价"] is not None else "—")
        c5.write(f"${row['市值']:,.2f}" if row["市值"] is not None else "—")
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
        c8.markdown(
            f"<span title='{advice_reason}'>{advice_text} ({row['目标仓位']:.1f}%)</span>",
            unsafe_allow_html=True
        )

        # 信号列
        signal = row["信号"]
        if signal == "BUY":
            c9.markdown(f"<span style='color:#0b7b44; font-weight:bold;' title='{signal_reason}'>买入</span>", unsafe_allow_html=True)
        elif signal == "SELL":
            c9.markdown(f"<span style='color:#c2410c; font-weight:bold;' title='{signal_reason}'>卖出</span>", unsafe_allow_html=True)
        else:
            c9.markdown(f"<span style='color:#6b7280;' title='{signal_reason}'>持有</span>", unsafe_allow_html=True)

        if c10.button("💰", key=f"sell_{i}", help="卖出"):
            on_sell(i)
            st.rerun()

        if c11.button("✏️", key=f"edit_{i}", help="编辑"):
            st.session_state.editing_holding = i
            st.rerun()

        if c12.button("🗑️", key=f"del_{i}"):
            on_delete(i)
            st.rerun()
        if c13.button("转到关注", key=f"to_watch_{i}", help="清仓并转入关注列表"):
            on_move_to_watch(i)
            st.rerun()

    if summary.missing_price_count:
        st.caption(f"注：有 {summary.missing_price_count} 个持仓缺少现价，盈亏仅基于已定价持仓计算。")
    return summary, records


def _watch_hint_by_signal(signal):
    normalized = str(signal or "").strip().upper()
    if normalized == "STRONG_BUY":
        return "强烈买入", "#047857"
    if normalized == "STRONG_SELL":
        return "强烈卖出", "#b91c1c"
    if normalized == "BUY":
        return "可以买入", "#0b7b44"
    if normalized == "SELL":
        return "不可买入", "#c2410c"
    return "观望", "#6b7280"


def render_watchlist_table(data, on_delete_batch, on_move_to_holding, strategy=None, analyst_consensus_cache=None):
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
        if strategy is None:
            signal, reason = "HOLD", "未选择策略，默认观望"
        else:
            signal, reason = su.get_signal(strategy, w["symbol"])
        consensus = ac.get_cached_analyst_consensus(w["symbol"], analyst_consensus_cache)
        analyst_status = "无数据"
        analyst_bullish = "—"
        analyst_bearish = "—"
        analyst_sample = "—"
        analyst_reason = "暂无分析师共识数据。"
        if consensus:
            is_fresh = ac.is_cached_consensus_fresh(consensus)
            raw_signal = str(consensus.get("signal") or "").upper()
            bullish_ratio = consensus.get("bullish_ratio")
            bearish_ratio = consensus.get("bearish_ratio")
            total = consensus.get("total")
            if bullish_ratio is not None:
                analyst_bullish = f"{float(bullish_ratio):.1%}"
            if bearish_ratio is not None:
                analyst_bearish = f"{float(bearish_ratio):.1%}"
            if total is not None:
                analyst_sample = str(total)
            if not is_fresh:
                analyst_status = "已过期"
                analyst_reason = "分析师共识缓存已过期（超过 7 天），不参与当前提示。"
            elif raw_signal == "STRONG_BUY":
                analyst_status = "强烈看多"
                analyst_reason = str(consensus.get("reason") or "分析师共识触发强烈买入。")
            elif raw_signal == "STRONG_SELL":
                analyst_status = "强烈看空"
                analyst_reason = str(consensus.get("reason") or "分析师共识触发强烈卖出。")
            else:
                analyst_status = "不触发"
                analyst_reason = str(consensus.get("reason") or "分析师共识未达到触发阈值。")
        signal, reason = ac.apply_analyst_consensus_to_signal(signal, reason, consensus)
        watch_hint, _ = _watch_hint_by_signal(signal)
        records.append({
            "选择": False,
            "序号": i,
            "代码": w["symbol"],
            "备注": w.get("notes", ""),
            "目标买入价": f"${target_buy:,.2f}" if target_buy else "—",
            "最新价": f"${last_price:,.2f}" if last_price else "—",
            "距目标": f"${diff:+,.2f}" if diff is not None else "—",
            "信号": signal,
            "提示": watch_hint,
            "信号说明": reason,
            "分析师意见": analyst_status,
            "分析师看多": analyst_bullish,
            "分析师看空": analyst_bearish,
            "分析师样本": analyst_sample,
            "分析师说明": analyst_reason,
        })

    df = pd.DataFrame(records)
    edited_df = st.data_editor(
        df,
        column_config={
            "选择": st.column_config.CheckboxColumn("选择", default=False),
            "序号": None,
        },
        disabled=[
            "序号", "代码", "备注", "目标买入价", "最新价", "距目标",
            "信号", "提示", "信号说明",
            "分析师意见", "分析师看多", "分析师看空", "分析师样本", "分析师说明",
        ],
        hide_index=True,
        width="stretch",
        key="watchlist_editor"
    )

    selected_indices = [i for i, row in edited_df.iterrows() if row["选择"]]
    if selected_indices:
        if st.button(f"🗑️ 批量删除选中 ({len(selected_indices)})", type="secondary"):
            on_delete_batch(selected_indices)
            st.rerun()

    st.markdown("**单条操作**")
    header_cols = st.columns([1.2, 1, 1.1, 1.1, 0.9, 2.2, 1.1])
    header_cols[0].markdown("**代码**")
    header_cols[1].markdown("**提示**")
    header_cols[2].markdown("**分析师意见**")
    header_cols[3].markdown("**看多/看空**")
    header_cols[4].markdown("**样本**")
    header_cols[5].markdown("**原因**")
    header_cols[6].markdown("**操作**")
    for row in records:
        hint_text, hint_color = _watch_hint_by_signal(row.get("信号"))
        c1, c2, c3, c4, c5, c6, c7 = st.columns([1.2, 1, 1.1, 1.1, 0.9, 2.2, 1.1])
        c1.write(row["代码"])
        c2.markdown(
            f"<span style='color:{hint_color}; font-weight:bold;'>{hint_text}</span>",
            unsafe_allow_html=True,
        )
        analyst_status = html.escape(str(row.get("分析师意见", "无数据")))
        analyst_reason = html.escape(str(row.get("分析师说明", "")))
        c3.markdown(f"<span title='{analyst_reason}'>{analyst_status}</span>", unsafe_allow_html=True)
        c4.write(f"{row.get('分析师看多', '—')} / {row.get('分析师看空', '—')}")
        c5.write(row.get("分析师样本", "—"))
        reason = html.escape(str(row.get("信号说明", "")))
        c6.markdown(f"<span title='{reason}'>{reason}</span>", unsafe_allow_html=True)
        if c7.button("转到持仓", key=f"to_holding_{row['序号']}", help="按 1 股转入持仓"):
            on_move_to_holding(row["序号"])
            st.rerun()
