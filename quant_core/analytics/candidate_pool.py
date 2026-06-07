from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Optional

import pandas as pd

from quant_core import paths as qpaths


DEFAULT_SATELLITE_UNIVERSE = {
    "source_indexes": ["sp500", "nasdaq100"],
    "manual_include": [],
    "manual_exclude": [],
    "max_candidate_pool_size": 100,
    "max_deep_analysis_size": 20,
    "max_recommendations": 3,
    "candidate_persistence_days": 2,
}

DEFAULT_SATELLITE_CANDIDATE_POOL_FILE = qpaths.SATELLITE_CANDIDATE_POOL_FILE


def _safe_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value, low, high):
    return max(low, min(high, value))


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
    target.write_text(json.dumps(dict(payload or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def normalize_satellite_universe(config) -> dict:
    payload = deepcopy(DEFAULT_SATELLITE_UNIVERSE)
    if not isinstance(config, Mapping):
        return payload
    payload["source_indexes"] = [
        str(item).strip().lower()
        for item in list(config.get("source_indexes", []) or [])
        if str(item).strip()
    ]
    payload["manual_include"] = sorted(
        {
            str(item).strip().upper()
            for item in list(config.get("manual_include", []) or [])
            if str(item).strip()
        }
    )
    payload["manual_exclude"] = sorted(
        {
            str(item).strip().upper()
            for item in list(config.get("manual_exclude", []) or [])
            if str(item).strip()
        }
    )
    for key, default_value in (
        ("max_candidate_pool_size", 100),
        ("max_deep_analysis_size", 20),
        ("max_recommendations", 3),
        ("candidate_persistence_days", 2),
    ):
        value = int(_safe_float(config.get(key), default_value) or default_value)
        payload[key] = max(1, value)
    return payload


def load_satellite_universe(path: str = qpaths.SATELLITE_UNIVERSE_FILE) -> dict:
    return normalize_satellite_universe(_read_json(path))


def save_satellite_universe(config, path: str = qpaths.SATELLITE_UNIVERSE_FILE) -> str:
    return _write_json(path, normalize_satellite_universe(config))


def load_satellite_candidate_pool_snapshot(*, path: str = DEFAULT_SATELLITE_CANDIDATE_POOL_FILE):
    return _read_json(path)


def save_satellite_candidate_pool_snapshot(snapshot: Mapping, *, path: str = DEFAULT_SATELLITE_CANDIDATE_POOL_FILE) -> str:
    return _write_json(path, snapshot)


def _close_series(history) -> pd.Series:
    if history is None or getattr(history, "empty", True):
        return pd.Series(dtype=float)
    if "Close" not in history.columns:
        return pd.Series(dtype=float)
    close = pd.to_numeric(history["Close"], errors="coerce").dropna()
    return close.astype(float)


def _moving_average(close: pd.Series, window: int):
    if close.empty:
        return None
    rolling = close.rolling(window=window, min_periods=max(5, min(window, 20))).mean()
    return _safe_float(rolling.iloc[-1])


def _trailing_return(close: pd.Series, lookback_days: int):
    if close.empty or len(close) < 2:
        return None
    anchor_idx = max(0, len(close) - lookback_days - 1)
    anchor = _safe_float(close.iloc[anchor_idx])
    latest = _safe_float(close.iloc[-1])
    if anchor is None or latest is None or anchor <= 0:
        return None
    return latest / anchor - 1.0


def _annualized_volatility(close: pd.Series):
    returns = close.pct_change().dropna()
    if returns.empty:
        return None
    return float(returns.std() * (252 ** 0.5))


def _max_drawdown(close: pd.Series):
    if close.empty:
        return None
    rolling_max = close.cummax()
    drawdown = close / rolling_max - 1.0
    return float(drawdown.min())


def _high_proximity(close: pd.Series):
    if close.empty:
        return None
    latest = _safe_float(close.iloc[-1])
    high_252 = _safe_float(close.tail(252).max())
    if latest is None or high_252 is None or high_252 <= 0:
        return None
    return latest / high_252


def _price_score(close: pd.Series):
    ret_3m = _trailing_return(close, 63)
    ret_6m = _trailing_return(close, 126)
    ret_12m = _trailing_return(close, 252)
    volatility = _annualized_volatility(close)
    drawdown = _max_drawdown(close)
    ma50 = _moving_average(close, 50)
    ma200 = _moving_average(close, 200)
    latest = _safe_float(close.iloc[-1]) if not close.empty else None
    score = 50.0
    if ret_3m is not None:
        score += _clamp(ret_3m * 70.0, -12.0, 12.0)
    if ret_6m is not None:
        score += _clamp(ret_6m * 50.0, -8.0, 10.0)
    if ret_12m is not None:
        score += _clamp(ret_12m * 35.0, -6.0, 7.0)
    if latest is not None and ma50 is not None and latest > ma50:
        score += 4.0
    if ma50 is not None and ma200 is not None and ma50 > ma200:
        score += 5.0
    if volatility is not None:
        score -= _clamp(volatility * 15.0, 0.0, 8.0)
    if drawdown is not None:
        score += _clamp(drawdown * 20.0, -8.0, 2.0)
    return _clamp(score, 0.0, 100.0), {
        "return_3m": ret_3m,
        "return_6m": ret_6m,
        "return_12m": ret_12m,
        "volatility": volatility,
        "max_drawdown": drawdown,
        "ma50": ma50,
        "ma200": ma200,
        "high_proximity": _high_proximity(close),
    }


def resolve_satellite_symbols(
    *,
    data: Mapping,
    universe: Mapping,
    core_symbols: Optional[set[str]] = None,
):
    core_symbols = {str(symbol).strip().upper() for symbol in list(core_symbols or set()) if str(symbol).strip()}
    universe = normalize_satellite_universe(universe)
    source_map = {}

    def _register(symbol: str, source: str):
        symbol = str(symbol or "").strip().upper()
        if not symbol or symbol in core_symbols:
            return
        source_map.setdefault(symbol, set()).add(source)

    for symbol in list(universe.get("manual_include", []) or []):
        _register(symbol, "manual_include")
    for row in list((data or {}).get("watchlist", []) or []):
        _register(row.get("symbol"), "watchlist")
    for row in list((data or {}).get("holdings", []) or []):
        _register(row.get("symbol"), "holding")

    for symbol in list(universe.get("manual_exclude", []) or []):
        source_map.pop(symbol, None)

    symbols = []
    for symbol, sources in source_map.items():
        symbols.append({"symbol": symbol, "sources": sorted(sources)})
    symbols.sort(key=lambda row: (0 if "holding" in row["sources"] else 1, row["symbol"]))
    return symbols


def _persistence_counts(previous_row: Optional[Mapping], *, entry_hit: bool, exit_hit: bool):
    previous_row = dict(previous_row or {})
    previous_entry = int(_safe_float(previous_row.get("entry_support_days"), 0) or 0)
    previous_exit = int(_safe_float(previous_row.get("exit_support_days"), 0) or 0)
    return {
        "entry_support_days": previous_entry + 1 if entry_hit else 0,
        "exit_support_days": previous_exit + 1 if exit_hit else 0,
    }


def _candidate_state(
    *,
    score: float,
    entry_support_days: int,
    exit_support_days: int,
    entry_threshold: float,
    exit_threshold: float,
    persistence_days: int,
):
    if score >= entry_threshold:
        return "ACTIVE" if entry_support_days >= persistence_days else "EMERGING"
    if score >= exit_threshold:
        return "WATCH"
    if exit_support_days >= persistence_days:
        return "REJECT"
    return "FADING"


def build_satellite_candidate_pool_snapshot(
    *,
    data: Mapping,
    strategy: Mapping,
    history_period: str = "2y",
    load_historical_data_fn: Optional[Callable[..., object]] = None,
    universe: Optional[Mapping] = None,
    core_symbols: Optional[set[str]] = None,
    previous_snapshot: Optional[Mapping] = None,
    discipline_snapshot: Optional[Mapping] = None,
    policy: Optional[Mapping] = None,
    risk_gate=None,
    allocation_regime=None,
    quant_analysis_snapshot_builder: Optional[Callable[..., Mapping]] = None,
    rank_candidates_fn: Optional[Callable[..., Mapping]] = None,
    now: Optional[datetime] = None,
):
    if load_historical_data_fn is None:
        from quant_core.analytics import quant_analysis as qa

        load_historical_data_fn = qa.get_historical_data
    if quant_analysis_snapshot_builder is None:
        from quant_core.analytics import portfolio_analysis as qpa

        quant_analysis_snapshot_builder = qpa.build_portfolio_quant_analysis_snapshot
    if rank_candidates_fn is None:
        from quant_core.analytics import satellite_ranker as sr

        rank_candidates_fn = sr.rank_satellite_candidates
    if policy is None:
        from quant_core.analytics import core_etf_rotation as cer

        policy = cer.load_engine_policy()

    now = now or datetime.now()
    universe = normalize_satellite_universe(universe or load_satellite_universe())
    previous_map = {
        str((row or {}).get("symbol") or "").strip().upper(): dict(row or {})
        for row in list((previous_snapshot or {}).get("symbols", []) or [])
        if (row or {}).get("symbol")
    }
    symbol_rows = resolve_satellite_symbols(data=data, universe=universe, core_symbols=core_symbols)
    entry_threshold = float(policy.get("candidate_entry_threshold", 65.0) or 65.0)
    exit_threshold = float(policy.get("candidate_exit_threshold", 45.0) or 45.0)
    persistence_days = max(1, int(universe.get("candidate_persistence_days", policy.get("candidate_persistence_days", 2)) or 2))

    rows = []
    for source_row in symbol_rows:
        symbol = source_row["symbol"]
        row = {
            "symbol": symbol,
            "sources": list(source_row.get("sources", [])),
            "error": None,
        }
        try:
            history = load_historical_data_fn(symbol, period=history_period)
            close = _close_series(history)
            if close.empty:
                raise ValueError("history unavailable")
            latest_price = _safe_float(close.iloc[-1])
            price_score, metrics = _price_score(close)
            previous_row = previous_map.get(symbol)
            persistence = _persistence_counts(
                previous_row,
                entry_hit=price_score >= entry_threshold,
                exit_hit=price_score < exit_threshold,
            )
            state = _candidate_state(
                score=price_score,
                entry_support_days=persistence["entry_support_days"],
                exit_support_days=persistence["exit_support_days"],
                entry_threshold=entry_threshold,
                exit_threshold=exit_threshold,
                persistence_days=persistence_days,
            )
            row.update(
                {
                    "current_price": latest_price,
                    "light_score": round(price_score, 4),
                    "candidate_state": state,
                    "entry_support_days": persistence["entry_support_days"],
                    "exit_support_days": persistence["exit_support_days"],
                    **metrics,
                }
            )
        except Exception as exc:
            row.update(
                {
                    "current_price": None,
                    "light_score": 0.0,
                    "candidate_state": "REJECT",
                    "entry_support_days": 0,
                    "exit_support_days": persistence_days,
                    "error": str(exc),
                }
            )
        rows.append(row)

    rows.sort(key=lambda row: (-float(row.get("light_score") or 0.0), row["symbol"]))
    candidate_rows = [row for row in rows if str(row.get("candidate_state") or "") != "REJECT"]
    candidate_rows = candidate_rows[: int(universe.get("max_candidate_pool_size", 100) or 100)]
    deep_analysis_symbols = [row["symbol"] for row in candidate_rows[: int(universe.get("max_deep_analysis_size", 20) or 20)]]

    deep_snapshot = {
        "generated_at": now.isoformat(),
        "summary": {"total_symbols": 0, "top_buy_symbols": []},
        "symbols": [],
    }
    if deep_analysis_symbols:
        temp_data = {
            "account": dict((data or {}).get("account", {}) or {}),
            "holdings": [],
            "watchlist": [
                {
                    "symbol": row["symbol"],
                    "last_price": row.get("current_price"),
                    "notes": ",".join(row.get("sources", [])),
                }
                for row in candidate_rows
                if row["symbol"] in deep_analysis_symbols
            ],
        }
        deep_snapshot = quant_analysis_snapshot_builder(
            temp_data,
            strategy=strategy,
            history_period=history_period,
            load_historical_data_fn=load_historical_data_fn,
            risk_gate=risk_gate,
            allocation_regime=allocation_regime,
            now=now,
        )

    deep_map = {
        str((row or {}).get("symbol") or "").strip().upper(): dict(row or {})
        for row in list((deep_snapshot or {}).get("symbols", []) or [])
        if (row or {}).get("symbol")
    }
    merged_rows = []
    for row in candidate_rows:
        merged = dict(row)
        deep_row = deep_map.get(row["symbol"], {})
        for key in (
            "signal",
            "raw_signal",
            "signal_reason",
            "backtest",
            "scoreboard",
            "guidance",
            "monte_carlo",
            "tcn_profile",
            "position_advice",
            "error",
        ):
            if key in deep_row:
                merged[key] = deep_row.get(key)
        merged["deep_analyzed"] = bool(deep_row)
        merged_rows.append(merged)

    snapshot = {
        "generated_at": now.isoformat(),
        "history_period": history_period,
        "universe": universe,
        "summary": {
            "scanned_symbols": len(symbol_rows),
            "candidate_count": len(candidate_rows),
            "deep_analysis_count": len(deep_analysis_symbols),
            "top_recommendation_count": 0,
            "candidate_symbols": [row["symbol"] for row in candidate_rows[:10]],
            "top_symbols": [],
        },
        "deep_analysis_snapshot": deep_snapshot,
        "symbols": merged_rows,
        "max_recommendations": int(universe.get("max_recommendations", 3) or 3),
    }
    return rank_candidates_fn(
        snapshot,
        policy=policy,
        discipline_snapshot=discipline_snapshot,
        previous_snapshot=previous_snapshot,
        max_recommendations=int(universe.get("max_recommendations", 3) or 3),
    )
