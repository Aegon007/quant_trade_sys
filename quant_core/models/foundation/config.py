from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from quant_core import paths as qpaths


DEFAULT_CONFIG_FILE = qpaths.FOUNDATION_MODEL_CONFIG_FILE


DEFAULT_CONFIG = {
    "schema_version": 1,
    "enabled": True,
    "model_id": "foundation_quant_engine",
    "default_backend": "auto",
    "backend_priority": ["chronos", "timesfm", "moment"],
    "require_real_backend": True,
    "allow_development_proxy": False,
    "history_period": "10y",
    "horizons": [63, 126, 252],
    "risk_free_benchmark": "BIL",
    "market_benchmark": "SPY",
    "growth_benchmark": "QQQ",
    "maximum_symbols": 100,
    "model_presets": {
        "chronos_2_small": {
            "label": "Chronos-2 Small",
            "backend": "chronos",
            "model_name": "autogluon/chronos-2-small",
            "parameter_count": "28M",
            "profile": "Small Chronos-2 variant for constrained local inference.",
        },
        "chronos_2": {
            "label": "Chronos-2",
            "backend": "chronos",
            "model_name": "amazon/chronos-2",
            "parameter_count": "120M",
            "profile": "Default universal forecasting model with multivariate/covariate support.",
        },
    },
    "backends": {
        "timesfm": {
            "enabled": False,
            "model_name": "google/timesfm-2.5-200m-pytorch",
            "supports_covariates": True,
        },
        "chronos": {
            "enabled": True,
            "model_name": "amazon/chronos-2",
            "revision": "",
            "supports_covariates": True,
            "device": "auto",
            "torch_dtype": "auto",
            "context_length": 2048,
            "batch_size": 8,
            "cross_learning": False,
            "quantile_levels": [0.1, 0.5, 0.9],
        },
        "moment": {
            "enabled": False,
            "model_name": "AutonLab/MOMENT-1-large",
            "supports_covariates": False,
        },
        "proxy": {
            "enabled": False,
            "lookback_days": 756,
            "trend_adjustment_weight": 0.35,
        },
    },
    "decision": {
        "core_max_weight_pct": 70.0,
        "satellite_max_weight_pct": 5.0,
        "minimum_core_weight_delta_pct": 3.0,
        "minimum_upside_probability": 0.55,
        "minimum_risk_free_outperformance_probability": 0.52,
    },
    "training_data": {
        "enabled": True,
        "retention_days": 1825,
    },
}


def normalize_foundation_model_config(config: Mapping | None = None) -> dict:
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for key, value in dict(config or {}).items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            nested = dict(merged[key])
            for nested_key, nested_value in dict(value).items():
                if isinstance(nested_value, Mapping) and isinstance(nested.get(nested_key), Mapping):
                    nested[nested_key] = {**dict(nested[nested_key]), **dict(nested_value)}
                else:
                    nested[nested_key] = nested_value
            merged[key] = nested
        else:
            merged[key] = value

    horizons = []
    for value in list(merged.get("horizons", []) or []):
        try:
            horizon = int(value)
        except (TypeError, ValueError):
            continue
        if horizon > 0 and horizon not in horizons:
            horizons.append(horizon)
    merged["horizons"] = horizons or list(DEFAULT_CONFIG["horizons"])
    merged["maximum_symbols"] = max(int(merged.get("maximum_symbols") or 100), 2)
    merged["history_period"] = str(merged.get("history_period") or "10y")
    merged["risk_free_benchmark"] = str(merged.get("risk_free_benchmark") or "BIL").strip().upper()
    merged["market_benchmark"] = str(merged.get("market_benchmark") or "SPY").strip().upper()
    merged["growth_benchmark"] = str(merged.get("growth_benchmark") or "QQQ").strip().upper()
    merged["enabled"] = bool(merged.get("enabled", True))
    merged["require_real_backend"] = bool(merged.get("require_real_backend", True))
    merged["allow_development_proxy"] = bool(merged.get("allow_development_proxy", False))
    merged["model_presets"] = json.loads(json.dumps(DEFAULT_CONFIG["model_presets"]))
    chronos_config = dict(dict(merged.get("backends", {}) or {}).get("chronos", {}) or {})
    model_name = str(chronos_config.get("model_name") or "").strip().lower()
    if not model_name or "chronos-bolt" in model_name:
        chronos_config["model_name"] = "amazon/chronos-2"
    chronos_config["supports_covariates"] = True
    chronos_config.setdefault("context_length", 2048)
    chronos_config.setdefault("cross_learning", False)
    merged.setdefault("backends", {})
    merged["backends"]["chronos"] = {**dict(DEFAULT_CONFIG["backends"]["chronos"]), **chronos_config}
    training_data = dict(merged.get("training_data", {}) or {})
    training_data["enabled"] = bool(training_data.get("enabled", True))
    training_data["retention_days"] = max(int(training_data.get("retention_days") or 1825), 30)
    merged["training_data"] = training_data
    merged["backend_priority"] = [
        str(name or "").strip().lower()
        for name in list(merged.get("backend_priority", []) or [])
        if str(name or "").strip()
    ] or list(DEFAULT_CONFIG["backend_priority"])
    return merged


def load_foundation_model_config(*, path: str = DEFAULT_CONFIG_FILE) -> dict:
    target = Path(path)
    if not target.exists():
        config = normalize_foundation_model_config()
        save_foundation_model_config(config, path=path)
        return config
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    return normalize_foundation_model_config(payload if isinstance(payload, Mapping) else {})


def save_foundation_model_config(config: Mapping, *, path: str = DEFAULT_CONFIG_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(normalize_foundation_model_config(config), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return str(target)
