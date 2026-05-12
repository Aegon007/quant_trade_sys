import pandas as pd


_RAW_TRANSACTION_COLUMNS = [
    "date",
    "event_type",
    "symbol",
    "side",
    "shares",
    "price",
    "cost_basis",
    "proceeds",
    "pl",
    "pl_pct",
    "notes",
]

_DISPLAY_TRANSACTION_COLUMNS = [
    "日期",
    "类型",
    "代码",
    "方向",
    "股数",
    "价格",
    "成本价",
    "收入",
    "盈亏 ($)",
    "盈亏 (%)",
    "备注",
]


def _format_money(value):
    return f"${value:,.2f}" if pd.notna(value) else "—"


def _format_percent(value):
    return f"{value:+.2f}%" if pd.notna(value) else "—"


def build_holdings_markdown(holding_records, summary, *, format_share_quantity_fn, labels):
    lines = ["| 代码 | 股数 | 成本价 | 现价 | 市值 | 盈亏 ($) | 盈亏 (%) | 信号 | 分析师意见 |"]
    lines.append("|------|------|--------|------|------|----------|----------|------|------------|")
    for row in holding_records or []:
        price_text = _format_money(row.get("现价"))
        value_text = _format_money(row.get("市值"))
        pl_text = f"${row['盈亏 ($)']:+,.2f}" if row.get("盈亏 ($)") is not None else "—"
        pl_pct_text = f"{row['盈亏 (%)']:+.2f}%" if row.get("盈亏 (%)") is not None else "—"
        lines.append(
            f"| {row.get('代码', '')} | {format_share_quantity_fn(row.get('股数', 0.0))} | "
            f"${float(row.get('成本价', 0.0)):,.2f} | {price_text} | {value_text} | "
            f"{pl_text} | {pl_pct_text} | {row.get('信号', '')} | {row.get('分析师意见', '无数据')} |"
        )
    lines.append(
        f"\n**{labels['total_cost']}**: ${float(summary.total_cost):,.2f}  "
        f"\n**{labels['total_value']}**: ${float(summary.total_value):,.2f}  "
        f"\n**{labels['total_pl']}**: ${float(summary.total_pl):+,.2f} ({float(summary.total_pl_pct):+.2f}%)"
    )
    return "\n".join(lines)


def build_transaction_display_dataframe(rows, *, format_share_quantity_fn):
    df = pd.DataFrame(rows or [])
    for column in _RAW_TRANSACTION_COLUMNS:
        if column not in df.columns:
            df[column] = None
    if df.empty:
        df = pd.DataFrame(columns=_RAW_TRANSACTION_COLUMNS)

    df_display = df[_RAW_TRANSACTION_COLUMNS].copy()
    df_display["shares"] = df_display["shares"].apply(
        lambda value: format_share_quantity_fn(value) if pd.notna(value) else "—"
    )
    df_display["价格"] = df_display["price"].apply(_format_money)
    df_display["成本价"] = df_display["cost_basis"].apply(_format_money)
    df_display["收入"] = df_display["proceeds"].apply(_format_money)
    df_display["盈亏 ($)"] = df_display["pl"].apply(
        lambda value: f"${value:+,.2f}" if pd.notna(value) else "—"
    )
    df_display["盈亏 (%)"] = df_display["pl_pct"].apply(_format_percent)
    df_display = df_display[
        [
            "date",
            "event_type",
            "symbol",
            "side",
            "shares",
            "价格",
            "成本价",
            "收入",
            "盈亏 ($)",
            "盈亏 (%)",
            "notes",
        ]
    ]
    df_display.columns = _DISPLAY_TRANSACTION_COLUMNS
    return df_display


def summarize_trade_records(transaction_rows):
    trade_records = [
        row
        for row in (transaction_rows or [])
        if str(row.get("record_type", "TRADE")).upper() == "TRADE"
    ]
    total_proceeds = sum(float(row.get("proceeds", 0.0) or 0.0) for row in trade_records)
    total_pl = sum(float(row.get("pl", 0.0) or 0.0) for row in trade_records)
    return total_proceeds, total_pl


def build_snapshot_alerts(active_market_events):
    alerts = []
    for event in active_market_events or []:
        alerts.append(
            {
                "title": getattr(event, "title", ""),
                "symbols": list(getattr(event, "symbols", []) or []),
                "severity": getattr(event, "severity", ""),
                "sentiment": getattr(event, "sentiment", ""),
                "source": getattr(event, "source", ""),
                "verified": bool(getattr(event, "verified", False)),
            }
        )
    return alerts


def format_robinhood_import_result_message(result):
    result = dict(result or {})
    return (
        f"Robinhood CSV 导入完成：新增 {int(result.get('imported_count', 0) or 0)} 条，"
        f"重复跳过 {int(result.get('duplicate_count', 0) or 0)} 条，"
        f"不支持/缺失字段跳过 {int(result.get('skipped_count', 0) or 0)} 条。"
    )


