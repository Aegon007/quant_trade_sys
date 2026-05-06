"""
Deep learning strategy utilities based on a lightweight Temporal CNN.

PyTorch is an optional dependency. The module can still be imported without it
so the rest of the app remains usable on environments that have not installed a
deep learning backend yet.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
import warnings

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


@dataclass
class DeepLearningDataset:
    features: np.ndarray
    targets: np.ndarray
    future_returns: np.ndarray
    index: pd.Index
    feature_columns: List[str]


def select_device_name(preferred: str = "auto", cuda_available: bool = False, mps_available: bool = False) -> str:
    """Select the safest available torch device name for the current platform."""
    preferred = (preferred or "auto").lower()
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
    feature_count = train_sequences.shape[-1]
    flat_train = train_sequences.reshape(-1, feature_count)
    mean = flat_train.mean(axis=0)
    std = flat_train.std(axis=0)
    std = np.where(std < 1e-8, 1.0, std)
    return (
        ((train_sequences - mean) / std).astype(np.float32),
        ((test_sequences - mean) / std).astype(np.float32),
    )


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
    epochs: int = 20,
    batch_size: int = 32,
    learning_rate: float = 0.001,
    hidden_channels: int = 32,
    num_layers: int = 3,
    kernel_size: int = 3,
    dropout: float = 0.15,
    min_train_samples: int = 30,
    device: str = "auto",
    period: str = "3y",
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
    if not TORCH_AVAILABLE:
        return "HOLD", f"{TORCH_ERROR_MSG or 'PyTorch 未安装'}，深度学习策略暂不可用"

    try:
        result = backtest_deep_tcn(symbol=symbol, **kwargs)
        if result is None or result["pred_prob"].dropna().empty:
            return "HOLD", "历史数据或有效预测不足"

        latest = result.dropna(subset=["pred_prob"]).iloc[-1]
        prob = float(latest["pred_prob"])
        expected_return = float(latest.get("expected_return", 0.0))
        buy_threshold = kwargs.get("buy_threshold", 0.57)
        sell_threshold = kwargs.get("sell_threshold", 0.43)
        min_expected_return = kwargs.get("min_expected_return", 0.005)
        device_name = str(resolve_torch_device(kwargs.get("device", "auto")))

        if prob > buy_threshold and expected_return > min_expected_return:
            return "BUY", f"TCN({device_name}) 预测上涨概率 {prob:.1%}，预期收益 {expected_return:.2%}，建议买入"
        if prob < sell_threshold or expected_return < -min_expected_return:
            return "SELL", f"TCN({device_name}) 预测上涨概率 {prob:.1%}，预期收益 {expected_return:.2%}，建议卖出"
        return "HOLD", f"TCN({device_name}) 预测上涨概率 {prob:.1%}，预期收益 {expected_return:.2%}，建议持有"
    except Exception as e:
        return "HOLD", f"信号计算异常：{e}"
