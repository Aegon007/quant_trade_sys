from __future__ import annotations

import math
from typing import Mapping, Optional

import pandas as pd


def _close(history: Optional[pd.DataFrame]) -> pd.Series:
    if not isinstance(history, pd.DataFrame) or history.empty or "Close" not in history:
        return pd.Series(dtype=float)
    values = pd.to_numeric(history["Close"], errors="coerce").dropna()
    return values[values > 0]


def _return(close: pd.Series, days: int) -> float:
    if len(close) < 2:
        return 0.0
    start = float(close.iloc[max(0, len(close) - days - 1)])
    return float(close.iloc[-1] / start - 1.0) if start else 0.0


def _scaled(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return max(0.0, min((float(value) - low) / (high - low) * 100.0, 100.0))


def _mean(close: pd.Series, days: int) -> float:
    return float(close.tail(days).mean()) if len(close) else 0.0


def _rsi(close: pd.Series, days: int = 14) -> float:
    changes = close.diff().dropna().tail(days)
    if changes.empty:
        return 50.0
    gains = float(changes.clip(lower=0).mean())
    losses = abs(float(changes.clip(upper=0).mean()))
    if losses <= 1e-12:
        return 100.0 if gains > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gains / losses)


def analyze_trend(
    history: pd.DataFrame,
    *,
    market_history: Optional[pd.DataFrame] = None,
    sector_history: Optional[pd.DataFrame] = None,
) -> dict:
    """Measure medium-term trend without treating recent gains as a valuation claim."""
    close = _close(history)
    market = _close(market_history)
    sector = _close(sector_history)
    if len(close) < 60:
        return {
            "status": "INSUFFICIENT_DATA",
            "trend_score": 0.0,
            "trend_state": "UNKNOWN",
            "reason_codes": [],
        }

    returns = {days: _return(close, days) for days in (5, 20, 60, 126, 252)}
    market_returns = {days: _return(market, days) for days in (20, 60, 126)}
    sector_returns = {days: _return(sector, days) for days in (20, 60, 126)}
    relatives = {
        days: returns[days] - (market_returns[days] * 0.4 + (sector_returns[days] if not sector.empty else market_returns[days]) * 0.6)
        for days in (20, 60, 126)
    }
    price = float(close.iloc[-1])
    ma20, ma50, ma200 = _mean(close, 20), _mean(close, 50), _mean(close, 200)
    high_52w = float(close.tail(252).max())
    distance_high = price / high_52w - 1.0 if high_52w else 0.0
    extension = price / ma50 - 1.0 if ma50 else 0.0
    structure = 0.0
    structure += 30.0 if price >= ma20 else 0.0
    structure += 30.0 if price >= ma50 else 0.0
    structure += 25.0 if not ma200 or price >= ma200 else 0.0
    structure += 15.0 if not ma200 or ma50 >= ma200 else 0.0
    score = (
        _scaled(relatives[20], -0.08, 0.20) * 0.22
        + _scaled(relatives[60], -0.12, 0.40) * 0.24
        + _scaled(returns[126], -0.18, 0.65) * 0.16
        + structure * 0.23
        + _scaled(distance_high, -0.35, -0.01) * 0.15
    )
    acceleration = returns[20] > 0.06 and returns[20] > max(returns[60] / 3.0, 0.0) and relatives[20] > 0.03
    if acceleration:
        score += 7.0
    score = max(0.0, min(score, 100.0))
    rsi = _rsi(close)
    extended = extension >= 0.16 or rsi >= 80
    if score >= 70 and extended:
        state = "EXTENDED"
    elif acceleration and score >= 62:
        state = "ACCELERATING"
    elif score >= 68:
        state = "TREND_CONFIRMED"
    elif score >= 52:
        state = "EMERGING"
    else:
        state = "WEAK"
    reasons = []
    if relatives[20] >= 0.03 or relatives[60] >= 0.08:
        reasons.append("RELATIVE_STRENGTH")
    if price >= ma50 and (not ma200 or price >= ma200):
        reasons.append("ABOVE_LONG_TERM_TREND")
    if acceleration:
        reasons.append("MOMENTUM_ACCELERATION")
    if distance_high >= -0.08:
        reasons.append("NEAR_52W_HIGH")
    if extended:
        reasons.append("PRICE_EXTENDED")
    daily = close.pct_change().dropna().tail(60)
    volatility = float(daily.std(ddof=0) * math.sqrt(252)) if len(daily) else 0.0
    return {
        "status": "READY",
        "trend_score": round(score, 1),
        "trend_state": state,
        "return_5d": round(returns[5], 4),
        "return_20d": round(returns[20], 4),
        "return_60d": round(returns[60], 4),
        "return_126d": round(returns[126], 4),
        "return_252d": round(returns[252], 4),
        "relative_return_20d": round(relatives[20], 4),
        "relative_return_60d": round(relatives[60], 4),
        "relative_return_126d": round(relatives[126], 4),
        "distance_from_52w_high": round(distance_high, 4),
        "extension_from_ma50": round(extension, 4),
        "ma20": round(ma20, 4),
        "ma50": round(ma50, 4),
        "ma200": round(ma200, 4) if ma200 else None,
        "rsi14": round(rsi, 1),
        "annualized_volatility": round(volatility, 4),
        "reason_codes": reasons,
    }


