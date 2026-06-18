from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FusedDecision:
    symbol: str
    action: str
    target_weight_low_pct: float
    target_weight_high_pct: float
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "target_weight_range_pct": [
                float(self.target_weight_low_pct),
                float(self.target_weight_high_pct),
            ],
            "reason_codes": list(self.reason_codes),
        }


def fuse_multi_horizon_decision(
    *,
    symbol: str,
    long_horizon_state: str,
    timing_state: str,
    current_weight_pct: float,
    risk_regime: str = "NORMAL",
    max_weight_pct: float = 10.0,
) -> FusedDecision:
    symbol = str(symbol or "").strip().upper()
    long_state = str(long_horizon_state or "UNKNOWN").strip().upper()
    timing = str(timing_state or "UNKNOWN").strip().upper()
    risk = str(risk_regime or "NORMAL").strip().upper()
    current = max(float(current_weight_pct or 0.0), 0.0)
    maximum = max(float(max_weight_pct or 0.0), 0.0)
    reasons = []

    if risk in {"RISK_OFF", "STOP", "BLOCKED"}:
        reasons.append("RISK_GATE_BLOCK")
        if current > maximum and maximum > 0:
            return FusedDecision(symbol, "TRIM", maximum * 0.75, maximum, tuple(reasons))
        return FusedDecision(symbol, "HOLD", min(current, maximum), min(current, maximum), tuple(reasons))

    if long_state in {"ATTRACTIVE", "STRONG"}:
        reasons.append("LONG_TERM_ATTRACTIVE")
        if timing in {"BUY_NOW", "CONFIRMED", "EARLY"}:
            reasons.append("TIMING_CONFIRMED")
            low = max(current, maximum * 0.5)
            return FusedDecision(symbol, "ACCUMULATE", min(low, maximum), maximum, tuple(reasons))
        reasons.append("WAIT_TO_ADD")
        low = min(current, maximum)
        high = max(low, maximum * 0.7)
        return FusedDecision(symbol, "HOLD", low, min(high, maximum), tuple(reasons))

    if long_state in {"NEUTRAL", "MIXED"}:
        reasons.append("LONG_TERM_NEUTRAL")
        if timing in {"BUY_NOW", "CONFIRMED"}:
            reasons.append("TIMING_CONFIRMED")
            return FusedDecision(symbol, "PROBE", current, min(max(current, maximum * 0.25), maximum), tuple(reasons))
        return FusedDecision(symbol, "HOLD", current, current, tuple(reasons))

    reasons.append("LONG_TERM_WEAK")
    if timing in {"BUY_NOW", "CONFIRMED"}:
        reasons.append("TACTICAL_ONLY")
        return FusedDecision(symbol, "WATCH_TACTICAL", 0.0, min(maximum * 0.15, 2.0), tuple(reasons))
    if current > 0:
        reasons.append("THESIS_DETERIORATED")
        return FusedDecision(symbol, "TRIM", 0.0, min(current, maximum * 0.25), tuple(reasons))
    return FusedDecision(symbol, "WATCH", 0.0, 0.0, tuple(reasons))
