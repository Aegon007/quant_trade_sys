from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths
from quant_core.llm import explainer


DEFAULT_DECISION_BRIEF_FILE = qpaths.DECISION_BRIEF_FILE
_ACTIONABLE = {"ACCUMULATE", "PROBE", "TRIM", "EXIT", "REDUCE"}


def _dict(value) -> dict:
    return dict(value or {}) if isinstance(value, Mapping) else {}


def _action(row: Mapping) -> str:
    row = _dict(row)
    decision = _dict(row.get("decision") or row.get("model_decision"))
    return str(decision.get("action") or row.get("final_action") or row.get("action") or "").strip().upper()


def _compact_model_row(row: Mapping) -> dict:
    row = _dict(row)
    decision = _dict(row.get("decision") or row.get("model_decision"))
    long_horizon = _dict(row.get("long_horizon"))
    timing = _dict(row.get("timing"))
    risk = _dict(row.get("risk"))
    return {
        "symbol": str(row.get("symbol") or "").strip().upper(),
        "action": _action(row) or "HOLD",
        "long_horizon": long_horizon.get("state"),
        "long_rank": long_horizon.get("blended_rank"),
        "timing": timing.get("state"),
        "target_weight_range_pct": decision.get("target_weight_range_pct"),
        "reason_codes": list(decision.get("reason_codes", []) or []),
        "downside": risk.get("maximum_adverse_excursion"),
    }


def build_decision_context(
    *,
    account: Optional[Mapping] = None,
    multi_horizon_snapshot: Optional[Mapping] = None,
    core_etf_snapshot: Optional[Mapping] = None,
    satellite_candidate_snapshot: Optional[Mapping] = None,
    discipline_snapshot: Optional[Mapping] = None,
    trade_plan: Optional[Mapping] = None,
    change_feed: Optional[Mapping] = None,
    news_intelligence: Optional[Mapping] = None,
    market_monitor_snapshot: Optional[Mapping] = None,
    data_health_snapshot: Optional[Mapping] = None,
    plan_quality_snapshot: Optional[Mapping] = None,
    analyst_context: Optional[Mapping] = None,
    intraday_events=None,
) -> dict:
    model = _dict(multi_horizon_snapshot)
    model_rows = [_compact_model_row(row) for row in list(model.get("symbols", []) or [])]
    approved = [row for row in model_rows if row["action"] in _ACTIONABLE]
    conflicts = [
        row
        for row in model_rows
        if str(row.get("long_horizon") or "").upper() == "ATTRACTIVE"
        and str(row.get("timing") or "").upper() in {"DETERIORATING", "FAILED"}
    ]
    core = _dict(core_etf_snapshot)
    core_rows = [_compact_model_row(row) for row in list(core.get("symbols", []) or [])]
    satellite = _dict(satellite_candidate_snapshot)
    satellite_rows = [
        _compact_model_row(row)
        for row in list(satellite.get("top_recommendations", []) or satellite.get("symbols", []) or [])[:5]
    ]
    discipline = _dict(discipline_snapshot)
    plan = _dict(trade_plan)
    feed = _dict(change_feed)
    news = _dict(news_intelligence)
    monitor = _dict(market_monitor_snapshot)
    health = _dict(data_health_snapshot)
    quality = _dict(plan_quality_snapshot)
    plan_items = list(plan.get("items", []) or [])
    executable_items = [
        dict(row or {})
        for row in plan_items
        if str(dict(row or {}).get("plan_action") or dict(row or {}).get("action") or "").strip().upper()
        not in {"", "HOLD", "WATCH", "NO_ACTION"}
    ]
    has_executable_plan = bool(plan.get("has_actions")) or bool(executable_items)
    return {
        "account": {
            key: _dict(account).get(key)
            for key in ("total_capital", "cash_available", "deployable_cash", "exposure_pct", "holdings_market_value")
        },
        "model": {
            "status": model.get("status"),
            "generated_at": model.get("generated_at"),
            "summary": _dict(model.get("summary")),
        },
        "all_model_signals": model_rows,
        "approved_actions": approved[:10],
        "signal_conflicts": conflicts,
        "core_etfs": core_rows,
        "satellite_top": satellite_rows,
        "discipline": {
            "regime": discipline.get("regime"),
            "risk_regime": discipline.get("risk_regime"),
            "target_exposure_pct": discipline.get("target_exposure_pct"),
            "can_open_new_core_positions": discipline.get("can_open_new_core_positions"),
            "can_open_new_satellite_positions": discipline.get("can_open_new_satellite_positions"),
            "summary": discipline.get("summary"),
        },
        "trade_plan": {
            "decision": plan.get("decision"),
            "has_actions": has_executable_plan,
            "action_count": plan.get("action_count"),
            "summary_reason": plan.get("summary_reason"),
            "items": plan_items[:10],
        },
        "canonical_decision": {
            "mode": "ACTION" if has_executable_plan else "NO_ACTION",
            "instruction": (
                "Only trade-plan items are executable. Raw model actions are candidates for review, not orders."
            ),
            "executable_items": executable_items[:10],
            "raw_model_action_count": len(approved),
        },
        "high_priority_changes": list(feed.get("high_items", []) or []),
        "medium_priority_changes": list(feed.get("medium_items", []) or []),
        "news": {
            "status": news.get("status"),
            "market_risk_level": news.get("market_risk_level"),
            "executive_summary": news.get("executive_summary"),
            "portfolio_impacts": list(news.get("portfolio_impacts", []) or [])[:6],
        },
        "market_monitor": {
            "status": monitor.get("status"),
            "summary": _dict(monitor.get("summary")),
        },
        "data_health": {
            "status": health.get("status") or _dict(health.get("summary")).get("status"),
            "summary": _dict(health.get("summary")),
        },
        "plan_quality": {
            "status": quality.get("status") or _dict(quality.get("summary")).get("status"),
            "summary": _dict(quality.get("summary")),
        },
        "analyst_context": _dict(analyst_context),
        "intraday_events": [dict(row or {}) for row in list(intraday_events or [])[:5]],
    }


