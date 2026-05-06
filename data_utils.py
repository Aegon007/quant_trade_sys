import json
import os
from datetime import datetime
import yfinance as yf
from share_utils import MIN_SHARE_QUANTITY, normalize_share_quantity, validate_share_quantity

DATA_FILE = "portfolio_data.json"
EDITABLE_DATA_FILE = "portfolio_input.json"
CACHE_FILE = "price_cache.json"

DEFAULT_DATA = {
    "holdings": [],
    "watchlist": [],
    "last_updated": None
}

def _default_data():
    return {
        "holdings": [],
        "watchlist": [],
        "last_updated": None
    }

def _read_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _load_runtime_data():
    if os.path.exists(DATA_FILE):
        data = _read_json_file(DATA_FILE)
    else:
        data = _default_data()
    data.setdefault("holdings", [])
    data.setdefault("watchlist", [])
    data.setdefault("last_updated", None)
    return data

def editable_data_file_exists():
    return os.path.exists(EDITABLE_DATA_FILE)

def has_newer_editable_data():
    if not editable_data_file_exists():
        return False
    if not os.path.exists(DATA_FILE):
        return True
    return os.path.getmtime(EDITABLE_DATA_FILE) > os.path.getmtime(DATA_FILE)

def _coerce_optional_float(value, field_name):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number or null") from exc

def _coerce_required_float(value, field_name):
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc

def _normalize_symbol(raw_symbol, collection_name, index):
    if not isinstance(raw_symbol, str) or not raw_symbol.strip():
        raise ValueError(f"{collection_name}[{index}].symbol is required")
    return raw_symbol.strip().upper()

def _index_by_symbol(records):
    indexed = {}
    for record in records:
        symbol = str(record.get("symbol", "")).strip().upper()
        if symbol:
            indexed[symbol] = record
    return indexed

def _normalize_editable_holding(record, index, existing_by_symbol):
    if not isinstance(record, dict):
        raise ValueError(f"holdings[{index}] must be an object")
    symbol = _normalize_symbol(record.get("symbol"), "holdings", index)
    existing = existing_by_symbol.get(symbol, {})
    current_price = record.get("current_price", existing.get("current_price"))
    return {
        "symbol": symbol,
        "shares": validate_share_quantity(record.get("shares"), field_name=f"holdings[{index}].shares"),
        "cost": _coerce_required_float(record.get("cost"), f"holdings[{index}].cost"),
        "current_price": _coerce_optional_float(current_price, f"holdings[{index}].current_price"),
        "sector": str(record.get("sector", existing.get("sector", ""))).strip()
    }

def _normalize_editable_watch(record, index, existing_by_symbol):
    if not isinstance(record, dict):
        raise ValueError(f"watchlist[{index}] must be an object")
    symbol = _normalize_symbol(record.get("symbol"), "watchlist", index)
    existing = existing_by_symbol.get(symbol, {})
    last_price = record.get("last_price", existing.get("last_price"))
    return {
        "symbol": symbol,
        "notes": str(record.get("notes", "")),
        "target_buy": _coerce_optional_float(record.get("target_buy"), f"watchlist[{index}].target_buy"),
        "last_price": _coerce_optional_float(last_price, f"watchlist[{index}].last_price")
    }

def normalize_editable_data(editable_data, existing_data=None):
    if not isinstance(editable_data, dict):
        raise ValueError("editable portfolio data must be a JSON object")

    existing_data = existing_data or _default_data()
    holdings = editable_data.get("holdings", existing_data.get("holdings", []))
    watchlist = editable_data.get("watchlist", existing_data.get("watchlist", []))
    if not isinstance(holdings, list):
        raise ValueError("holdings must be a list")
    if not isinstance(watchlist, list):
        raise ValueError("watchlist must be a list")

    existing_holdings = _index_by_symbol(existing_data.get("holdings", []))
    existing_watchlist = _index_by_symbol(existing_data.get("watchlist", []))
    return {
        "holdings": [
            _normalize_editable_holding(record, index, existing_holdings)
            for index, record in enumerate(holdings)
        ],
        "watchlist": [
            _normalize_editable_watch(record, index, existing_watchlist)
            for index, record in enumerate(watchlist)
        ],
        "last_updated": existing_data.get("last_updated")
    }

