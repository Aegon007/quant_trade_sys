from __future__ import annotations

import importlib.util
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

import pandas as pd

from quant_core import paths as qpaths
from quant_core.data import market_data


CACHE_FILE = qpaths.RESEARCH_STATE_DIR / "price_cache.parquet"
HISTORY_CACHE_DIR = qpaths.RESEARCH_CACHE_DIR / "prices"
DEFAULT_SOURCE_ORDER = ("stooq", "yfinance")


def _symbols(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value or "").strip().upper() for value in values if str(value or "").strip()))


def _source_order() -> list[str]:
    configured = str(os.getenv("MARKET_DATA_PRICE_SOURCES") or "").strip()
    values = configured.split(",") if configured else DEFAULT_SOURCE_ORDER
    return [str(value).strip().lower() for value in values if str(value).strip()]


def _history_cache_path(symbol: str, period: str) -> Path:
    safe_symbol = "".join(char if char.isalnum() or char in "-_" else "_" for char in symbol.upper())
    safe_period = "".join(char for char in str(period).lower() if char.isalnum()) or "max"
    return HISTORY_CACHE_DIR / f"{safe_symbol}_{safe_period}.parquet"


def get_history(symbol: str, period: str = "2y", *, force: bool = False, ttl_seconds: int = 3600) -> pd.DataFrame:
    symbol = str(symbol or "").strip().upper()
    cache_path = _history_cache_path(symbol, period)
    if not force and cache_path.exists() and time.time() - cache_path.stat().st_mtime <= max(int(ttl_seconds), 0):
        try:
            cached = pd.read_parquet(cache_path)
            if "Date" in cached.columns:
                cached["Date"] = pd.to_datetime(cached["Date"], errors="coerce")
                cached = cached.dropna(subset=["Date"]).set_index("Date")
            if market_data.history_is_usable(cached):
                cached.attrs["source"] = "local_history_cache"
                return cached.sort_index()
        except Exception:
            pass
    errors = []
    for source in _source_order():
        try:
            if source == "stooq":
                frame = market_data.fetch_stooq_history(symbol, period=period)
            elif source == "yfinance" and importlib.util.find_spec("yfinance") is not None:
                import yfinance as yf

                frame = yf.Ticker(symbol).history(period=period, auto_adjust=False)
            else:
                continue
        except Exception as exc:
            errors.append(f"{source}: {exc}")
            continue
        if market_data.history_is_usable(frame):
            market_data.record_history_source(symbol, source, error="; ".join(errors) or None)
            frame = frame.sort_index()
            frame.attrs["source"] = source
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = cache_path.with_suffix(".tmp.parquet")
                frame.rename_axis("Date").reset_index().to_parquet(temporary, index=False)
                temporary.replace(cache_path)
            except Exception:
                pass
            return frame
    market_data.record_history_source(symbol, _source_order()[0] if _source_order() else "none", error="; ".join(errors) or "history unavailable")
    return pd.DataFrame()


def _read_cache(path: Path = CACHE_FILE) -> pd.DataFrame:
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame(columns=["symbol", "price", "timestamp", "source"])
    required = {"symbol", "price", "timestamp", "source"}
    return frame if required.issubset(frame.columns) else pd.DataFrame(columns=sorted(required))


def _write_cache(frame: pd.DataFrame, path: Path = CACHE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.drop_duplicates("symbol", keep="last").sort_values("symbol").to_parquet(path, index=False)


def fetch_latest_prices(symbols: Iterable[str], *, force: bool = False, ttl_seconds: int = 3600, workers: int = 8) -> dict[str, float]:
    wanted = _symbols(symbols)
    cache = _read_cache()
    now = time.time()
    result = {}
    cached_by_symbol = {str(row.symbol).upper(): row for row in cache.itertuples(index=False)}
    missing = []
    for symbol in wanted:
        row = cached_by_symbol.get(symbol)
        if not force and row is not None and now - float(row.timestamp) < ttl_seconds:
            price = float(row.price)
            if math.isfinite(price) and price > 0:
                result[symbol] = price
                continue
        missing.append(symbol)
    new_rows = []

    def resolve(symbol):
        history = get_history(symbol, period="1mo", force=force, ttl_seconds=ttl_seconds)
        if history.empty:
            return symbol, None, None
        values = pd.to_numeric(history["Close"], errors="coerce").dropna()
        return symbol, (float(values.iloc[-1]) if len(values) else None), history.attrs.get("source") or "unknown"

    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 16))) as pool:
        futures = {pool.submit(resolve, symbol): symbol for symbol in missing}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                _, price, source = future.result()
            except Exception:
                continue
            if price is not None and math.isfinite(price) and price > 0:
                result[symbol] = price
                new_rows.append({"symbol": symbol, "price": price, "timestamp": now, "source": source})
    if new_rows:
        cache = pd.concat([cache, pd.DataFrame(new_rows)], ignore_index=True)
        _write_cache(cache)
    return {symbol: result[symbol] for symbol in wanted if symbol in result}


def cache_status(path: Path = CACHE_FILE) -> dict:
    frame = _read_cache(path)
    if frame.empty:
        return {"status": "MISSING", "symbol_count": 0, "source_counts": {}}
    ages = time.time() - pd.to_numeric(frame["timestamp"], errors="coerce")
    return {
        "status": "OK" if float(ages.max()) < 86400 else "STALE",
        "symbol_count": int(len(frame)),
        "oldest_age_seconds": round(float(ages.max()), 1),
        "newest_age_seconds": round(float(ages.min()), 1),
        "source_counts": {str(key): int(value) for key, value in frame["source"].fillna("unknown").value_counts().items()},
    }
