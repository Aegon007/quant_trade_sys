from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MonteCarloDistribution:
    horizon_days: int
    simulations: int
    latest_price: float
    expected_return: float
    median_return: float
    p05_return: float
    p95_return: float
    var_95: float
    cvar_95: float
    positive_probability: float
    expected_price: float
    p05_price: float
    p95_price: float


def _extract_close_prices(history: pd.DataFrame) -> Optional[pd.Series]:
    if history is None or history.empty:
        return None
    if "Close" not in history.columns:
        return None
    close = history["Close"].dropna()
    if len(close) < 30:
        return None
    return close.astype(float)


def simulate_return_distribution(
    history: pd.DataFrame,
    *,
    horizon_days: int = 20,
    simulations: int = 2000,
    seed: Optional[int] = 42,
) -> Optional[MonteCarloDistribution]:
    close = _extract_close_prices(history)
    if close is None:
        return None

    returns = close.pct_change().dropna().values
    if len(returns) < 20:
        return None

    horizon_days = int(horizon_days)
    simulations = int(simulations)
    if horizon_days <= 0 or simulations <= 0:
        return None

    rng = np.random.default_rng(seed)
    sampled = rng.choice(returns, size=(simulations, horizon_days), replace=True)
    path_returns = np.prod(1.0 + sampled, axis=1) - 1.0

    expected_return = float(np.mean(path_returns))
    median_return = float(np.median(path_returns))
    p05_return = float(np.quantile(path_returns, 0.05))
    p95_return = float(np.quantile(path_returns, 0.95))
    var_95 = p05_return
    tail = path_returns[path_returns <= var_95]
    cvar_95 = float(np.mean(tail)) if len(tail) > 0 else var_95
    positive_probability = float(np.mean(path_returns > 0))

    latest_price = float(close.iloc[-1])
    expected_price = latest_price * (1.0 + expected_return)
    p05_price = latest_price * (1.0 + p05_return)
    p95_price = latest_price * (1.0 + p95_return)

    return MonteCarloDistribution(
        horizon_days=horizon_days,
        simulations=simulations,
        latest_price=latest_price,
        expected_return=expected_return,
        median_return=median_return,
        p05_return=p05_return,
        p95_return=p95_return,
        var_95=var_95,
        cvar_95=cvar_95,
        positive_probability=positive_probability,
        expected_price=expected_price,
        p05_price=p05_price,
        p95_price=p95_price,
    )
