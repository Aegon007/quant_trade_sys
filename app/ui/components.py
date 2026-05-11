import streamlit as st
import pandas as pd
import html
from strategies import ui as su
from quant_core.events import analyst_consensus as ac
from quant_core.portfolio import allocation as ca
import deep_learning_strategy as dl_utils
from quant_core.portfolio.metrics import PortfolioSummary, summarize_holdings
from share_utils import format_share_quantity
from quant_core.portfolio.position import recommend_position_action
from signal_approval import approve_signal


def _consensus_display_fields(consensus, now=None):
    summary = ac.summarize_consensus_status(consensus, now=now)
    return {
        "分析师意见": summary["status"],
        "分析师看多": summary["bullish_display"],
        "分析师看空": summary["bearish_display"],
        "分析师样本": summary["sample_display"],
        "分析师说明": summary["reason"],
    }


def _resolve_signal_and_profile(strategy, symbol):
    if strategy is None:
        return "HOLD", "未选择策略，默认观望", None
    if str(strategy.get("id") or "") == "deep_tcn":
        profile = dl_utils.get_deep_tcn_signal_profile(symbol, **strategy.get("params", {}))
        return profile.signal, profile.reason, profile
    signal, reason = su.get_signal(strategy, symbol)
    return signal, reason, None


def _allocation_display_fields(
    symbol,
    last_price,
    signal,
    account,
    signal_profile=None,
    risk_gate=None,
    allocation_regime=None,
    current_invested_dollars=None,
):
    if last_price is None:
        return {
            "建议动作": "—",
            "建议投入": "—",
            "建议股数": "—",
            "资金说明": "缺少最新价格，暂无法估算建议投入金额。",
        }

    plan = ca.recommend_allocation(
        symbol=symbol,
        current_price=float(last_price),
        signal=signal,
        account=account or {},
        signal_profile=signal_profile,
        risk_gate=risk_gate,
        allocation_regime=allocation_regime,
        current_invested_dollars=current_invested_dollars,
    )
    action_label = "买入" if plan.action == "BUY" else "观望"
    dollars_text = f"${plan.recommended_dollars:,.2f}" if plan.recommended_dollars > 0 else "—"
    shares_text = format_share_quantity(plan.recommended_shares) if plan.recommended_shares > 0 else "—"
    return {
        "建议动作": action_label,
        "建议投入": dollars_text,
        "建议股数": shares_text,
        "资金说明": plan.reason,
    }


def _format_price_range(low, high):
    if low is None or high is None:
        return "—"
    try:
        low_value = float(low)
        high_value = float(high)
    except (TypeError, ValueError):
        return "—"
    if low_value <= 0 or high_value <= 0:
        return "—"
    if high_value < low_value:
        low_value, high_value = high_value, low_value
    return f"${low_value:,.2f} ~ ${high_value:,.2f}"


def _upside_price_range_display(current_price, signal_profile=None):
    if current_price is None:
        return "—"
    try:
        current_price = float(current_price)
    except (TypeError, ValueError):
        return "—"

    if signal_profile is None:
        return "—"

    expected_return_pct = getattr(signal_profile, "expected_return_pct", None)
    if expected_return_pct is None:
        return "—"
    try:
        expected_return_pct = float(expected_return_pct)
    except (TypeError, ValueError):
        return "—"
    if expected_return_pct <= 0:
        return "—"

    center_price = getattr(signal_profile, "take_profit_price", None)
    if center_price is None:
        center_price = current_price * (1.0 + expected_return_pct)
    else:
        try:
            center_price = float(center_price)
        except (TypeError, ValueError):
            center_price = current_price * (1.0 + expected_return_pct)

    confidence = getattr(signal_profile, "confidence", None)
    try:
        confidence = 0.5 if confidence is None else max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.5

    band_pct = max(
        0.02,
        min(0.08, abs(expected_return_pct) * 0.6 + (1.0 - confidence) * 0.02),
    )
    low_price = max(current_price * 1.01, center_price * (1.0 - band_pct))
    high_price = max(low_price, center_price * (1.0 + band_pct))
    return _format_price_range(low_price, high_price)


