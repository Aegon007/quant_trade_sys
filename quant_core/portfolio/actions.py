from quant_core.data import storage as du
from quant_core.ledger import transactions as tx
from share_utils import MIN_SHARE_QUANTITY, normalize_share_quantity, validate_share_quantity


def _normalize_symbol(symbol: str) -> str:
    text = str(symbol or "").strip().upper()
    if not text:
        raise ValueError("symbol is required")
    return text


def _find_index(records, symbol: str):
    normalized_symbol = _normalize_symbol(symbol)
    for index, record in enumerate(records):
        if str(record.get("symbol", "")).strip().upper() == normalized_symbol:
            return index
    return None


def _ensure_account(data):
    if "account" not in data or not isinstance(data.get("account"), dict):
        data["account"] = du.default_account_data()
    return data["account"]


def _adjust_cash(account, delta: float):
    if account.get("cash_available") is None:
        return
    updated_cash = round(float(account.get("cash_available", 0.0)) + float(delta), 4)
    if updated_cash < 0:
        raise ValueError("cash_available would become negative")
    account["cash_available"] = updated_cash


def _execution_price(holding_or_watch, price=None) -> float:
    return du.resolve_record_price(holding_or_watch, price=price)


def buy_symbol(symbol: str, shares: float, price=None, sector: str = ""):
    symbol = _normalize_symbol(symbol)
    shares_to_buy = validate_share_quantity(shares, field_name="shares")
    data = du.load_data()
    account = _ensure_account(data)
    watch_index = _find_index(data.get("watchlist", []), symbol)
    watch_record = data["watchlist"].pop(watch_index) if watch_index is not None else None
    entry_context = watch_record or {}
    entry_price = _execution_price(entry_context, price=price)
    total_cost = shares_to_buy * entry_price
    _adjust_cash(account, -total_cost)

    holding_index = _find_index(data.get("holdings", []), symbol)
    if holding_index is None:
        data["holdings"].append(
            {
                "symbol": symbol,
                "shares": shares_to_buy,
                "cost": float(entry_price),
                "current_price": float(entry_price),
                "sector": str(sector or "").strip(),
            }
        )
    else:
        holding = data["holdings"][holding_index]
        current_shares = normalize_share_quantity(holding.get("shares", 0.0))
        current_cost = float(holding.get("cost", 0.0))
        total_shares = normalize_share_quantity(current_shares + shares_to_buy)
        total_cost_amount = current_shares * current_cost + shares_to_buy * float(entry_price)
        holding["shares"] = total_shares
        holding["cost"] = total_cost_amount / total_shares if total_shares > 0 else float(entry_price)
        holding["current_price"] = float(entry_price)
        if sector:
            holding["sector"] = str(sector).strip()

    du.invalidate_market_data_timestamp(data)
    du.save_data(data)
    tx.add_buy_transaction(symbol, float(entry_price), shares_to_buy)
    return {"action": "BUY", "symbol": symbol, "shares": shares_to_buy, "price": float(entry_price)}


def sell_symbol(symbol: str, shares: float, price=None):
    symbol = _normalize_symbol(symbol)
    shares_to_sell = validate_share_quantity(shares, field_name="shares")
    data = du.load_data()
    account = _ensure_account(data)
    holding_index = _find_index(data.get("holdings", []), symbol)
    if holding_index is None:
        raise ValueError(f"holding {symbol} not found")

    holding = data["holdings"][holding_index]
    current_shares = normalize_share_quantity(holding.get("shares", 0.0))
    if shares_to_sell > current_shares:
        raise ValueError("sell shares cannot exceed current holding shares")

    execution_price = _execution_price(holding, price=price)
    remaining_shares = normalize_share_quantity(current_shares - shares_to_sell)
    if remaining_shares < float(MIN_SHARE_QUANTITY):
        data["holdings"].pop(holding_index)
    else:
        holding["shares"] = remaining_shares
        holding["current_price"] = float(execution_price)

    _adjust_cash(account, shares_to_sell * execution_price)
    du.invalidate_market_data_timestamp(data)
    du.save_data(data)
    tx.add_transaction(symbol, float(execution_price), shares_to_sell, float(holding.get("cost", 0.0)))
    return {"action": "SELL", "symbol": symbol, "shares": shares_to_sell, "price": float(execution_price)}


def sell_all_symbol(symbol: str, price=None, notes: str = ""):
    symbol = _normalize_symbol(symbol)
    data = du.load_data()
    account = _ensure_account(data)
    holding_index = _find_index(data.get("holdings", []), symbol)
    if holding_index is None:
        raise ValueError(f"holding {symbol} not found")

    holding = data["holdings"].pop(holding_index)
    execution_price = _execution_price(holding, price=price)
    shares_to_sell = normalize_share_quantity(holding.get("shares", 0.0))
    _adjust_cash(account, shares_to_sell * execution_price)
    tx.add_transaction(symbol, float(execution_price), shares_to_sell, float(holding.get("cost", 0.0)))

    watch_index = _find_index(data.get("watchlist", []), symbol)
    if watch_index is None:
        data["watchlist"].append(
            {
                "symbol": symbol,
                "notes": str(notes or ""),
                "last_price": float(execution_price),
            }
        )
    else:
        watch_record = data["watchlist"][watch_index]
        watch_record["last_price"] = float(execution_price)

    du.invalidate_market_data_timestamp(data)
    du.save_data(data)
    return {"action": "SELL_ALL", "symbol": symbol, "shares": shares_to_sell, "price": float(execution_price)}


