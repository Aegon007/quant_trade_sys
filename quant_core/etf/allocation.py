from __future__ import annotations

from typing import Mapping, Optional

import pandas as pd

from quant_core.trend.engine import analyze_trend


def _number(value, default=0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float) -> float:
    return max(0.0, min(float(value), 100.0))


def _last_price(history: Optional[pd.DataFrame]) -> Optional[float]:
    if not isinstance(history, pd.DataFrame) or history.empty or "Close" not in history:
        return None
    values = pd.to_numeric(history["Close"], errors="coerce").dropna()
    return float(values.iloc[-1]) if len(values) else None


def analyze_etf_allocation(
    record: Mapping,
    history: pd.DataFrame,
    *,
    financials: Optional[Mapping] = None,
    market_risk: Optional[Mapping] = None,
    benchmark_history: Optional[pd.DataFrame] = None,
) -> dict:
    record = dict(record or {})
    financials = dict(financials or {})
    market_risk = dict(market_risk or {})
    symbol = str(record.get("symbol") or financials.get("symbol") or "").upper()
    price = _last_price(history)
    if price is None:
        return {"symbol": symbol, "status": "INSUFFICIENT_DATA", "engine": "deterministic_etf_allocation"}
    benchmark = benchmark_history if isinstance(benchmark_history, pd.DataFrame) and not benchmark_history.empty else history
    trend = analyze_trend(history, market_history=benchmark, sector_history=benchmark)
    role = str(record.get("role") or "core").lower()
    current_yield = _number(financials.get("earnings_yield"))
    historical_yield = _number(financials.get("historical_earnings_yield") or record.get("historical_earnings_yield"))
    if current_yield > 0 and historical_yield > 0:
        yield_ratio = current_yield / historical_yield
        valuation_score = _clamp(50.0 + (yield_ratio - 1.0) * 110.0)
        valuation_state = "ATTRACTIVE" if yield_ratio >= 1.12 else "FAIR" if yield_ratio >= 0.92 else "PREMIUM" if yield_ratio >= 0.78 else "EXPENSIVE"
    else:
        yield_ratio = None
        valuation_score = 50.0
        valuation_state = "NOT_APPLICABLE" if role == "commodity" else "LIMITED_DATA"
    risk_score = _number(market_risk.get("risk_score"), 40.0)
    trend_score = _number(trend.get("trend_score"), 35.0)
    if role == "commodity":
        allocation_score = trend_score * 0.55 + min(risk_score + 15.0, 100.0) * 0.30 + valuation_score * 0.15
    else:
        allocation_score = valuation_score * 0.34 + trend_score * 0.43 + (100.0 - risk_score) * 0.23
    allocation_score = _clamp(allocation_score)
    extended = str(trend.get("trend_state")) == "EXTENDED"
    if allocation_score >= 70 and not extended:
        action = "ACCUMULATE_MORE"
    elif allocation_score >= 51 and not extended:
        action = "REGULAR_DCA"
    elif allocation_score >= 38 or extended:
        action = "REDUCE_PACE"
    else:
        action = "PAUSE_LUMP_SUM"
    role_growth = {"broad_market": 0.055, "growth": 0.075, "dividend_quality": 0.045, "commodity": 0.025}.get(role, 0.05)
    starting_yield = current_yield if current_yield > 0 else 0.02
    valuation_drag = 0.0 if yield_ratio is None else max(0.0, 1.0 - yield_ratio) * 0.035
    central_return = max(-0.02, min(starting_yield + role_growth - valuation_drag, 0.18))
    ma50 = _number(trend.get("ma50"), price)
    ma200 = _number(trend.get("ma200"), price)
    pullback_anchor = max(min(ma50, price), ma200 * 0.98 if ma200 else price * 0.92)
    reasons = ["长期定投与一次性加仓分开判断"]
    if valuation_state in {"PREMIUM", "EXPENSIVE"}:
        reasons.append("估值高于长期参考，不停止定投但降低一次性投入速度")
    if str(trend.get("trend_state")) in {"ACCELERATING", "TREND_CONFIRMED"}:
        reasons.append("中期趋势保持正向")
    if extended:
        reasons.append("价格偏离中期均线，等待回撤而非追涨")
    return {
        "symbol": symbol,
        "status": "READY",
        "engine": "deterministic_etf_allocation",
        "role": role,
        "current_price": round(price, 4),
        "action": action,
        "allocation_score": round(allocation_score, 1),
        "valuation_state": valuation_state,
        "valuation_reference": {
            "current_earnings_yield": round(current_yield, 4) if current_yield > 0 else None,
            "historical_earnings_yield": round(historical_yield, 4) if historical_yield > 0 else None,
            "yield_ratio": round(yield_ratio, 3) if yield_ratio is not None else None,
            "score": round(valuation_score, 1),
        },
        "trend": trend,
        "expected_annual_return": {
            "horizon_years": "3-5",
            "low": round(central_return - 0.045, 4),
            "central": round(central_return, 4),
            "high": round(central_return + 0.045, 4),
            "method": "起始收益率、长期增长假设与估值回归的透明组合，不是价格预测",
        },
        "price_zones": {
            "regular_buy": [round(price * 0.985, 2), round(price * 1.015, 2)],
            "add_on_pullback": [round(pullback_anchor * 0.97, 2), round(pullback_anchor * 1.01, 2)],
            "avoid_lump_sum_above": round(max(price, ma50) * 1.08, 2),
        },
        "market_risk_score": round(risk_score, 1),
        "reasoning": reasons,
    }
