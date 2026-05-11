import json
import os
from datetime import datetime
import yfinance as yf
from share_utils import MIN_SHARE_QUANTITY, normalize_share_quantity, validate_share_quantity
from quant_core import paths as qpaths

qpaths.bootstrap_storage_paths()

DATA_FILE = qpaths.PORTFOLIO_DATA_FILE
EDITABLE_DATA_FILE = qpaths.PORTFOLIO_INPUT_FILE
CACHE_FILE = qpaths.PRICE_CACHE_FILE

DEFAULT_ACCOUNT = {
    "total_capital": None,
    "cash_available": None,
    "min_cash_buffer_pct": 0.05,
    "max_single_position_pct": 0.20,
    "max_total_exposure_pct": 1.0,
}

DEFAULT_DATA = {
    "account": DEFAULT_ACCOUNT,
    "holdings": [],
    "watchlist": [],
    "last_updated": None,
    "prices_last_updated": None
}
DEFAULT_AUTO_REFRESH_SECONDS = 300

def _default_account():
    return {
        "total_capital": None,
        "cash_available": None,
        "min_cash_buffer_pct": 0.05,
        "max_single_position_pct": 0.20,
        "max_total_exposure_pct": 1.0,
    }

def _default_data():
    return {
        "account": _default_account(),
        "holdings": [],
        "watchlist": [],
        "last_updated": None,
        "prices_last_updated": None
    }

def default_account_data():
    return _default_account()

def _read_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _load_runtime_data():
    if os.path.exists(DATA_FILE):
        data = _read_json_file(DATA_FILE)
    else:
        data = _default_data()
    data["account"] = _normalize_account(data.get("account"), _default_account())
    data.setdefault("holdings", [])
    data.setdefault("watchlist", [])
    data.setdefault("last_updated", None)
    data.setdefault("prices_last_updated", None)
    data["watchlist"] = _sanitize_watchlist_records(data.get("watchlist") or [])
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

def _coerce_optional_non_negative_float(value, field_name):
    if value in (None, ""):
        return None
    coerced = _coerce_required_float(value, field_name)
    if coerced < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return coerced

def _coerce_pct(value, field_name, default):
    if value in (None, ""):
        return float(default)
    coerced = _coerce_required_float(value, field_name)
    if not 0 <= coerced <= 1:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return coerced

def _normalize_symbol(raw_symbol, collection_name, index):
    if not isinstance(raw_symbol, str) or not raw_symbol.strip():
        raise ValueError(f"{collection_name}[{index}].symbol is required")
    return raw_symbol.strip().upper()

def _normalize_account(account, existing_account=None):
    existing_account = existing_account or _default_account()
    if account is None:
        account = {}
    if not isinstance(account, dict):
        raise ValueError("account must be an object")
    return {
        "total_capital": _coerce_optional_non_negative_float(
            account.get("total_capital", existing_account.get("total_capital")),
            "account.total_capital",
        ),
        "cash_available": _coerce_optional_non_negative_float(
            account.get("cash_available", existing_account.get("cash_available")),
            "account.cash_available",
        ),
        "min_cash_buffer_pct": _coerce_pct(
            account.get("min_cash_buffer_pct", existing_account.get("min_cash_buffer_pct", 0.05)),
            "account.min_cash_buffer_pct",
            0.05,
        ),
        "max_single_position_pct": _coerce_pct(
            account.get("max_single_position_pct", existing_account.get("max_single_position_pct", 0.20)),
            "account.max_single_position_pct",
            0.20,
        ),
        "max_total_exposure_pct": _coerce_pct(
            account.get("max_total_exposure_pct", existing_account.get("max_total_exposure_pct", 1.0)),
            "account.max_total_exposure_pct",
            1.0,
        ),
    }

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

