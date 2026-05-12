from __future__ import annotations

from datetime import datetime

from share_utils import MIN_SHARE_QUANTITY, normalize_share_quantity


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
    for row in list(records or []):
        if str((row or {}).get("source", "") or "").strip().upper() != str(source).strip().upper():
            continue
        normalized.append(dict(row or {}))
    normalized.sort(key=lambda row: _parse_dt(row.get("date")))
    return normalized


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
            current_shares = float(state["shares"] or 0.0)
            current_cost = float(state["cost"] or 0.0)
            total_shares = normalize_share_quantity(current_shares + shares)
            total_cost_amount = current_shares * current_cost + shares * float(price)
            state["shares"] = total_shares
            state["cost"] = total_cost_amount / total_shares if total_shares > 0 else float(price)
            cash_balance -= shares * float(price)
            continue

        if event_type == "SELL":
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
        shares = float(state.get("shares") or 0.0)
        if shares < float(MIN_SHARE_QUANTITY):
            continue
        existing_holding = existing_holdings.get(symbol, {})
        existing_watch = existing_watchlist.get(symbol, {})
        current_price = existing_holding.get("current_price")
        if current_price is None:
            current_price = existing_watch.get("last_price")
        if current_price is None:
            current_price = state.get("last_trade_price")
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

    cash_mode = "imported_cash_events" if saw_cash_event else "trade_flows_only"
    account = {
        "total_capital": None,
        "cash_available": round(cash_balance, 4),
        "min_cash_buffer_pct": existing_account.get("min_cash_buffer_pct", 0.05),
        "max_single_position_pct": existing_account.get("max_single_position_pct", 0.20),
        "max_total_exposure_pct": existing_account.get("max_total_exposure_pct", 1.0),
    }

    return {
        "account": account,
        "cash_available": round(cash_balance, 4),
        "cash_mode": cash_mode,
        "holdings": holdings,
        "watchlist": watchlist,
        "issues": issues,
        "imported_record_count": len(imported_rows),
    }
