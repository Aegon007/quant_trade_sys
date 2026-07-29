from __future__ import annotations

from typing import Mapping


def _float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _primary_horizon(row: Mapping, preferred: int = 252) -> dict:
    horizons = dict(row.get("horizons", {}) or {})
    if str(preferred) in horizons:
        return dict(horizons[str(preferred)] or {})
    if horizons:
        return dict(horizons[sorted(horizons.keys(), key=lambda value: int(value))[-1]] or {})
    return {}


def classify_long_horizon(row: Mapping) -> str:
    horizon = _primary_horizon(row)
    p50 = _float(dict(horizon.get("return_range", {}) or {}).get("p50"), 0.0)
    upside = _float(horizon.get("positive_return_probability"), 0.5)
    beat_rf = _float(horizon.get("risk_free_outperformance_probability"), 0.5)
    if p50 >= 0.12 and upside >= 0.58 and beat_rf >= 0.55:
        return "ATTRACTIVE"
    if p50 >= 0.04 and upside >= 0.52:
        return "NEUTRAL"
    if p50 <= -0.06 or upside < 0.44:
        return "WEAK"
    return "MIXED"


def classify_timing(history_row: Mapping | None = None, *, latest_price=None, average_50=None, average_200=None) -> str:
    price = _float(latest_price, 0.0)
    ma50 = _float(average_50, 0.0)
    ma200 = _float(average_200, 0.0)
    if price > 0 and ma50 > 0 and ma200 > 0:
        if price >= ma50 >= ma200:
            return "CONFIRMED"
        if price >= ma200 and ma50 < ma200:
            return "EARLY"
        if price < ma50 < ma200:
            return "DETERIORATING"
    return "UNKNOWN"


def fuse_foundation_decision(
    *,
    symbol: str,
    asset_type: str,
    forecast_row: Mapping,
    current_weight_pct: float = 0.0,
    market_sentiment: Mapping | None = None,
    systemic_risk: Mapping | None = None,
    risk_regime: str = "NORMAL",
    max_weight_pct: float = 10.0,
) -> dict:
    symbol = str(symbol or "").strip().upper()
    asset_type = str(asset_type or "satellite_stock").strip().lower()
    long_state = classify_long_horizon(forecast_row)
    horizon = _primary_horizon(forecast_row)
    p50 = _float(dict(horizon.get("return_range", {}) or {}).get("p50"), 0.0)
    p10 = _float(dict(horizon.get("return_range", {}) or {}).get("p10"), 0.0)
    upside = _float(horizon.get("positive_return_probability"), 0.5)
    beat_rf = _float(horizon.get("risk_free_outperformance_probability"), 0.5)
    confidence = _float(horizon.get("forecast_confidence"), 0.4)
    current = max(_float(current_weight_pct), 0.0)
    maximum = max(_float(max_weight_pct, 10.0), 0.0)
    sentiment = dict(market_sentiment or {})
    systemic = dict(systemic_risk or {})
    risk = str(risk_regime or "NORMAL").strip().upper()
    risk_appetite = str(sentiment.get("risk_appetite_state") or "NEUTRAL").upper()
    systemic_state = str(systemic.get("ai_capex_stress") or "LOW").upper()
    risk_overrides = []
    reasons = []

    if risk in {"RISK_OFF", "STOP", "BLOCKED"}:
        risk_overrides.append("RISK_GATE_BLOCK")
    if risk_appetite == "RISK_OFF":
        risk_overrides.append("MARKET_SENTIMENT_RISK_OFF")
    if systemic_state in {"STRESS", "CRISIS_WATCH"}:
        risk_overrides.append(f"AI_CAPEX_{systemic_state}")
    elif systemic_state == "CAUTION":
        reasons.append("AI_CAPEX_CAUTION")
    if confidence < 0.35:
        risk_overrides.append("LOW_MODEL_CONFIDENCE")

    is_core = asset_type == "core_etf"
    if is_core:
        base_low = max(min(current, maximum), 0.0)
        base_high = maximum
        if risk_overrides:
            action = "PAUSE_BUY" if current <= maximum else "TRIM"
            target_low = min(current, maximum * 0.75)
            target_high = min(current, maximum)
        elif long_state == "ATTRACTIVE" and beat_rf >= 0.55:
            action = "ACCUMULATE"
            target_low = max(base_low, maximum * 0.75)
            target_high = base_high
            reasons.append("CORE_FORECAST_BEATS_RISK_FREE")
        elif long_state in {"NEUTRAL", "MIXED"}:
            action = "HOLD"
            target_low = base_low
            target_high = min(max(base_low, maximum * 0.7), maximum)
            reasons.append("CORE_PATIENT_HOLD")
        else:
            action = "PAUSE_BUY"
            target_low = min(current, maximum * 0.65)
            target_high = min(current, maximum * 0.8)
            reasons.append("CORE_WEAK_FORECAST")
    else:
        if risk_overrides:
            action = "HOLD" if current > 0 else "AVOID"
            target_low = 0.0 if current <= 0 else min(current, maximum * 0.5)
            target_high = min(current, maximum * 0.8)
        elif long_state == "ATTRACTIVE" and upside >= 0.58 and beat_rf >= 0.55:
            action = "PROBE" if current <= 0 else "ACCUMULATE"
            target_low = max(current, maximum * 0.25)
            target_high = maximum
            reasons.append("SATELLITE_HIGH_UPSIDE")
        elif long_state in {"NEUTRAL", "MIXED"}:
            action = "WATCH" if current <= 0 else "HOLD"
            target_low = min(current, maximum)
            target_high = min(max(current, maximum * 0.25), maximum)
            reasons.append("SATELLITE_NOT_STRONG_ENOUGH")
        else:
            action = "WATCH" if current <= 0 else "TRIM"
            target_low = 0.0
            target_high = min(current, maximum * 0.35)
            reasons.append("SATELLITE_WEAK_FORECAST")

    latest_price = _float(forecast_row.get("latest_price"), 0.0)
    buy_low = latest_price * 0.97 if latest_price > 0 else None
    buy_high = latest_price * 1.01 if latest_price > 0 else None
    invalidation = None
    if latest_price > 0:
        invalidation = (
            f"Signal weakens if price breaks below {latest_price * (1.0 + min(p10, -0.04)):.2f} "
            f"or risk overlay changes to STRESS."
        )

    return {
        "symbol": symbol,
        "action": action,
        "action_strength": "STRONG" if action in {"ACCUMULATE", "TRIM", "AVOID"} and not risk_overrides else "MODERATE",
        "target_weight_range_pct": [round(target_low, 2), round(target_high, 2)],
        "suggested_trade_size_pct": round(max(target_high - current, 0.0), 2),
        "buy_price_range": [round(buy_low, 2), round(buy_high, 2)] if buy_low and buy_high else [],
        "sell_or_trim_price_range": [],
        "invalidation_condition": invalidation,
        "expected_return_range": dict(horizon.get("return_range", {}) or {}),
        "downside_range": {"p10": p10},
        "risk_reward_grade": "A" if p50 > 0.15 and p10 > -0.12 else "B" if p50 > 0.06 else "C" if p50 > 0 else "D",
        "confidence": round(confidence, 3),
        "primary_reason": reasons[0] if reasons else (risk_overrides[0] if risk_overrides else "NO_STRONG_EDGE"),
        "reason_codes": [*reasons, *risk_overrides],
        "risk_overrides": risk_overrides,
    }
