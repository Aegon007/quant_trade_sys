from typing import Callable, Iterable, List, Mapping, Optional

from quant_core.analytics.signal_scoreboard import build_signal_scoreboard


def _float(value, default=0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _composite_score(*, sharpe_ratio, expectancy_return_pct, profit_factor, win_rate, max_drawdown_pct) -> float:
    sharpe_component = _float(sharpe_ratio)
    expectancy_component = _float(expectancy_return_pct) * 100.0
    profit_component = (_float(profit_factor, 1.0) - 1.0) * 3.0
    win_rate_component = (_float(win_rate, 0.5) - 0.5) * 8.0
    drawdown_component = max(_float(max_drawdown_pct), -0.50) * 5.0
    return sharpe_component + expectancy_component + profit_component + win_rate_component + drawdown_component


def compare_strategies_for_symbol(
    *,
    symbol: str,
    strategies: Iterable[Mapping],
    load_historical_data_fn: Callable[..., object],
    create_strategy_fn: Callable[[Mapping], object],
    engine_factory_fn: Callable[[], object],
    history_period: str = "2y",
    runtime_param_fn: Optional[Callable[[Mapping], Mapping]] = None,
) -> List[dict]:
    history = load_historical_data_fn(symbol, period=history_period)
    if history is None or getattr(history, "empty", False):
        return []

    rows = []
    for strategy in strategies or []:
        runtime_strategy = runtime_param_fn(strategy) if runtime_param_fn is not None else dict(strategy)
        strategy_id = str(runtime_strategy.get("id", "")).strip()
        strategy_name = runtime_strategy.get("name", strategy_id or "unknown")
        if not strategy_id:
            continue
        try:
            strategy_obj = create_strategy_fn(runtime_strategy)
            engine = engine_factory_fn()
            engine.set_data(history)
            engine.set_strategy(strategy_obj)
            result = engine.run()
            scoreboard = build_signal_scoreboard(
                result.trade_log,
                equity_curve=result.equity_curve,
                benchmark_history=history,
            )
            composite_score = _composite_score(
                sharpe_ratio=result.sharpe_ratio,
                expectancy_return_pct=scoreboard.expectancy_return_pct,
                profit_factor=scoreboard.profit_factor,
                win_rate=scoreboard.win_rate,
                max_drawdown_pct=scoreboard.max_drawdown_pct,
            )
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "strategy_name": strategy_name,
                    "total_return": _float(result.total_return),
                    "sharpe_ratio": _float(result.sharpe_ratio),
                    "max_drawdown": _float(result.max_drawdown),
                    "win_rate": _float(result.win_rate),
                    "completed_trades": int(_float(scoreboard.completed_trades, 0)),
                    "expectancy_return_pct": scoreboard.expectancy_return_pct,
                    "profit_factor": scoreboard.profit_factor,
                    "composite_score": composite_score,
                }
            )
        except Exception:
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "strategy_name": strategy_name,
                    "error": "comparison_failed",
                    "composite_score": float("-inf"),
                }
            )

    rows.sort(key=lambda item: _float(item.get("composite_score"), float("-inf")), reverse=True)
    return rows
