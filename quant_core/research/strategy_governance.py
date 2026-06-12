from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Optional

from quant_core import paths as qpaths
from quant_core.research import strategy_validation
from strategies import ui as strategy_config


DEFAULT_STRATEGY_REGISTRY_STATE_FILE = qpaths.STRATEGY_REGISTRY_STATE_FILE


def _read_json(path: str):
    target = Path(path)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: str, payload: Mapping):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload or {}), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return str(target)


def load_strategy_registry_state(*, path: str = DEFAULT_STRATEGY_REGISTRY_STATE_FILE):
    return _read_json(path) or {}


def save_strategy_registry_state(snapshot: Mapping, *, path: str = DEFAULT_STRATEGY_REGISTRY_STATE_FILE):
    return _write_json(path, snapshot)


def _default_strategy_id(strategies):
    for row in list(strategies or []):
        if bool(dict(row or {}).get("is_default")):
            return str(dict(row or {}).get("id") or "").strip()
    for row in list(strategies or []):
        if bool(dict(row or {}).get("enabled", True)):
            return str(dict(row or {}).get("id") or "").strip()
    return ""


def _candidate_leaders(validation_snapshot: Mapping, default_id: str):
    leaders = {}
    for row in list(dict(validation_snapshot or {}).get("symbols", []) or []):
        best_id = str(dict(row or {}).get("best_strategy_id") or "").strip()
        if best_id and best_id != default_id:
            leaders[best_id] = leaders.get(best_id, 0) + 1
    return leaders


def build_strategy_governance_snapshot(
    *,
    strategies: Optional[Iterable[Mapping]] = None,
    validation_snapshot: Optional[Mapping] = None,
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.now()
    strategies = list(strategies if strategies is not None else strategy_config.load_strategies(include_disabled=True))
    validation_snapshot = dict(validation_snapshot or strategy_validation.load_strategy_validation_snapshot() or {})
    validation_summary = dict(validation_snapshot.get("summary", {}) or {})
    default_id = _default_strategy_id(strategies)
    validation_status = str(validation_summary.get("status") or "NO_DATA").strip().upper()
    leaders = _candidate_leaders(validation_snapshot, default_id)

    registry = []
    recommendations = []
    for strategy in strategies:
        row = dict(strategy or {})
        strategy_id = str(row.get("id") or "").strip()
        if not strategy_id:
            continue
        enabled = bool(row.get("enabled", True))
        is_default = strategy_id == default_id
        if not enabled:
            lifecycle = "DISABLED"
            recommendation = "Do not use until explicitly re-enabled."
        elif is_default and validation_status == "REVIEW":
            lifecycle = "REVIEW"
            recommendation = "Keep current default for now, but review downgrade candidates before next production change."
            recommendations.append(
                {
                    "type": "DEFAULT_REVIEW",
                    "strategy_id": strategy_id,
                    "message": "默认策略处于 REVIEW；先复核，不自动切换。",
                }
            )
        elif is_default:
            lifecycle = "PRODUCTION"
            recommendation = "Continue as default; no automatic switch required."
        elif leaders.get(strategy_id, 0) >= 2:
            lifecycle = "PROMOTION_WATCH"
            recommendation = "Candidate leads multiple validation targets; consider paper review before promotion."
            recommendations.append(
                {
                    "type": "PROMOTION_WATCH",
                    "strategy_id": strategy_id,
                    "message": f"{strategy_id} 在 {leaders[strategy_id]} 个目标上领先，可进入候选观察。",
                }
            )
        else:
            lifecycle = "CANDIDATE" if enabled else "DISABLED"
            recommendation = "Candidate only; requires validation before production use."
        registry.append(
            {
                "strategy_id": strategy_id,
                "name": row.get("name") or strategy_id,
                "enabled": enabled,
                "is_default": is_default,
                "lifecycle_state": lifecycle,
                "leader_count": leaders.get(strategy_id, 0),
                "recommendation": recommendation,
            }
        )

    status = "REVIEW" if any(row["lifecycle_state"] == "REVIEW" for row in registry) else "OK"
    return {
        "generated_at": now.isoformat(),
        "status": status,
        "summary": {
            "status": status,
            "default_strategy_id": default_id or None,
            "validation_status": validation_status,
            "strategy_count": len(registry),
            "review_count": sum(1 for row in registry if row["lifecycle_state"] == "REVIEW"),
            "promotion_watch_count": sum(1 for row in registry if row["lifecycle_state"] == "PROMOTION_WATCH"),
            "message": "策略治理要求人工确认，不自动切换默认策略。",
        },
        "strategies": registry,
        "recommendations": recommendations,
        "validation_snapshot": validation_snapshot,
    }
