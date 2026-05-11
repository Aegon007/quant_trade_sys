import io
import re
import urllib.parse
import urllib.request
from copy import deepcopy
from datetime import datetime

import pandas as pd


STOOQ_DAILY_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"
_COMMON_SYMBOL_MAP = {
    "^VIX": "^vix",
}
_DEFAULT_STATUS = {
    "history": {
        "primary_requests": 0,
        "fallback_requests": 0,
        "last_source": None,
        "last_symbol": None,
        "last_error": None,
    },
    "prices": {
        "primary_symbols": 0,
        "fallback_symbols": 0,
        "last_source": None,
        "last_symbols": [],
        "last_error": None,
    },
}
_MARKET_DATA_STATUS = deepcopy(_DEFAULT_STATUS)


def reset_market_data_status():
    global _MARKET_DATA_STATUS
    _MARKET_DATA_STATUS = deepcopy(_DEFAULT_STATUS)


def get_market_data_status_snapshot():
    return deepcopy(_MARKET_DATA_STATUS)


def record_history_source(symbol: str, source: str, *, error=None):
    status = _MARKET_DATA_STATUS["history"]
    normalized_symbol = _normalize_symbol(symbol)
    if str(source).lower() == "stooq":
        status["fallback_requests"] += 1
    else:
        status["primary_requests"] += 1
    status["last_source"] = str(source).lower()
    status["last_symbol"] = normalized_symbol
    status["last_error"] = None if error in (None, "") else str(error)


def record_price_source(symbols, source: str, *, error=None, count=None):
    status = _MARKET_DATA_STATUS["prices"]
    normalized_symbols = [_normalize_symbol(symbol) for symbol in (symbols or []) if str(symbol or "").strip()]
    resolved_count = int(count if count is not None else len(normalized_symbols))
    if str(source).lower() == "stooq":
        status["fallback_symbols"] += resolved_count
    else:
        status["primary_symbols"] += resolved_count
    status["last_source"] = str(source).lower()
    status["last_symbols"] = normalized_symbols
    status["last_error"] = None if error in (None, "") else str(error)


def _normalize_symbol(symbol: str) -> str:
    text = str(symbol or "").strip().upper()
    if not text:
        raise ValueError("symbol is required")
    return text


def stooq_symbol(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    if normalized in _COMMON_SYMBOL_MAP:
        return _COMMON_SYMBOL_MAP[normalized]
    if normalized.startswith("^"):
        return normalized.lower()
    if normalized.lower().endswith(".us"):
        return normalized.lower()
    return f"{normalized.lower()}.us"


def _period_start(period: str, *, now=None):
    period_text = str(period or "").strip().lower()
    if not period_text or period_text == "max":
        return None

    now_ts = pd.Timestamp(now or datetime.now()).tz_localize(None)
    if period_text == "ytd":
        return pd.Timestamp(year=now_ts.year, month=1, day=1)

    match = re.match(r"^(\d+)(d|w|wk|mo|y)$", period_text)
    if not match:
        return None

    value = int(match.group(1))
    unit = match.group(2)
    if unit == "d":
        return now_ts - pd.Timedelta(days=value)
    if unit in {"w", "wk"}:
        return now_ts - pd.Timedelta(weeks=value)
    if unit == "mo":
        return now_ts - pd.DateOffset(months=value)
    if unit == "y":
        return now_ts - pd.DateOffset(years=value)
    return None


def _normalize_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()

    data = frame.copy()
    if "Date" in data.columns:
        data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
        data = data.dropna(subset=["Date"]).set_index("Date")
    else:
        data.index = pd.to_datetime(data.index, errors="coerce")
        data = data[~data.index.isna()]

    data = data.sort_index()
    renamed = {column: str(column).title() for column in data.columns}
    data = data.rename(columns=renamed)
    for column in ["Open", "High", "Low", "Close", "Volume"]:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    return data.dropna(how="all")


def _filter_history_by_period(frame: pd.DataFrame, period: str, *, now=None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    start = _period_start(period, now=now)
    if start is None:
        return frame
    filtered = frame[frame.index >= start]
    return filtered.copy()


def fetch_stooq_history(symbol: str, period: str = "6mo", *, urlopen=urllib.request.urlopen, timeout: int = 10):
    resolved_symbol = stooq_symbol(symbol)
    url = STOOQ_DAILY_URL.format(symbol=urllib.parse.quote(resolved_symbol, safe="^"))
    try:
        with urlopen(url, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except Exception:
        return pd.DataFrame()

    try:
        frame = pd.read_csv(io.StringIO(payload))
    except Exception:
        return pd.DataFrame()

    normalized = _normalize_history_frame(frame)
    if normalized.empty:
        return normalized
    return _filter_history_by_period(normalized, period)


def history_is_usable(frame: pd.DataFrame) -> bool:
    return frame is not None and not frame.empty and "Close" in frame.columns and not frame["Close"].dropna().empty


def fetch_latest_prices_from_stooq(symbols, *, history_fetcher=fetch_stooq_history, timeout: int = 4):
    prices = {}
    for symbol in symbols or []:
        try:
            history = history_fetcher(symbol, period="1mo", timeout=timeout)
        except TypeError:
            history = history_fetcher(symbol, period="1mo")
        except Exception:
            continue
        if not history_is_usable(history):
            continue
        prices[str(symbol).strip().upper()] = float(history["Close"].dropna().iloc[-1])
    return prices
