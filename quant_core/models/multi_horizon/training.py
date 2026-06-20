from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import DataLoader, TensorDataset

from .dataset import (
    DEFAULT_HORIZONS,
    FEATURE_COLUMNS,
    build_feature_frame,
    build_forward_labels,
)
from .network import FinanceMultiAssetTransformer, MultiAssetTransformerConfig


DEFAULT_CHECKPOINT_FILE = "trained_models/finance_multi_asset_transformer.pt"


@dataclass(frozen=True)
class MultiAssetTensorBundle:
    sequences: np.ndarray
    market_context: np.ndarray
    asset_mask: np.ndarray
    absolute_returns: np.ndarray
    risk_free_excess_returns: np.ndarray
    market_excess_returns: np.ndarray
    favorable_excursion: np.ndarray
    adverse_excursion: np.ndarray
    timing_targets: np.ndarray
    observation_dates: tuple[str, ...]
    symbols: tuple[str, ...]
    horizons: tuple[int, ...]
    feature_columns: tuple[str, ...]
    risk_free_symbol: str


def _observation_dates(index: pd.Index, frequency: str) -> pd.DatetimeIndex:
    marker = pd.Series(np.arange(len(index)), index=pd.DatetimeIndex(index))
    positions = marker.resample(frequency).last().dropna().astype(int)
    return pd.DatetimeIndex(index[positions.to_numpy()])


def _market_context(benchmark_history: pd.DataFrame, observation_date: pd.Timestamp) -> np.ndarray:
    close = pd.to_numeric(benchmark_history["Close"], errors="coerce").loc[:observation_date].dropna()
    if close.empty:
        return np.zeros(5, dtype=np.float32)
    returns = close.pct_change()
    return np.asarray(
        [
            close.pct_change(21).iloc[-1] if len(close) > 21 else 0.0,
            close.pct_change(63).iloc[-1] if len(close) > 63 else 0.0,
            returns.tail(21).std() * np.sqrt(252) if len(returns.dropna()) >= 5 else 0.0,
            close.iloc[-1] / close.tail(252).max() - 1.0,
            returns.tail(21).gt(0).mean() if len(returns.dropna()) else 0.5,
        ],
        dtype=np.float32,
    )


def _timing_target(feature_row: pd.Series, forward_return: float) -> int:
    recent_return = float(feature_row.get("return_21d") or 0.0)
    high_proximity = float(feature_row.get("high_proximity_252d") or 0.0)
    if forward_return <= -0.05:
        return 4  # FAILED
    if recent_return < 0 and forward_return > 0.02:
        return 0  # EARLY
    if recent_return > 0.12 and high_proximity > 0.98:
        return 2  # EXTENDED
    if recent_return < -0.03:
        return 3  # DETERIORATING
    return 1  # CONFIRMED


