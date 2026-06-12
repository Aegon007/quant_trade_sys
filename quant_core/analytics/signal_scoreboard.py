from dataclasses import dataclass, field
from statistics import mean, median
from typing import Iterable, List, Mapping, Optional

import pandas as pd


@dataclass(frozen=True)
class RegimeStats:
    regime: str
    trades: int
    win_rate: Optional[float]
    avg_return_pct: Optional[float]


@dataclass(frozen=True)
class SignalScoreboard:
    completed_trades: int
    win_rate: Optional[float]
    avg_return_pct: Optional[float]
    avg_win_return_pct: Optional[float]
    avg_loss_return_pct: Optional[float]
    payoff_ratio: Optional[float]
    expectancy_return_pct: Optional[float]
    profit_factor: Optional[float]
    median_holding_days: Optional[float]
    cumulative_return_pct: Optional[float]
    max_drawdown_pct: Optional[float]
    regime_breakdown: List[RegimeStats] = field(default_factory=list)


def _shares(trade: Mapping) -> float:
    value = trade.get("shares", trade.get("size", 0.0))
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return 0.0


def _trade_action(trade: Mapping) -> str:
    action = str(trade.get("action", "")).strip().upper()
    if action in {"BUY", "SELL"}:
        return action

    side = str(trade.get("side", "")).strip().upper()
    if side in {"BUY", "SELL"}:
        return side

    event_type = str(trade.get("event_type", "")).strip().upper()
    if event_type in {"BUY", "SELL"}:
        return event_type
    if event_type == "SELL_ALL":
        return "SELL"
    return ""


def _trade_price(trade: Mapping) -> Optional[float]:
    value = trade.get("price")
    if value is None:
        value = trade.get("sell_price")
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _trade_date(trade: Mapping):
    value = trade.get("date")
    if value is None:
        return None
    try:
        return pd.Timestamp(value)
    except Exception:
        return None


def _holding_days(entry_trade: Mapping, exit_trade: Mapping) -> Optional[int]:
    if "bar_index" in entry_trade and "bar_index" in exit_trade:
        try:
            return max(int(exit_trade["bar_index"]) - int(entry_trade["bar_index"]), 1)
        except Exception:
            return None

    entry_date = _trade_date(entry_trade)
    exit_date = _trade_date(exit_trade)
    if entry_date is None or exit_date is None:
        return None
    return max((exit_date - entry_date).days, 1)


def _pair_round_trips(trade_log: Iterable[Mapping]) -> list:
    entry_trade = None
    pairs = []

    for trade in trade_log or []:
        record_type = str(trade.get("record_type", "TRADE")).strip().upper()
        if record_type not in {"", "TRADE"}:
            continue

        action = _trade_action(trade)
        if action == "BUY":
            entry_trade = trade
            continue
        if action != "SELL" or entry_trade is None:
            continue

        entry_price = _trade_price(entry_trade)
        exit_price = _trade_price(trade)
        if entry_price is None or exit_price is None:
            entry_trade = None
            continue
        if entry_price <= 0:
            entry_trade = None
            continue

        pairs.append(
            {
                "entry_date": _trade_date(entry_trade),
                "exit_date": _trade_date(trade),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "return_pct": exit_price / entry_price - 1.0,
                "holding_days": _holding_days(entry_trade, trade),
                "shares": min(_shares(entry_trade), _shares(trade)),
            }
        )
        entry_trade = None

    return pairs


def _equity_stats(equity_curve) -> tuple[Optional[float], Optional[float]]:
    if equity_curve is None:
        return None, None
    equity = pd.Series(list(equity_curve), dtype=float).dropna()
    if len(equity) < 2:
        return None, None
    first = float(equity.iloc[0])
    if first <= 0:
        return None, None
    cumulative_return = float(equity.iloc[-1]) / first - 1.0
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min())
    return cumulative_return, max_drawdown


def _volatility_at_entry(
    benchmark_history: Optional[pd.DataFrame],
    volatility_window: int,
) -> Optional[pd.Series]:
    if benchmark_history is None or benchmark_history.empty or "Close" not in benchmark_history.columns:
        return None
    close = benchmark_history["Close"].dropna()
    if close.empty:
        return None
    returns = close.pct_change().dropna()
    if returns.empty:
        return None
    rolling_vol = returns.rolling(window=max(int(volatility_window), 2)).std() * (252 ** 0.5)
    return rolling_vol.dropna()