def _normalize_watch_record(record, index, existing_by_symbol=None):
    if not isinstance(record, dict):
        raise ValueError(f"watchlist[{index}] must be an object")
    symbol = _normalize_symbol(record.get("symbol"), "watchlist", index)
    existing_by_symbol = existing_by_symbol or {}
    existing = existing_by_symbol.get(symbol, {})
    last_price = record.get("last_price", existing.get("last_price"))
    notes = record.get("notes", existing.get("notes", ""))
    if notes is None:
        notes = ""
    return {
        "symbol": symbol,
        "notes": str(notes),
        "last_price": _coerce_optional_float(last_price, f"watchlist[{index}].last_price")
    }


def _sanitize_watchlist_records(records, existing_by_symbol=None):
    return [
        _normalize_watch_record(record, index, existing_by_symbol)
        for index, record in enumerate(records)
    ]

def normalize_editable_data(editable_data, existing_data=None):
    if not isinstance(editable_data, dict):
        raise ValueError("editable portfolio data must be a JSON object")

    existing_data = existing_data or _default_data()
    account = editable_data.get("account", existing_data.get("account", _default_account()))
    holdings = editable_data.get("holdings", existing_data.get("holdings", []))
    watchlist = editable_data.get("watchlist", existing_data.get("watchlist", []))
    if not isinstance(holdings, list):
        raise ValueError("holdings must be a list")
    if not isinstance(watchlist, list):
        raise ValueError("watchlist must be a list")

    existing_holdings = _index_by_symbol(existing_data.get("holdings", []))
    existing_watchlist = _index_by_symbol(existing_data.get("watchlist", []))
    return {
        "account": _normalize_account(account, existing_data.get("account")),
        "holdings": [
            _normalize_editable_holding(record, index, existing_holdings)
            for index, record in enumerate(holdings)
        ],
        "watchlist": _sanitize_watchlist_records(watchlist, existing_watchlist),
        "last_updated": existing_data.get("last_updated"),
        "prices_last_updated": existing_data.get("prices_last_updated")
    }

def load_data(force_editable_sync=False):
    data = _load_runtime_data()
    if force_editable_sync or has_newer_editable_data():
        if editable_data_file_exists():
            data = normalize_editable_data(_read_json_file(EDITABLE_DATA_FILE), data)
            invalidate_market_data_timestamp(data)
            save_data(data)
    return data

def save_data(data):
    data["account"] = _normalize_account(data.get("account"), _default_account())
    data["watchlist"] = _sanitize_watchlist_records(data.get("watchlist") or [])
    data["last_updated"] = datetime.now().isoformat()
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _tracked_symbols(data):
    symbols = set()
    for holding in data.get("holdings", []):
        symbol = holding.get("symbol")
        if symbol:
            symbols.add(str(symbol).strip().upper())
    for watch in data.get("watchlist", []):
        symbol = watch.get("symbol")
        if symbol:
            symbols.add(str(symbol).strip().upper())
    return sorted(symbols)

def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None

def market_data_age_seconds(data, now=None):
    now = now or datetime.now()
    last_refresh = _parse_iso_datetime(data.get("prices_last_updated"))
    if last_refresh is None:
        return None
    return max(0.0, (now - last_refresh).total_seconds())

def should_auto_refresh_market_data(data, refresh_interval_seconds=DEFAULT_AUTO_REFRESH_SECONDS, now=None, force=False):
    if not _tracked_symbols(data):
        return False
    if force:
        return True
    age_seconds = market_data_age_seconds(data, now=now)
    if age_seconds is None:
        return True
    return age_seconds >= refresh_interval_seconds

def mark_prices_updated(data, now=None):
    now = now or datetime.now()
    data["prices_last_updated"] = now.isoformat()
    return data

def invalidate_market_data_timestamp(data):
    data["prices_last_updated"] = None
    return data

def refresh_market_data(data, now=None):
    if not _tracked_symbols(data):
        return data
    updated = update_all_prices(data)
    return mark_prices_updated(updated, now=now)

