from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Optional

import pandas as pd

from quant_core import paths as qpaths


DEFAULT_CORE_ETF_UNIVERSE = {
    "etfs": [
        {"symbol": "VOO", "enabled": True, "role": "broad_market", "priority": 1, "long_term_core": True},
        {"symbol": "VTI", "enabled": True, "role": "broad_market", "priority": 2, "long_term_core": True},
        {"symbol": "QQQ", "enabled": True, "role": "growth", "priority": 3, "long_term_core": True},
        {"symbol": "SCHD", "enabled": True, "role": "dividend_quality", "priority": 4, "long_term_core": True},
        {"symbol": "QUAL", "enabled": True, "role": "quality", "priority": 5, "long_term_core": True},
        {"symbol": "SGOV", "enabled": True, "role": "cash_substitute", "priority": 6, "long_term_core": True},
    ]
}

DEFAULT_ENGINE_POLICY = {
    "core_etf_weight_ranges": {
        "broad_market": {"min_pct": 20.0, "max_pct": 65.0},
        "growth": {"min_pct": 5.0, "max_pct": 35.0},
        "dividend_quality": {"min_pct": 5.0, "max_pct": 25.0},
        "quality": {"min_pct": 0.0, "max_pct": 20.0},
        "cash_substitute": {"min_pct": 0.0, "max_pct": 25.0},
        "other": {"min_pct": 0.0, "max_pct": 15.0},
    },
    "min_weight_change_pct": 3.0,
    "action_confirmation_days": 2,
    "minimum_trade_value": 250.0,
    "action_cooldown_days": 2,
    "high_volatility_threshold": 0.28,
    "high_volatility_confirmation_boost_days": 1,
    "satellite_max_total_weight_pct": 15.0,
    "satellite_max_single_weight_pct": 5.0,
    "candidate_entry_threshold": 65.0,
    "candidate_exit_threshold": 45.0,
    "candidate_persistence_days": 2,
    "top3_promotion_confirmation_days": 2,
    "top3_demotion_confirmation_days": 2,
    "minimum_top3_residency_days": 2,
}

DEFAULT_ROTATION_SNAPSHOT_FILE = qpaths.CORE_ETF_SNAPSHOT_FILE


def _clone(value):
    return deepcopy(value)


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


def normalize_core_etf_universe(config) -> dict:
    payload = _clone(DEFAULT_CORE_ETF_UNIVERSE)
    if not isinstance(config, Mapping):
        return payload

    rows = []
    for item in list(config.get("etfs", []) or []):
        symbol = str((item or {}).get("symbol") or "").strip().upper()
        if not symbol:
            continue
        rows.append(
            {
                "symbol": symbol,
                "enabled": bool((item or {}).get("enabled", True)),
                "role": str((item or {}).get("role") or "other").strip().lower() or "other",
                "priority": int(_safe_float((item or {}).get("priority"), len(rows) + 1) or len(rows) + 1),
                "long_term_core": bool((item or {}).get("long_term_core", True)),
            }
        )
    if rows:
        rows.sort(key=lambda row: (row["priority"], row["symbol"]))
        payload["etfs"] = rows
    return payload


def load_core_etf_universe(path: str = qpaths.CORE_ETF_UNIVERSE_FILE) -> dict:
    return normalize_core_etf_universe(_read_json(path))


def save_core_etf_universe(config, path: str = qpaths.CORE_ETF_UNIVERSE_FILE) -> str:
    return _write_json(path, normalize_core_etf_universe(config))


def normalize_engine_policy(config) -> dict:
    payload = _clone(DEFAULT_ENGINE_POLICY)
    if not isinstance(config, Mapping):
        return payload
    weight_ranges = dict(config.get("core_etf_weight_ranges", {}) or {})
    normalized_ranges = {}
    for role, default_range in payload["core_etf_weight_ranges"].items():
        branch = dict(weight_ranges.get(role, {}) or {})
        min_pct = _safe_float(branch.get("min_pct"), default_range["min_pct"])
        max_pct = _safe_float(branch.get("max_pct"), default_range["max_pct"])
        if max_pct is None:
            max_pct = default_range["max_pct"]
        if min_pct is None:
            min_pct = default_range["min_pct"]
        if max_pct < min_pct:
            min_pct, max_pct = max_pct, min_pct
        normalized_ranges[role] = {"min_pct": float(min_pct), "max_pct": float(max_pct)}
    payload["core_etf_weight_ranges"] = normalized_ranges
    for key in (
        "min_weight_change_pct",
        "action_confirmation_days",
        "minimum_trade_value",
        "action_cooldown_days",
        "high_volatility_threshold",
        "high_volatility_confirmation_boost_days",
        "satellite_max_total_weight_pct",
        "satellite_max_single_weight_pct",
        "candidate_entry_threshold",
        "candidate_exit_threshold",
        "candidate_persistence_days",
        "top3_promotion_confirmation_days",
        "top3_demotion_confirmation_days",
        "minimum_top3_residency_days",
    ):
        value = _safe_float(config.get(key), payload[key])
        payload[key] = int(value) if "days" in key else float(value)
    return payload


