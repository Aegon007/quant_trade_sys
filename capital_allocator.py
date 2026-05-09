from dataclasses import dataclass
from typing import Mapping, Optional

from share_utils import MIN_SHARE_QUANTITY, normalize_share_quantity


@dataclass(frozen=True)
class AllocationPlan:
    action: str
    symbol: str
    target_weight_pct: float
    recommended_dollars: float
    recommended_shares: float
    max_additional_dollars: float
    cash_buffer_dollars: float
    reason: str


def _float(value, default=0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _profile_value(profile, name: str):
    if profile is None:
        return None
    if isinstance(profile, Mapping):
        return profile.get(name)
    return getattr(profile, name, None)


def _conviction_from_profile(signal_profile=None) -> tuple[float, list[str]]:
    conviction = 0.50
    reasons = []

    probability = _profile_value(signal_profile, "probability")
    expected_return_pct = _profile_value(signal_profile, "expected_return_pct")

    if probability is not None:
        prob = _float(probability)
        reasons.append(f"上涨概率 {prob:.1%}")
        if prob >= 0.70:
            conviction += 0.20
        elif prob >= 0.62:
            conviction += 0.10
        elif prob >= 0.55:
            conviction += 0.05

    if expected_return_pct is not None:
        expected_return = _float(expected_return_pct)
        reasons.append(f"预期收益 {expected_return:.2%}")
        if expected_return >= 0.10:
            conviction += 0.15
        elif expected_return >= 0.05:
            conviction += 0.10
        elif expected_return > 0:
            conviction += 0.05
        else:
            conviction -= 0.15

    return max(0.0, min(conviction, 1.0)), reasons


def recommend_allocation(
    *,
    symbol: str,
    current_price: float,
    signal: str,
    account: Mapping,
    current_shares: float = 0.0,
    current_invested_dollars: Optional[float] = None,
    signal_profile=None,
    risk_gate=None,
    monte_carlo=None,
    sector_crowding_penalty: float = 0.0,
    correlation_penalty: float = 0.0,
) -> AllocationPlan:
    symbol = str(symbol or "").strip().upper()
    signal = str(signal or "").strip().upper()
    total_capital = _float(account.get("total_capital"))
    cash_available_raw = account.get("cash_available")
    cash_available = None if cash_available_raw is None else _float(cash_available_raw)
    min_cash_buffer_pct = max(0.0, min(1.0, _float(account.get("min_cash_buffer_pct"), 0.05)))
    max_single_position_pct = max(0.0, min(1.0, _float(account.get("max_single_position_pct"), 0.20)))
    max_total_exposure_pct = max(0.0, min(1.0, _float(account.get("max_total_exposure_pct"), 1.0)))

    if total_capital <= 0 or current_price is None or _float(current_price) <= 0:
        return AllocationPlan(
            action="HOLD",
            symbol=symbol,
            target_weight_pct=0.0,
            recommended_dollars=0.0,
            recommended_shares=0.0,
            max_additional_dollars=0.0,
            cash_buffer_dollars=0.0,
            reason="缺少账户资金或现价，暂无法计算投入金额。",
        )

    current_price = _float(current_price)
    current_value = normalize_share_quantity(current_shares) * current_price
    cash_buffer_dollars = total_capital * min_cash_buffer_pct
    deployable_cash = max((cash_available if cash_available is not None else 0.0) - cash_buffer_dollars, 0.0)
    invested_dollars = (
        _float(current_invested_dollars)
        if current_invested_dollars is not None
        else max(total_capital - (cash_available if cash_available is not None else 0.0), current_value)
    )

    if signal != "BUY":
        return AllocationPlan(
            action="HOLD",
            symbol=symbol,
            target_weight_pct=0.0,
            recommended_dollars=0.0,
            recommended_shares=0.0,
            max_additional_dollars=0.0,
            cash_buffer_dollars=cash_buffer_dollars,
            reason="当前不是买入信号，暂不新增仓位。",
        )

    if risk_gate is not None and bool(getattr(risk_gate, "block_new_buys", False)):
        return AllocationPlan(
            action="HOLD",
            symbol=symbol,
            target_weight_pct=0.0,
            recommended_dollars=0.0,
            recommended_shares=0.0,
            max_additional_dollars=0.0,
            cash_buffer_dollars=cash_buffer_dollars,
            reason="风险闸门已启用，当前暂停新增仓位。",
        )

    conviction, reason_parts = _conviction_from_profile(signal_profile)
    conviction += 0.20
    conviction -= max(0.0, _float(sector_crowding_penalty)) * 0.15
    conviction -= max(0.0, _float(correlation_penalty)) * 0.15

    if monte_carlo is not None:
        mc_expected = _float(getattr(monte_carlo, "expected_return_pct", None) if not isinstance(monte_carlo, Mapping) else monte_carlo.get("expected_return_pct"))
        mc_cvar = _float(getattr(monte_carlo, "cvar_95", None) if not isinstance(monte_carlo, Mapping) else monte_carlo.get("cvar_95"))
        if mc_expected > 0:
            conviction += 0.05
        if mc_cvar < -0.10:
            conviction -= 0.10

    conviction = max(0.0, min(conviction, 1.0))
    risk_multiplier = 1.0
    if risk_gate is not None:
        regime = str(getattr(risk_gate, "regime", "NORMAL") or "NORMAL").upper()
        if regime == "CAUTION":
            risk_multiplier = 0.60
        gate_max_position_weight = getattr(risk_gate, "max_position_weight", None)
        if gate_max_position_weight is not None:
            max_single_position_pct = min(max_single_position_pct, _float(gate_max_position_weight, max_single_position_pct))
        reasons = list(getattr(risk_gate, "reasons", []) or [])
        if reasons:
            reason_parts.append("风险约束: " + " ".join(reasons))

    target_weight = max_single_position_pct * conviction * risk_multiplier
    max_position_value = total_capital * target_weight
    max_additional_dollars = max(max_position_value - current_value, 0.0)
    exposure_headroom = max(total_capital * max_total_exposure_pct - invested_dollars, 0.0)
    recommended_dollars = min(max_additional_dollars, deployable_cash, exposure_headroom)

    if recommended_dollars <= 0:
        return AllocationPlan(
            action="HOLD",
            symbol=symbol,
            target_weight_pct=target_weight * 100.0,
            recommended_dollars=0.0,
            recommended_shares=0.0,
            max_additional_dollars=max_additional_dollars,
            cash_buffer_dollars=cash_buffer_dollars,
            reason="新增仓位空间不足，可能受现金缓冲或总暴露上限约束。",
        )

    recommended_shares = normalize_share_quantity(recommended_dollars / current_price)
    if recommended_shares < float(MIN_SHARE_QUANTITY):
        recommended_shares = 0.0
        recommended_dollars = 0.0
        action = "HOLD"
    else:
        recommended_dollars = round(recommended_shares * current_price, 4)
        action = "BUY"

    return AllocationPlan(
        action=action,
        symbol=symbol,
        target_weight_pct=round(target_weight * 100.0, 4),
        recommended_dollars=recommended_dollars,
        recommended_shares=recommended_shares,
        max_additional_dollars=round(max_additional_dollars, 4),
        cash_buffer_dollars=round(cash_buffer_dollars, 4),
        reason="；".join(reason_parts) if reason_parts else "基于账户资金、信号强度和风险状态计算建议仓位。",
    )
