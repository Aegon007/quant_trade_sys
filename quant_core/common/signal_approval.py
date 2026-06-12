from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovedSignal:
    raw_signal: str
    approved_signal: str
    blocked: bool
    reason: str = ""


def _normalize_signal(signal) -> str:
    normalized = str(signal or "").strip().upper()
    if normalized not in {"BUY", "SELL", "HOLD", "STRONG_BUY", "STRONG_SELL"}:
        return "HOLD"
    return normalized


def normalize_signal_direction(signal) -> str:
    normalized = _normalize_signal(signal)
    if normalized in {"BUY", "STRONG_BUY"}:
        return "BUY"
    if normalized in {"SELL", "STRONG_SELL"}:
        return "SELL"
    return "HOLD"


def approve_signal(signal, *, risk_gate=None) -> ApprovedSignal:
    raw_signal = _normalize_signal(signal)
    signal_direction = normalize_signal_direction(raw_signal)
    approved_signal = raw_signal
    blocked = False
    reason_parts = []

    gate_block_buys = bool(getattr(risk_gate, "block_new_buys", False)) if risk_gate is not None else False
    gate_reasons = list(getattr(risk_gate, "reasons", []) or []) if risk_gate is not None else []

    if signal_direction == "BUY" and gate_block_buys:
        approved_signal = "HOLD"
        blocked = True
        reason_parts.append("风险闸门已启用，买入信号被拦截。")
        if gate_reasons:
            reason_parts.append("风险因子：" + " ".join(gate_reasons))

    return ApprovedSignal(
        raw_signal=raw_signal,
        approved_signal=approved_signal,
        blocked=blocked,
        reason=" ".join(reason_parts).strip(),
    )