def build_multi_asset_tensor_bundle(
    histories: Mapping[str, pd.DataFrame],
    *,
    symbols: Sequence[str],
    benchmark_map: Mapping[str, str],
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    lookback: int = 252,
    observation_frequency: str = "W-FRI",
    risk_free_symbol: str = "BIL",
) -> MultiAssetTensorBundle:
    normalized = {
        str(symbol).strip().upper(): frame.sort_index().copy()
        for symbol, frame in dict(histories or {}).items()
        if isinstance(frame, pd.DataFrame) and not frame.empty and str(symbol).strip()
    }
    normalized_symbols = tuple(
        str(symbol).strip().upper()
        for symbol in symbols
        if str(symbol).strip().upper() in normalized
    )
    normalized_horizons = tuple(max(int(horizon), 1) for horizon in horizons)
    normalized_risk_free_symbol = str(risk_free_symbol or "BIL").strip().upper()
    if not normalized_symbols:
        raise ValueError("No asset histories are available for tensor construction.")
    if normalized_risk_free_symbol not in normalized:
        raise ValueError(f"Missing risk-free benchmark history: {normalized_risk_free_symbol}")

    feature_frames = {}
    label_frames = {}
    for symbol in normalized_symbols:
        benchmark_symbol = str(benchmark_map.get(symbol) or "SPY").strip().upper()
        if benchmark_symbol not in normalized:
            raise ValueError(f"Missing benchmark history for {symbol}: {benchmark_symbol}")
        feature_frames[symbol] = build_feature_frame(normalized[symbol], normalized[benchmark_symbol])
        label_frames[symbol] = build_forward_labels(
            normalized[symbol],
            normalized[benchmark_symbol],
            normalized[normalized_risk_free_symbol],
            horizons=normalized_horizons,
        )

    reference_symbol = normalized_symbols[0]
    reference_index = feature_frames[reference_symbol].index
    observation_dates = _observation_dates(reference_index, observation_frequency)
    sequences = []
    contexts = []
    masks = []
    risk_free_excess_returns = []
    market_excess_returns = []
    absolute_returns = []
    favorable = []
    adverse = []
    timing_targets = []
    accepted_dates = []

    for observation_date in observation_dates:
        sample_sequences = []
        sample_mask = []
        sample_market_excess = []
        sample_risk_free_excess = []
        sample_absolute_returns = []
        sample_favorable = []
        sample_adverse = []
        sample_timing = []
        for symbol in normalized_symbols:
            feature_frame = feature_frames[symbol].loc[:observation_date]
            if len(feature_frame) < lookback or observation_date not in label_frames[symbol].index:
                sample_sequences.append(np.zeros((lookback, len(FEATURE_COLUMNS)), dtype=np.float32))
                sample_mask.append(False)
                sample_market_excess.append(np.full(len(normalized_horizons), np.nan, dtype=np.float32))
                sample_risk_free_excess.append(np.full(len(normalized_horizons), np.nan, dtype=np.float32))
                sample_absolute_returns.append(np.full(len(normalized_horizons), np.nan, dtype=np.float32))
                sample_favorable.append(np.full(len(normalized_horizons), np.nan, dtype=np.float32))
                sample_adverse.append(np.full(len(normalized_horizons), np.nan, dtype=np.float32))
                sample_timing.append(4)
                continue
            labels = label_frames[symbol].loc[observation_date]
            market_excess = np.asarray(
                [labels.get(f"market_excess_return_{horizon}d") for horizon in normalized_horizons],
                dtype=np.float32,
            )
            risk_free_excess = np.asarray(
                [labels.get(f"risk_free_excess_return_{horizon}d") for horizon in normalized_horizons],
                dtype=np.float32,
            )
            absolute = np.asarray(
                [labels.get(f"forward_return_{horizon}d") for horizon in normalized_horizons],
                dtype=np.float32,
            )
            if (
                not np.isfinite(market_excess).all()
                or not np.isfinite(risk_free_excess).all()
                or not np.isfinite(absolute).all()
            ):
                sample_sequences.append(np.zeros((lookback, len(FEATURE_COLUMNS)), dtype=np.float32))
                sample_mask.append(False)
                sample_market_excess.append(market_excess)
                sample_risk_free_excess.append(risk_free_excess)
                sample_absolute_returns.append(absolute)
                sample_favorable.append(np.full(len(normalized_horizons), np.nan, dtype=np.float32))
                sample_adverse.append(np.full(len(normalized_horizons), np.nan, dtype=np.float32))
                sample_timing.append(4)
                continue
            sequence = (
                feature_frame[list(FEATURE_COLUMNS)]
                .tail(lookback)
                .replace([np.inf, -np.inf], np.nan)
                .ffill()
                .fillna(0.0)
                .to_numpy(dtype=np.float32)
            )
            favorable_values = np.asarray(
                [labels.get(f"max_favorable_{horizon}d") for horizon in normalized_horizons],
                dtype=np.float32,
            )
            adverse_values = np.asarray(
                [labels.get(f"max_adverse_{horizon}d") for horizon in normalized_horizons],
                dtype=np.float32,
            )
            sample_sequences.append(sequence)
            sample_mask.append(True)
            sample_market_excess.append(market_excess)
            sample_risk_free_excess.append(risk_free_excess)
            sample_absolute_returns.append(absolute)
            sample_favorable.append(favorable_values)
            sample_adverse.append(adverse_values)
            sample_timing.append(_timing_target(feature_frame.iloc[-1], float(absolute[0])))
        mask_array = np.asarray(sample_mask, dtype=bool)
        if int(mask_array.sum()) < 2:
            continue
        benchmark_symbol = str(benchmark_map.get(reference_symbol) or "SPY").strip().upper()
        sequences.append(np.asarray(sample_sequences, dtype=np.float32))
        contexts.append(_market_context(normalized[benchmark_symbol], observation_date))
        masks.append(mask_array)
        market_excess_returns.append(np.asarray(sample_market_excess, dtype=np.float32))
        risk_free_excess_returns.append(np.asarray(sample_risk_free_excess, dtype=np.float32))
        absolute_returns.append(np.asarray(sample_absolute_returns, dtype=np.float32))
        favorable.append(np.asarray(sample_favorable, dtype=np.float32))
        adverse.append(np.asarray(sample_adverse, dtype=np.float32))
        timing_targets.append(np.asarray(sample_timing, dtype=np.int64))
        accepted_dates.append(pd.Timestamp(observation_date).isoformat())

    if not sequences:
        raise ValueError("No valid multi-asset training samples were produced.")
    return MultiAssetTensorBundle(
        sequences=np.asarray(sequences, dtype=np.float32),
        market_context=np.asarray(contexts, dtype=np.float32),
        asset_mask=np.asarray(masks, dtype=bool),
        absolute_returns=np.asarray(absolute_returns, dtype=np.float32),
        risk_free_excess_returns=np.asarray(risk_free_excess_returns, dtype=np.float32),
        market_excess_returns=np.asarray(market_excess_returns, dtype=np.float32),
        favorable_excursion=np.asarray(favorable, dtype=np.float32),
        adverse_excursion=np.asarray(adverse, dtype=np.float32),
        timing_targets=np.asarray(timing_targets, dtype=np.int64),
        observation_dates=tuple(accepted_dates),
        symbols=normalized_symbols,
        horizons=normalized_horizons,
        feature_columns=tuple(FEATURE_COLUMNS),
        risk_free_symbol=normalized_risk_free_symbol,
    )