def _read_json(path: str) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def build_current_decision_context(*, data: Optional[Mapping] = None, intraday_events=None) -> dict:
    from quant_core.data import storage as data_storage
    from quant_core.snapshots import system_snapshot

    portfolio_data = dict(data or data_storage.load_data() or {})
    news_intelligence = _read_json(qpaths.NEWS_INTELLIGENCE_FILE)
    try:
        account = system_snapshot.build_account_snapshot(portfolio_data)
    except (KeyError, TypeError, ValueError):
        account = dict(portfolio_data.get("account", {}) or {})
    return build_decision_context(
        account=account,
        multi_horizon_snapshot=_read_json(qpaths.MULTI_HORIZON_SNAPSHOT_FILE),
        core_etf_snapshot=_read_json(qpaths.CORE_ETF_SNAPSHOT_FILE),
        satellite_candidate_snapshot=_read_json(qpaths.SATELLITE_CANDIDATE_POOL_FILE),
        discipline_snapshot=_read_json(qpaths.DISCIPLINE_SNAPSHOT_FILE),
        trade_plan=_read_json(qpaths.NEXT_DAY_TRADE_PLAN_FILE),
        change_feed=_read_json(qpaths.CHANGE_FEED_FILE),
        news_intelligence=news_intelligence,
        market_monitor_snapshot=_read_json(qpaths.MARKET_MONITOR_SNAPSHOT_FILE),
        data_health_snapshot=_read_json(qpaths.DATA_HEALTH_SNAPSHOT_FILE),
        plan_quality_snapshot=_read_json(qpaths.PLAN_QUALITY_SNAPSHOT_FILE),
        analyst_context=_dict(news_intelligence.get("analyst_context")),
        intraday_events=intraday_events,
    )


def decision_signature(context: Mapping) -> str:
    material = _dict(context)
    model = _dict(material.get("model"))
    model.pop("generated_at", None)
    material["model"] = model
    digest = hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return digest


def _fallback_summary(context: Mapping) -> str:
    context = _dict(context)
    discipline = _dict(context.get("discipline"))
    approved = list(context.get("approved_actions", []) or [])
    conflicts = list(context.get("signal_conflicts", []) or [])
    changes = list(context.get("high_priority_changes", []) or [])
    canonical = _dict(context.get("canonical_decision"))
    regime = str(discipline.get("regime") or "UNKNOWN")
    risk = str(discipline.get("risk_regime") or "UNKNOWN")
    if str(canonical.get("mode") or "").upper() == "ACTION":
        executable = list(canonical.get("executable_items", []) or [])
        action_text = "；".join(
            f"{row.get('symbol')} {row.get('plan_action') or row.get('action')}" for row in executable[:3]
        )
        opening = f"当前纪律状态 {regime}、风险状态 {risk}，需要复核的动作：{action_text}。"
    else:
        opening = f"当前纪律状态 {regime}、风险状态 {risk}，无强交易信号，默认保持不动。"
        if approved:
            opening += f" 模型层有 {len(approved)} 个候选动作，但尚未进入可执行次日计划。"
    notes = []
    if conflicts:
        notes.append(f"{len(conflicts)} 个长期与入场时机冲突")
    if changes:
        notes.append(f"{len(changes)} 个高优先级异动")
    return opening + (f" 同时存在{'、'.join(notes)}。" if notes else "")


def load_decision_brief(*, path: str = DEFAULT_DECISION_BRIEF_FILE) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_decision_brief(payload: Mapping, *, path: str = DEFAULT_DECISION_BRIEF_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(payload or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return str(target)


def refresh_decision_brief(
    *,
    context: Mapping,
    notification_config: Mapping,
    trigger: str,
    force: bool = False,
    llm_runner=None,
    path: str = DEFAULT_DECISION_BRIEF_FILE,
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.now()
    signature = decision_signature(context)
    previous = load_decision_brief(path=path)
    if not force and previous.get("material_signature") == signature:
        return {**previous, "refreshed": False}

    llm_runner = llm_runner or explainer.summarize_trading_system
    ok, text, meta = llm_runner(
        decision_context=context,
        notification_config=notification_config,
    )
    snapshot = {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "status": "READY" if ok else "STRUCTURED_ONLY",
        "trigger": str(trigger or "UNKNOWN").strip().upper(),
        "material_signature": signature,
        "executive_summary": str(text or "").strip() if ok else _fallback_summary(context),
        "approved_action_count": len(list(_dict(context).get("approved_actions", []) or [])),
        "conflict_count": len(list(_dict(context).get("signal_conflicts", []) or [])),
        "high_priority_change_count": len(list(_dict(context).get("high_priority_changes", []) or [])),
        "context": dict(context or {}),
        "llm": {
            "route_name": str(_dict(meta).get("route_name") or ""),
            "model": str(_dict(meta).get("model") or ""),
            "cached": bool(_dict(meta).get("cached")),
            "fallback_attempts": list(_dict(meta).get("fallback_attempts", []) or []),
            "error": "" if ok else str(text or "").strip(),
        },
        "refreshed": True,
    }
    save_decision_brief(snapshot, path=path)
    return snapshot
