from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd


@dataclass(frozen=True)
class MarketRiskSnapshot:
    vix: Optional[float] = None
    benchmark_drawdown: Optional[float] = None
    benchmark_volatility: Optional[float] = None
    sector_alert_count: int = 0
    correlation_alert_count: int = 0


@dataclass(frozen=True)
class MarketRiskGateDecision:
    regime: str
    risk_score: int
    block_new_buys: bool
    max_position_weight: float
    reasons: List[str] = field(default_factory=list)


_REGIME_RANK = {"NORMAL": 0, "CAUTION": 1, "RISK_OFF": 2}


def merge_risk_gate_decisions(
    base_decision: Optional[MarketRiskGateDecision],
    override_decision: Optional[MarketRiskGateDecision],
) -> Optional[MarketRiskGateDecision]:
    if base_decision is None:
        return override_decision
    if override_decision is None:
        return base_decision

    base_regime = str(base_decision.regime or "NORMAL").upper()
    override_regime = str(override_decision.regime or "NORMAL").upper()
    merged_regime = (
        base_regime
        if _REGIME_RANK.get(base_regime, 0) >= _REGIME_RANK.get(override_regime, 0)
        else override_regime
    )
    merged_reasons = []
    for reason in list(base_decision.reasons) + list(override_decision.reasons):
        if reason and reason not in merged_reasons:
            merged_reasons.append(reason)

    return MarketRiskGateDecision(
        regime=merged_regime,
        risk_score=max(int(base_decision.risk_score), int(override_decision.risk_score)),
        block_new_buys=bool(base_decision.block_new_buys or override_decision.block_new_buys),
        max_position_weight=min(
            float(base_decision.max_position_weight),
            float(override_decision.max_position_weight),
        ),
        reasons=merged_reasons,
    )


def _latest_close(history: Optional[pd.DataFrame]) -> Optional[float]:
    if history is None or history.empty or "Close" not in history.columns:
        return None
    close = history["Close"].dropna()
    if close.empty:
        return None
    return float(close.iloc[-1])


def _latest_drawdown_from_history(history: Optional[pd.DataFrame]) -> Optional[float]:
    if history is None or history.empty or "Close" not in history.columns:
        return None
    close = history["Close"].dropna()
    if len(close) < 2:
        return None
    running_peak = close.cummax()
    peak = float(running_peak.iloc[-1])
    if peak <= 0:
        return None
    return float(close.iloc[-1]) / peak - 1.0


def _annualized_volatility_from_history(history: Optional[pd.DataFrame]) -> Optional[float]:
    if history is None or history.empty or "Close" not in history.columns:
        return None
    close = history["Close"].dropna()
    returns = close.pct_change().dropna()
    if returns.empty:
        return None
    return float(returns.std()) * (252 ** 0.5)


def build_market_risk_snapshot_from_histories(
    benchmark_history: Optional[pd.DataFrame],
    vix_history: Optional[pd.DataFrame],
    sector_alert_count: int = 0,
    correlation_alert_count: int = 0,
) -> MarketRiskSnapshot:
    return MarketRiskSnapshot(
        vix=_latest_close(vix_history),
        benchmark_drawdown=_latest_drawdown_from_history(benchmark_history),
        benchmark_volatility=_annualized_volatility_from_history(benchmark_history),
        sector_alert_count=int(sector_alert_count or 0),
        correlation_alert_count=int(correlation_alert_count or 0),
    )


def evaluate_market_risk_gate(
    snapshot: MarketRiskSnapshot,
    *,
    caution_vix: float = 22.0,
    danger_vix: float = 30.0,
    caution_drawdown: float = -0.08,
    danger_drawdown: float = -0.12,
    caution_volatility: float = 0.28,
    danger_volatility: float = 0.40,
) -> MarketRiskGateDecision:
    score = 0
    reasons: List[str] = []

    if snapshot.vix is not None:
        if snapshot.vix >= danger_vix:
            score += 3
            reasons.append(f"VIX {snapshot.vix:.1f} 偏高，市场恐慌显著。")
        elif snapshot.vix >= caution_vix:
            score += 1
            reasons.append(f"VIX {snapshot.vix:.1f} 偏高，波动进入警戒区。")

    if snapshot.benchmark_drawdown is not None:
        if snapshot.benchmark_drawdown <= danger_drawdown:
            score += 2
            reasons.append(f"基准回撤 {snapshot.benchmark_drawdown:.1%}，趋势明显走弱。")
        elif snapshot.benchmark_drawdown <= caution_drawdown:
            score += 1
            reasons.append(f"基准回撤 {snapshot.benchmark_drawdown:.1%}，需要降低节奏。")

    if snapshot.benchmark_volatility is not None:
        if snapshot.benchmark_volatility >= danger_volatility:
            score += 2
            reasons.append(f"基准波动率 {snapshot.benchmark_volatility:.1%}，波动过高。")
        elif snapshot.benchmark_volatility >= caution_volatility:
            score += 1
            reasons.append(f"基准波动率 {snapshot.benchmark_volatility:.1%}，波动升温。")

    if snapshot.sector_alert_count > 0:
        score += 1
        reasons.append("组合行业集中度偏高。")

    if snapshot.correlation_alert_count >= 2:
        score += 1
        reasons.append("组合相关性拥挤，分散度不足。")

    if score >= 5:
        return MarketRiskGateDecision(
            regime="RISK_OFF",
            risk_score=score,
            block_new_buys=True,
            max_position_weight=0.08,
            reasons=reasons or ["风险因子显著偏高，建议风险收缩。"],
        )
    if score >= 2:
        return MarketRiskGateDecision(
            regime="CAUTION",
            risk_score=score,
            block_new_buys=False,
            max_position_weight=0.12,
            reasons=reasons or ["风险因子偏高，建议谨慎加仓。"],
        )
    return MarketRiskGateDecision(
        regime="NORMAL",
        risk_score=score,
        block_new_buys=False,
        max_position_weight=0.20,
        reasons=reasons or ["风险状态正常。"],
    )