def auto_refresh_market_data(data, refresh_interval_seconds=DEFAULT_AUTO_REFRESH_SECONDS, now=None, force=False):
    if not should_auto_refresh_market_data(data, refresh_interval_seconds, now=now, force=force):
        return data, False
    return refresh_market_data(data, now=now), True

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


def _latest_market_price(symbol):
    latest_prices = fetch_prices([symbol])
    return latest_prices.get(symbol)


def resolve_record_price(record, symbol=None, price=None, allow_cost_fallback=True):
    if price is not None:
        return float(price)

    for field in ("current_price", "last_price"):
        value = record.get(field)
        if value is not None:
            return float(value)

    resolved_symbol = str(symbol or record.get("symbol") or "").strip().upper()
    if resolved_symbol:
        latest_price = _latest_market_price(resolved_symbol)
        if latest_price is not None:
            return float(latest_price)

    if allow_cost_fallback:
        cost = record.get("cost")
        if cost is not None:
            return float(cost)

    raise ValueError(
        f"Unable to resolve price for {resolved_symbol or 'record'}; refresh market data first."
    )

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
    invalidate_market_data_timestamp(data)
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

def add_watch(symbol, notes=""):
    data = load_data()
    data["watchlist"].append({
        "symbol": symbol.upper(),
        "notes": notes,
        "last_price": None
    })
    invalidate_market_data_timestamp(data)
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


def _find_record_index_by_symbol(records, symbol):
    normalized_symbol = str(symbol).strip().upper()
    for idx, record in enumerate(records):
        if str(record.get("symbol", "")).strip().upper() == normalized_symbol:
            return idx
    return None


def move_holding_to_watchlist(index, notes=""):
    data = load_data()
    holding = data["holdings"].pop(index)

    symbol = str(holding.get("symbol", "")).strip().upper()
    latest_price = holding.get("current_price")
    if latest_price is None:
        latest_price = _latest_market_price(symbol)

    existing_watch_idx = _find_record_index_by_symbol(data["watchlist"], symbol)
    if existing_watch_idx is None:
        data["watchlist"].append({
            "symbol": symbol,
            "notes": str(notes or ""),
            "last_price": latest_price,
        })
    else:
        existing_watch = data["watchlist"][existing_watch_idx]
        if latest_price is not None:
            existing_watch["last_price"] = latest_price
        if notes:
            existing_watch["notes"] = str(notes)

    invalidate_market_data_timestamp(data)
    save_data(data)
    return symbol


def move_watch_to_holding(index, shares=1.0):
    shares_to_buy = validate_share_quantity(shares, field_name="shares")
    data = load_data()
    watch = data["watchlist"].pop(index)

    symbol = str(watch.get("symbol", "")).strip().upper()
    entry_price = resolve_record_price(watch, symbol=symbol, allow_cost_fallback=False)
    latest_price = watch.get("last_price")
    if latest_price is None:
        latest_price = entry_price

    existing_holding_idx = _find_record_index_by_symbol(data["holdings"], symbol)
    if existing_holding_idx is None:
        data["holdings"].append({
            "symbol": symbol,
            "shares": shares_to_buy,
            "cost": float(entry_price),
            "current_price": latest_price,
            "sector": "",
        })
    else:
        holding = data["holdings"][existing_holding_idx]
        current_shares = normalize_share_quantity(holding.get("shares", 0))
        current_cost = float(holding.get("cost", 0.0))
        total_shares = normalize_share_quantity(current_shares + shares_to_buy)
        total_cost_amount = (current_shares * current_cost) + (shares_to_buy * float(entry_price))
        holding["shares"] = total_shares
        holding["cost"] = total_cost_amount / total_shares if total_shares > 0 else float(entry_price)
        if latest_price is not None:
            holding["current_price"] = latest_price

    invalidate_market_data_timestamp(data)
    save_data(data)
    return symbol, shares_to_buy, float(entry_price)
