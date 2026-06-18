from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Mapping

from quant_core import paths as qpaths


DEFAULT_CONFIG_FILE = qpaths.MULTI_HORIZON_MODEL_CONFIG_FILE
DEFAULT_CONFIG = {
    "schema_version": 1,
    "enabled": True,
    "model_id": "finance_multi_asset_transformer",
    "role": "primary_quant_decision_candidate",
    "history_period": "10y",
    "horizons": [63, 126, 252],
    "lookback": 252,
    "observation_frequency": "W-FRI",
    "maximum_training_symbols": 100,
    "architecture": {
        "d_model": 64,
        "temporal_layers": 2,
        "cross_asset_layers": 2,
        "attention_heads": 4,
        "feedforward_multiplier": 4,
        "dropout": 0.1,
        "patch_size": 10,
        "patch_stride": 5,
        "expert_count": 4,
        "top_k_experts": 2,
    },
    "training": {
        "epochs": 30,
        "batch_size": 8,
        "learning_rate": 3e-4,
        "weight_decay": 1e-4,
        "device": "auto",
        "pretraining_epochs": 5,
        "walk_forward_epochs": 5,
        "retrain_interval_days": 30,
    },
    "artifacts": {
        "checkpoint_path": qpaths.MULTI_HORIZON_CHECKPOINT_FILE,
        "pretraining_checkpoint_path": qpaths.MULTI_HORIZON_PRETRAIN_CHECKPOINT_FILE,
        "snapshot_path": qpaths.MULTI_HORIZON_SNAPSHOT_FILE,
        "validation_path": qpaths.MULTI_HORIZON_VALIDATION_FILE,
        "panel_path": qpaths.MULTI_HORIZON_PANEL_FILE,
    },
    "promotion": {"automatic": False},
    "traditional_ml_policy": {
        "production_enabled": False,
        "allow_only_after_positive_ablation": True,
    },
}


def normalize_multi_horizon_config(config: Mapping | None = None) -> dict:
    normalized = deepcopy(DEFAULT_CONFIG)
    for key, value in dict(config or {}).items():
        if isinstance(value, Mapping) and isinstance(normalized.get(key), Mapping):
            normalized[key].update(dict(value))
        else:
            normalized[key] = value
    normalized["horizons"] = sorted({max(int(value), 1) for value in normalized.get("horizons", [])})
    normalized["lookback"] = max(int(normalized.get("lookback", 252)), 40)
    normalized["maximum_training_symbols"] = max(int(normalized.get("maximum_training_symbols", 100)), 2)
    training = normalized["training"]
    for key, default in (
        ("epochs", 30),
        ("pretraining_epochs", 5),
        ("walk_forward_epochs", 5),
        ("retrain_interval_days", 30),
        ("batch_size", 8),
    ):
        training[key] = max(int(training.get(key, default)), 1)
    normalized["promotion"]["automatic"] = False
    # Traditional models are offline controls only. Production admission
    # requires a future explicit governance change backed by ablation results.
    normalized["traditional_ml_policy"]["production_enabled"] = False
    return normalized


def load_multi_horizon_config(*, path: str = DEFAULT_CONFIG_FILE) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return normalize_multi_horizon_config()
    return normalize_multi_horizon_config(payload)


def save_multi_horizon_config(config: Mapping, *, path: str = DEFAULT_CONFIG_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(normalize_multi_horizon_config(config), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return str(target)
