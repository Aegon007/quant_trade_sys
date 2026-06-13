from __future__ import annotations

from datetime import datetime

from quant_core.common.share_utils import MIN_SHARE_QUANTITY, normalize_share_quantity

DEFAULT_DUST_POSITION_VALUE = 5.0


def _parse_dt(value):
    text = str(value or "").strip()
    if not text:
        return datetime.min
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return datetime.min


def _normalize_source_records(records, *, source="ROBINHOOD_ACCOUNT_ACTIVITY_CSV"):
    normalized = []
    for index, row in enumerate(list(records or [])):
        if str((row or {}).get("source", "") or "").strip().upper() != str(source).strip().upper():
            continue
        normalized_row = dict(row or {})
        normalized_row["_source_order"] = index
        normalized.append(normalized_row)
    normalized.sort(key=_reconcile_sort_key)
    return normalized


def _reconcile_sort_key(row):
    parsed = _parse_dt((row or {}).get("date"))
    record_type = str((row or {}).get("record_type") or "").strip().upper()
    side = str((row or {}).get("side") or (row or {}).get("event_type") or "").strip().upper()
    if record_type == "CORPORATE_ACTION":
        side_rank = {"REMOVE": 0, "SHARE_DECREASE": 0, "ADD": 1, "SHARE_INCREASE": 1}.get(side, 1)
        return (parsed.date(), side_rank, int((row or {}).get("_source_order", 0) or 0))
    # Robinhood Account Activity exports often provide only the date, not the
    # intraday time. For end-of-day reconciliation, grouping buys before sells
    # on the same date avoids false residual positions when the CSV lists a
    # closing sell before the same-day opening buys.
    side_rank = {"BUY": 2, "SELL": 3}.get(side, 4)
    return (parsed.date(), side_rank, int((row or {}).get("_source_order", 0) or 0))


