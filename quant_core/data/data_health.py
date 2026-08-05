from __future__ import annotations

import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths
from quant_core.data import market_data as md


DEFAULT_DATA_HEALTH_SNAPSHOT_FILE = qpaths.DATA_HEALTH_SNAPSHOT_FILE
DEFAULT_PRICE_STALE_SECONDS = 3 * 3600


def _safe_float(value, default=None):
    try:
        if value is None:
            return default
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _read_json(path: str):
    target = Path(path)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: str, payload: Mapping):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload or {}), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return str(target)


def _tracked_rows(data: Mapping):
    rows = []
    for row in list((data or {}).get("holdings", []) or []):
        symbol = str((row or {}).get("symbol") or "").strip().upper()
        if symbol:
            rows.append({"symbol": symbol, "list_type": "holding", "price": (row or {}).get("current_price")})
    for row in list((data or {}).get("watchlist", []) or []):
        symbol = str((row or {}).get("symbol") or "").strip().upper()
        if symbol:
            rows.append({"symbol": symbol, "list_type": "watchlist", "price": (row or {}).get("last_price")})
    return rows


def _normalize_price_cache(cache):
    if not isinstance(cache, Mapping):
        return {}
    normalized = {}
    for symbol, row in dict(cache or {}).items():
        symbol_text = str(symbol or "").strip().upper()
        if not symbol_text:
            continue
        if isinstance(row, Mapping):
            normalized[symbol_text] = dict(row)
    return normalized


def _derive_health_reason(
    *,
    tracked_count: int,
    missing_count: int,
    invalid_count: int,
    stale_count: int,
    fallback_symbols: int,
    last_error: str,
):
    if tracked_count > 0 and missing_count + invalid_count >= tracked_count:
        return "all_prices_missing_or_invalid", "check_data_source", False
    if missing_count or invalid_count:
        return "missing_or_invalid_prices", "check_data_source", False
    if stale_count:
        return "stale_prices", "refresh_market_data", False
    if last_error:
        return "source_error", "review_data_source_log", False
    if fallback_symbols:
        return "fallback_source_used", "review_primary_source", True
    return "ok", "none", False


def _timestamp_age_seconds(timestamp, *, now_ts: float):
    number = _safe_float(timestamp)
    if number is not None:
        return max(now_ts - number, 0.0)
    text = str(timestamp or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    try:
        parsed_ts = parsed.timestamp()
    except Exception:
        return None
    return max(now_ts - parsed_ts, 0.0)


def load_data_health_snapshot(*, path: str = DEFAULT_DATA_HEALTH_SNAPSHOT_FILE):
    return _read_json(path) or {}


def save_data_health_snapshot(snapshot: Mapping, *, path: str = DEFAULT_DATA_HEALTH_SNAPSHOT_FILE):
    return _write_json(path, snapshot)


def build_data_health_snapshot(
    data: Mapping,
    *,
    data_sources: Optional[Mapping] = None,
    price_cache: Optional[Mapping] = None,
    price_cache_path: str = qpaths.PRICE_CACHE_FILE,
    stale_after_seconds: int = DEFAULT_PRICE_STALE_SECONDS,
    now: Optional[datetime] = None,
) -> dict:
    now = now if isinstance(now, datetime) else datetime.now()
    now_ts = now.timestamp()
    data_sources = dict(data_sources or md.get_market_data_status_snapshot() or {})
    if price_cache is None:
        price_cache = _read_json(price_cache_path) or {}
    price_cache = _normalize_price_cache(price_cache)

    invalid_rows = []
    missing_rows = []
    stale_rows = []
    symbol_rows = []
    for row in _tracked_rows(data):
        symbol = row["symbol"]
        raw_price = row.get("price")
        price = _safe_float(raw_price)
        is_missing = raw_price is None or str(raw_price) == ""
        is_invalid = raw_price is not None and price is None
        cache_row = dict(price_cache.get(symbol, {}) or {})
        age_seconds = _timestamp_age_seconds(cache_row.get("timestamp"), now_ts=now_ts)
        is_stale = bool(age_seconds is not None and age_seconds > int(stale_after_seconds or DEFAULT_PRICE_STALE_SECONDS))
        source = str(cache_row.get("source") or "").strip().lower()
        status = "OK"
        reason = ""
        if is_missing:
            status = "MISSING"
            reason = "price_missing"
            missing_rows.append({**row, "reason": reason})
        elif is_invalid:
            status = "INVALID"
            reason = "price_not_finite"
            invalid_rows.append({**row, "reason": reason, "raw_price": str(raw_price)})
        elif is_stale:
            status = "STALE"
            reason = "cache_stale"
            stale_rows.append({**row, "reason": reason, "cache_age_seconds": age_seconds})
        symbol_rows.append(
            {
                "symbol": symbol,
                "list_type": row["list_type"],
                "price": price,
                "status": status,
                "reason": reason,
                "cache_age_seconds": age_seconds,
                "source": source or None,
            }
        )

    prices_status = dict(data_sources.get("prices", {}) or {})
    fallback_symbols = int(_safe_float(prices_status.get("fallback_symbols"), 0) or 0)
    primary_symbols = int(_safe_float(prices_status.get("primary_symbols"), 0) or 0)
    last_error = str(prices_status.get("last_error") or "").strip()
    issue_count = len(invalid_rows) + len(missing_rows) + len(stale_rows)
    tracked_count = len(symbol_rows)
    usable_price_count = len([row for row in symbol_rows if row.get("status") == "OK"])

    if tracked_count > 0 and len(missing_rows) + len(invalid_rows) >= tracked_count:
        status = "BROKEN"
    elif issue_count or fallback_symbols or last_error:
        status = "DEGRADED"
    else:
        status = "OK"
    health_reason, action_required, fallback_only = _derive_health_reason(
        tracked_count=tracked_count,
        missing_count=len(missing_rows),
        invalid_count=len(invalid_rows),
        stale_count=len(stale_rows),
        fallback_symbols=fallback_symbols,
        last_error=last_error,
    )

    return {
        "generated_at": now.isoformat(),
        "status": status,
        "summary": {
            "status": status,
            "health_reason": health_reason,
            "action_required": action_required,
            "fallback_only": fallback_only,
            "price_data_usable": bool(tracked_count > 0 and len(missing_rows) == 0 and len(invalid_rows) == 0),
            "tracked_symbol_count": tracked_count,
            "usable_price_count": usable_price_count,
            "problem_symbol_count": issue_count,
            "missing_price_count": len(missing_rows),
            "invalid_price_count": len(invalid_rows),
            "stale_price_count": len(stale_rows),
            "primary_symbol_count": primary_symbols,
            "fallback_symbol_count": fallback_symbols,
            "last_error": last_error or None,
        },
        "symbols": symbol_rows,
        "missing_symbols": [row["symbol"] for row in missing_rows],
        "invalid_symbols": [row["symbol"] for row in invalid_rows],
        "stale_symbols": [row["symbol"] for row in stale_rows],
        "data_sources": data_sources,
    }