def format_robinhood_reconcile_result_message(result):
    result = dict(result or {})
    issues = list(result.get("issues", []) or [])
    issue_text = " | ".join(issues[:3]) if issues else "无异常。"
    return (
        f"Robinhood 持仓同步完成：持仓 {len(result.get('holdings', []) or [])} 个，"
        f"可用现金 ${float(result.get('cash_available', 0.0) or 0.0):,.2f}，"
        f"现金依据 {result.get('cash_mode', 'unknown')}。"
        f" {issue_text}"
    )


def render_transactions_tab(
    *,
    tx_module,
    L,
    format_share_quantity_fn,
    st_module=None,
    session_state=None,
    portfolio_actions_module=None,
    data_utils_module=None,
):
    if st_module is None:
        import streamlit as st_module  # lazy import to keep helper tests lightweight

    if session_state is not None:
        notice = session_state.pop("robinhood_reconcile_notice", None)
        if isinstance(notice, dict):
            level = str(notice.get("level", "info")).lower()
            message = str(notice.get("message", "") or "")
            if message:
                if level == "success":
                    st_module.success(message)
                elif level == "warning":
                    st_module.warning(message)
                else:
                    st_module.info(message)

    st_module.subheader("Robinhood CSV 导入")
    st_module.caption("支持导入 Robinhood Account activity report CSV；会同步股票/ETF 买卖以及可识别的现金事件，并自动按导入指纹去重。")
    uploaded_file = st_module.file_uploader(
        "上传 Robinhood Account activity report CSV",
        type=["csv"],
        key="robinhood_activity_csv_uploader",
    )
    if uploaded_file is not None and st_module.button("导入 Robinhood CSV", key="import_robinhood_activity_csv"):
        result = tx_module.import_robinhood_activity_csv(
            uploaded_file.getvalue(),
            filename=getattr(uploaded_file, "name", "robinhood_activity.csv"),
        )
        message = format_robinhood_import_result_message(result)
        if int(result.get("imported_count", 0) or 0) > 0:
            st_module.success(message)
        elif int(result.get("duplicate_count", 0) or 0) > 0 or int(result.get("skipped_count", 0) or 0) > 0:
            st_module.info(message)
        else:
            st_module.warning("未识别到可导入的交易记录，请检查 CSV 是否为 Robinhood Account activity report。")

    if portfolio_actions_module is not None and data_utils_module is not None:
        if st_module.button("按 Robinhood 导入记录同步当前持仓/可用现金", key="reconcile_robinhood_imports"):
            try:
                result = portfolio_actions_module.reconcile_portfolio_from_robinhood_imports()
            except ValueError as exc:
                st_module.error(str(exc))
            else:
                if session_state is not None:
                    session_state.app_data = data_utils_module.load_data()
                message = format_robinhood_reconcile_result_message(result)
                has_issues = bool(result.get("issues"))
                if session_state is not None:
                    session_state["robinhood_reconcile_notice"] = {
                        "level": "warning" if has_issues else "success",
                        "message": message,
                    }
                    rerun_fn = getattr(st_module, "rerun", None) or getattr(st_module, "experimental_rerun", None)
                    if callable(rerun_fn):
                        rerun_fn()
                elif has_issues:
                    st_module.warning(message)
                else:
                    st_module.success(message)

    transaction_rows = tx_module.normalize_transactions(tx_module.load_transactions())
    if not transaction_rows:
        st_module.info(L("no_transactions"))
        return

    all_event_types = sorted({row.get("event_type", "") for row in transaction_rows if row.get("event_type")})
    all_sides = sorted({row.get("side", "") for row in transaction_rows if row.get("side")})
    all_symbols = sorted({row.get("symbol", "") for row in transaction_rows if row.get("symbol")})

    c_filter1, c_filter2, c_filter3 = st_module.columns(3)
    selected_event_type = c_filter1.selectbox("类型筛选", ["全部"] + all_event_types, index=0)
    selected_side = c_filter2.selectbox("方向筛选", ["全部"] + all_sides, index=0)
    selected_symbol = c_filter3.selectbox("代码筛选", ["全部"] + all_symbols, index=0)

    filtered_rows = tx_module.filter_transactions(
        transaction_rows,
        event_type=None if selected_event_type == "全部" else selected_event_type,
        side=None if selected_side == "全部" else selected_side,
        symbol=None if selected_symbol == "全部" else selected_symbol,
    )
    if not filtered_rows:
        st_module.info("当前筛选条件下没有记录。")
        filtered_rows = []

    df_display = build_transaction_display_dataframe(
        filtered_rows,
        format_share_quantity_fn=format_share_quantity_fn,
    )
    st_module.dataframe(df_display, hide_index=True, width="stretch")
    total_proceeds, total_pl = summarize_trade_records(transaction_rows)
    c1, c2 = st_module.columns(2)
    c1.metric(L("total_income"), f"${total_proceeds:,.2f}")
    c2.metric(L("total_pl_trans"), f"${total_pl:+,.2f}")
