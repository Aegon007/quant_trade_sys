from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Mapping

from quant_core import paths as qpaths


DEFAULT_SATELLITE_UNIVERSE = {
    "source_indexes": ["sp500", "nasdaq100"],
    "manual_include": [],
    "manual_exclude": [],
    "max_candidate_pool_size": 100,
    "max_deep_analysis_size": 20,
    "max_recommendations": 3,
    "candidate_persistence_days": 2,
}

DEFAULT_SATELLITE_CANDIDATE_POOL_FILE = qpaths.SATELLITE_CANDIDATE_POOL_FILE


def _read_json(path: str):
    target = Path(path)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: str, payload: Mapping):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def _positive_int(value, default: int) -> int:
    try:
        return max(1, int(float(value)))
    except (TypeError, ValueError):
        return default


def normalize_satellite_universe(config) -> dict:
    payload = deepcopy(DEFAULT_SATELLITE_UNIVERSE)
    if not isinstance(config, Mapping):
        return payload
    payload["source_indexes"] = [
        str(item).strip().lower()
        for item in list(config.get("source_indexes", []) or [])
        if str(item).strip()
    ]
    payload["manual_include"] = sorted(
        {
            str(item).strip().upper()
            for item in list(config.get("manual_include", []) or [])
            if str(item).strip()
        }
    )
    payload["manual_exclude"] = sorted(
        {
            str(item).strip().upper()
            for item in list(config.get("manual_exclude", []) or [])
            if str(item).strip()
        }
    )
    for key, default in (
        ("max_candidate_pool_size", 100),
        ("max_deep_analysis_size", 20),
        ("max_recommendations", 3),
        ("candidate_persistence_days", 2),
    ):
        payload[key] = _positive_int(config.get(key), default)
    return payload


def load_satellite_universe(path: str = qpaths.SATELLITE_UNIVERSE_FILE) -> dict:
    return normalize_satellite_universe(_read_json(path))


def save_satellite_universe(config, path: str = qpaths.SATELLITE_UNIVERSE_FILE) -> str:
    return _write_json(path, normalize_satellite_universe(config))


def load_satellite_candidate_pool_snapshot(*, path: str = DEFAULT_SATELLITE_CANDIDATE_POOL_FILE):
    return _read_json(path)


def save_satellite_candidate_pool_snapshot(
    snapshot: Mapping,
    *,
    path: str = DEFAULT_SATELLITE_CANDIDATE_POOL_FILE,
) -> str:
    return _write_json(path, snapshot)
