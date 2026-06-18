from __future__ import annotations

from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


DEFAULT_HORIZONS = (63, 126, 252)
FEATURE_COLUMNS = (
    "return_21d",
    "return_63d",
    "return_126d",
    "return_252d",
    "relative_strength_21d",
    "relative_strength_63d",
    "relative_strength_126d",
    "relative_strength_252d",
    "volatility_21d",
    "volatility_63d",
    "drawdown_252d",
    "high_proximity_252d",
    "volume_ratio_21d",
    "trend_slope_63d",
    "trend_consistency_63d",
)


def _close(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty or "Close" not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame["Close"], errors="coerce").sort_index().dropna()


def _volume(frame: pd.DataFrame, index: pd.Index) -> pd.Series:
    if frame is None or frame.empty or "Volume" not in frame.columns:
        return pd.Series(0.0, index=index)
    return pd.to_numeric(frame["Volume"], errors="coerce").reindex(index).fillna(0.0)


def _future_path_stat(close: pd.Series, horizon: int, reducer) -> pd.Series:
    values = close.to_numpy(dtype=float)
    result = np.full(len(values), np.nan, dtype=float)
    for position in range(0, max(len(values) - horizon, 0)):
        current = values[position]
        path = values[position + 1 : position + horizon + 1] / current - 1.0
        result[position] = reducer(path)
    return pd.Series(result, index=close.index, dtype=float)


def build_forward_labels(
    asset_history: pd.DataFrame,
    benchmark_history: pd.DataFrame,
    *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> pd.DataFrame:
    asset_close = _close(asset_history)
    benchmark_close = _close(benchmark_history).reindex(asset_close.index).ffill()
    labels = pd.DataFrame(index=asset_close.index)
    for raw_horizon in horizons:
        horizon = max(int(raw_horizon), 1)
        asset_return = asset_close.shift(-horizon) / asset_close - 1.0
        benchmark_return = benchmark_close.shift(-horizon) / benchmark_close - 1.0
        labels[f"forward_return_{horizon}d"] = asset_return
        labels[f"benchmark_return_{horizon}d"] = benchmark_return
        labels[f"excess_return_{horizon}d"] = asset_return - benchmark_return
        labels[f"max_favorable_{horizon}d"] = _future_path_stat(asset_close, horizon, np.max)
        labels[f"max_adverse_{horizon}d"] = _future_path_stat(asset_close, horizon, np.min)
    return labels


def _trend_slope(close: pd.Series, window: int) -> pd.Series:
    time_axis = np.arange(window, dtype=float)
    denominator = float(np.sum((time_axis - time_axis.mean()) ** 2))

    def slope(values):
        values = np.asarray(values, dtype=float)
        if len(values) != window or values[0] <= 0 or denominator <= 0:
            return np.nan
        normalized = values / values[0] - 1.0
        return float(np.sum((time_axis - time_axis.mean()) * (normalized - normalized.mean())) / denominator)

    return close.rolling(window).apply(slope, raw=True)


def build_feature_frame(asset_history: pd.DataFrame, benchmark_history: pd.DataFrame) -> pd.DataFrame:
    close = _close(asset_history)
    benchmark_close = _close(benchmark_history).reindex(close.index).ffill()
    volume = _volume(asset_history, close.index)
    features = pd.DataFrame(index=close.index)
    for horizon in (21, 63, 126, 252):
        asset_return = close.pct_change(horizon)
        benchmark_return = benchmark_close.pct_change(horizon)
        features[f"return_{horizon}d"] = asset_return
        features[f"relative_strength_{horizon}d"] = asset_return - benchmark_return
    daily_returns = close.pct_change()
    features["volatility_21d"] = daily_returns.rolling(21).std() * np.sqrt(252)
    features["volatility_63d"] = daily_returns.rolling(63).std() * np.sqrt(252)
    rolling_high = close.rolling(252, min_periods=63).max()
    features["drawdown_252d"] = close / rolling_high - 1.0
    features["high_proximity_252d"] = close / rolling_high
    features["volume_ratio_21d"] = volume / volume.rolling(21).mean().replace(0, np.nan)
    features["trend_slope_63d"] = _trend_slope(close, 63)
    features["trend_consistency_63d"] = (
        daily_returns.gt(0).rolling(63).mean() - daily_returns.lt(0).rolling(63).mean()
    )
    return features.replace([np.inf, -np.inf], np.nan)


def _observation_dates(index: pd.Index, frequency: str) -> pd.DatetimeIndex:
    marker = pd.Series(np.arange(len(index)), index=pd.DatetimeIndex(index))
    positions = marker.resample(frequency).last().dropna().astype(int)
    return pd.DatetimeIndex(index[positions.to_numpy()])


def build_panel_frame(
    histories: Mapping[str, pd.DataFrame],
    *,
    benchmark_map: Mapping[str, str],
    symbols: Iterable[str] | None = None,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    observation_frequency: str = "W-FRI",
    include_unlabeled: bool = False,
) -> pd.DataFrame:
    normalized_histories = {
        str(symbol).strip().upper(): frame.copy()
        for symbol, frame in dict(histories or {}).items()
        if str(symbol).strip() and isinstance(frame, pd.DataFrame)
    }
    selected_symbols = [
        str(symbol).strip().upper()
        for symbol in (symbols or normalized_histories.keys())
        if str(symbol).strip().upper() in normalized_histories
    ]
    rows = []
    required_labels = [f"excess_return_{int(horizon)}d" for horizon in horizons]
    for symbol in selected_symbols:
        benchmark_symbol = str(benchmark_map.get(symbol) or "SPY").strip().upper()
        if symbol == benchmark_symbol or benchmark_symbol not in normalized_histories:
            continue
        asset_history = normalized_histories[symbol]
        benchmark_history = normalized_histories[benchmark_symbol]
        features = build_feature_frame(asset_history, benchmark_history)
        labels = build_forward_labels(asset_history, benchmark_history, horizons=horizons)
        frame = features.join(labels, how="left")
        for observation_date in _observation_dates(frame.index, observation_frequency):
            row = frame.loc[observation_date]
            if not include_unlabeled and any(pd.isna(row.get(column)) for column in required_labels):
                continue
            payload = {
                "observation_date": pd.Timestamp(observation_date),
                "symbol": symbol,
                "benchmark": benchmark_symbol,
            }
            payload.update({column: row.get(column) for column in frame.columns})
            rows.append(payload)
    if not rows:
        return pd.DataFrame(columns=("observation_date", "symbol", "benchmark", *FEATURE_COLUMNS))
    panel = pd.DataFrame(rows).sort_values(["observation_date", "symbol"]).reset_index(drop=True)
    for horizon in horizons:
        label_column = f"excess_return_{int(horizon)}d"
        rank_column = f"relevance_{int(horizon)}d"
        panel[rank_column] = panel.groupby("observation_date")[label_column].rank(
            pct=True,
            method="average",
        )
    return panel
