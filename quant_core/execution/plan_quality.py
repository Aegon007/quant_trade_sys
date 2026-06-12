from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Optional

from quant_core import paths as qpaths


DEFAULT_PLAN_QUALITY_SNAPSHOT_FILE = qpaths.PLAN_QUALITY_SNAPSHOT_FILE


def _safe_float(value, default=None):
    try:
        if value is None:
            return default
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


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


def load_plan_quality_snapshot(*, path: str = DEFAULT_PLAN_QUALITY_SNAPSHOT_FILE):
    return _read_json(path) or {}


def save_plan_quality_snapshot(snapshot: Mapping, *, path: str = DEFAULT_PLAN_QUALITY_SNAPSHOT_FILE):
    return _write_json(path, snapshot)


def _plan_group(row: Mapping, *, core_symbols=None) -> str:
    row = dict(row or {})
    symbol = str(row.get("symbol") or "").strip().upper()
    list_type = str(row.get("list_type") or row.get("focus_role") or "").strip().lower()
    action = str(row.get("plan_action") or row.get("recommended_action") or "").strip().upper()
    core_symbols = {str(item or "").strip().upper() for item in list(core_symbols or []) if str(item or "").strip()}
    if "TACTICAL" in action or list_type == "tactical":
        return "tactical"
    if symbol in core_symbols or list_type in {"core", "core_etf", "etf"}:
        return "core"
    if list_type in {"candidate_pool", "satellite", "watchlist"}:
        return "satellite"
    return "unknown"


def _empty_group():
    return {
        "planned_count": 0,
        "executed_count": 0,
        "missed_count": 0,
        "reachable_count": 0,
        "missed_reachable_count": 0,
        "invalidated_count": 0,
        "unreachable_count": 0,
    }


def _review_rows(review: Mapping):
    rows = []
    for item in list(dict(review or {}).get("items", []) or []):
        row = dict(item or {})
        rows.append(row)
    return rows


def _dedupe_reviews(reviews: Iterable[Mapping]):
    seen = set()
    result = []
    for review in list(reviews or []):
        row = dict(review or {})
        key = (
            str(row.get("review_day") or ""),
            str(row.get("decision_signature") or ""),
            int(_safe_float(row.get("executed_count"), 0) or 0),
            int(_safe_float(row.get("missed_count"), 0) or 0),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def build_plan_quality_snapshot(
    *,
    trade_plan: Optional[Mapping] = None,
    latest_review: Optional[Mapping] = None,
    review_history: Optional[Iterable[Mapping]] = None,
    core_symbols=None,
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.now()
    trade_plan = dict(trade_plan or {})
    latest_review = dict(latest_review or {})
    reviews = _dedupe_reviews([*(list(review_history or [])), latest_review] if latest_review else list(review_history or []))

    planned_items = list(trade_plan.get("items", []) or [])
    groups = {name: _empty_group() for name in ("core", "satellite", "tactical", "unknown")}
    for item in planned_items:
        group_name = _plan_group(item, core_symbols=core_symbols)
        groups[group_name]["planned_count"] += 1

    total_executed = 0
    total_missed = 0
    total_reachable = 0
    total_missed_reachable = 0
    total_unreachable = 0
    total_invalidated = 0
    total_unplanned = 0
    rows = []
    for review in reviews:
        executed = int(_safe_float(review.get("executed_count"), 0) or 0)
        missed = int(_safe_float(review.get("missed_count"), 0) or 0)
        reachable = int(_safe_float(review.get("reachable_count"), 0) or 0)
        missed_reachable = int(_safe_float(review.get("missed_reachable_count"), 0) or 0)
        unreachable = int(_safe_float(review.get("unreachable_count"), 0) or 0)
        invalidated = int(_safe_float(review.get("invalidated_count"), 0) or 0)
        unplanned = int(_safe_float(review.get("unplanned_trade_count"), 0) or 0)
        total_executed += executed
        total_missed += missed
        total_reachable += reachable
        total_missed_reachable += missed_reachable
        total_unreachable += unreachable
        total_invalidated += invalidated
        total_unplanned += unplanned
        rows.append(
            {
                "review_day": review.get("review_day"),
                "decision_signature": review.get("decision_signature"),
                "executed_count": executed,
                "missed_count": missed,
                "reachable_count": reachable,
                "missed_reachable_count": missed_reachable,
                "unreachable_count": unreachable,
                "invalidated_count": invalidated,
                "unplanned_trade_count": unplanned,
            }
        )
        for item in _review_rows(review):
            group_name = _plan_group(item, core_symbols=core_symbols)
            group = groups[group_name]
            if str(item.get("status") or "").strip().upper() == "EXECUTED":
                group["executed_count"] += 1
            else:
                group["missed_count"] += 1
            if item.get("plan_zone_reachable") is True:
                group["reachable_count"] += 1
            if str(item.get("opportunity_status") or "").strip().upper() == "REACHABLE" and str(item.get("status") or "").strip().upper() != "EXECUTED":
                group["missed_reachable_count"] += 1
            if str(item.get("opportunity_status") or "").strip().upper() == "UNREACHABLE":
                group["unreachable_count"] += 1
            if bool(item.get("invalidated_before_entry")):
                group["invalidated_count"] += 1

    denominator = total_executed + total_missed
    execution_rate = (total_executed / denominator) if denominator else None
    actionable_denominator = total_executed + total_missed_reachable
    actionable_execution_rate = (total_executed / actionable_denominator) if actionable_denominator else None

    status = "OK"
    if total_unplanned or total_missed_reachable:
        status = "DEGRADED"
    if denominator == 0 and planned_items:
        status = "PENDING"

    return {
        "generated_at": now.isoformat(),
        "status": status,
        "summary": {
            "status": status,
            "current_plan_decision": trade_plan.get("decision"),
            "current_action_count": int(_safe_float(trade_plan.get("action_count"), len(planned_items)) or 0),
            "review_count": len(reviews),
            "executed_count": total_executed,
            "missed_count": total_missed,
            "unplanned_trade_count": total_unplanned,
            "reachable_count": total_reachable,
            "missed_reachable_count": total_missed_reachable,
            "unreachable_count": total_unreachable,
            "invalidated_count": total_invalidated,
            "execution_rate": execution_rate,
            "actionable_execution_rate": actionable_execution_rate,
        },
        "groups": groups,
        "recent_reviews": rows[-20:],
        "current_plan": {
            "plan_date": trade_plan.get("plan_date"),
            "decision": trade_plan.get("decision"),
            "decision_signature": trade_plan.get("decision_signature"),
            "summary_reason": trade_plan.get("summary_reason"),
            "items": planned_items,
        },
    }