def load_data(force_editable_sync=False):
    data = _load_runtime_data()
    if force_editable_sync or has_newer_editable_data():
        if editable_data_file_exists():
            data = normalize_editable_data(_read_json_file(EDITABLE_DATA_FILE), data)
            save_data(data)
    return data

def save_data(data):
    data["last_updated"] = datetime.now().isoformat()
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def _save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

def fetch_prices(symbols, use_cache=True, cache_ttl=60):
    """批量获取价格，支持缓存（默认 60 秒 TTL）"""
    prices = {}
    if use_cache:
        cache = _load_cache()
    else:
        cache = {}
    
    now = datetime.now().timestamp()
    symbols_to_fetch = []
    
    for sym in symbols:
        if sym in cache:
            cached_time = cache[sym].get("timestamp", 0)
            if now - cached_time < cache_ttl:
                prices[sym] = cache[sym]["price"]
                continue
        symbols_to_fetch.append(sym)
    
    if symbols_to_fetch:
        try:
            tickers = yf.Tickers(" ".join(symbols_to_fetch))
            for sym in symbols_to_fetch:
                try:
                    ticker = tickers.tickers.get(sym)
                    if ticker:
                        current_price = ticker.fast_info.last_price
                        if current_price is not None:
                            prices[sym] = current_price
                            cache[sym] = {"price": current_price, "timestamp": now}
                except Exception:
                    continue
        except Exception:
            for sym in symbols_to_fetch:
                try:
                    ticker = yf.Ticker(sym)
                    current_price = ticker.fast_info.last_price
                    if current_price is not None:
                        prices[sym] = current_price
                        cache[sym] = {"price": current_price, "timestamp": now}
                except Exception:
                    continue
    
    if use_cache:
        _save_cache(cache)
    return prices

def update_all_prices(data):
    symbols_to_fetch = set()
    for h in data["holdings"]:
        symbols_to_fetch.add(h["symbol"])
    for w in data["watchlist"]:
        symbols_to_fetch.add(w["symbol"])
    if not symbols_to_fetch:
        return data
    prices = fetch_prices(list(symbols_to_fetch))
    for h in data["holdings"]:
        if h["symbol"] in prices:
            h["current_price"] = prices[h["symbol"]]
    for w in data["watchlist"]:
        if w["symbol"] in prices:
            w["last_price"] = prices[w["symbol"]]
    return data

def add_holding(symbol, shares, cost, sector=""):
    normalized_shares = validate_share_quantity(shares, field_name="shares")
    data = load_data()
    data["holdings"].append({
        "symbol": symbol.upper(),
        "shares": normalized_shares,
        "cost": cost,
        "current_price": None,
        "sector": sector.strip() if isinstance(sector, str) else ""
    })
    save_data(data)

def update_holding_price(index, price):
    data = load_data()
    data["holdings"][index]["current_price"] = price
    save_data(data)

def delete_holding(index):
    data = load_data()
    data["holdings"].pop(index)
    save_data(data)

def clear_holdings():
    data = load_data()
    data["holdings"] = []
    save_data(data)

def sell_partial_holding(index, sell_shares, sell_price):
    data = load_data()
    holding = data["holdings"][index]

    current_shares = normalize_share_quantity(holding["shares"])
    shares_to_sell = validate_share_quantity(sell_shares, field_name="sell_shares")

    if shares_to_sell > current_shares:
        raise ValueError("sell_shares cannot exceed current holding shares")

    remaining_shares = normalize_share_quantity(current_shares - shares_to_sell)

    if remaining_shares < float(MIN_SHARE_QUANTITY):
        data["holdings"].pop(index)
    else:
        holding["shares"] = remaining_shares
    save_data(data)
    return holding["symbol"], holding["cost"]

def add_watch(symbol, notes="", target_buy=None):
    data = load_data()
    data["watchlist"].append({
        "symbol": symbol.upper(),
        "notes": notes,
        "target_buy": target_buy,
        "last_price": None
    })
    save_data(data)

def delete_watch(index):
    data = load_data()
    data["watchlist"].pop(index)
    save_data(data)

def clear_watchlist():
    data = load_data()
    data["watchlist"] = []
    save_data(data)

def delete_watch_batch(indices):
    data = load_data()
    for i in sorted(indices, reverse=True):
        data["watchlist"].pop(i)
    save_data(data)
