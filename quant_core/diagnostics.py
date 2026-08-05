from __future__ import annotations

import io
import json
import math
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths
from quant_core.api import snapshot_loader as loader


_SAFE_STATE_FILES = {
    "portfolio_data.json": qpaths.PORTFOLIO_DATA_FILE,
    "data_health_snapshot.json": qpaths.DATA_HEALTH_SNAPSHOT_FILE,
    "job_status.json": qpaths.JOB_STATUS_FILE,
    "next_day_trade_plan.json": qpaths.NEXT_DAY_TRADE_PLAN_FILE,
    "plan_quality_snapshot.json": qpaths.PLAN_QUALITY_SNAPSHOT_FILE,
    "multi_horizon_snapshot.json": qpaths.MULTI_HORIZON_SNAPSHOT_FILE,
    "foundation_model_snapshot.json": qpaths.FOUNDATION_MODEL_SNAPSHOT_FILE,
    "core_etf_snapshot.json": qpaths.CORE_ETF_SNAPSHOT_FILE,
    "satellite_candidate_pool.json": qpaths.SATELLITE_CANDIDATE_POOL_FILE,
    "discipline_snapshot.json": qpaths.DISCIPLINE_SNAPSHOT_FILE,
    "market_monitor_snapshot.json": qpaths.MARKET_MONITOR_SNAPSHOT_FILE,
    "market_sentiment_snapshot.json": qpaths.MARKET_SENTIMENT_SNAPSHOT_FILE,
    "systemic_risk_snapshot.json": qpaths.SYSTEMIC_RISK_SNAPSHOT_FILE,
    "change_feed_latest.json": qpaths.CHANGE_FEED_FILE,
    "nightly_run_manifest.json": qpaths.NIGHTLY_RUN_MANIFEST_FILE,
    "news_intelligence.json": qpaths.NEWS_INTELLIGENCE_FILE,
    "financials_intelligence.json": qpaths.FINANCIALS_INTELLIGENCE_FILE,
    "decision_brief.json": qpaths.DECISION_BRIEF_FILE,
}


def _safe_json(path: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _safe_float(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _age_seconds(timestamp, *, now_ts: float):
    number = _safe_float(timestamp)
    if number is not None:
        return max(now_ts - number, 0.0)
    return None


def _load_price_cache() -> dict:
    payload = _safe_json(qpaths.PRICE_CACHE_FILE)
    if isinstance(payload, dict) and payload:
        return {str(symbol).upper(): dict(row or {}) for symbol, row in payload.items() if isinstance(row, Mapping)}
    parquet_path = Path(qpaths.PRICE_CACHE_FILE).with_suffix(".parquet")
    if not parquet_path.exists():
        return {}
    try:
        import pandas as pd

        frame = pd.read_parquet(parquet_path)
    except Exception:
        return {}
    cache = {}
    for row in frame.to_dict("records"):
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol:
            cache[symbol] = {
                "price": row.get("price"),
                "timestamp": row.get("timestamp"),
                "source": row.get("source"),
            }
    return cache


def summarize_price_cache(*, now: Optional[datetime] = None) -> dict:
    now = now if isinstance(now, datetime) else datetime.now()
    now_ts = now.timestamp()
    cache = _load_price_cache()
    source_counts: dict[str, int] = {}
    ages = []
    stale_symbols = []
    for symbol, row in cache.items():
        source = str(row.get("source") or "unknown").strip().lower() or "unknown"
        source_counts[source] = source_counts.get(source, 0) + 1
        age = _age_seconds(row.get("timestamp"), now_ts=now_ts)
        if age is not None:
            ages.append(age)
            if age > 3 * 3600:
                stale_symbols.append({"symbol": symbol, "age_seconds": round(age, 2), "source": source})
    ages.sort()
    stale_symbols.sort(key=lambda item: item["age_seconds"], reverse=True)
    return {
        "cache_entry_count": len(cache),
        "source_counts": source_counts,
        "freshest_age_seconds": round(ages[0], 2) if ages else None,
        "oldest_age_seconds": round(ages[-1], 2) if ages else None,
        "stale_symbol_count": len(stale_symbols),
        "stale_symbols_sample": stale_symbols[:30],
    }


def summarize_recommendation_consistency(*, now: Optional[datetime] = None) -> dict:
    dashboard = loader.load_dashboard_response(now=now)
    summary = dict(dashboard.get("summary", {}) or {})
    return {
        "status": summary.get("recommendation_consistency_status"),
        "message": summary.get("recommendation_consistency_message"),
        "model_candidate_action_count": summary.get("model_candidate_action_count"),
        "executable_plan_action_count": summary.get("executable_plan_action_count"),
        "blocked_plan_count": summary.get("blocked_plan_count"),
        "trade_plan_decision": summary.get("trade_plan_decision"),
    }


def build_diagnostics_summary(*, now: Optional[datetime] = None) -> dict:
    now = now if isinstance(now, datetime) else datetime.now()
    portfolio = _safe_json(qpaths.PORTFOLIO_DATA_FILE)
    holdings = list(dict(portfolio or {}).get("holdings", []) or [])
    watchlist = list(dict(portfolio or {}).get("watchlist", []) or [])
    data_health = _safe_json(qpaths.DATA_HEALTH_SNAPSHOT_FILE)
    return {
        "generated_at": now.isoformat(),
        "portfolio": {
            "holding_symbols": [str(row.get("symbol") or "").upper() for row in holdings if isinstance(row, Mapping)],
            "holding_count": len(holdings),
            "watchlist_count": len(watchlist),
            "cash_available": dict(dict(portfolio or {}).get("account", {}) or {}).get("cash_available"),
            "prices_last_updated": dict(portfolio or {}).get("prices_last_updated"),
        },
        "data_health": dict(data_health.get("summary", {}) or {}),
        "price_cache": summarize_price_cache(now=now),
        "recommendation_consistency": summarize_recommendation_consistency(now=now),
        "job_status": dict(_safe_json(qpaths.JOB_STATUS_FILE).get("summary", {}) or {}),
    }


def build_diagnostics_bundle(*, now: Optional[datetime] = None) -> bytes:
    now = now if isinstance(now, datetime) else datetime.now()
    summary = build_diagnostics_summary(now=now)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics_summary.json", json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        archive.writestr(
            "README.txt",
            "Quant Trade System diagnostics bundle. Safe snapshots only; notification secrets are intentionally excluded.\n",
        )
        for name, path in _SAFE_STATE_FILES.items():
            target = Path(path)
            if target.exists():
                archive.write(target, f"state/{name}")
    return buffer.getvalue()
