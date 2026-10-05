from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd


def _close(history: Optional[pd.DataFrame]) -> pd.Series:
    if not isinstance(history, pd.DataFrame) or history.empty or "Close" not in history:
        return pd.Series(dtype=float)
    values = pd.to_numeric(history["Close"], errors="coerce").dropna()
    return values[values > 0]


def _ret(close: pd.Series, days: int) -> float:
    if len(close) < 2:
        return 0.0
    start = close.iloc[max(0, len(close) - days - 1)]
    return float(close.iloc[-1] / start - 1.0) if start else 0.0


def _drawdown(close: pd.Series, days: int) -> float:
    if close.empty:
        return 0.0
    window = close.tail(days)
    peak = float(window.max())
    return float(window.iloc[-1] / peak - 1.0) if peak else 0.0


def _clip(value: float, low=0.0, high=100.0) -> float:
    return max(low, min(float(value), high))


def measure_dislocation(
    history: pd.DataFrame,
    *,
    market_history: Optional[pd.DataFrame] = None,
    sector_history: Optional[pd.DataFrame] = None,
) -> dict:
    close = _close(history)
    market = _close(market_history)
    sector = _close(sector_history)
    if len(close) < 20:
        return {
            "status": "INSUFFICIENT_DATA",
            "return_20d": 0.0,
            "return_60d": 0.0,
            "drawdown_52w": 0.0,
            "abnormal_return_20d": 0.0,
            "dislocation_score": 0.0,
            "stabilization_score": 0.0,
        }
    return_20 = _ret(close, 20)
    return_60 = _ret(close, 60)
    market_20 = _ret(market, 20)
    sector_20 = _ret(sector, 20) if not sector.empty else market_20
    expected_20 = market_20 * 0.4 + sector_20 * 0.6
    abnormal = return_20 - expected_20
    drawdown = _drawdown(close, 252)
    returns = close.pct_change().dropna()
    volatility = float(returns.tail(60).std(ddof=0) * math.sqrt(252)) if len(returns) else 0.0
    downside_z = abs(min(abnormal, 0.0)) / max(float(returns.tail(60).std(ddof=0)) * math.sqrt(20), 0.025)
    score = _clip(abs(min(drawdown, 0.0)) * 155 + abs(min(abnormal, 0.0)) * 240 + min(downside_z, 4.0) * 9)
    recent_return = _ret(close, 5)
    recent_low = float(close.tail(10).min())
    rebound = float(close.iloc[-1] / recent_low - 1.0) if recent_low else 0.0
    prior_vol = float(returns.tail(30).head(20).std(ddof=0)) if len(returns) >= 20 else 0.0
    recent_vol = float(returns.tail(5).std(ddof=0)) if len(returns) >= 5 else prior_vol
    stabilization = 35 + _clip(rebound * 300, 0, 30) + _clip(recent_return * 180, -15, 20)
    if prior_vol and recent_vol < prior_vol:
        stabilization += 12
    return {
        "status": "READY",
        "return_5d": round(recent_return, 4),
        "return_20d": round(return_20, 4),
        "return_60d": round(return_60, 4),
        "market_return_20d": round(market_20, 4),
        "sector_return_20d": round(sector_20, 4),
        "drawdown_52w": round(drawdown, 4),
        "abnormal_return_20d": round(abnormal, 4),
        "annualized_volatility": round(volatility, 4),
        "downside_zscore": round(downside_z, 3),
        "dislocation_score": round(score, 1),
        "stabilization_score": round(_clip(stabilization), 1),
    }
