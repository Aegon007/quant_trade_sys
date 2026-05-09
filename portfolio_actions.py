import data_utils as du
import transactions as tx
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
    if price is not None:
        return float(price)
    for field in ("current_price", "last_price", "target_buy", "cost"):
        value = holding_or_watch.get(field)
        if value is not None:
            return float(value)
    raise ValueError("price is required when no existing market price is available")


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
                "target_buy": float(execution_price),
                "last_price": float(execution_price),
            }
        )
    else:
        watch_record = data["watchlist"][watch_index]
        watch_record["last_price"] = float(execution_price)
        if watch_record.get("target_buy") is None:
            watch_record["target_buy"] = float(execution_price)

    du.invalidate_market_data_timestamp(data)
    du.save_data(data)
    return {"action": "SELL_ALL", "symbol": symbol, "shares": shares_to_sell, "price": float(execution_price)}


def refresh_all_market_data():
    data = du.load_data()
    refreshed = du.refresh_market_data(data)
    du.save_data(refreshed)
    return refreshed
