from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np
import pandas as pd
import torch

from .dataset import FEATURE_COLUMNS, build_feature_frame
from .prediction import build_prediction_snapshot
from .training import _market_context, load_model_checkpoint


def build_latest_model_input(
    histories: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    benchmark_map: Mapping[str, str],
    lookback: int,
    feature_mean,
    feature_std,
):
    normalized = {
        str(symbol).strip().upper(): frame.sort_index().copy()
        for symbol, frame in dict(histories or {}).items()
        if isinstance(frame, pd.DataFrame) and not frame.empty
    }
    sequences = []
    mask = []
    latest_date = None
    for symbol in symbols:
        normalized_symbol = str(symbol).strip().upper()
        benchmark_symbol = str(benchmark_map.get(normalized_symbol) or "SPY").strip().upper()
        if normalized_symbol not in normalized or benchmark_symbol not in normalized:
            sequences.append(np.zeros((lookback, len(FEATURE_COLUMNS)), dtype=np.float32))
            mask.append(False)
            continue
        features = build_feature_frame(normalized[normalized_symbol], normalized[benchmark_symbol])
        if len(features) < lookback:
            sequences.append(np.zeros((lookback, len(FEATURE_COLUMNS)), dtype=np.float32))
            mask.append(False)
            continue
        sequence = (
            features[list(FEATURE_COLUMNS)]
            .tail(lookback)
            .replace([np.inf, -np.inf], np.nan)
            .ffill()
            .fillna(0.0)
            .to_numpy(dtype=np.float32)
        )
        sequences.append(sequence)
        mask.append(True)
        current_latest = pd.Timestamp(features.index[-1])
        latest_date = current_latest if latest_date is None else min(latest_date, current_latest)
    mask_array = np.asarray(mask, dtype=bool)
    if int(mask_array.sum()) < 2:
        raise ValueError("At least two valid symbols are required for cross-sectional inference.")
    mean = np.asarray(feature_mean, dtype=np.float32).reshape(1, 1, -1)
    std = np.asarray(feature_std, dtype=np.float32).reshape(1, 1, -1)
    scaled = (np.asarray(sequences, dtype=np.float32) - mean) / np.where(std < 1e-6, 1.0, std)
    benchmark_symbol = str(benchmark_map.get(str(symbols[0]).upper()) or "SPY").strip().upper()
    context = _market_context(normalized[benchmark_symbol], latest_date)
    return (
        torch.tensor(scaled[None, ...], dtype=torch.float32),
        torch.tensor(context[None, ...], dtype=torch.float32),
        torch.tensor(mask_array[None, ...], dtype=torch.bool),
        latest_date,
    )


def run_multi_horizon_inference(
    histories: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    benchmark_map: Mapping[str, str],
    current_weights_pct: Mapping[str, float] | None = None,
    risk_regime: str = "NORMAL",
    checkpoint_path: str,
    device: str = "auto",
) -> dict:
    model, metadata = load_model_checkpoint(checkpoint_path, device=device)
    sequence, context, mask, latest_date = build_latest_model_input(
        histories,
        symbols=symbols,
        benchmark_map=benchmark_map,
        lookback=int(metadata.get("lookback") or metadata.get("config", {}).get("lookback") or 252),
        feature_mean=metadata.get("feature_mean"),
        feature_std=metadata.get("feature_std"),
    )
    resolved_device = next(model.parameters()).device
    with torch.no_grad():
        outputs = model(
            sequence.to(resolved_device),
            market_context=context.to(resolved_device),
            asset_mask=mask.to(resolved_device),
        )
    valid_symbols = [
        str(symbol).strip().upper()
        for index, symbol in enumerate(symbols)
        if bool(mask[0, index])
    ]
    valid_indices = [index for index in range(len(symbols)) if bool(mask[0, index])]
    filtered_outputs = {}
    for key, value in outputs.items():
        if key == "representation":
            continue
        filtered_outputs[key] = value[:, valid_indices]
    return build_prediction_snapshot(
        filtered_outputs,
        symbols=valid_symbols,
        horizons=metadata.get("horizons") or [63, 126, 252],
        current_weights_pct=current_weights_pct,
        risk_regime=risk_regime,
        model_metadata=metadata,
        generated_at=pd.Timestamp(latest_date).isoformat(),
    )
