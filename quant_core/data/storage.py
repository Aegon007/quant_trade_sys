import json
import os
import time
from datetime import datetime

import pandas as pd
import yfinance as yf
from share_utils import MIN_SHARE_QUANTITY, normalize_share_quantity, validate_share_quantity
from quant_core import paths as qpaths
from quant_core.data import market_data as md

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
DEFAULT_PRICE_CACHE_TTL_SECONDS = 3600
DEFAULT_PRICE_SOURCE_ORDER = ("stooq", "yfinance")
CUSTOM_PRICE_PROVIDERS = {}

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


def build_editable_portfolio_payload(data=None):
    runtime_data = data or _load_runtime_data()
    runtime_data["account"] = _normalize_account(runtime_data.get("account"), _default_account())
    runtime_data["watchlist"] = _sanitize_watchlist_records(runtime_data.get("watchlist") or [])
    holdings = []
    for record in list(runtime_data.get("holdings", []) or []):
        holdings.append(
            {
                "symbol": str(record.get("symbol", "")).strip().upper(),
                "shares": normalize_share_quantity(record.get("shares", 0.0)),
                "cost": float(record.get("cost", 0.0)),
                "sector": str(record.get("sector", "") or "").strip(),
            }
        )
    watchlist = []
    for record in list(runtime_data.get("watchlist", []) or []):
        watchlist.append(
            {
                "symbol": str(record.get("symbol", "")).strip().upper(),
                "notes": str(record.get("notes", "") or ""),
            }
        )
    account = dict(runtime_data.get("account") or {})
    return {
        "account": {
            "cash_available": account.get("cash_available"),
            "min_cash_buffer_pct": account.get("min_cash_buffer_pct", 0.05),
            "max_single_position_pct": account.get("max_single_position_pct", 0.20),
            "max_total_exposure_pct": account.get("max_total_exposure_pct", 1.0),
        },
        "holdings": holdings,
        "watchlist": watchlist,
    }


def load_editable_data():
    runtime_data = _load_runtime_data()
    if editable_data_file_exists():
        try:
            editable_payload = _read_json_file(EDITABLE_DATA_FILE)
            normalized = normalize_editable_data(editable_payload, runtime_data)
            return build_editable_portfolio_payload(normalized)
        except Exception:
            return build_editable_portfolio_payload(runtime_data)
    return build_editable_portfolio_payload(runtime_data)


