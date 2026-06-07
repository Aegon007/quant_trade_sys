from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths


DEFAULT_NIGHTLY_DECISION_JOURNAL_FILE = qpaths.NIGHTLY_DECISION_JOURNAL_FILE


def _safe_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def build_nightly_decision_entry(snapshot: Optional[Mapping]) -> dict:
    snapshot = dict(snapshot or {})
    trade_plan = dict(snapshot.get("trade_plan", {}) or {})
    core_etf_snapshot = dict(snapshot.get("core_etf_snapshot", {}) or {})
    satellite_snapshot = dict(snapshot.get("satellite_candidate_snapshot", {}) or {})
    discipline_snapshot = dict(snapshot.get("discipline_snapshot", {}) or {})
    monthly_discipline_review = dict(snapshot.get("monthly_discipline_review", {}) or {})
    strategy_validation_snapshot = dict(snapshot.get("strategy_validation_snapshot", {}) or {})
    change_feed = dict(snapshot.get("change_feed", {}) or {})
    risk = dict(snapshot.get("risk", {}) or {})
    allocation_regime = dict(snapshot.get("allocation_regime", {}) or {})
    execution_review = dict(snapshot.get("execution_review", {}) or {})

    change_messages = [
        str(item.get("message") or "").strip()
        for item in list(change_feed.get("high_items", []) or [])[:5]
        if str(item.get("message") or "").strip()
    ]
    top_recommendations = []
    for row in list(satellite_snapshot.get("top_recommendations", []) or [])[:3]:
        top_recommendations.append(
            {
                "symbol": str(row.get("symbol") or "").strip().upper(),
                "status": str(row.get("recommendation_status") or row.get("candidate_state") or "").strip().upper(),
                "score": _safe_float(row.get("satellite_score")),
                "weight_pct": _safe_float(row.get("suggested_weight_pct")),
                "membership_state": str(row.get("top3_membership_state") or "").strip().upper() or None,
            }
        )
    core_rows = []
    for row in list(core_etf_snapshot.get("symbols", []) or []):
        core_rows.append(
            {
                "symbol": str(row.get("symbol") or "").strip().upper(),
                "action": str(row.get("action") or "").strip().upper(),
                "rotation_score": _safe_float(row.get("rotation_score")),
                "signal_stability_score": _safe_float(row.get("signal_stability_score")),
                "current_weight_pct": _safe_float(row.get("current_weight_pct")),
                "target_weight_pct": _safe_float(row.get("target_weight_pct")),
            }
        )
    plan_items = []
    for item in list(trade_plan.get("items", []) or [])[:12]:
        plan_items.append(
            {
                "symbol": str(item.get("symbol") or "").strip().upper(),
                "action": str(item.get("plan_action") or "").strip().upper(),
                "weight_delta_pct": _safe_float(item.get("plan_weight_delta_pct")),
                "buy_zone_low": _safe_float(item.get("buy_zone_low")),
                "buy_zone_high": _safe_float(item.get("buy_zone_high")),
                "trim_zone_low": _safe_float(item.get("trim_zone_low")),
                "trim_zone_high": _safe_float(item.get("trim_zone_high")),
                "risk_break_level": _safe_float(item.get("risk_break_level")),
            }
        )

    return {
        "generated_at": snapshot.get("generated_at"),
        "plan_date": trade_plan.get("plan_date"),
        "decision_signature": snapshot.get("decision_signature") or trade_plan.get("decision_signature"),
        "trade_plan_decision": trade_plan.get("decision"),
        "has_actions": bool(trade_plan.get("has_actions")),
        "action_count": int(_safe_float(trade_plan.get("action_count"), 0) or 0),
        "summary_reason": str(trade_plan.get("summary_reason") or "").strip(),
        "risk_regime": str(risk.get("regime") or "").strip().upper() or None,
        "allocation_regime": str(allocation_regime.get("regime") or "").strip().upper() or None,
        "discipline_regime": str(discipline_snapshot.get("regime") or "").strip().upper() or None,
        "monthly_discipline_status": str(monthly_discipline_review.get("status") or "").strip().upper() or None,
        "strategy_validation_status": str(dict(strategy_validation_snapshot.get("summary", {}) or {}).get("status") or "").strip().upper() or None,
        "core_focus_symbols": list((core_etf_snapshot.get("summary", {}) or {}).get("focus_symbols", []) or []),
        "top3_symbols": list((satellite_snapshot.get("summary", {}) or {}).get("top_symbols", []) or []),
        "high_priority_change_messages": change_messages,
        "execution_review": {
            "status": str(execution_review.get("status") or "").strip().upper() or None,
            "executed_count": int(_safe_float(execution_review.get("executed_count"), 0) or 0),
            "missed_count": int(_safe_float(execution_review.get("missed_count"), 0) or 0),
            "unplanned_trade_count": int(_safe_float(execution_review.get("unplanned_trade_count"), 0) or 0),
        },
        "core_etf_rows": core_rows,
        "top_recommendations": top_recommendations,
        "plan_items": plan_items,
    }


def append_nightly_decision_journal(
    snapshot: Optional[Mapping],
    *,
    journal_path: str = DEFAULT_NIGHTLY_DECISION_JOURNAL_FILE,
) -> str:
    entry = build_nightly_decision_entry(snapshot)
    target = Path(journal_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return str(target)


def load_nightly_decision_journal(*, journal_path: str = DEFAULT_NIGHTLY_DECISION_JOURNAL_FILE, limit=None):
    target = Path(journal_path)
    if not target.exists():
        return []
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines():
        text = str(line or "").strip()
        if not text:
            continue
        try:
            rows.append(json.loads(text))
        except Exception:
            continue
    if limit is not None:
        return rows[-max(0, int(limit or 0)) :]
    return rows
