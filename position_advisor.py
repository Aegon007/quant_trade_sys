from dataclasses import dataclass
from statistics import mean, median
from typing import Iterable, Mapping, Optional

import pandas as pd

from share_utils import MIN_SHARE_QUANTITY, normalize_share_quantity


@dataclass(frozen=True)
class BacktestGuidance:
    completed_trades: int
    expected_return_pct: Optional[float] = None
    expected_holding_days: Optional[int] = None
    suggested_exit_price: Optional[float] = None
    median_win_return_pct: Optional[float] = None
    win_rate: Optional[float] = None


@dataclass(frozen=True)
class PositionAdvice:
    action: str
    current_weight_pct: float
    target_weight_pct: float
    target_shares: Optional[float]
    delta_shares: Optional[float]
    expected_return_pct: Optional[float]
    expected_holding_days: Optional[int]
    suggested_exit_price: Optional[float]
    reason: str


def _trade_shares(trade: Mapping) -> float:
    value = trade.get("shares", trade.get("size", 0.0))
    return abs(float(value))


def _holding_days(entry_trade: Mapping, exit_trade: Mapping) -> Optional[int]:
    if "bar_index" in entry_trade and "bar_index" in exit_trade:
        return max(int(exit_trade["bar_index"]) - int(entry_trade["bar_index"]), 1)

    if "date" not in entry_trade or "date" not in exit_trade:
        return None

    entry_date = pd.Timestamp(entry_trade["date"])
    exit_date = pd.Timestamp(exit_trade["date"])
    return max((exit_date - entry_date).days, 1)


def summarize_backtest_guidance(trade_log: Iterable[Mapping], current_price: Optional[float] = None) -> BacktestGuidance:
    completed_trades = []
    entry_trade = None

    for trade in trade_log:
        action = str(trade.get("action", "")).upper()
        if action == "BUY":
            entry_trade = trade
        elif action == "SELL" and entry_trade is not None:
            entry_price = float(entry_trade["price"])
            exit_price = float(trade["price"])
            trade_return_pct = exit_price / entry_price - 1.0
            completed_trades.append(
                {
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "return_pct": trade_return_pct,
                    "holding_days": _holding_days(entry_trade, trade),
                    "shares": min(_trade_shares(entry_trade), _trade_shares(trade)),
                }
            )
            entry_trade = None

    if not completed_trades:
        return BacktestGuidance(completed_trades=0)

    returns = [trade["return_pct"] for trade in completed_trades]
    win_returns = [value for value in returns if value > 0]
    holding_days = [trade["holding_days"] for trade in completed_trades if trade["holding_days"] is not None]

    expected_return_pct = mean(returns)
    median_win_return_pct = median(win_returns) if win_returns else None
    expected_holding_days = round(mean(holding_days)) if holding_days else None
    win_rate = len(win_returns) / len(returns) if returns else None

    suggested_exit_price = None
    if current_price is not None and median_win_return_pct is not None:
        suggested_exit_price = float(current_price) * (1.0 + median_win_return_pct)

    return BacktestGuidance(
        completed_trades=len(completed_trades),
        expected_return_pct=expected_return_pct,
        expected_holding_days=expected_holding_days,
        suggested_exit_price=suggested_exit_price,
        median_win_return_pct=median_win_return_pct,
        win_rate=win_rate,
    )


def _buy_target_weight(expected_return_pct: Optional[float], max_position_weight: float) -> float:
    if expected_return_pct is None:
        return min(0.10, max_position_weight)
    if expected_return_pct >= 0.15:
        return min(0.20, max_position_weight)
    if expected_return_pct >= 0.08:
        return min(0.15, max_position_weight)
    if expected_return_pct > 0:
        return min(0.10, max_position_weight)
    return min(0.05, max_position_weight)


def recommend_position_action(
    holding: Mapping,
    portfolio_value: float,
    signal: str,
    signal_reason: str,
    guidance: Optional[BacktestGuidance] = None,
    max_position_weight: float = 0.20,
    min_position_weight: float = 0.05,
) -> PositionAdvice:
    current_price = holding.get("current_price")
    current_shares = float(holding.get("shares", 0.0))

    if current_price is None or current_price <= 0 or portfolio_value <= 0:
        return PositionAdvice(
            action="HOLD",
            current_weight_pct=0.0,
            target_weight_pct=0.0,
            target_shares=None,
            delta_shares=None,
            expected_return_pct=getattr(guidance, "expected_return_pct", None),
            expected_holding_days=getattr(guidance, "expected_holding_days", None),
            suggested_exit_price=getattr(guidance, "suggested_exit_price", None),
            reason="缺少现价或组合市值，暂无法计算仓位建议。",
        )

    current_value = current_shares * float(current_price)
    current_weight = current_value / float(portfolio_value)
    expected_return_pct = getattr(guidance, "expected_return_pct", None)

    signal = str(signal).upper()
    if signal == "SELL":
        target_weight = 0.0
    elif signal == "BUY":
        target_weight = _buy_target_weight(expected_return_pct, max_position_weight)
    else:
        if current_weight > max_position_weight:
            target_weight = max_position_weight
        elif expected_return_pct is not None and expected_return_pct < 0 and current_weight > min_position_weight:
            target_weight = min_position_weight
        else:
            target_weight = current_weight

    target_shares = 0.0 if target_weight == 0 else normalize_share_quantity(target_weight * float(portfolio_value) / float(current_price))
    delta_shares = normalize_share_quantity(target_shares - current_shares)

    if abs(delta_shares) < float(MIN_SHARE_QUANTITY):
        delta_shares = 0.0

    if signal == "SELL" and current_shares > 0:
        action = "EXIT"
    elif delta_shares > 0:
        action = "ADD"
    elif delta_shares < 0:
        action = "TRIM" if target_weight > 0 else "EXIT"
    else:
        action = "HOLD"

    target_weight_pct = target_weight * 100.0
    current_weight_pct = current_weight * 100.0

    reason_parts = [signal_reason]
    if action == "ADD":
        reason_parts.append(f"当前仓位 {current_weight_pct:.1f}%，建议提升至 {target_weight_pct:.1f}%。")
    elif action == "TRIM":
        reason_parts.append(f"当前仓位 {current_weight_pct:.1f}% 偏高，建议降至 {target_weight_pct:.1f}%。")
    elif action == "EXIT":
        reason_parts.append("当前信号偏空，建议逐步退出该仓位。")
    else:
        reason_parts.append(f"当前仓位 {current_weight_pct:.1f}% 与信号匹配，可继续持有。")

    if expected_return_pct is not None:
        reason_parts.append(f"回测单笔期望收益约 {expected_return_pct:.2%}。")

    return PositionAdvice(
        action=action,
        current_weight_pct=current_weight_pct,
        target_weight_pct=target_weight_pct,
        target_shares=target_shares,
        delta_shares=delta_shares,
        expected_return_pct=expected_return_pct,
        expected_holding_days=getattr(guidance, "expected_holding_days", None),
        suggested_exit_price=getattr(guidance, "suggested_exit_price", None),
        reason=" ".join(reason_parts),
    )