def _resolve_device(preferred: str):
    preferred = str(preferred or "auto").strip().lower()
    if preferred == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    if preferred in {"auto", "mps"} and hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    if preferred == "auto" and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def describe_compute_device(preferred: str = "auto") -> dict:
    device = _resolve_device(preferred)
    cuda_available = bool(torch.cuda.is_available())
    cuda_version = str(torch.version.cuda or "")
    common = {
        "torch_version": str(torch.__version__),
        "torch_cuda_version": cuda_version or None,
        "cuda_available": cuda_available,
    }
    if device.type == "cuda":
        index = device.index if device.index is not None else torch.cuda.current_device()
        name = torch.cuda.get_device_name(index)
        return {
            "device": str(device),
            "accelerator": "CUDA",
            "label": f"NVIDIA {name}",
            "fallback_reason": None,
            **common,
        }
    if device.type == "mps":
        return {
            "device": "mps",
            "accelerator": "MPS",
            "label": "Apple Metal / MPS",
            "fallback_reason": None,
            **common,
        }
    preferred = str(preferred or "auto").strip().lower()
    if preferred in {"auto", "cuda"} and not cuda_version:
        fallback_reason = "This PyTorch build has no CUDA support"
    elif preferred in {"auto", "cuda"} and not cuda_available:
        fallback_reason = "CUDA runtime is unavailable to this Python process"
    else:
        fallback_reason = None
    return {
        "device": "cpu",
        "accelerator": "CPU",
        "label": "CPU",
        "fallback_reason": fallback_reason,
        **common,
    }


def _masked_mean(values, mask):
    mask = mask.to(values.dtype)
    while mask.ndim < values.ndim:
        mask = mask.unsqueeze(-1)
    return (values * mask).sum() / mask.sum().clamp_min(1.0)


def _pairwise_rank_loss(scores, targets, asset_mask):
    total = scores.new_tensor(0.0)
    count = 0
    for batch_index in range(scores.shape[0]):
        valid = asset_mask[batch_index].bool()
        for horizon_index in range(scores.shape[-1]):
            score = scores[batch_index, valid, horizon_index]
            target = targets[batch_index, valid, horizon_index]
            finite = torch.isfinite(target)
            score, target = score[finite], target[finite]
            if len(score) < 2:
                continue
            score_diff = score[:, None] - score[None, :]
            target_diff = target[:, None] - target[None, :]
            pair_mask = target_diff.abs() > 1e-8
            if not pair_mask.any():
                continue
            total = total + F.softplus(-torch.sign(target_diff[pair_mask]) * score_diff[pair_mask]).mean()
            count += 1
    return total / max(count, 1)


def _quantile_loss(predictions, target, mask):
    quantiles = predictions.new_tensor([0.1, 0.5, 0.9])
    errors = target.unsqueeze(-1) - predictions
    losses = torch.maximum((quantiles - 1.0) * errors, quantiles * errors)
    finite_mask = mask.unsqueeze(-1) & torch.isfinite(target).unsqueeze(-1)
    return _masked_mean(torch.where(finite_mask, losses, torch.zeros_like(losses)), finite_mask)