def build_robinhood_reconciled_portfolio(records, *, existing_data=None):
    existing_data = dict(existing_data or {})
    existing_account = dict(existing_data.get("account", {}) or {})
    existing_holdings = {
        str(row.get("symbol", "")).strip().upper(): dict(row or {})
        for row in list(existing_data.get("holdings", []) or [])
        if row.get("symbol")
    }
    existing_watchlist = {
        str(row.get("symbol", "")).strip().upper(): dict(row or {})
        for row in list(existing_data.get("watchlist", []) or [])
        if row.get("symbol")
    }

    positions = {}
    issues = []
    cash_balance = 0.0
    saw_cash_event = False
    imported_rows = _normalize_source_records(records)
    imported_trade_symbols = set()
    net_shares = {}

    for row in imported_rows:
        record_type = str(row.get("record_type", "") or "").strip().upper()
        event_type = str(row.get("event_type", "") or "").strip().upper()
        symbol = str(row.get("symbol", "") or "").strip().upper()

        if record_type == "CASH_EVENT":
            amount = row.get("proceeds")
            try:
                cash_balance += float(amount or 0.0)
                saw_cash_event = True
            except (TypeError, ValueError):
                issues.append(f"Invalid cash event amount for {event_type or 'UNKNOWN'} on {row.get('date')}.")
            continue

        if record_type == "CORPORATE_ACTION":
            try:
                shares = normalize_share_quantity(row.get("shares", 0.0))
            except (TypeError, ValueError):
                issues.append(f"Invalid corporate action row for {symbol or 'UNKNOWN'} on {row.get('date')}.")
                continue
            if not symbol or shares <= 0:
                issues.append(f"Incomplete corporate action row for {symbol or 'UNKNOWN'} on {row.get('date')}.")
                continue

            imported_trade_symbols.add(symbol)
            state = positions.setdefault(
                symbol,
                {
                    "shares": 0.0,
                    "cost": 0.0,
                    "last_trade_price": None,
                },
            )
            current_shares = float(state["shares"] or 0.0)
            current_cost = float(state["cost"] or 0.0)
            side = str(row.get("side") or "").strip().upper()
            event_type = str(row.get("event_type") or "").strip().upper()
            if side == "REMOVE" or event_type == "SHARE_DECREASE":
                net_shares[symbol] = net_shares.get(symbol, 0.0) - shares
                if shares > current_shares + 1e-9:
                    state["shares"] = 0.0
                else:
                    state["shares"] = normalize_share_quantity(current_shares - shares)
                continue

            net_shares[symbol] = net_shares.get(symbol, 0.0) + shares
            total_cost_amount = current_shares * current_cost
            total_shares = normalize_share_quantity(current_shares + shares)
            state["shares"] = total_shares
            state["cost"] = total_cost_amount / total_shares if total_shares > 0 else current_cost
            continue

        if record_type != "TRADE":
            continue

        try:
            shares = normalize_share_quantity(row.get("shares", 0.0))
            price = float(row.get("price") or row.get("cost_basis") or 0.0)
        except (TypeError, ValueError):
            issues.append(f"Invalid trade row for {symbol or 'UNKNOWN'} on {row.get('date')}.")
            continue
        if not symbol or shares <= 0 or price <= 0:
            issues.append(f"Incomplete trade row for {symbol or 'UNKNOWN'} on {row.get('date')}.")
            continue

        imported_trade_symbols.add(symbol)
        state = positions.setdefault(
            symbol,
            {
                "shares": 0.0,
                "cost": 0.0,
                "last_trade_price": None,
            },
        )
        state["last_trade_price"] = float(price)

        if event_type == "BUY":
            net_shares[symbol] = net_shares.get(symbol, 0.0) + shares
            current_shares = float(state["shares"] or 0.0)
            current_cost = float(state["cost"] or 0.0)
            total_shares = normalize_share_quantity(current_shares + shares)
            total_cost_amount = current_shares * current_cost + shares * float(price)
            state["shares"] = total_shares
            state["cost"] = total_cost_amount / total_shares if total_shares > 0 else float(price)
            cash_balance -= shares * float(price)
            continue

        if event_type == "SELL":
            net_shares[symbol] = net_shares.get(symbol, 0.0) - shares
            current_shares = float(state["shares"] or 0.0)
            if shares > current_shares + 1e-9:
                issues.append(
                    f"Detected sell quantity larger than reconstructed position for {symbol}; imported history may be incomplete."
                )
                state["shares"] = 0.0
            else:
                state["shares"] = normalize_share_quantity(current_shares - shares)
            proceeds = row.get("proceeds")
            try:
                cash_balance += float(proceeds if proceeds is not None else shares * float(price))
            except (TypeError, ValueError):
                cash_balance += shares * float(price)

    holdings = []
    held_symbols = []
    for symbol in sorted(positions.keys()):
        state = positions[symbol]
        shares = max(float(net_shares.get(symbol, state.get("shares") or 0.0) or 0.0), 0.0)
        shares = normalize_share_quantity(shares) if shares >= float(MIN_SHARE_QUANTITY) else 0.0
        if shares < float(MIN_SHARE_QUANTITY):
            continue
        existing_holding = existing_holdings.get(symbol, {})
        existing_watch = existing_watchlist.get(symbol, {})
        current_price = existing_holding.get("current_price")
        if current_price is None:
            current_price = existing_watch.get("last_price")
        if current_price is None:
            current_price = state.get("last_trade_price")
        reference_price = current_price if current_price is not None else state.get("cost")
        try:
            position_value = shares * float(reference_price)
        except (TypeError, ValueError):
            position_value = None
        if position_value is not None and 0 <= position_value < DEFAULT_DUST_POSITION_VALUE:
            issues.append(
                f"Suppressed dust-level reconstructed position for {symbol}: "
                f"{shares:.6f} shares worth about ${position_value:.2f}."
            )
            continue
        holdings.append(
            {
                "symbol": symbol,
                "shares": shares,
                "cost": float(state.get("cost") or 0.0),
                "current_price": current_price,
                "sector": str(existing_holding.get("sector", "") or "").strip(),
            }
        )
        held_symbols.append(symbol)

    watchlist = []
    for symbol, row in sorted(existing_watchlist.items()):
        if symbol in held_symbols:
            continue
        watchlist.append(row)

    watch_symbols = {str(row.get("symbol", "")).strip().upper() for row in watchlist if row.get("symbol")}
    for symbol in sorted(imported_trade_symbols):
        if symbol in held_symbols or symbol in watch_symbols:
            continue
        state = positions.get(symbol, {})
        existing_holding = existing_holdings.get(symbol, {})
        existing_watch = existing_watchlist.get(symbol, {})
        last_price = existing_watch.get("last_price")
        if last_price is None:
            last_price = existing_holding.get("current_price")
        if last_price is None:
            last_price = state.get("last_trade_price")
        watchlist.append(
            {
                "symbol": symbol,
                "notes": str(existing_watch.get("notes", "") or ""),
                "last_price": last_price,
            }
        )
        watch_symbols.add(symbol)

    watchlist.sort(key=lambda row: str(row.get("symbol", "")).strip().upper())

    cash_mode = "imported_cash_events" if saw_cash_event else "trade_flows_only"
    reconstructed_cash = round(cash_balance, 4)
    if saw_cash_event and reconstructed_cash >= 0:
        cash_available = reconstructed_cash
    else:
        # Account Activity exports often omit the starting cash balance and
        # sometimes omit transfer/sweep events. In that case the trade cash
        # flow alone is not an account cash balance, and may legitimately be
        # negative. Preserve the user's current cash input while still using
        # the CSV as the source of truth for positions.
        if saw_cash_event and reconstructed_cash < 0:
            cash_mode = "cash_preserved_incomplete_csv"
            issues.append(
                "Imported Robinhood cash events did not reconstruct a non-negative cash balance; "
                "preserved existing cash_available and rebuilt positions from trades."
            )
        cash_available = existing_account.get("cash_available")
    account = {
        "total_capital": None,
        "cash_available": cash_available,
        "min_cash_buffer_pct": existing_account.get("min_cash_buffer_pct", 0.05),
        "max_single_position_pct": existing_account.get("max_single_position_pct", 0.20),
        "max_total_exposure_pct": existing_account.get("max_total_exposure_pct", 1.0),
    }

    return {
        "account": account,
        "cash_available": cash_available,
        "trade_cash_flow": reconstructed_cash,
        "cash_mode": cash_mode,
        "holdings": holdings,
        "watchlist": watchlist,
        "issues": issues,
        "imported_record_count": len(imported_rows),
    }