def build_holding_records(
    holdings,
    strategy,
    portfolio_value,
    risk_gate=None,
    analyst_consensus_cache=None,
    allocation_regime=None,
):
    records = []
    for i, h in enumerate(holdings):
        cost = h["cost"]
        shares = h["shares"]
        price = h.get("current_price")
        market_value = shares * price if price is not None else None
        pl = market_value - shares * cost if market_value is not None else None
        pl_pct = (pl / (shares * cost) * 100) if pl is not None and shares * cost != 0 else None

        try:
            signal, reason, _ = _resolve_signal_and_profile(strategy, h["symbol"])
        except Exception as e:
            signal, reason = "HOLD", f"信号计算失败: {e}"
        signal_approval = approve_signal(signal, risk_gate=risk_gate)
        display_signal = signal_approval.approved_signal
        display_reason = reason
        if signal_approval.blocked and signal_approval.reason:
            display_reason = f"{reason} | {signal_approval.reason}"

        advice = recommend_position_action(
            holding=h,
            portfolio_value=portfolio_value,
            signal=display_signal,
            signal_reason=display_reason,
            risk_gate=risk_gate,
            allocation_regime=allocation_regime,
        )
        consensus_fields = _consensus_display_fields(
            ac.get_cached_analyst_consensus(h["symbol"], analyst_consensus_cache)
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
            "信号": display_signal,
            "信号说明": display_reason,
            "当前仓位": advice.current_weight_pct,
            "目标仓位": advice.target_weight_pct,
            "仓位建议": advice_text,
            "仓位说明": advice.reason,
            **consensus_fields,
        })
    return records


def build_watchlist_records(
    watchlist,
    strategy=None,
    analyst_consensus_cache=None,
    account=None,
    risk_gate=None,
    allocation_regime=None,
    current_invested_dollars=None,
):
    records = []
    for i, w in enumerate(watchlist):
        last_price = w.get("last_price")
        signal, reason, signal_profile = _resolve_signal_and_profile(strategy, w["symbol"])
        consensus = ac.get_cached_analyst_consensus(w["symbol"], analyst_consensus_cache)
        consensus_fields = _consensus_display_fields(consensus)
        signal, reason = ac.apply_analyst_consensus_to_signal(signal, reason, consensus)
        signal_approval = approve_signal(signal, risk_gate=risk_gate)
        signal = signal_approval.approved_signal
        if signal_approval.blocked and signal_approval.reason:
            reason = f"{reason} | {signal_approval.reason}"
        watch_hint, _ = _watch_hint_by_signal(signal)
        allocation_fields = _allocation_display_fields(
            w["symbol"],
            last_price,
            signal,
            account or {},
            signal_profile=signal_profile,
            risk_gate=risk_gate,
            allocation_regime=allocation_regime,
            current_invested_dollars=current_invested_dollars,
        )
        records.append({
            "选择": False,
            "序号": i,
            "代码": w["symbol"],
            "备注": w.get("notes", ""),
            "最新价": f"${last_price:,.2f}" if last_price else "—",
            "上涨预期价": _upside_price_range_display(last_price, signal_profile=signal_profile),
            "信号": signal,
            "提示": watch_hint,
            "信号说明": reason,
            **allocation_fields,
            **consensus_fields,
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
    analyst_consensus_cache=None,
    allocation_regime=None,
):
    if not data["holdings"]:
        st.info("暂无持仓，请在侧边栏添加。")
        return PortfolioSummary(), []

    summary = summarize_holdings(data["holdings"])
    records = build_holding_records(
        data["holdings"],
        strategy,
        summary.total_value,
        risk_gate=risk_gate,
        analyst_consensus_cache=analyst_consensus_cache,
        allocation_regime=allocation_regime,
    )
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
            "分析师意见": None,
            "分析师看多": None,
            "分析师看空": None,
            "分析师样本": None,
            "分析师说明": None,
        },
        disabled=[
            "序号", "代码", "股数", "成本价", "市值", "盈亏 ($)", "盈亏 (%)",
            "数据来源", "信号", "信号说明", "当前仓位", "目标仓位", "仓位建议", "仓位说明",
            "分析师意见", "分析师看多", "分析师看空", "分析师样本", "分析师说明",
        ],
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
    cols = st.columns([1.1, 0.95, 0.95, 0.95, 1.15, 1.15, 0.95, 1.25, 0.8, 1.15, 0.7, 0.7, 0.7, 1.1])
    headers = ["代码", "股数", "成本价", "现价", "市值", "盈亏 ($)", "盈亏 (%)", "仓位建议", "信号", "分析师", "卖出", "编辑", "删除", "转到关注"]
    for col, h in zip(cols, headers):
        col.markdown(f"**{h}**")

    for i, row in enumerate(records):
        c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11, c12, c13, c14 = st.columns(
            [1.1, 0.95, 0.95, 0.95, 1.15, 1.15, 0.95, 1.25, 0.8, 1.15, 0.7, 0.7, 0.7, 1.1]
        )
        signal_reason = html.escape(str(row["信号说明"]))
        advice_reason = html.escape(str(row["仓位说明"]))
        advice_text = html.escape(str(row["仓位建议"]))
        analyst_status = html.escape(str(row.get("分析师意见", "无数据")))
        analyst_reason = html.escape(str(row.get("分析师说明", "")))
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

        c10.markdown(f"<span title='{analyst_reason}'>{analyst_status}</span>", unsafe_allow_html=True)

        if c11.button("💰", key=f"sell_{i}", help="卖出"):
            result = on_sell(i)
            if result is not False:
                st.rerun()

        if c12.button("✏️", key=f"edit_{i}", help="编辑"):
            st.session_state.editing_holding = i
            st.rerun()

        if c13.button("🗑️", key=f"del_{i}"):
            result = on_delete(i)
            if result is not False:
                st.rerun()
        if c14.button("转到关注", key=f"to_watch_{i}", help="清仓并转入关注列表"):
            result = on_move_to_watch(i)
            if result is not False:
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