def _training_loss(
    outputs,
    absolute_returns,
    risk_free_excess_returns,
    market_excess_returns,
    favorable,
    adverse,
    timing_targets,
    asset_mask,
):
    finite_absolute = torch.isfinite(absolute_returns)
    finite_risk_free_excess = torch.isfinite(risk_free_excess_returns)
    finite_market_excess = torch.isfinite(market_excess_returns)
    absolute_mask = asset_mask.unsqueeze(-1) & finite_absolute
    risk_free_mask = asset_mask.unsqueeze(-1) & finite_risk_free_excess
    market_mask = asset_mask.unsqueeze(-1) & finite_market_excess
    rank_loss = _pairwise_rank_loss(outputs["rank_scores"], market_excess_returns, asset_mask)
    positive_bce = F.binary_cross_entropy_with_logits(
        outputs["positive_return_logits"],
        torch.nan_to_num((absolute_returns > 0).to(outputs["positive_return_logits"].dtype)),
        reduction="none",
    )
    positive_loss = _masked_mean(positive_bce, absolute_mask)
    risk_free_bce = F.binary_cross_entropy_with_logits(
        outputs["risk_free_outperformance_logits"],
        torch.nan_to_num(
            (risk_free_excess_returns > 0).to(outputs["risk_free_outperformance_logits"].dtype)
        ),
        reduction="none",
    )
    risk_free_outperformance_loss = _masked_mean(risk_free_bce, risk_free_mask)
    market_bce = F.binary_cross_entropy_with_logits(
        outputs["market_outperformance_logits"],
        torch.nan_to_num(
            (market_excess_returns > 0).to(outputs["market_outperformance_logits"].dtype)
        ),
        reduction="none",
    )
    market_outperformance_loss = _masked_mean(market_bce, market_mask)
    quantile_loss = _quantile_loss(outputs["return_quantiles"], absolute_returns, absolute_mask)
    favorable_loss = _masked_mean(
        (outputs["favorable_excursion"] - torch.nan_to_num(favorable)) ** 2,
        absolute_mask & torch.isfinite(favorable),
    )
    adverse_loss = _masked_mean(
        (outputs["adverse_excursion"] - torch.nan_to_num(adverse)) ** 2,
        absolute_mask & torch.isfinite(adverse),
    )
    timing_loss = F.cross_entropy(
        outputs["timing_logits"].reshape(-1, outputs["timing_logits"].shape[-1]),
        timing_targets.reshape(-1),
        reduction="none",
    )
    timing_loss = _masked_mean(timing_loss.reshape_as(asset_mask), asset_mask)
    expert_usage = outputs["expert_weights"].mean(dim=(0, 1))
    balance_loss = torch.mean((expert_usage - expert_usage.mean()) ** 2)
    total = (
        0.45 * rank_loss
        + 1.0 * quantile_loss
        + 0.7 * positive_loss
        + 0.7 * risk_free_outperformance_loss
        + 0.25 * market_outperformance_loss
        + 0.2 * favorable_loss
        + 0.2 * adverse_loss
        + 0.25 * timing_loss
        + 0.05 * balance_loss
    )
    return total, {
        "rank_loss": rank_loss,
        "quantile_loss": quantile_loss,
        "positive_return_loss": positive_loss,
        "risk_free_outperformance_loss": risk_free_outperformance_loss,
        "market_outperformance_loss": market_outperformance_loss,
        "timing_loss": timing_loss,
        "expert_balance_loss": balance_loss,
    }