def load_engine_policy(path: str = qpaths.ENGINE_POLICY_FILE) -> dict:
    return normalize_engine_policy(_read_json(path))


def save_engine_policy(config, path: str = qpaths.ENGINE_POLICY_FILE) -> str:
    return _write_json(path, normalize_engine_policy(config))


def _latest_price_from_data(data: Mapping, symbol: str):
    symbol = str(symbol or "").strip().upper()
    for row in list((data or {}).get("holdings", []) or []):
        if str(row.get("symbol") or "").strip().upper() == symbol:
            price = _safe_float(row.get("current_price"))
            if price is not None and price > 0:
                return price
    for row in list((data or {}).get("watchlist", []) or []):
        if str(row.get("symbol") or "").strip().upper() == symbol:
            price = _safe_float(row.get("last_price"))
            if price is not None and price > 0:
                return price
    return None


def _close_series(history) -> pd.Series:
    if history is None or getattr(history, "empty", True):
        return pd.Series(dtype=float)
    if "Close" not in history.columns:
        return pd.Series(dtype=float)
    close = pd.to_numeric(history["Close"], errors="coerce").dropna()
    return close.astype(float)


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


def _moving_average(close: pd.Series, window: int):
    if close.empty:
        return None
    series = close.rolling(window=window, min_periods=max(5, min(window, 20))).mean()
    value = _safe_float(series.iloc[-1])
    return value


def _rotation_backtest(close: pd.Series):
    if close.empty or len(close) < 40:
        return {
            "strategy_total_return": None,
            "buy_hold_return": _trailing_return(close, len(close) - 1),
            "excess_return": None,
            "strategy_max_drawdown": None,
        }
    slow_ma = close.rolling(window=100, min_periods=30).mean()
    signal = (close > slow_ma).astype(float)
    daily_returns = close.pct_change().fillna(0.0)
    strategy_returns = daily_returns * signal.shift(1).fillna(0.0)
    equity = (1.0 + strategy_returns).cumprod()
    strategy_total_return = float(equity.iloc[-1] - 1.0)
    rolling_max = equity.cummax()
    strategy_drawdown = float((equity / rolling_max - 1.0).min())
    buy_hold_return = _trailing_return(close, len(close) - 1)
    excess_return = None
    if buy_hold_return is not None:
        excess_return = strategy_total_return - buy_hold_return
    return {
        "strategy_total_return": strategy_total_return,
        "buy_hold_return": buy_hold_return,
        "excess_return": excess_return,
        "strategy_max_drawdown": strategy_drawdown,
    }


def _role_bias(role: str, risk_regime: str, allocation_regime: str) -> float:
    role = str(role or "other").strip().lower()
    risk_regime = str(risk_regime or "NORMAL").strip().upper()
    allocation_regime = str(allocation_regime or "NORMAL").strip().upper()
    if risk_regime == "RISK_OFF" or allocation_regime == "STOP":
        if role == "cash_substitute":
            return 15.0
        if role in {"dividend_quality", "quality"}:
            return 8.0
        if role == "growth":
            return -15.0
        return -5.0
    if risk_regime == "CAUTION" or allocation_regime == "LIGHT":
        if role == "cash_substitute":
            return 10.0
        if role in {"dividend_quality", "quality"}:
            return 6.0
        if role == "growth":
            return -8.0
        return 2.0
    if allocation_regime == "HEAVY":
        if role == "growth":
            return 10.0
        if role == "broad_market":
            return 5.0
        if role == "cash_substitute":
            return -10.0
    return 0.0


def _trend_quality_score(close: pd.Series) -> float:
    if close.empty or len(close) < 30:
        return 0.0
    ma20 = _moving_average(close, 20)
    ma50 = _moving_average(close, 50)
    ma200 = _moving_average(close, 200)
    latest = _safe_float(close.iloc[-1], 0.0) or 0.0
    score = 0.0
    if latest > 0 and ma20 is not None and latest > ma20:
        score += 4.0
    if ma20 is not None and ma50 is not None and ma20 > ma50:
        score += 4.0
    if ma50 is not None and ma200 is not None and ma50 > ma200:
        score += 4.0
    return score