def render_watchlist_table(
    data,
    on_delete_batch,
    on_move_to_holding,
    strategy=None,
    analyst_consensus_cache=None,
    risk_gate=None,
    allocation_regime=None,
):
    if not data["watchlist"]:
        st.info("暂无关注标的，请在侧边栏添加。")
        return []

    current_invested_dollars = summarize_holdings(data.get("holdings", [])).total_value
    records = build_watchlist_records(
        data["watchlist"],
        strategy=strategy,
        analyst_consensus_cache=analyst_consensus_cache,
        account=data.get("account", {}),
        risk_gate=risk_gate,
        allocation_regime=allocation_regime,
        current_invested_dollars=current_invested_dollars,
    )

    df = pd.DataFrame(records)
    edited_df = st.data_editor(
        df,
        column_config={
            "选择": st.column_config.CheckboxColumn("选择", default=False),
            "序号": None,
        },
        disabled=[
            "序号", "代码", "备注", "最新价", "上涨预期价",
            "信号", "提示", "信号说明",
            "建议动作", "建议投入", "建议股数", "资金说明",
            "分析师意见", "分析师看多", "分析师看空", "分析师样本", "分析师说明",
        ],
        hide_index=True,
        width="stretch",
        key="watchlist_editor"
    )

    selected_indices = [i for i, row in edited_df.iterrows() if row["选择"]]
    if selected_indices:
        if st.button(f"🗑️ 批量删除选中 ({len(selected_indices)})", type="secondary"):
            result = on_delete_batch(selected_indices)
            if result is not False:
                st.rerun()

    st.markdown("**单条操作**")
    header_cols = st.columns([1.1, 1, 1.2, 1.1, 1.1, 0.9, 2.0, 1.1])
    header_cols[0].markdown("**代码**")
    header_cols[1].markdown("**提示**")
    header_cols[2].markdown("**建议投入**")
    header_cols[3].markdown("**建议股数**")
    header_cols[4].markdown("**分析师意见**")
    header_cols[5].markdown("**样本**")
    header_cols[6].markdown("**原因**")
    header_cols[7].markdown("**操作**")
    for row in records:
        hint_text, hint_color = _watch_hint_by_signal(row.get("信号"))
        c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([1.1, 1, 1.2, 1.1, 1.1, 0.9, 2.0, 1.1])
        c1.write(row["代码"])
        c2.markdown(
            f"<span style='color:{hint_color}; font-weight:bold;'>{hint_text}</span>",
            unsafe_allow_html=True,
        )
        allocation_reason = html.escape(str(row.get("资金说明", "")))
        c3.markdown(f"<span title='{allocation_reason}'>{row.get('建议投入', '—')}</span>", unsafe_allow_html=True)
        c4.write(row.get("建议股数", "—"))
        analyst_status = html.escape(str(row.get("分析师意见", "无数据")))
        analyst_reason = html.escape(str(row.get("分析师说明", "")))
        c5.markdown(f"<span title='{analyst_reason}'>{analyst_status}</span>", unsafe_allow_html=True)
        c6.write(row.get("分析师样本", "—"))
        reason = html.escape(str(row.get("信号说明", "")))
        c7.markdown(f"<span title='{reason}'>{reason}</span>", unsafe_allow_html=True)
        if c8.button("转到持仓", key=f"to_holding_{row['序号']}", help="打开窗口输入转入股数"):
            result = on_move_to_holding(row["序号"])
            if result is not False:
                st.rerun()
    return records
