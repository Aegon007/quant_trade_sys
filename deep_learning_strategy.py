"""
Deep learning strategy utilities based on a lightweight Temporal CNN.

PyTorch is an optional dependency. The module can still be imported without it
so the rest of the app remains usable on environments that have not installed a
deep learning backend yet.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import warnings
import json
import os
import time

import numpy as np
import pandas as pd
import yfinance as yf

from ml_strategy import compute_features

warnings.filterwarnings("ignore", category=UserWarning)

TORCH_AVAILABLE = False
TORCH_ERROR_MSG = ""

try:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset

    TORCH_AVAILABLE = True
except ImportError as e:
    TORCH_ERROR_MSG = f"PyTorch 未安装：{e}"
except Exception as e:
    TORCH_ERROR_MSG = f"PyTorch 加载异常：{e}"


FEATURE_COLUMNS = [
    "ret_1", "ret_5", "ret_10", "ret_20",
    "vol_5", "vol_20",
    "volume_ratio", "volume_change_5",
    "price_to_ma_5", "price_to_ma_20", "price_to_ma_50", "ma_5_20_cross",
    "rsi", "bb_position",
    "macd", "macd_diff",
    "atr_ratio", "high_low_ratio",
]

MODEL_DIR = "trained_models"
DEEP_TCN_MODEL_SUFFIX = "_deep_tcn_model.pt"
TRAINING_STATE_FILE = "deep_tcn_training_state.json"
SIGNAL_CACHE_TTL_SECONDS = 120

_SIGNAL_CACHE: Dict[str, Dict] = {}
_PROFILE_CACHE: Dict[str, Dict] = {}


@dataclass
class DeepLearningDataset:
    features: np.ndarray
    targets: np.ndarray
    future_returns: np.ndarray
    index: pd.Index
    feature_columns: List[str]


@dataclass(frozen=True)
class DeepTCNSignalProfile:
    signal: str
    reason: str
    probability: Optional[float] = None
    expected_return_pct: Optional[float] = None
    confidence: Optional[float] = None
    take_profit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    recommended_max_weight_pct: Optional[float] = None
    device: Optional[str] = None
    trained_at: Optional[str] = None


def _ensure_model_dir():
    os.makedirs(MODEL_DIR, exist_ok=True)


def _state_file_path():
    _ensure_model_dir()
    return os.path.join(MODEL_DIR, TRAINING_STATE_FILE)


def get_deep_tcn_model_path(symbol: str):
    _ensure_model_dir()
    safe_symbol = str(symbol).strip().upper()
    return os.path.join(MODEL_DIR, f"{safe_symbol}{DEEP_TCN_MODEL_SUFFIX}")


def is_nightly_retrain_window(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    return now.hour in (23, 0)


def training_cycle_key_for_timestamp(now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    cycle_day = now.date() if now.hour == 23 else (now - timedelta(days=1)).date()
    return cycle_day.isoformat()


def load_training_state() -> Dict:
    path = _state_file_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def save_training_state(state: Dict):
    path = _state_file_path()
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)


def should_run_nightly_retraining(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    if not is_nightly_retrain_window(now):
        return False
    cycle_key = training_cycle_key_for_timestamp(now)
    state = load_training_state()
    return state.get("last_cycle_key") != cycle_key


def mark_nightly_retraining_done(now: Optional[datetime] = None):
    now = now or datetime.now()
    state = load_training_state()
    state["last_cycle_key"] = training_cycle_key_for_timestamp(now)
    state["last_trained_at"] = now.isoformat()
    save_training_state(state)


def select_device_name(preferred: str = "auto", cuda_available: bool = False, mps_available: bool = False) -> str:
    """Select the safest available torch device name for the current platform."""
    preferred = str(preferred).strip().lower() if preferred is not None else "auto"
    if not preferred:
        preferred = "auto"
    if preferred == "cpu":
        return "cpu"
    if preferred == "cuda" and cuda_available:
        return "cuda"
    if preferred == "mps" and mps_available:
        return "mps"
    if preferred in ("auto", "cuda"):
        if cuda_available:
            return "cuda"
        if mps_available:
            return "mps"
        return "cpu"
    if preferred == "mps":
        return "cuda" if cuda_available else "cpu"
    return "cpu"


def resolve_torch_device(preferred: str = "auto"):
    if not TORCH_AVAILABLE:
        return None
    cuda_available = bool(torch.cuda.is_available())
    mps_available = bool(
        hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    )
    return torch.device(select_device_name(preferred, cuda_available, mps_available))


def _empty_dataset(sequence_length: int) -> DeepLearningDataset:
    return DeepLearningDataset(
        features=np.empty((0, sequence_length, len(FEATURE_COLUMNS)), dtype=np.float32),
        targets=np.empty((0,), dtype=np.float32),
        future_returns=np.empty((0,), dtype=np.float32),
        index=pd.Index([]),
        feature_columns=FEATURE_COLUMNS.copy(),
    )


def build_feature_target_frame(data: pd.DataFrame, target_horizon: int = 5) -> Tuple[pd.DataFrame, pd.Series, pd.Series, pd.DataFrame]:
    df = compute_features(data.copy())
    features = df[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
    future_returns = df["Close"].shift(-target_horizon) / df["Close"] - 1
    targets = pd.Series(np.nan, index=df.index, dtype=float)
    valid_mask = future_returns.notna()
    targets.loc[valid_mask] = (future_returns.loc[valid_mask] > 0).astype(float)
    common_index = features.index.intersection(targets.dropna().index)
    return (
        features.loc[common_index],
        targets.loc[common_index],
        future_returns.loc[common_index],
        df.loc[common_index],
    )


def build_feature_frame(data: pd.DataFrame) -> pd.DataFrame:
    df = compute_features(data.copy())
    return df[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan).ffill().fillna(0)


def prepare_deep_learning_dataset(
    data: pd.DataFrame,
    sequence_length: int = 60,
    target_horizon: int = 5,
) -> DeepLearningDataset:
    if data is None or len(data) < sequence_length + target_horizon:
        return _empty_dataset(sequence_length)

    features, targets, future_returns, _ = build_feature_target_frame(data, target_horizon)
    if len(features) < sequence_length:
        return _empty_dataset(sequence_length)

    sequences = []
    labels = []
    returns = []
    indices = []
    for end_pos in range(sequence_length - 1, len(features)):
        start_pos = end_pos - sequence_length + 1
        sequences.append(features.iloc[start_pos:end_pos + 1].to_numpy(dtype=np.float32))
        labels.append(float(targets.iloc[end_pos]))
        returns.append(float(future_returns.iloc[end_pos]))
        indices.append(features.index[end_pos])

    return DeepLearningDataset(
        features=np.asarray(sequences, dtype=np.float32),
        targets=np.asarray(labels, dtype=np.float32),
        future_returns=np.asarray(returns, dtype=np.float32),
        index=pd.Index(indices),
        feature_columns=FEATURE_COLUMNS.copy(),
    )


def _standardize_sequences(train_sequences: np.ndarray, test_sequences: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    if train_sequences.size == 0:
        return train_sequences, test_sequences
    mean, std = _fit_sequence_standardization(train_sequences)
    return (
        _apply_sequence_standardization(train_sequences, mean, std),
        _apply_sequence_standardization(test_sequences, mean, std),
    )


def _fit_sequence_standardization(sequences: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    feature_count = sequences.shape[-1]
    flat = sequences.reshape(-1, feature_count)
    mean = flat.mean(axis=0)
    std = flat.std(axis=0)
    std = np.where(std < 1e-8, 1.0, std)
    return mean.astype(np.float32), std.astype(np.float32)


def _apply_sequence_standardization(
    sequences: np.ndarray, mean: np.ndarray, std: np.ndarray
) -> np.ndarray:
    return ((sequences - mean) / std).astype(np.float32)


if TORCH_AVAILABLE:
    class TemporalCNNClassifier(nn.Module):
        def __init__(
            self,
            feature_count: int,
            hidden_channels: int = 32,
            num_layers: int = 3,
            kernel_size: int = 3,
            dropout: float = 0.15,
        ):
            super().__init__()
            layers = []
            in_channels = feature_count
            for layer_idx in range(num_layers):
                dilation = 2 ** layer_idx
                left_padding = (kernel_size - 1) * dilation
                layers.extend([
                    nn.ConstantPad1d((left_padding, 0), 0.0),
                    nn.Conv1d(in_channels, hidden_channels, kernel_size, dilation=dilation),
                    nn.ReLU(),
                    nn.Dropout(dropout),
                ])
                in_channels = hidden_channels
            self.network = nn.Sequential(*layers)
            self.head = nn.Linear(hidden_channels, 1)

        def forward(self, x):
            x = x.transpose(1, 2)
            encoded = self.network(x)
            return self.head(encoded[:, :, -1]).squeeze(-1)
else:
    TemporalCNNClassifier = None


def _train_tcn_predict_proba(
    train_sequences: np.ndarray,
    train_targets: np.ndarray,
    test_sequences: np.ndarray,
    *,
    epochs: int = 20,
    batch_size: int = 32,
    learning_rate: float = 0.001,
    hidden_channels: int = 32,
    num_layers: int = 3,
    kernel_size: int = 3,
    dropout: float = 0.15,
    device: str = "auto",
    seed: int = 42,
) -> np.ndarray:
    if not TORCH_AVAILABLE:
        raise RuntimeError(TORCH_ERROR_MSG or "PyTorch 不可用")
    if len(test_sequences) == 0:
        return np.asarray([], dtype=float)
    if len(train_sequences) == 0:
        return np.full(len(test_sequences), 0.5, dtype=float)

    positive_rate = float(np.mean(train_targets))
    if len(np.unique(train_targets)) < 2:
        return np.full(len(test_sequences), positive_rate, dtype=float)

    torch.manual_seed(seed)
    np.random.seed(seed)
    resolved_device = resolve_torch_device(device)

    model = TemporalCNNClassifier(
        feature_count=train_sequences.shape[-1],
        hidden_channels=hidden_channels,
        num_layers=num_layers,
        kernel_size=kernel_size,
        dropout=dropout,
    ).to(resolved_device)

    train_x = torch.tensor(train_sequences, dtype=torch.float32, device=resolved_device)
    train_y = torch.tensor(train_targets, dtype=torch.float32, device=resolved_device)
    test_x = torch.tensor(test_sequences, dtype=torch.float32, device=resolved_device)

    loader = DataLoader(
        TensorDataset(train_x, train_y),
        batch_size=max(1, batch_size),
        shuffle=False,
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_fn = nn.BCEWithLogitsLoss()

    model.train()
    for _ in range(max(1, epochs)):
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            loss = loss_fn(model(batch_x), batch_y)
            loss.backward()
            optimizer.step()

    model.eval()
    with torch.no_grad():
        probabilities = torch.sigmoid(model(test_x)).detach().cpu().numpy()
    return probabilities.astype(float)


def _estimate_expected_returns(
    probabilities: np.ndarray,
    train_targets: np.ndarray,
    train_returns: np.ndarray,
) -> np.ndarray:
    positive_returns = train_returns[train_targets >= 0.5]
    negative_returns = train_returns[train_targets < 0.5]
    absolute_return = np.nanmean(np.abs(train_returns)) if len(train_returns) else 0.01
    fallback_move = max(float(absolute_return) if not np.isnan(absolute_return) else 0.01, 0.001)
    mean_positive = float(np.nanmean(positive_returns)) if len(positive_returns) else fallback_move
    mean_negative = float(np.nanmean(negative_returns)) if len(negative_returns) else -fallback_move
    return probabilities * mean_positive + (1 - probabilities) * mean_negative


def _train_tcn_model(
    train_sequences: np.ndarray,
    train_targets: np.ndarray,
    *,
    epochs: int = 20,
    batch_size: int = 32,
    learning_rate: float = 0.001,
    hidden_channels: int = 32,
    num_layers: int = 3,
    kernel_size: int = 3,
    dropout: float = 0.15,
    device: str = "auto",
    seed: int = 42,
):
    if not TORCH_AVAILABLE:
        raise RuntimeError(TORCH_ERROR_MSG or "PyTorch 不可用")
    if len(train_sequences) == 0:
        return None
    torch.manual_seed(seed)
    np.random.seed(seed)
    resolved_device = resolve_torch_device(device)
    model = TemporalCNNClassifier(
        feature_count=train_sequences.shape[-1],
        hidden_channels=hidden_channels,
        num_layers=num_layers,
        kernel_size=kernel_size,
        dropout=dropout,
    ).to(resolved_device)
    train_x = torch.tensor(train_sequences, dtype=torch.float32, device=resolved_device)
    train_y = torch.tensor(train_targets, dtype=torch.float32, device=resolved_device)
    loader = DataLoader(
        TensorDataset(train_x, train_y),
        batch_size=max(1, batch_size),
        shuffle=False,
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_fn = nn.BCEWithLogitsLoss()
    model.train()
    for _ in range(max(1, epochs)):
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            loss = loss_fn(model(batch_x), batch_y)
            loss.backward()
            optimizer.step()
    return model


def train_and_save_deep_tcn_model(
    symbol: str,
    *,
    period: str = "2y",
    sequence_length: int = 60,
    train_window: int = 180,
    target_horizon: int = 5,
    epochs: int = 50,
    batch_size: int = 32,
    learning_rate: float = 0.001,
    hidden_channels: int = 32,
    num_layers: int = 3,
    kernel_size: int = 3,
    dropout: float = 0.15,
    min_train_samples: int = 30,
    device: str = "auto",
    **kwargs,
) -> Tuple[bool, str]:
    if not TORCH_AVAILABLE:
        return False, TORCH_ERROR_MSG or "PyTorch 不可用"
    history = yf.Ticker(symbol).history(period=period)
    if history.empty:
        return False, "历史数据为空"
    dataset = prepare_deep_learning_dataset(history, sequence_length, target_horizon)
    if len(dataset.features) < min_train_samples:
        return False, f"训练样本不足：{len(dataset.features)}"

    train_sequences = dataset.features[-train_window:] if len(dataset.features) > train_window else dataset.features
    train_targets = dataset.targets[-train_window:] if len(dataset.targets) > train_window else dataset.targets
    train_returns = (
        dataset.future_returns[-train_window:]
        if len(dataset.future_returns) > train_window
        else dataset.future_returns
    )
    if len(train_sequences) < min_train_samples:
        return False, f"训练样本不足：{len(train_sequences)}"

    mean, std = _fit_sequence_standardization(train_sequences)
    train_scaled = _apply_sequence_standardization(train_sequences, mean, std)
    model = _train_tcn_model(
        train_scaled,
        train_targets,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        hidden_channels=hidden_channels,
        num_layers=num_layers,
        kernel_size=kernel_size,
        dropout=dropout,
        device=device,
    )
    if model is None:
        return False, "模型训练失败"

    positive_returns = train_returns[train_targets >= 0.5]
    negative_returns = train_returns[train_targets < 0.5]
    abs_ret = np.nanmean(np.abs(train_returns)) if len(train_returns) else 0.01
    fallback_move = max(float(abs_ret) if not np.isnan(abs_ret) else 0.01, 0.001)
    mean_positive = float(np.nanmean(positive_returns)) if len(positive_returns) else fallback_move
    mean_negative = float(np.nanmean(negative_returns)) if len(negative_returns) else -fallback_move

    path = get_deep_tcn_model_path(symbol)
    checkpoint = {
        "state_dict": model.state_dict(),
        "mean": mean.tolist(),
        "std": std.tolist(),
        "trained_at": datetime.now().isoformat(),
        "feature_columns": FEATURE_COLUMNS.copy(),
        "sequence_length": sequence_length,
        "target_horizon": target_horizon,
        "period": period,
        "mean_positive_return": mean_positive,
        "mean_negative_return": mean_negative,
        "model_params": {
            "hidden_channels": hidden_channels,
            "num_layers": num_layers,
            "kernel_size": kernel_size,
            "dropout": dropout,
        },
    }
    torch.save(checkpoint, path)
    return True, path


def load_deep_tcn_model_bundle(symbol: str):
    if not TORCH_AVAILABLE:
        return None
    path = get_deep_tcn_model_path(symbol)
    if not os.path.exists(path):
        return None
    try:
        return torch.load(path, map_location="cpu")
    except Exception:
        return None


def predict_with_saved_deep_tcn_model(
    symbol: str,
    *,
    data: Optional[pd.DataFrame] = None,
    period: Optional[str] = None,
    device: str = "auto",
) -> Optional[Dict[str, float]]:
    if not TORCH_AVAILABLE:
        return None
    bundle = load_deep_tcn_model_bundle(symbol)
    if bundle is None:
        return None

    sequence_length = int(bundle.get("sequence_length", 60))
    model_params = bundle.get("model_params", {})
    feature_columns = bundle.get("feature_columns") or FEATURE_COLUMNS
    mean = np.asarray(bundle.get("mean"), dtype=np.float32)
    std = np.asarray(bundle.get("std"), dtype=np.float32)
    if len(mean) != len(feature_columns) or len(std) != len(feature_columns):
        return None

    if data is not None:
        history = data.copy()
    else:
        effective_period = period or bundle.get("period", "2y")
        history = yf.Ticker(symbol).history(period=effective_period)
    if history.empty:
        return None

    features = build_feature_frame(history)
    if len(features) < sequence_length:
        return None
    latest_sequence = features[feature_columns].iloc[-sequence_length:].to_numpy(dtype=np.float32)
    latest_sequence = _apply_sequence_standardization(
        latest_sequence.reshape(1, sequence_length, len(feature_columns)), mean, std
    )

    resolved_device = resolve_torch_device(device)
    model = TemporalCNNClassifier(
        feature_count=len(feature_columns),
        hidden_channels=int(model_params.get("hidden_channels", 32)),
        num_layers=int(model_params.get("num_layers", 3)),
        kernel_size=int(model_params.get("kernel_size", 3)),
        dropout=float(model_params.get("dropout", 0.15)),
    ).to(resolved_device)
    try:
        model.load_state_dict(bundle["state_dict"])
    except Exception:
        return None
    model.eval()
    with torch.no_grad():
        tensor_input = torch.tensor(latest_sequence, dtype=torch.float32, device=resolved_device)
        prob = float(torch.sigmoid(model(tensor_input))[0].item())

    mean_positive = float(bundle.get("mean_positive_return", 0.01))
    mean_negative = float(bundle.get("mean_negative_return", -0.01))
    expected_return = prob * mean_positive + (1 - prob) * mean_negative
    return {
        "probability": prob,
        "expected_return": expected_return,
        "device": str(resolved_device),
        "trained_at": bundle.get("trained_at"),
        "latest_price": float(history["Close"].iloc[-1]),
    }


def _signal_cache_key(symbol: str, kwargs: Dict) -> str:
    normalized_kwargs = tuple(sorted((k, str(v)) for k, v in kwargs.items()))
    return f"{str(symbol).upper()}::{normalized_kwargs}"


def _get_cached_signal(cache_key: str):
    cached = _SIGNAL_CACHE.get(cache_key)
    if not cached:
        return None
    if time.time() - cached["timestamp"] > SIGNAL_CACHE_TTL_SECONDS:
        _SIGNAL_CACHE.pop(cache_key, None)
        return None
    return cached["signal"], cached["reason"]


def _set_cached_signal(cache_key: str, signal: str, reason: str):
    _SIGNAL_CACHE[cache_key] = {
        "signal": signal,
        "reason": reason,
        "timestamp": time.time(),
    }


def _get_cached_profile(cache_key: str):
    cached = _PROFILE_CACHE.get(cache_key)
    if not cached:
        return None
    if time.time() - cached["timestamp"] > SIGNAL_CACHE_TTL_SECONDS:
        _PROFILE_CACHE.pop(cache_key, None)
        return None
    return cached["profile"]


def _set_cached_profile(cache_key: str, profile: DeepTCNSignalProfile):
    _PROFILE_CACHE[cache_key] = {
        "profile": profile,
        "timestamp": time.time(),
    }


def run_nightly_retraining_for_symbols(
    symbols: List[str],
    params: Optional[Dict] = None,
    now: Optional[datetime] = None,
    force: bool = False,
) -> Tuple[bool, str]:
    now = now or datetime.now()
    if not TORCH_AVAILABLE:
        return False, TORCH_ERROR_MSG or "PyTorch 不可用"
    if not force and not should_run_nightly_retraining(now=now):
        return False, "不在重训窗口或本轮已完成重训"

    params = params or {}
    unique_symbols = sorted({str(symbol).strip().upper() for symbol in symbols if symbol})
    if not unique_symbols:
        return False, "没有可训练标的"

    success_count = 0
    failure_count = 0
    for symbol in unique_symbols:
        ok, _ = train_and_save_deep_tcn_model(symbol, **params)
        if ok:
            success_count += 1
        else:
            failure_count += 1

    if success_count > 0 and not force:
        mark_nightly_retraining_done(now=now)
    label = "TCN 手动重训完成" if force else "TCN 夜间重训完成"
    return True, f"{label}: 成功 {success_count}, 失败 {failure_count}"


def get_deep_tcn_signal_profile(symbol: str, **kwargs) -> DeepTCNSignalProfile:
    if not TORCH_AVAILABLE:
        return DeepTCNSignalProfile(
            signal="HOLD",
            reason=f"{TORCH_ERROR_MSG or 'PyTorch 未安装'}，深度学习策略暂不可用",
        )

    cache_key = _signal_cache_key(symbol, kwargs)
    cached_profile = _get_cached_profile(cache_key)
    if cached_profile is not None:
        return cached_profile

    prediction = predict_with_saved_deep_tcn_model(
        symbol,
        period=kwargs.get("period", "2y"),
        device=kwargs.get("device", "auto"),
    )
    if prediction is None:
        profile = DeepTCNSignalProfile(
            signal="HOLD",
            reason="TCN 模型未就绪，等待夜间自动重训后再推理",
        )
        _set_cached_profile(cache_key, profile)
        return profile

    prob = float(prediction["probability"])
    expected_return = float(prediction["expected_return"])
    latest_price = float(prediction["latest_price"])
    confidence = max(0.0, min(1.0, abs(prob - 0.5) * 2.0))

    if expected_return > 0.08 and confidence >= 0.70:
        recommended_max_weight_pct = 15.0
    elif expected_return > 0 and confidence >= 0.45:
        recommended_max_weight_pct = 10.0
    else:
        recommended_max_weight_pct = 5.0

    risk_budget = max(0.015, min(0.06, abs(expected_return) * 0.8))
    take_profit_price = latest_price * (1.0 + max(expected_return, 0.01))
    stop_loss_price = latest_price * (1.0 - risk_budget)

    buy_threshold = kwargs.get("buy_threshold", 0.57)
    sell_threshold = kwargs.get("sell_threshold", 0.43)
    min_expected_return = kwargs.get("min_expected_return", 0.005)
    if prob > buy_threshold and expected_return > min_expected_return:
        signal = "BUY"
    elif prob < sell_threshold or expected_return < -min_expected_return:
        signal = "SELL"
    else:
        signal = "HOLD"

    reason = (
        f"TCN({prediction.get('device', 'cpu')}) 预测上涨概率 {prob:.1%}，"
        f"预期收益 {expected_return:.2%}，置信度 {confidence:.1%}。"
    )
    profile = DeepTCNSignalProfile(
        signal=signal,
        reason=reason,
        probability=prob,
        expected_return_pct=expected_return,
        confidence=confidence,
        take_profit_price=take_profit_price,
        stop_loss_price=stop_loss_price,
        recommended_max_weight_pct=recommended_max_weight_pct,
        device=prediction.get("device"),
        trained_at=prediction.get("trained_at"),
    )
    _set_cached_profile(cache_key, profile)
    return profile


def backtest_deep_tcn(
    symbol: str = None,
    data: pd.DataFrame = None,
    sequence_length: int = 60,
    lookback: int = 120,
    train_window: int = 180,
    retrain_freq: int = 20,
    target_horizon: int = 5,
    buy_threshold: float = 0.57,
    sell_threshold: float = 0.43,
    min_expected_return: float = 0.005,
    max_holding_days: int = 20,
    epochs: int = 50,
    batch_size: int = 32,
    learning_rate: float = 0.001,
    hidden_channels: int = 32,
    num_layers: int = 3,
    kernel_size: int = 3,
    dropout: float = 0.15,
    min_train_samples: int = 30,
    device: str = "auto",
    period: str = "2y",
    **kwargs,
) -> Optional[pd.DataFrame]:
    if not TORCH_AVAILABLE:
        raise RuntimeError(TORCH_ERROR_MSG or "PyTorch 不可用")

    if data is not None:
        source = data.copy()
    elif symbol is not None:
        source = yf.Ticker(symbol).history(period=period)
        if source.empty:
            return None
    else:
        raise ValueError("必须提供 symbol 或 data 参数")

    dataset = prepare_deep_learning_dataset(source, sequence_length, target_horizon)
    if len(dataset.features) < max(lookback, min_train_samples + 1):
        return None

    _, _, _, meta_frame = build_feature_target_frame(source, target_horizon)
    meta = meta_frame.reindex(dataset.index).copy()
    meta["pred_prob"] = np.nan
    meta["expected_return"] = np.nan
    meta["Position"] = 0
    meta["Trade"] = 0

    sample_count = len(dataset.features)
    for test_start in range(lookback, sample_count, retrain_freq):
        test_end = min(test_start + retrain_freq, sample_count)
        train_start = max(0, test_start - train_window)

        train_sequences = dataset.features[train_start:test_start]
        train_targets = dataset.targets[train_start:test_start]
        train_returns = dataset.future_returns[train_start:test_start]
        test_sequences = dataset.features[test_start:test_end]
        if len(train_sequences) < min_train_samples or len(test_sequences) == 0:
            continue

        train_scaled, test_scaled = _standardize_sequences(train_sequences, test_sequences)
        probabilities = _train_tcn_predict_proba(
            train_scaled,
            train_targets,
            test_scaled,
            epochs=epochs,
            batch_size=batch_size,
            learning_rate=learning_rate,
            hidden_channels=hidden_channels,
            num_layers=num_layers,
            kernel_size=kernel_size,
            dropout=dropout,
            device=device,
        )
        expected_returns = _estimate_expected_returns(probabilities, train_targets, train_returns)
        target_index = dataset.index[test_start:test_end]
        meta.loc[target_index, "pred_prob"] = probabilities
        meta.loc[target_index, "expected_return"] = expected_returns

    position = 0
    holding_days = 0
    for i in range(1, len(meta)):
        prob = meta["pred_prob"].iloc[i]
        expected_return = meta["expected_return"].iloc[i]
        if pd.isna(prob):
            meta.loc[meta.index[i], "Position"] = position
            holding_days = holding_days + 1 if position > 0 else 0
            continue

        if position == 0:
            if prob > buy_threshold and expected_return > min_expected_return:
                meta.loc[meta.index[i], "Trade"] = 1
                position = 1
                holding_days = 1
            else:
                holding_days = 0
        else:
            holding_days += 1
            should_exit = (
                prob < sell_threshold
                or expected_return < -min_expected_return
                or holding_days >= max_holding_days
            )
            if should_exit:
                meta.loc[meta.index[i], "Trade"] = -1
                position = 0
                holding_days = 0
        meta.loc[meta.index[i], "Position"] = position

    meta["Returns"] = meta["Close"].pct_change()
    meta["Strategy"] = meta["Returns"] * meta["Position"].shift(1)
    return meta


def get_deep_tcn_signal(symbol: str, **kwargs) -> Tuple[str, str]:
    try:
        cache_key = _signal_cache_key(symbol, kwargs)
        cached = _get_cached_signal(cache_key)
        if cached is not None:
            return cached

        profile = get_deep_tcn_signal_profile(symbol, **kwargs)
        signal = profile.signal
        if profile.probability is not None and profile.expected_return_pct is not None:
            reason = (
                f"{profile.reason} 建议仓位上限 {profile.recommended_max_weight_pct:.1f}%"
                if profile.recommended_max_weight_pct is not None
                else profile.reason
            )
        else:
            reason = profile.reason
        _set_cached_signal(cache_key, signal, reason)
        return signal, reason
    except Exception as e:
        return "HOLD", f"信号计算异常：{e}"
