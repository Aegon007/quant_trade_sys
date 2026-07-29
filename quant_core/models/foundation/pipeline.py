from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

import pandas as pd

from quant_core.analytics import quant_analysis as qa
from quant_core.data import storage as data_storage
from quant_core.models.foundation.backends import select_backend
from quant_core.models.foundation.config import load_foundation_model_config, normalize_foundation_model_config
from quant_core.models.foundation.fusion import classify_long_horizon, classify_timing, fuse_foundation_decision
from quant_core.models.multi_horizon.pipeline import (
    _current_weights_pct,
    _load_default_universes,
    build_benchmark_map,
    build_model_universe_report,
    load_histories,
    summarize_history_failures,
)
from quant_core.risk.market_sentiment import build_market_sentiment_snapshot
from quant_core.risk.systemic import build_systemic_risk_snapshot
from quant_core import paths as qpaths


def _write_json(path: str, payload: Mapping) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload or {}), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return str(target)


def _latest_moving_average(frame: pd.DataFrame | None, window: int):
    if not isinstance(frame, pd.DataFrame) or frame.empty or "Close" not in frame.columns:
        return None
    close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
    if len(close) < window:
        return None
    return float(close.tail(window).mean())


def _asset_type(symbol: str, *, core_symbols: set[str]) -> str:
    return "core_etf" if symbol in core_symbols else "satellite_stock"


def _long_horizon_payload(forecast: Mapping) -> dict:
    horizons = dict(forecast.get("horizons", {}) or {})
    primary = dict(horizons.get("252") or (list(horizons.values())[-1] if horizons else {}) or {})
    return {
        "state": classify_long_horizon(forecast),
        "blended_rank": primary.get("risk_free_outperformance_probability"),
        "expected_return": dict(primary.get("return_range", {}) or {}).get("p50"),
        "positive_return_probability": primary.get("positive_return_probability"),
        "risk_free_outperformance_probability": primary.get("risk_free_outperformance_probability"),
        "market_outperformance_probability": primary.get("market_outperformance_probability"),
        "growth_outperformance_probability": primary.get("growth_outperformance_probability"),
        "horizons": horizons,
    }


def _score_satellite(row: Mapping) -> float:
    long = dict(row.get("long_horizon", {}) or {})
    decision = dict(row.get("shadow_decision", {}) or row.get("decision", {}) or {})
    expected = float(long.get("expected_return") or 0.0)
    beat_rf = float(long.get("risk_free_outperformance_probability") or 0.0)
    confidence = float(decision.get("confidence") or 0.0)
    penalty = 0.0
    if decision.get("risk_overrides"):
        penalty += 20.0
    return round(expected * 100.0 + beat_rf * 45.0 + confidence * 25.0 - penalty, 2)


def _summary(rows: list[dict], *, backend_name: str) -> dict:
    action_counts = {}
    for row in rows:
        action = str(dict(row.get("decision", {}) or {}).get("action") or "UNKNOWN").upper()
        action_counts[action] = action_counts.get(action, 0) + 1
    conflict_count = sum(
        1
        for row in rows
        if str(dict(row.get("long_horizon", {}) or {}).get("state") or "").upper() == "ATTRACTIVE"
        and str(dict(row.get("timing", {}) or {}).get("state") or "").upper() == "DETERIORATING"
    )
    return {
        "symbol_count": len(rows),
        "action_counts": action_counts,
        "conflict_count": conflict_count,
        "model_family": "FOUNDATION_MODEL",
        "backend": backend_name,
    }