def _regime_label(volatility, low_vol_threshold: float, high_vol_threshold: float) -> str:
    if volatility is None:
        return "UNKNOWN"
    if volatility < low_vol_threshold:
        return "LOW_VOL"
    if volatility >= high_vol_threshold:
        return "HIGH_VOL"
    return "NORMAL"


def _build_regime_breakdown(
    pairs: list,
    *,
    benchmark_history: Optional[pd.DataFrame],
    volatility_window: int,
    low_vol_threshold: float,
    high_vol_threshold: float,
) -> List[RegimeStats]:
    if not pairs:
        return []

    vol_series = _volatility_at_entry(benchmark_history, volatility_window)
    if vol_series is None:
        returns = [pair["return_pct"] for pair in pairs]
        wins = [value for value in returns if value > 0]
        return [
            RegimeStats(
                regime="ALL",
                trades=len(returns),
                win_rate=len(wins) / len(returns) if returns else None,
                avg_return_pct=mean(returns) if returns else None,
            )
        ]

    buckets = {}
    for pair in pairs:
        entry_date = pair.get("entry_date")
        if entry_date is None:
            regime = "UNKNOWN"
        else:
            try:
                vol = vol_series.asof(entry_date)
                vol_value = None if pd.isna(vol) else float(vol)
            except Exception:
                vol_value = None
            regime = _regime_label(vol_value, low_vol_threshold, high_vol_threshold)
        buckets.setdefault(regime, []).append(float(pair["return_pct"]))

    order = {"LOW_VOL": 0, "NORMAL": 1, "HIGH_VOL": 2, "UNKNOWN": 3}
    items = []
    for regime, returns in sorted(buckets.items(), key=lambda item: order.get(item[0], 99)):
        wins = [value for value in returns if value > 0]
        items.append(
            RegimeStats(
                regime=regime,
                trades=len(returns),
                win_rate=len(wins) / len(returns) if returns else None,
                avg_return_pct=mean(returns) if returns else None,
            )
        )
    return items


def build_signal_scoreboard(
    trade_log: Iterable[Mapping],
    *,
    equity_curve=None,
    benchmark_history: Optional[pd.DataFrame] = None,
    volatility_window: int = 20,
    low_vol_threshold: float = 0.20,
    high_vol_threshold: float = 0.35,
) -> SignalScoreboard:
    pairs = _pair_round_trips(trade_log)
    if not pairs:
        return SignalScoreboard(
            completed_trades=0,
            win_rate=None,
            avg_return_pct=None,
            avg_win_return_pct=None,
            avg_loss_return_pct=None,
            payoff_ratio=None,
            expectancy_return_pct=None,
            profit_factor=None,
            median_holding_days=None,
            cumulative_return_pct=None,
            max_drawdown_pct=None,
            regime_breakdown=[],
        )

    returns = [float(pair["return_pct"]) for pair in pairs]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    win_rate = len(wins) / len(returns) if returns else None
    avg_return = mean(returns) if returns else None
    avg_win = mean(wins) if wins else None
    avg_loss = mean(losses) if losses else None

    payoff_ratio = None
    if avg_win is not None and avg_loss is not None and avg_loss != 0:
        payoff_ratio = avg_win / abs(avg_loss)

    expectancy = None
    if win_rate is not None:
        expectancy = win_rate * (avg_win or 0.0) + (1.0 - win_rate) * (avg_loss or 0.0)

    profit_factor = None
    total_win = sum(wins) if wins else 0.0
    total_loss = sum(losses) if losses else 0.0
    if total_loss < 0:
        profit_factor = total_win / abs(total_loss)

    holding_days = [pair["holding_days"] for pair in pairs if pair["holding_days"] is not None]
    median_days = median(holding_days) if holding_days else None
    cumulative_return, max_drawdown = _equity_stats(equity_curve)
    regime_breakdown = _build_regime_breakdown(
        pairs,
        benchmark_history=benchmark_history,
        volatility_window=volatility_window,
        low_vol_threshold=low_vol_threshold,
        high_vol_threshold=high_vol_threshold,
    )

    return SignalScoreboard(
        completed_trades=len(pairs),
        win_rate=win_rate,
        avg_return_pct=avg_return,
        avg_win_return_pct=avg_win,
        avg_loss_return_pct=avg_loss,
        payoff_ratio=payoff_ratio,
        expectancy_return_pct=expectancy,
        profit_factor=profit_factor,
        median_holding_days=median_days,
        cumulative_return_pct=cumulative_return,
        max_drawdown_pct=max_drawdown,
        regime_breakdown=regime_breakdown,
    )
