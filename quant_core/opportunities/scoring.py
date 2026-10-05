from __future__ import annotations

from typing import Mapping


def _value(payload: Mapping, key: str, default=0.0) -> float:
    try:
        value = dict(payload or {}).get(key, default)
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, low=0.0, high=100.0) -> float:
    return max(low, min(float(value), high))


def score_opportunity(
    *,
    dislocation: Mapping,
    valuation: Mapping,
    fundamentals: Mapping,
    event: Mapping,
    market_risk: Mapping,
    policy: Mapping | None = None,
) -> dict:
    policy = dict(policy or {})
    valuation_usable = dict(valuation or {}).get("valuation_usable") is not False
    margin = _value(valuation, "margin_of_safety") if valuation_usable else 0.0
    confidence = _value(valuation, "confidence")
    dispersion = _value(valuation, "dispersion", 1.0)
    quality = _value(fundamentals, "quality_score", 50)
    damage = _value(fundamentals, "damage_score", 50)
    distress = _value(fundamentals, "distress_probability", 0.25)
    transience = _value(event, "transience_probability", 0.4)
    catalyst = _value(event, "catalyst_score", 30)
    dislocation_score = _value(dislocation, "dislocation_score")
    stabilization = _value(dislocation, "stabilization_score")
    risk = _value(market_risk, "risk_score", 40)
    minimum_margin = _value(policy, "minimum_margin_of_safety", 0.15)
    strong_margin = _value(policy, "strong_margin_of_safety", 0.25)
    minimum_confidence = _value(policy, "minimum_valuation_confidence", 0.45)
    maximum_damage = _value(policy, "maximum_damage_score", 60)
    maximum_distress = _value(policy, "maximum_distress_probability", 0.35)
    maximum_dispersion = _value(policy, "maximum_valuation_dispersion", 0.8)
    risk_margin = minimum_margin + max(risk - 50, 0) / 500
    margin_score = _clamp(margin / 0.5 * 100) if valuation_usable else 0.0
    gross = (
        dislocation_score * 0.22
        + margin_score * 0.28
        + quality * 0.15
        + transience * 100 * 0.12
        + catalyst * 0.07
        + stabilization * 0.08
        + confidence * 100 * 0.08
    )
    penalty = damage * 0.10 + distress * 100 * 0.15 + risk * 0.06 + min(dispersion, 2.0) * 8
    score = round(_clamp(gross - penalty), 1)
    reasons = []
    if valuation_usable and margin >= 0.2:
        reasons.append("VALUATION_MARGIN")
    if dislocation_score >= 60:
        reasons.append("ABNORMAL_SELLOFF")
    if transience >= 0.65:
        reasons.append("EVENT_LIKELY_TEMPORARY")
    if stabilization >= 55:
        reasons.append("PRICE_STABILIZING")
    blocking_reasons = []
    if not valuation_usable:
        blocking_reasons.append("UNUSABLE_VALUATION")
    if confidence < minimum_confidence:
        blocking_reasons.append("LOW_VALUATION_CONFIDENCE")
    if dispersion > maximum_dispersion:
        blocking_reasons.append("HIGH_VALUATION_DISPERSION")
    if blocking_reasons:
        recommendation, actionable = "INSUFFICIENT_DATA", False
    elif damage >= maximum_damage or distress >= maximum_distress:
        recommendation, actionable = "FUNDAMENTALS_DAMAGED", False
    elif margin >= risk_margin and (damage >= maximum_damage * 0.67 or transience < 0.35):
        recommendation, actionable = "VALUE_TRAP_RISK", False
    elif margin <= -0.15:
        recommendation, actionable = "OVERVALUED", False
    elif dislocation_score < 40:
        recommendation, actionable = "FAIR_VALUE_NOT_OVERSOLD", False
    elif stabilization < 40:
        recommendation, actionable = "WAIT_FOR_STABILIZATION", False
    elif score >= 78 and margin >= max(strong_margin, risk_margin):
        recommendation, actionable = "STRONG_OPPORTUNITY", True
    elif score >= 65 and margin >= risk_margin:
        recommendation, actionable = "ACCUMULATE", True
    else:
        recommendation, actionable = "WATCH", False
    if "UNUSABLE_VALUATION" in blocking_reasons:
        warnings = set(str(item) for item in list(dict(valuation or {}).get("validation_warnings", []) or []))
        recommendation_detail = "财报数据已过期，暂不计算合理价值" if "stale_financial_period" in warnings else "估值关键输入缺失，暂不计算合理价值"
    elif blocking_reasons:
        details = []
        if "LOW_VALUATION_CONFIDENCE" in blocking_reasons:
            details.append(f"估值置信度 {confidence:.1%}，低于 {minimum_confidence:.1%} 门槛")
        if "HIGH_VALUATION_DISPERSION" in blocking_reasons:
            details.append(f"估值区间离散度 {dispersion:.2f}，高于 {maximum_dispersion:.2f} 上限")
        recommendation_detail = "；".join(details)
    else:
        recommendation_detail = ""
    return {
        "opportunity_score": score,
        "recommendation": recommendation,
        "actionable": actionable,
        "recommendation_detail": recommendation_detail,
        "blocking_reasons": blocking_reasons,
        "reason_codes": reasons,
        "components": {
            "dislocation": round(dislocation_score, 1),
            "valuation_margin": round(margin_score, 1),
            "quality": round(quality, 1),
            "event_transience": round(transience * 100, 1),
            "catalyst": round(catalyst, 1),
            "stabilization": round(stabilization, 1),
            "valuation_confidence": round(confidence * 100, 1),
            "penalty": round(penalty, 1),
            "required_margin_of_safety": round(risk_margin, 3),
        },
    }