def run_foundation_job(
    *,
    config: Mapping | None = None,
    data: Mapping | None = None,
    core_universe: Mapping | None = None,
    satellite_universe: Mapping | None = None,
    train: bool = False,
    load_history_fn: Callable = qa.get_historical_data,
    risk_regime: str = "NORMAL",
    now: datetime | None = None,
    progress_callback: Callable[[Mapping], None] | None = None,
) -> dict:
    now = now or datetime.now()
    normalized = normalize_foundation_model_config(config) if config is not None else load_foundation_model_config()
    if progress_callback:
        progress_callback({"stage": "foundation_prepare", "detail": "Preparing foundation-model engine", "progress_pct": 3})
    if not bool(normalized.get("enabled", True)):
        snapshot = {
            "schema_version": 3,
            "generated_at": now.isoformat(),
            "status": "MODEL_DISABLED",
            "model": {"model_id": normalized["model_id"], "model_family": "FOUNDATION_MODEL", "status": "DISABLED"},
            "summary": {"symbol_count": 0, "message": "Foundation model engine is disabled."},
            "symbols": [],
        }
        _write_json(qpaths.FOUNDATION_MODEL_SNAPSHOT_FILE, snapshot)
        _write_json(qpaths.MULTI_HORIZON_SNAPSHOT_FILE, snapshot)
        return snapshot

    data = dict(data or data_storage.load_data())
    if core_universe is None or satellite_universe is None:
        default_core, default_satellite = _load_default_universes()
        core_universe = default_core if core_universe is None else core_universe
        satellite_universe = default_satellite if satellite_universe is None else satellite_universe

    universe_report = build_model_universe_report(
        data,
        core_universe=dict(core_universe or {}),
        satellite_universe=dict(satellite_universe or {}),
        universe_policy={"exclude_tactical_products_from_long_horizon": True},
        maximum_symbols=int(normalized["maximum_symbols"]),
    )
    symbols = list(universe_report["symbols"])
    risk_free_symbol = str(normalized.get("risk_free_benchmark") or "BIL").upper()
    market_symbol = str(normalized.get("market_benchmark") or "SPY").upper()
    growth_symbol = str(normalized.get("growth_benchmark") or "QQQ").upper()
    history_symbols = list(dict.fromkeys([*symbols, market_symbol, growth_symbol, "VOO", "^VIX"]))
    if progress_callback:
        progress_callback({"stage": "foundation_history", "detail": f"Loading history for {len(history_symbols)} symbols", "progress_pct": 12})
    histories, failures = load_histories(
        history_symbols,
        history_period=str(normalized["history_period"]),
        risk_free_symbol=risk_free_symbol,
        load_history_fn=load_history_fn,
    )
    usable_symbols = [symbol for symbol in symbols if symbol in histories]
    news_intelligence = {}
    try:
        news_intelligence = json.loads(Path(qpaths.NEWS_INTELLIGENCE_FILE).read_text(encoding="utf-8"))
    except Exception:
        news_intelligence = {}
    try:
        financials_intelligence = json.loads(Path(qpaths.FINANCIALS_INTELLIGENCE_FILE).read_text(encoding="utf-8"))
    except Exception:
        financials_intelligence = {}
    market_sentiment = build_market_sentiment_snapshot(
        histories,
        symbols=usable_symbols,
        news_intelligence=news_intelligence,
        now=now,
    )
    systemic_risk = build_systemic_risk_snapshot(
        histories,
        symbols=usable_symbols,
        news_intelligence=news_intelligence,
        financials_intelligence=financials_intelligence,
        market_sentiment=market_sentiment,
        now=now,
    )
    _write_json(qpaths.MARKET_SENTIMENT_SNAPSHOT_FILE, market_sentiment)
    _write_json(qpaths.SYSTEMIC_RISK_SNAPSHOT_FILE, systemic_risk)

    backend, attempts = select_backend(normalized)
    capabilities = backend.capabilities()
    if progress_callback:
        progress_callback({"stage": "foundation_backend", "detail": f"Using backend {backend.name}", "progress_pct": 35})
    if capabilities.status != "READY":
        snapshot = {
            "schema_version": 3,
            "generated_at": now.isoformat(),
            "status": "MODEL_UNAVAILABLE",
            "model": {
                "model_id": normalized["model_id"],
                "display_name": "Foundation Quant Engine",
                "model_family": "FOUNDATION_MODEL",
                "backend": backend.name,
                "backend_family": capabilities.model_family,
                "status": capabilities.status,
                "version": f"{normalized['model_id']}:unavailable:{now.date().isoformat()}",
                "trained_at": None,
                "authority": "BLOCKED",
            },
            "benchmarks": {"risk_free": risk_free_symbol, "market": market_symbol, "growth": growth_symbol},
            "market_sentiment": market_sentiment,
            "systemic_risk": systemic_risk,
            "financials_intelligence": financials_intelligence,
            "backend_attempts": attempts,
            "symbols": [],
            "core_etfs": [],
            "satellite_top3": [],
            "satellite_ranked_pool": [],
            "summary": {
                "symbol_count": 0,
                "action_counts": {},
                "conflict_count": 0,
                "model_family": "FOUNDATION_MODEL",
                "backend": backend.name,
                "message": capabilities.message,
                "installation_hint": (
                    "~/venv/bin/pip install chronos-forecasting && "
                    "~/venv/bin/python -c \"from chronos import BaseChronosPipeline; "
                    "BaseChronosPipeline.from_pretrained('amazon/chronos-bolt-small', device_map='cpu')\""
                ),
            },
            "data_quality": {
                "requested_symbol_count": len(symbols),
                "usable_symbol_count": len(usable_symbols),
                "failed_symbol_count": len(failures),
                "failures": failures,
                "failure_summary": summarize_history_failures(failures),
                "excluded_from_long_horizon": list(universe_report["excluded"]),
            },
            "universe": {
                "asset_groups": {symbol: universe_report["asset_groups"].get(symbol) for symbol in usable_symbols},
                "excluded": list(universe_report["excluded"]),
            },
        }
        _write_json(qpaths.FOUNDATION_MODEL_SNAPSHOT_FILE, snapshot)
        _write_json(qpaths.MULTI_HORIZON_SNAPSHOT_FILE, snapshot)
        if progress_callback:
            progress_callback({"stage": "foundation_blocked", "detail": capabilities.message, "progress_pct": 100})
        return snapshot
    forecasts = backend.forecast(
        histories,
        symbols=usable_symbols,
        horizons=list(normalized["horizons"]),
        benchmarks={"risk_free": risk_free_symbol, "market": market_symbol, "growth": growth_symbol},
    )

    core_symbols = {
        str(dict(row or {}).get("symbol") or "").strip().upper()
        for row in list(dict(core_universe or {}).get("etfs", []) or [])
        if bool(dict(row or {}).get("enabled", True))
    }
    holding_symbols = {
        str(row.get("symbol") or "").strip().upper()
        for row in list(data.get("holdings", []) or [])
    }
    watchlist_symbols = {
        str(row.get("symbol") or "").strip().upper()
        for row in list(data.get("watchlist", []) or [])
    }
    current_weights = _current_weights_pct(data)
    decision_config = dict(normalized.get("decision", {}) or {})
    rows = []
    for symbol in usable_symbols:
        forecast = dict(forecasts.get(symbol, {}) or {})
        if not forecast:
            continue
        history = histories.get(symbol)
        timing_state = classify_timing(
            latest_price=forecast.get("latest_price"),
            average_50=_latest_moving_average(history, 50),
            average_200=_latest_moving_average(history, 200),
        )
        asset_type = _asset_type(symbol, core_symbols=core_symbols)
        max_weight = (
            float(decision_config.get("core_max_weight_pct") or 70.0)
            if asset_type == "core_etf"
            else float(decision_config.get("satellite_max_weight_pct") or 5.0)
        )
        decision = fuse_foundation_decision(
            symbol=symbol,
            asset_type=asset_type,
            forecast_row=forecast,
            current_weight_pct=float(current_weights.get(symbol, 0.0)),
            market_sentiment=market_sentiment,
            systemic_risk=systemic_risk,
            risk_regime=risk_regime,
            max_weight_pct=max_weight,
        )
        row = {
            "symbol": symbol,
            "asset_type": asset_type,
            "model_id": normalized["model_id"],
            "model_family": capabilities.model_family,
            "foundation": {
                "backend": backend.name,
                "backend_status": capabilities.status,
                "capabilities": capabilities.__dict__,
            },
            "latest_price": forecast.get("latest_price"),
            "current_weight_pct": float(current_weights.get(symbol, 0.0)),
            "list_type": (
                "holding"
                if symbol in holding_symbols
                else "watchlist"
                if symbol in watchlist_symbols
                else "candidate_pool"
            ),
            "long_horizon": _long_horizon_payload(forecast),
            "timing": {"state": timing_state},
            "decision_fusion": {
                "market_sentiment_state": market_sentiment.get("risk_appetite_state"),
                "systemic_risk_state": systemic_risk.get("ai_capex_stress"),
                "risk_regime": risk_regime,
            },
            "shadow_decision": decision,
            "decision": decision,
        }
        rows.append(row)

    satellite_candidates = [row for row in rows if row["asset_type"] != "core_etf" and row["symbol"] not in holding_symbols]
    for row in satellite_candidates:
        row["satellite_score"] = _score_satellite(row)
    satellite_candidates.sort(key=lambda row: float(row.get("satellite_score") or 0.0), reverse=True)
    satellite_top3 = satellite_candidates[:3]
    top3_symbols = {row["symbol"] for row in satellite_top3}
    for index, row in enumerate(satellite_candidates, start=1):
        row["satellite_rank"] = index
        row["top3_state"] = "RETAINED" if row["symbol"] in top3_symbols else "WATCH"
        if row["symbol"] not in top3_symbols and str(dict(row.get("decision", {}) or {}).get("action")).upper() in {"PROBE", "ACCUMULATE"}:
            row["decision"] = {
                **dict(row["decision"]),
                "action": "WATCH",
                "target_weight_range_pct": [0.0, 0.0],
                "reason_codes": [*list(dict(row["decision"]).get("reason_codes", []) or []), "OUTSIDE_SATELLITE_TOP3"],
            }
            row["shadow_decision"] = dict(row["decision"])

    core_rows = [row for row in rows if row["asset_type"] == "core_etf"]
    snapshot = {
        "schema_version": 3,
        "generated_at": now.isoformat(),
        "status": "READY",
        "model": {
            "model_id": normalized["model_id"],
            "display_name": "Foundation Quant Engine",
            "model_family": "FOUNDATION_MODEL",
            "backend": backend.name,
            "backend_family": capabilities.model_family,
            "status": capabilities.status,
            "version": f"{normalized['model_id']}:{backend.name}:{now.date().isoformat()}",
            "trained_at": now.isoformat(),
            "authority": "SHADOW_UNTIL_VALIDATED" if capabilities.model_family == "FOUNDATION_PROXY" else "CANDIDATE",
        },
        "benchmarks": {"risk_free": risk_free_symbol, "market": market_symbol, "growth": growth_symbol},
        "market_sentiment": market_sentiment,
        "systemic_risk": systemic_risk,
        "financials_intelligence": financials_intelligence,
        "backend_attempts": attempts,
        "symbols": rows,
        "core_etfs": core_rows,
        "satellite_top3": satellite_top3,
        "satellite_ranked_pool": satellite_candidates,
        "summary": {
            **_summary(rows, backend_name=backend.name),
            "top_satellite_symbols": [row["symbol"] for row in satellite_top3],
            "market_sentiment_score": market_sentiment.get("market_sentiment_score"),
            "risk_appetite_state": market_sentiment.get("risk_appetite_state"),
            "ai_capex_stress": systemic_risk.get("ai_capex_stress"),
            "systemic_risk_score": systemic_risk.get("systemic_risk_score"),
            "message": capabilities.message,
        },
        "data_quality": {
            "requested_symbol_count": len(symbols),
            "usable_symbol_count": len(usable_symbols),
            "failed_symbol_count": len(failures),
            "failures": failures,
            "failure_summary": summarize_history_failures(failures),
            "excluded_from_long_horizon": list(universe_report["excluded"]),
        },
        "universe": {
            "asset_groups": {symbol: universe_report["asset_groups"].get(symbol) for symbol in usable_symbols},
            "excluded": list(universe_report["excluded"]),
        },
    }
    _write_json(qpaths.FOUNDATION_MODEL_SNAPSHOT_FILE, snapshot)
    _write_json(qpaths.MULTI_HORIZON_SNAPSHOT_FILE, snapshot)
    if progress_callback:
        progress_callback({"stage": "foundation_complete", "detail": f"Foundation snapshot ready for {len(rows)} symbols", "progress_pct": 100})
    return snapshot