def _composite_score(close: pd.Series, *, role: str, risk_regime: str, allocation_regime: str):
    ret_3m = _trailing_return(close, 63)
    ret_6m = _trailing_return(close, 126)
    ret_12m = _trailing_return(close, 252)
    volatility = _annualized_volatility(close)
    drawdown = _max_drawdown(close)
    backtest = _rotation_backtest(close)

    score = 50.0
    if ret_3m is not None:
        score += _clamp(ret_3m * 100.0, -12.0, 12.0)
    if ret_6m is not None:
        score += _clamp(ret_6m * 60.0, -10.0, 10.0)
    if ret_12m is not None:
        score += _clamp(ret_12m * 40.0, -8.0, 8.0)
    score += _trend_quality_score(close)
    score += _role_bias(role, risk_regime, allocation_regime)
    excess_return = _safe_float(backtest.get("excess_return"))
    if excess_return is not None:
        score += _clamp(excess_return * 100.0, -8.0, 8.0)
    if volatility is not None:
        score -= _clamp(volatility * 18.0, 0.0, 10.0)
    if drawdown is not None:
        score += _clamp(drawdown * 20.0, -10.0, 2.0)
    return _clamp(score, 0.0, 100.0), {
        "return_3m": ret_3m,
        "return_6m": ret_6m,
        "return_12m": ret_12m,
        "volatility": volatility,
        "max_drawdown": drawdown,
        "backtest": backtest,
        "ma20": _moving_average(close, 20),
        "ma50": _moving_average(close, 50),
        "ma200": _moving_average(close, 200),
    }


def _row_status(score: float, entry_threshold: float, exit_threshold: float) -> str:
    if score >= entry_threshold:
        return "FOCUS"
    if score >= exit_threshold:
        return "WATCH"
    return "PAUSE"


def build_core_etf_rotation_snapshot(
    *,
    data: Mapping,
    history_period: str = "2y",
    load_historical_data_fn: Optional[Callable[[str, str], pd.DataFrame]] = None,
    universe: Optional[Mapping] = None,
    policy: Optional[Mapping] = None,
    risk_gate=None,
    allocation_regime=None,
    now: Optional[datetime] = None,
) -> dict:
    if load_historical_data_fn is None:
        from quant_core.analytics import quant_analysis as qa

        load_historical_data_fn = qa.get_historical_data

    now = now or datetime.now()
    universe = normalize_core_etf_universe(universe or load_core_etf_universe())
    policy = normalize_engine_policy(policy or load_engine_policy())
    risk_regime = str(getattr(risk_gate, "regime", "NORMAL") or "NORMAL").upper() if risk_gate is not None else "NORMAL"
    allocation_name = (
        str(getattr(allocation_regime, "regime", "NORMAL") or "NORMAL").upper()
        if allocation_regime is not None
        else "NORMAL"
    )

    symbols = []
    for item in list(universe.get("etfs", []) or []):
        if not bool(item.get("enabled", True)):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        if symbol:
            symbols.append(dict(item))

    rows = []
    for item in symbols:
        symbol = item["symbol"]
        role = item.get("role", "other")
        history = load_historical_data_fn(symbol, period=history_period)
        close = _close_series(history)
        current_price = _latest_price_from_data(data, symbol)
        if current_price is None and not close.empty:
            current_price = _safe_float(close.iloc[-1])
        score, metrics = _composite_score(
            close,
            role=role,
            risk_regime=risk_regime,
            allocation_regime=allocation_name,
        )
        status = _row_status(
            score,
            float(policy.get("candidate_entry_threshold", 65.0)),
            float(policy.get("candidate_exit_threshold", 45.0)),
        )
        rows.append(
            {
                "symbol": symbol,
                "enabled": bool(item.get("enabled", True)),
                "role": role,
                "priority": int(item.get("priority", 0) or 0),
                "long_term_core": bool(item.get("long_term_core", True)),
                "current_price": current_price,
                "rotation_score": round(score, 4),
                "rotation_status": status,
                "confidence": round(score / 100.0, 4),
                "risk_regime": risk_regime,
                "allocation_regime": allocation_name,
                "expected_return_3m": metrics["return_3m"],
                "expected_return_6m": metrics["return_6m"],
                "expected_return_12m": metrics["return_12m"],
                "volatility": metrics["volatility"],
                "max_drawdown": metrics["max_drawdown"],
                "ma20": metrics["ma20"],
                "ma50": metrics["ma50"],
                "ma200": metrics["ma200"],
                "rotation_backtest": metrics["backtest"],
            }
        )

    rows.sort(key=lambda row: (-float(row.get("rotation_score") or 0.0), int(row.get("priority", 0) or 0), row["symbol"]))
    focus_symbols = [row["symbol"] for row in rows if row.get("rotation_status") == "FOCUS"]
    return {
        "generated_at": now.isoformat(),
        "history_period": history_period,
        "risk_regime": risk_regime,
        "allocation_regime": allocation_name,
        "summary": {
            "enabled_count": len(rows),
            "focus_count": len(focus_symbols),
            "focus_symbols": focus_symbols[:5],
            "top_symbol": rows[0]["symbol"] if rows else None,
        },
        "symbols": rows,
    }


def save_core_etf_rotation_snapshot(snapshot: Mapping, *, path: str = DEFAULT_ROTATION_SNAPSHOT_FILE) -> str:
    return _write_json(path, snapshot)


def load_core_etf_rotation_snapshot(*, path: str = DEFAULT_ROTATION_SNAPSHOT_FILE):
    return _read_json(path)
