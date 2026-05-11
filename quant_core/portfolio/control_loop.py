from dataclasses import dataclass, field
from typing import List, Mapping, Optional


@dataclass(frozen=True)
class AllocationRegimeDecision:
    regime: str
    risk_multiplier: float
    block_new_buys: bool
    target_exposure_min_pct: float
    target_exposure_max_pct: float
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "risk_multiplier": float(self.risk_multiplier),
            "block_new_buys": bool(self.block_new_buys),
            "target_exposure_min_pct": float(self.target_exposure_min_pct),
            "target_exposure_max_pct": float(self.target_exposure_max_pct),
            "reasons": list(self.reasons or []),
        }


def _metric(scoreboard, name: str):
    if scoreboard is None:
        return None
    if isinstance(scoreboard, Mapping):
        return scoreboard.get(name)
    return getattr(scoreboard, name, None)


def _float(value, default=0.0):
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def evaluate_allocation_regime(
    scoreboard,
    *,
    risk_gate=None,
    account_snapshot: Optional[Mapping] = None,
    min_sample_trades: int = 6,
) -> AllocationRegimeDecision:
    reasons: List[str] = []
    account_snapshot = account_snapshot or {}
    exposure_pct = _float(account_snapshot.get("exposure_pct"), 0.0)
    deployable_cash = _float(account_snapshot.get("deployable_cash"), 0.0)

    gate_regime = str(getattr(risk_gate, "regime", "NORMAL") or "NORMAL").upper() if risk_gate is not None else "NORMAL"
    gate_block_buys = bool(getattr(risk_gate, "block_new_buys", False)) if risk_gate is not None else False
    gate_reasons = list(getattr(risk_gate, "reasons", []) or []) if risk_gate is not None else []

    if gate_regime == "RISK_OFF" or gate_block_buys:
        reasons.append("风险闸门处于风险收缩状态，新增仓位暂停。")
        if gate_reasons:
            reasons.append(" ".join(gate_reasons))
        return AllocationRegimeDecision(
            regime="STOP",
            risk_multiplier=0.0,
            block_new_buys=True,
            target_exposure_min_pct=10.0,
            target_exposure_max_pct=40.0,
            reasons=reasons,
        )

    completed_trades = int(_float(_metric(scoreboard, "completed_trades"), 0))
    win_rate = _metric(scoreboard, "win_rate")
    expectancy = _metric(scoreboard, "expectancy_return_pct")
    profit_factor = _metric(scoreboard, "profit_factor")
    max_drawdown = _metric(scoreboard, "max_drawdown_pct")

    quality_score = 0
    if completed_trades >= int(min_sample_trades):
        quality_score += 1
    else:
        reasons.append(f"闭环样本不足（仅 {completed_trades} 笔已完成交易）。")

    if expectancy is not None and float(expectancy) > 0:
        quality_score += 1
    elif expectancy is not None:
        quality_score -= 1
        reasons.append(f"单笔期望收益 {float(expectancy):.2%} 偏弱。")

    if profit_factor is not None:
        if float(profit_factor) >= 1.2:
            quality_score += 1
        elif float(profit_factor) < 1.0:
            quality_score -= 1
            reasons.append(f"利润因子 {float(profit_factor):.2f} 低于 1。")

    if win_rate is not None:
        if float(win_rate) >= 0.55:
            quality_score += 1
        elif float(win_rate) < 0.45:
            quality_score -= 1
            reasons.append(f"胜率 {float(win_rate):.1%} 偏低。")

    if max_drawdown is not None and float(max_drawdown) <= -0.15:
        quality_score -= 1
        reasons.append(f"回撤 {float(max_drawdown):.1%} 偏大。")

    if gate_regime == "CAUTION":
        quality_score -= 1
        reasons.append("市场风险处于警戒区，降低杠杆节奏。")

    if quality_score >= 3 and deployable_cash > 0:
        regime = "HEAVY"
        multiplier = 1.2
        min_exp, max_exp = 55.0, 95.0
    elif quality_score <= 0:
        regime = "LIGHT"
        multiplier = 0.5
        min_exp, max_exp = 20.0, 65.0
    else:
        regime = "NORMAL"
        multiplier = 1.0
        min_exp, max_exp = 40.0, 85.0

    if deployable_cash <= 0 and regime == "HEAVY":
        regime = "NORMAL"
        multiplier = 1.0
        reasons.append("可部署现金不足，重仓建议降级为正常仓位。")

    if exposure_pct >= max_exp and regime in {"HEAVY", "NORMAL"}:
        regime = "LIGHT"
        multiplier = min(multiplier, 0.6)
        reasons.append(f"当前暴露 {exposure_pct:.1f}% 已接近上限，转为轻仓节奏。")

    if not reasons:
        reasons.append("风险与历史表现匹配，维持当前仓位节奏。")

    return AllocationRegimeDecision(
        regime=regime,
        risk_multiplier=multiplier,
        block_new_buys=False,
        target_exposure_min_pct=min_exp,
        target_exposure_max_pct=max_exp,
        reasons=reasons,
    )

