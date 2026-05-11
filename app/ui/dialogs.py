import streamlit as st


def clear_dialog_index_if_out_of_range(session_state, *, key: str, record_count: int) -> bool:
    idx = session_state.get(key)
    if idx is None:
        return False
    if idx < 0 or idx >= int(record_count):
        session_state[key] = None
        return True
    return False


def render_portfolio_dialogs(
    *,
    session_state,
    data,
    L,
    st_module=None,
    data_utils_module=None,
    portfolio_actions_module=None,
    format_share_quantity_fn=None,
    validate_share_quantity_fn=None,
):
    st_module = st_module or st
    du = data_utils_module
    pactions = portfolio_actions_module
    format_share_quantity = format_share_quantity_fn
    validate_share_quantity = validate_share_quantity_fn

    if clear_dialog_index_if_out_of_range(session_state, key="sell_dialog_index", record_count=len(data.get("holdings", []))):
        st_module.rerun()
    if clear_dialog_index_if_out_of_range(session_state, key="buy_dialog_index", record_count=len(data.get("holdings", []))):
        st_module.rerun()
    if clear_dialog_index_if_out_of_range(session_state, key="editing_holding", record_count=len(data.get("holdings", []))):
        st_module.rerun()
    if clear_dialog_index_if_out_of_range(session_state, key="move_watch_dialog_index", record_count=len(data.get("watchlist", []))):
        st_module.rerun()

    if session_state.sell_dialog_index is not None:
        idx = session_state.sell_dialog_index
        h = data["holdings"][idx]
        with st_module.expander(f"{L('sell_dialog_title')} {h['symbol']}", expanded=True):
            col1, col2 = st_module.columns(2)
            with col1:
                sell_price = st_module.number_input(
                    L("sell_price"),
                    min_value=0.0,
                    value=h.get("current_price") or 0.0,
                    step=0.01,
                    format="%.2f",
                )
            with col2:
                max_s = h["shares"]
                sell_shares = st_module.number_input(
                    L("sell_shares"),
                    min_value=0.0,
                    max_value=float(max_s),
                    value=float(max_s),
                    step=0.001,
                    format="%.3f",
                )
            if st_module.button(L("confirm_sell")) and sell_shares > 0:
                try:
                    result = pactions.sell_symbol(h["symbol"], sell_shares, price=sell_price)
                    session_state.app_data = du.load_data()
                    st_module.success(
                        f"已卖出 {result['symbol']} {format_share_quantity(sell_shares)} 股 @ ${result['price']:.2f}"
                    )
                    session_state.sell_dialog_index = None
                    st_module.rerun()
                except ValueError as e:
                    st_module.error(str(e))
            if st_module.button(L("cancel")):
                session_state.sell_dialog_index = None
                st_module.rerun()

    if session_state.buy_dialog_index is not None:
        idx = session_state.buy_dialog_index
        h = data["holdings"][idx]
        default_price = float(h.get("current_price") or h.get("cost") or 0.0)
        with st_module.expander(f"买入加仓 {h['symbol']}", expanded=True):
            col1, col2 = st_module.columns(2)
            with col1:
                buy_price = st_module.number_input(
                    "买入价格",
                    min_value=0.0,
                    value=default_price,
                    step=0.01,
                    format="%.2f",
                    key=f"buy_price_input_{idx}",
                )
            with col2:
                buy_shares = st_module.number_input(
                    "买入股数",
                    min_value=0.001,
                    value=1.0,
                    step=0.001,
                    format="%.3f",
                    key=f"buy_shares_input_{idx}",
                )
            if st_module.button("确认买入", key=f"confirm_buy_{idx}") and buy_shares > 0:
                try:
                    normalized_shares = validate_share_quantity(buy_shares, field_name="shares")
                    result = pactions.buy_symbol(
                        h["symbol"],
                        normalized_shares,
                        price=buy_price,
                        sector=h.get("sector", ""),
                    )
                    session_state.app_data = du.load_data()
                    st_module.success(
                        f"已买入 {result['symbol']} {format_share_quantity(normalized_shares)} 股 @ ${result['price']:.2f}"
                    )
                    session_state.buy_dialog_index = None
                    st_module.rerun()
                except ValueError as e:
                    st_module.error(str(e))
            if st_module.button(L("cancel"), key=f"cancel_buy_{idx}"):
                session_state.buy_dialog_index = None
                st_module.rerun()

    if session_state.editing_holding is not None:
        idx = session_state.editing_holding
        h = data["holdings"][idx]
        with st_module.expander(f"{L('edit_dialog_title')} {h['symbol']}", expanded=True):
            with st_module.form("edit_holding_form"):
                new_shares = st_module.number_input(
                    L("shares"),
                    min_value=0.0,
                    value=float(h["shares"]),
                    step=0.001,
                    format="%.3f",
                )
                new_cost = st_module.number_input(
                    L("cost_price"),
                    min_value=0.0,
                    value=float(h["cost"]),
                    step=0.01,
                    format="%.2f",
                )
                new_sector = st_module.text_input(L("sector"), value=h.get("sector", ""))
                c1, c2 = st_module.columns(2)
                with c1:
                    if st_module.form_submit_button(L("save")):
                        if new_shares > 0:
                            try:
                                normalized_shares = validate_share_quantity(new_shares, field_name="shares")
                                pactions.update_holding_record(
                                    h["symbol"],
                                    shares=normalized_shares,
                                    cost=new_cost,
                                    sector=new_sector.strip(),
                                    current_price=h.get("current_price"),
                                )
                                session_state.app_data = du.load_data()
                                st_module.success(L("save") + " 成功")
                                session_state.editing_holding = None
                                st_module.rerun()
                            except ValueError as e:
                                st_module.error(str(e))
                        else:
                            st_module.error(L("shares") + " 必须大于0")
                with c2:
                    if st_module.form_submit_button(L("cancel")):
                        session_state.editing_holding = None
                        st_module.rerun()

    if session_state.move_watch_dialog_index is not None:
        idx = session_state.move_watch_dialog_index
        watch_item = data["watchlist"][idx]
        symbol = watch_item["symbol"]
        default_shares = float(session_state.get("move_watch_dialog_shares", 1.0) or 1.0)

        def _render_move_watch_form():
            st_module.write(f"将 `{symbol}` 转到持仓。")
            shares = st_module.number_input(
                "买入股数",
                min_value=0.001,
                value=default_shares,
                step=0.001,
                format="%.3f",
                key=f"move_watch_shares_input_{idx}",
            )
            c1, c2 = st_module.columns(2)
            with c1:
                if st_module.button("确认转入", key=f"confirm_move_watch_{idx}"):
                    try:
                        normalized_shares = validate_share_quantity(shares, field_name="shares")
                        action = pactions.move_watch_to_holding(symbol, normalized_shares)
                        session_state.app_data = du.load_data()
                        session_state.move_watch_dialog_shares = float(normalized_shares)
                        st_module.success(
                            f"已转到持仓 {action['symbol']} {format_share_quantity(action['shares'])} 股 @ ${action['price']:.2f}"
                        )
                        session_state.move_watch_dialog_index = None
                        st_module.rerun()
                    except ValueError as e:
                        st_module.error(str(e))
            with c2:
                if st_module.button(L("cancel"), key=f"cancel_move_watch_{idx}"):
                    session_state.move_watch_dialog_index = None
                    st_module.rerun()

        dialog_api = getattr(st_module, "dialog", None)
        if callable(dialog_api):
            @dialog_api("转到持仓", width="small")
            def _move_watch_dialog():
                _render_move_watch_form()

            _move_watch_dialog()
        else:
            experimental_dialog_api = getattr(st_module, "experimental_dialog", None)
            if callable(experimental_dialog_api):
                @experimental_dialog_api("转到持仓", width="small")
                def _move_watch_dialog_legacy():
                    _render_move_watch_form()

                _move_watch_dialog_legacy()
            else:
                with st_module.expander(f"转到持仓 {symbol}", expanded=True):
                    _render_move_watch_form()