def score_trend_candidate(trend: Mapping, *, fundamentals: Optional[Mapping] = None, market_risk: Optional[Mapping] = None) -> dict:
    trend = dict(trend or {})
    fundamentals = dict(fundamentals or {})
    market_risk = dict(market_risk or {})
    base = float(trend.get("trend_score") or 0.0)
    quality = float(fundamentals.get("quality_score") or 50.0)
    damage = float(fundamentals.get("damage_score") or 35.0)
    distress = float(fundamentals.get("distress_probability") or 0.15)
    risk = float(market_risk.get("risk_score") or 40.0)
    has_fundamentals = bool(fundamentals) and str(fundamentals.get("status") or "").upper() not in {"MISSING", "ERROR", "STALE"}
    score = max(0.0, min(base * 0.72 + quality * 0.20 + (100.0 - risk) * 0.08 - damage * 0.12 - distress * 18.0, 100.0))
    state = str(trend.get("trend_state") or "UNKNOWN")
    blocking = []
    if trend.get("status") != "READY":
        blocking.append("INSUFFICIENT_PRICE_HISTORY")
    if has_fundamentals and (damage >= 60 or distress >= 0.35):
        blocking.append("FUNDAMENTALS_DAMAGED")
    if risk >= 80:
        blocking.append("MARKET_RISK_EXTREME")
    if blocking:
        recommendation, actionable = "TREND_REJECTED", False
    elif state == "EXTENDED":
        recommendation, actionable = "WAIT_FOR_PULLBACK", False
    elif state in {"ACCELERATING", "TREND_CONFIRMED"} and score >= 64 and has_fundamentals:
        recommendation, actionable = "TREND_CONFIRMED", True
    elif state in {"ACCELERATING", "TREND_CONFIRMED", "EMERGING"}:
        recommendation, actionable = "TREND_WATCH", False
    else:
        recommendation, actionable = "NO_TREND", False
    detail = {
        "TREND_CONFIRMED": "中期趋势与相对强度已确认，基本面过滤未发现硬性阻断",
        "WAIT_FOR_PULLBACK": "趋势强但价格偏离中期均线较远，不把追涨当成买点",
        "TREND_WATCH": "趋势正在形成，等待基本面或价格结构进一步确认",
        "TREND_REJECTED": "趋势信号被数据、基本面或市场风险门槛阻断",
        "NO_TREND": "尚未形成可识别的中期趋势",
    }[recommendation]
    return {
        "signal_score": round(score, 1),
        "recommendation": recommendation,
        "recommendation_detail": detail,
        "actionable": actionable,
        "blocking_reasons": blocking,
        "reason_codes": list(trend.get("reason_codes", []) or []),
        "fundamental_status": "READY" if has_fundamentals else "NOT_ANALYZED",
        "components": {
            "price_trend": round(base, 1),
            "quality": round(quality, 1),
            "damage": round(damage, 1),
            "market_risk": round(risk, 1),
        },
    }