def move_holding_to_watch(symbol: str, notes: str = ""):
    symbol = _normalize_symbol(symbol)
    action = sell_all_symbol(symbol, notes=notes)
    tx.add_portfolio_event(
        "MOVE_TO_WATCH",
        symbol=symbol,
        shares=action["shares"],
        price=action["price"],
        side="SELL",
        notes=notes,
    )
    return {
        "action": "MOVE_TO_WATCH",
        "symbol": action["symbol"],
        "shares": action["shares"],
        "price": action["price"],
    }


def move_watch_to_holding(symbol: str, shares: float = 1.0):
    symbol = _normalize_symbol(symbol)
    notes = ""
    data = du.load_data()
    watch_index = _find_index(data.get("watchlist", []), symbol)
    if watch_index is not None:
        notes = str(data["watchlist"][watch_index].get("notes", "") or "")
    action = buy_symbol(symbol, shares)
    tx.add_portfolio_event(
        "MOVE_TO_HOLDING",
        symbol=symbol,
        shares=action["shares"],
        price=action["price"],
        side="BUY",
        notes=notes,
    )
    return {
        "action": "MOVE_TO_HOLDING",
        "symbol": action["symbol"],
        "shares": action["shares"],
        "price": action["price"],
    }


def add_watch_symbol(symbol: str, notes: str = ""):
    symbol = _normalize_symbol(symbol)
    data = du.load_data()
    if _find_index(data.get("holdings", []), symbol) is not None:
        raise ValueError(f"{symbol} already exists in holdings")
    if _find_index(data.get("watchlist", []), symbol) is not None:
        raise ValueError(f"{symbol} already exists in watchlist")

    data["watchlist"].append(
        {
            "symbol": symbol,
            "notes": str(notes or ""),
            "last_price": None,
        }
    )
    du.invalidate_market_data_timestamp(data)
    du.save_data(data)
    return {"action": "ADD_WATCH", "symbol": symbol, "notes": str(notes or "")}


def remove_watch_symbol(symbol: str):
    symbol = _normalize_symbol(symbol)
    data = du.load_data()
    watch_index = _find_index(data.get("watchlist", []), symbol)
    if watch_index is None:
        raise ValueError(f"watchlist {symbol} not found")

    removed = data["watchlist"].pop(watch_index)
    du.invalidate_market_data_timestamp(data)
    du.save_data(data)
    return {
        "action": "REMOVE_WATCH",
        "symbol": symbol,
        "notes": str(removed.get("notes", "") or ""),
        "price": removed.get("last_price"),
    }


def update_holding_record(
    symbol: str,
    *,
    shares=None,
    cost=None,
    sector=None,
    current_price=None,
):
    """Administrative holding update through actions layer (no cash adjustment)."""
    symbol = _normalize_symbol(symbol)
    data = du.load_data()
    holding_index = _find_index(data.get("holdings", []), symbol)
    if holding_index is None:
        raise ValueError(f"holding {symbol} not found")

    holding = data["holdings"][holding_index]
    if shares is not None:
        holding["shares"] = validate_share_quantity(shares, field_name="shares")
    if cost is not None:
        holding["cost"] = float(cost)
    if sector is not None:
        holding["sector"] = str(sector).strip()
    if current_price is not None:
        holding["current_price"] = float(current_price)

    du.invalidate_market_data_timestamp(data)
    du.save_data(data)
    tx.add_portfolio_event(
        "UPDATE_HOLDING",
        symbol=symbol,
        shares=float(holding.get("shares", 0.0)),
        price=holding.get("current_price"),
        side="",
        notes="manual update",
    )
    return {
        "action": "UPDATE_HOLDING",
        "symbol": symbol,
        "shares": float(holding.get("shares", 0.0)),
        "price": holding.get("current_price"),
    }


def remove_holding_record(symbol: str, *, notes: str = "manual remove"):
    """Administrative holding removal through actions layer (no cash adjustment)."""
    symbol = _normalize_symbol(symbol)
    data = du.load_data()
    holding_index = _find_index(data.get("holdings", []), symbol)
    if holding_index is None:
        raise ValueError(f"holding {symbol} not found")
    holding = data["holdings"].pop(holding_index)
    du.invalidate_market_data_timestamp(data)
    du.save_data(data)
    tx.add_portfolio_event(
        "REMOVE_HOLDING",
        symbol=symbol,
        shares=float(holding.get("shares", 0.0)),
        price=holding.get("current_price"),
        side="",
        notes=notes,
    )
    return {
        "action": "REMOVE_HOLDING",
        "symbol": symbol,
        "shares": float(holding.get("shares", 0.0)),
        "price": holding.get("current_price"),
    }


def clear_all_holdings(*, notes: str = "manual clear"):
    """Administrative holding clear through actions layer (no cash adjustment)."""
    data = du.load_data()
    holdings = list(data.get("holdings", []))
    if not holdings:
        return {"action": "CLEAR_HOLDINGS", "count": 0}

    data["holdings"] = []
    du.invalidate_market_data_timestamp(data)
    du.save_data(data)
    for holding in holdings:
        symbol = str(holding.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        tx.add_portfolio_event(
            "REMOVE_HOLDING",
            symbol=symbol,
            shares=float(holding.get("shares", 0.0)),
            price=holding.get("current_price"),
            side="",
            notes=notes,
        )
    return {"action": "CLEAR_HOLDINGS", "count": len(holdings)}


def refresh_all_market_data():
    data = du.load_data()
    refreshed = du.refresh_market_data(data)
    du.save_data(refreshed)
    return refreshed
