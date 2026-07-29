from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from quant_core import paths as qpaths
from quant_core.models.interfaces import ModelRegistryEntry


DEFAULT_MODEL_REGISTRY_FILE = qpaths.MODEL_REGISTRY_CONFIG_FILE


def default_model_registry() -> dict:
    return {
        "schema_version": 1,
        "models": [
            {
                "model_id": "foundation_quant_engine",
                "display_name": "Foundation Quant Engine",
                "role": "primary_quant_decision",
                "adapter_path": "quant_core.models.foundation.pipeline.run_foundation_job",
                "enabled": True,
                "is_default": True,
                "params": {"horizons": [63, 126, 252], "history_period": "10y", "backend": "auto"},
            },
            {
                "model_id": "finance_multi_asset_transformer",
                "display_name": "Legacy Finance Multi-Asset Transformer",
                "role": "legacy_benchmark",
                "adapter_path": "quant_core.models.multi_horizon.pipeline.run_multi_horizon_job",
                "enabled": False,
                "is_default": False,
                "params": {"horizons": [63, 126, 252], "history_period": "10y"},
            }
        ],
    }


def _read_json(path: str):
    target = Path(path)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_model_registry(config: Mapping, *, path: str = DEFAULT_MODEL_REGISTRY_FILE):
    payload = dict(config or {})
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return str(target)


def load_model_registry(*, path: str = DEFAULT_MODEL_REGISTRY_FILE) -> dict:
    payload = _read_json(path)
    if not isinstance(payload, dict) or not payload:
        payload = default_model_registry()
        save_model_registry(payload, path=path)
    payload.setdefault("schema_version", 1)
    payload.setdefault("models", [])
    return payload


def list_model_entries(*, path: str = DEFAULT_MODEL_REGISTRY_FILE) -> list[ModelRegistryEntry]:
    entries = []
    for row in list(load_model_registry(path=path).get("models", []) or []):
        item = dict(row or {})
        model_id = str(item.get("model_id") or "").strip()
        if not model_id:
            continue
        entries.append(
            ModelRegistryEntry(
                model_id=model_id,
                display_name=str(item.get("display_name") or model_id).strip(),
                role=str(item.get("role") or "signal").strip(),
                adapter_path=str(item.get("adapter_path") or "").strip(),
                enabled=bool(item.get("enabled", True)),
                is_default=bool(item.get("is_default", False)),
                params=dict(item.get("params", {}) or {}),
            )
        )
    return entries