def train_multi_asset_model(
    bundle: MultiAssetTensorBundle,
    *,
    config: MultiAssetTransformerConfig,
    epochs: int = 20,
    batch_size: int = 8,
    learning_rate: float = 3e-4,
    weight_decay: float = 1e-4,
    device: str = "auto",
    checkpoint_path: str = DEFAULT_CHECKPOINT_FILE,
    pretrained_checkpoint_path: str | None = None,
    progress_callback: Callable[[Mapping], None] | None = None,
) -> dict:
    resolved_device = _resolve_device(device)
    sequences = np.asarray(bundle.sequences, dtype=np.float32)
    valid_sequences = sequences[np.asarray(bundle.asset_mask, dtype=bool)]
    mean = valid_sequences.reshape(-1, sequences.shape[-1]).mean(axis=0)
    std = valid_sequences.reshape(-1, sequences.shape[-1]).std(axis=0)
    std = np.where(std < 1e-6, 1.0, std)
    scaled_sequences = (sequences - mean.reshape(1, 1, 1, -1)) / std.reshape(1, 1, 1, -1)

    dataset = TensorDataset(
        torch.tensor(scaled_sequences, dtype=torch.float32),
        torch.tensor(bundle.market_context, dtype=torch.float32),
        torch.tensor(bundle.asset_mask, dtype=torch.bool),
        torch.tensor(bundle.absolute_returns, dtype=torch.float32),
        torch.tensor(bundle.risk_free_excess_returns, dtype=torch.float32),
        torch.tensor(bundle.market_excess_returns, dtype=torch.float32),
        torch.tensor(bundle.favorable_excursion, dtype=torch.float32),
        torch.tensor(bundle.adverse_excursion, dtype=torch.float32),
        torch.tensor(bundle.timing_targets, dtype=torch.long),
    )
    loader = DataLoader(dataset, batch_size=max(int(batch_size), 1), shuffle=True)
    model = FinanceMultiAssetTransformer(config).to(resolved_device)
    pretraining_loaded = False
    pretraining_metadata = {}
    if pretrained_checkpoint_path:
        pretraining_payload = torch.load(pretrained_checkpoint_path, map_location=resolved_device)
        temporal_state = dict(pretraining_payload.get("temporal_state_dict", {}) or {})
        if temporal_state:
            model.temporal.load_state_dict(temporal_state)
            pretraining_loaded = True
            pretraining_metadata = dict(pretraining_payload.get("metadata", {}) or {})
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(learning_rate), weight_decay=float(weight_decay))
    epoch_metrics = {}
    epoch_history = []
    model.train()
    epoch_count = max(int(epochs), 1)
    for epoch_index in range(epoch_count):
        totals = {}
        batch_count = 0
        for batch in loader:
            sequence, context, mask, absolute, risk_free_excess, market_excess, favorable, adverse, timing = [
                tensor.to(resolved_device) for tensor in batch
            ]
            optimizer.zero_grad()
            outputs = model(sequence, market_context=context, asset_mask=mask)
            loss, components = _training_loss(
                outputs,
                absolute,
                risk_free_excess,
                market_excess,
                favorable,
                adverse,
                timing,
                mask,
            )
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            totals["loss"] = totals.get("loss", 0.0) + float(loss.detach().cpu())
            for name, value in components.items():
                totals[name] = totals.get(name, 0.0) + float(value.detach().cpu())
            batch_count += 1
        epoch_metrics = {name: value / max(batch_count, 1) for name, value in totals.items()}
        epoch_history.append(
            {
                "epoch": epoch_index + 1,
                **{name: round(float(value), 8) for name, value in epoch_metrics.items()},
            }
        )
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "supervised_training",
                    "detail": f"Epoch {epoch_index + 1}/{epoch_count}",
                    "progress_pct": round((epoch_index + 1) / epoch_count * 100.0, 1),
                    "epoch": epoch_index + 1,
                    "epochs": epoch_count,
                    "loss": round(float(epoch_metrics.get("loss", 0.0)), 6),
                    "device": str(resolved_device),
                }
            )

    target = Path(checkpoint_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    trained_at = datetime.now().isoformat()
    metadata = {
        "model_id": "finance_multi_asset_transformer",
        "target_schema_version": 2,
        "target_definition": {
            "primary": ["absolute_return", "positive_return", "risk_free_outperformance"],
            "risk_free_benchmark": bundle.risk_free_symbol,
            "auxiliary": ["market_outperformance", "cross_sectional_rank"],
        },
        "trained_at": trained_at,
        "version": trained_at,
        "config": asdict(config),
        "symbols": list(bundle.symbols),
        "horizons": list(bundle.horizons),
        "feature_columns": list(bundle.feature_columns),
        "lookback": int(bundle.sequences.shape[2]),
        "feature_mean": mean.tolist(),
        "feature_std": std.tolist(),
        "metrics": epoch_metrics,
        "epoch_history": epoch_history,
        "pretraining": {
            "loaded": pretraining_loaded,
            "checkpoint_path": (
                Path(pretrained_checkpoint_path).name
                if pretrained_checkpoint_path
                else None
            ),
            "metadata": pretraining_metadata,
        },
    }
    torch.save({"state_dict": model.state_dict(), "metadata": metadata}, target)
    return {
        "checkpoint_path": str(target),
        "device": str(resolved_device),
        "sample_count": int(len(bundle.sequences)),
        "pretraining_loaded": pretraining_loaded,
        "epoch_history": epoch_history,
        **epoch_metrics,
    }


def load_model_checkpoint(path: str = DEFAULT_CHECKPOINT_FILE, *, device: str = "auto"):
    resolved_device = _resolve_device(device)
    payload = torch.load(path, map_location=resolved_device)
    metadata = dict(payload.get("metadata", {}) or {})
    if int(metadata.get("target_schema_version", 0) or 0) < 2:
        raise ValueError(
            "Checkpoint uses the retired relative-ranking target schema; retrain the model."
        )
    config = MultiAssetTransformerConfig(**dict(metadata.get("config", {}) or {}))
    model = FinanceMultiAssetTransformer(config).to(resolved_device)
    model.load_state_dict(payload["state_dict"])
    model.eval()
    return model, metadata