def save_editable_data(editable_data, *, sync_runtime=True):
    runtime_data = _load_runtime_data()
    normalized = normalize_editable_data(editable_data, runtime_data)
    editable_payload = build_editable_portfolio_payload(normalized)
    with open(EDITABLE_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(editable_payload, f, indent=2, ensure_ascii=False)
    if sync_runtime:
        invalidate_market_data_timestamp(normalized)
        save_data(normalized)
    return editable_payload

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

def refresh_market_data(data, now=None, force_source_refresh=False):
    if not _tracked_symbols(data):
        return data
    updated = update_all_prices(data, force_source_refresh=force_source_refresh)
    return mark_prices_updated(updated, now=now)

def auto_refresh_market_data(data, refresh_interval_seconds=DEFAULT_AUTO_REFRESH_SECONDS, now=None, force=False, force_source_refresh=False):
    if not should_auto_refresh_market_data(data, refresh_interval_seconds, now=now, force=force):
        return data, False
    return refresh_market_data(data, now=now, force_source_refresh=force_source_refresh), True

def _cache_parquet_file(cache_file=None):
    cache_file = str(cache_file or CACHE_FILE)
    root, _ = os.path.splitext(cache_file)
    return f"{root}.parquet"


def _normalize_symbols(symbols):
    normalized = []
    seen = set()
    for symbol in symbols or []:
        text = str(symbol or "").strip().upper()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _coerce_price(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cache_dict_to_frame(cache_dict):
    rows = []
    for symbol, payload in (cache_dict or {}).items():
        price = _coerce_price((payload or {}).get("price"))
        timestamp = _coerce_price((payload or {}).get("timestamp"))
        source = str((payload or {}).get("source") or "")
        if price is None or timestamp is None:
            continue
        rows.append({"symbol": str(symbol).strip().upper(), "price": price, "timestamp": timestamp, "source": source})
    if not rows:
        return pd.DataFrame(columns=["symbol", "price", "timestamp", "source"])
    return pd.DataFrame(rows)


def _cache_frame_to_dict(frame):
    cache_dict = {}
    if frame is None or frame.empty:
        return cache_dict
    for row in frame.itertuples(index=False):
        symbol = str(getattr(row, "symbol", "")).strip().upper()
        price = _coerce_price(getattr(row, "price", None))
        timestamp = _coerce_price(getattr(row, "timestamp", None))
        if not symbol or price is None or timestamp is None:
            continue
        source = str(getattr(row, "source", "") or "")
        cache_dict[symbol] = {
            "price": price,
            "timestamp": timestamp,
            "source": source,
        }
    return cache_dict


def _load_cache():
    parquet_path = _cache_parquet_file()
    if os.path.exists(parquet_path):
        try:
            cache_frame = pd.read_parquet(parquet_path)
            expected_cols = {"symbol", "price", "timestamp"}
            if expected_cols.issubset(set(cache_frame.columns)):
                cache_frame = cache_frame.copy()
                if "source" not in cache_frame.columns:
                    cache_frame["source"] = ""
                cache_frame["symbol"] = cache_frame["symbol"].astype(str).str.upper().str.strip()
                cache_frame = cache_frame.dropna(subset=["symbol", "price", "timestamp"])
                cache_frame = cache_frame.drop_duplicates(subset=["symbol"], keep="last")
                return cache_frame[["symbol", "price", "timestamp", "source"]]
        except Exception:
            pass

    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return pd.DataFrame(columns=["symbol", "price", "timestamp", "source"])
        if isinstance(payload, dict):
            return _cache_dict_to_frame(payload)
    return pd.DataFrame(columns=["symbol", "price", "timestamp", "source"])


def _save_cache(cache_frame):
    cache_frame = cache_frame if cache_frame is not None else pd.DataFrame(columns=["symbol", "price", "timestamp", "source"])
    cache_dict = _cache_frame_to_dict(cache_frame)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache_dict, f, indent=2, ensure_ascii=False)

    if cache_frame.empty:
        return
    parquet_path = _cache_parquet_file()
    try:
        cache_frame.to_parquet(parquet_path, index=False)
    except Exception:
        # Keep JSON cache as compatibility fallback when parquet engine is unavailable.
        return


def _fetch_prices_from_yfinance(symbols):
    prices = {}
    symbols = _normalize_symbols(symbols)
    if not symbols:
        return prices
    try:
        tickers = yf.Tickers(" ".join(symbols))
    except Exception:
        tickers = None

    for symbol in symbols:
        price = None
        if tickers is not None:
            try:
                ticker = tickers.tickers.get(symbol)
                if ticker is not None:
                    price = _coerce_price(getattr(ticker.fast_info, "last_price", None))
            except Exception:
                price = None
        if price is not None:
            prices[symbol] = price
            continue
        try:
            ticker = yf.Ticker(symbol)
            price = _coerce_price(getattr(ticker.fast_info, "last_price", None))
        except Exception:
            price = None
        if price is not None:
            prices[symbol] = price
    return prices


def _fetch_prices_from_stooq(symbols):
    return md.fetch_latest_prices_from_stooq(_normalize_symbols(symbols))


def _provider_map():
    providers = {
        "stooq": _fetch_prices_from_stooq,
        "yfinance": _fetch_prices_from_yfinance,
    }
    providers.update(dict(CUSTOM_PRICE_PROVIDERS or {}))
    return providers


def _resolve_price_provider_order():
    env_value = str(os.getenv("MARKET_DATA_PRICE_SOURCES", "")).strip()
    if env_value:
        requested = [segment.strip().lower() for segment in env_value.split(",")]
    else:
        requested = [str(name).strip().lower() for name in DEFAULT_PRICE_SOURCE_ORDER]
    providers = _provider_map()
    resolved = []
    seen = set()
    for name in requested:
        if not name or name in seen:
            continue
        fetcher = providers.get(name)
        if fetcher is None:
            continue
        resolved.append((name, fetcher))
        seen.add(name)
    return resolved


def _fetch_prices_from_provider(provider, symbols):
    provider_name, fetcher = provider
    payload = fetcher(_normalize_symbols(symbols))
    normalized = {}
    for symbol, value in (payload or {}).items():
        symbol_text = str(symbol or "").strip().upper()
        price = _coerce_price(value)
        if not symbol_text or price is None:
            continue
        normalized[symbol_text] = price
    return normalized


def _format_provider_errors(provider_errors):
    if not provider_errors:
        return None
    return "; ".join(f"{name}: {error}" for name, error in provider_errors.items())


def fetch_prices(symbols, use_cache=True, cache_ttl=DEFAULT_PRICE_CACHE_TTL_SECONDS, write_cache=True):
    """批量获取价格：本地缓存优先，缓存失效后按数据源顺序自动降级。"""
    normalized_symbols = _normalize_symbols(symbols)
    if not normalized_symbols:
        return {}

    prices = {}
    now_ts = float(time.time())
    cache_frame = _load_cache() if (use_cache or write_cache) else pd.DataFrame(columns=["symbol", "price", "timestamp", "source"])
    cache_lookup = _cache_frame_to_dict(cache_frame)

    symbols_to_fetch = []
    for symbol in normalized_symbols:
        if not use_cache:
            symbols_to_fetch.append(symbol)
            continue
        cached = cache_lookup.get(symbol)
        if cached is None:
            symbols_to_fetch.append(symbol)
            continue
        cached_time = _coerce_price(cached.get("timestamp"))
        cached_price = _coerce_price(cached.get("price"))
        if cached_time is None or cached_price is None or (now_ts - cached_time) >= float(cache_ttl):
            symbols_to_fetch.append(symbol)
            continue
        prices[symbol] = cached_price

    provider_errors = {}
    if symbols_to_fetch:
        unresolved = set(symbols_to_fetch)
        provider_chain = _resolve_price_provider_order()
        md.configure_price_source_order([name for name, _fetcher in provider_chain])
        for provider in provider_chain:
            if not unresolved:
                break
            provider_name = provider[0]
            provider_symbols = sorted(unresolved)
            try:
                provider_prices = _fetch_prices_from_provider(provider, provider_symbols)
            except Exception as exc:
                provider_errors[provider_name] = exc
                continue

            resolved_symbols = []
            for symbol, price in provider_prices.items():
                if symbol not in unresolved:
                    continue
                prices[symbol] = price
                cache_lookup[symbol] = {"price": price, "timestamp": now_ts, "source": provider_name}
                unresolved.discard(symbol)
                resolved_symbols.append(symbol)

            if resolved_symbols:
                md.record_price_source(
                    resolved_symbols,
                    provider_name,
                    error=_format_provider_errors(provider_errors),
                    count=len(resolved_symbols),
                )

        if unresolved:
            md.record_price_source(
                sorted(unresolved),
                provider_chain[0][0] if provider_chain else "none",
                error=_format_provider_errors(provider_errors) or "price unavailable from configured sources",
                count=0,
            )

    if write_cache:
        cache_frame = _cache_dict_to_frame(cache_lookup)
        _save_cache(cache_frame)
    return {symbol: prices[symbol] for symbol in normalized_symbols if symbol in prices}

def update_all_prices(data, force_source_refresh=False):
    symbols_to_fetch = set()
    for h in data["holdings"]:
        symbols_to_fetch.add(h["symbol"])
    for w in data["watchlist"]:
        symbols_to_fetch.add(w["symbol"])
    if not symbols_to_fetch:
        return data
    prices = fetch_prices(
        list(symbols_to_fetch),
        use_cache=not force_source_refresh,
        write_cache=True,
    )
    for h in data["holdings"]:
        if h["symbol"] in prices:
            h["current_price"] = prices[h["symbol"]]
    for w in data["watchlist"]:
        if w["symbol"] in prices:
            w["last_price"] = prices[w["symbol"]]
    return data


def _latest_market_price(symbol, *, force_source_refresh=False):
    latest_prices = fetch_prices([symbol], use_cache=not force_source_refresh, write_cache=True)
    return latest_prices.get(symbol)


def resolve_record_price(record, symbol=None, price=None, allow_cost_fallback=True, force_source_refresh=False):
    if price is not None:
        return float(price)

    for field in ("current_price", "last_price"):
        value = record.get(field)
        if value is not None:
            return float(value)

    resolved_symbol = str(symbol or record.get("symbol") or "").strip().upper()
    if resolved_symbol:
        latest_price = _latest_market_price(
            resolved_symbol,
            force_source_refresh=force_source_refresh,
        )
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
    entry_price = resolve_record_price(
        watch,
        symbol=symbol,
        allow_cost_fallback=False,
        force_source_refresh=True,
    )
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
