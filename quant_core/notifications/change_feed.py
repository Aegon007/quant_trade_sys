from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths


DEFAULT_CHANGE_FEED_FILE = qpaths.CHANGE_FEED_FILE
DEFAULT_INTRADAY_ALERT_STATE_FILE = qpaths.INTRADAY_ALERT_STATE_FILE


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
    target.write_text(json.dumps(dict(payload or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


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


def _snapshot_map(snapshot: Optional[Mapping], *, key: str = "symbol") -> dict:
    mapped = {}
    for row in list((snapshot or {}).get("symbols", []) or []):
        symbol = str((row or {}).get(key, "")).strip().upper()
        if symbol:
            mapped[symbol] = dict(row or {})
    return mapped


def load_change_feed(*, path: str = DEFAULT_CHANGE_FEED_FILE):
    return _read_json(path)


def save_change_feed(feed: Mapping, *, path: str = DEFAULT_CHANGE_FEED_FILE) -> str:
    return _write_json(path, feed)


def load_intraday_alert_state(*, path: str = DEFAULT_INTRADAY_ALERT_STATE_FILE):
    return _read_json(path)


def save_intraday_alert_state(state: Mapping, *, path: str = DEFAULT_INTRADAY_ALERT_STATE_FILE) -> str:
    return _write_json(path, state)


def _add_item(
    items,
    *,
    priority: str,
    category: str,
    title: str,
    message: str,
    symbol: Optional[str] = None,
    reason_codes=None,
    before_value=None,
    after_value=None,
    explanation_summary: str = "",
    explanation_bullets=None,
):
    items.append(
        {
            "priority": str(priority or "LOW").upper(),
            "category": str(category or "general"),
            "title": str(title or "").strip(),
            "message": str(message or "").strip(),
            "symbol": str(symbol or "").strip().upper() or None,
            "reason_codes": [
                str(item).strip()
                for item in list(reason_codes or [])
                if str(item).strip()
            ],
            "details": {
                "before_value": before_value,
                "after_value": after_value,
            },
            "explanation_summary": str(explanation_summary or message or "").strip(),
            "explanation_bullets": [
                str(item).strip()
                for item in list(explanation_bullets or [])
                if str(item).strip()
            ],
        }
    )


def _discipline_month_rank(status: str) -> int:
    normalized = str(status or "").strip().upper()
    ranks = {
        "ALIGNED": 0,
        "MONITOR": 1,
        "CAUTION": 2,
    }
    return ranks.get(normalized, 1)


def select_priority_items(
    feed: Optional[Mapping],
    *,
    priority: str = "HIGH",
    categories=None,
    limit: Optional[int] = None,
):
    feed = dict(feed or {})
    priority = str(priority or "HIGH").strip().upper()
    key = {
        "HIGH": "high_items",
        "MEDIUM": "medium_items",
        "LOW": "low_items",
    }.get(priority, "items")
    rows = list(feed.get(key, []) or [])
    category_filter = {str(item).strip().lower() for item in list(categories or []) if str(item).strip()}
    if category_filter:
        rows = [row for row in rows if str(row.get("category") or "").strip().lower() in category_filter]
    if limit is not None:
        rows = rows[: max(int(limit), 0)]
    return rows


def build_priority_summary_text(
    feed: Optional[Mapping],
    *,
    priority: str = "HIGH",
    categories=None,
    limit: int = 2,
):
    rows = select_priority_items(feed, priority=priority, categories=categories, limit=limit)
    if not rows:
        return ""
    return " | ".join(
        [
            f"{row.get('title', '')}: {row.get('explanation_summary') or row.get('message', '')}".strip(": ")
            for row in rows
            if str(row.get("title") or "").strip() or str(row.get("message") or "").strip()
        ]
    )


def build_intraday_discipline_month_alert(
    feed: Optional[Mapping],
    *,
    monthly_discipline_review: Optional[Mapping] = None,
):
    items = select_priority_items(feed, priority="HIGH", categories={"discipline_month"}, limit=2)
    if not items:
        return None
    generated_at = str(dict(feed or {}).get("generated_at") or "").strip()
    signature = "||".join(
        [
            generated_at,
            *[
                "|".join(
                    [
                        str(item.get("category") or "").strip(),
                        str(item.get("title") or "").strip(),
                        str(item.get("message") or "").strip(),
                    ]
                )
                for item in items
            ],
        ]
    )
    message = build_priority_summary_text(feed, priority="HIGH", categories={"discipline_month"}, limit=2)
    summary = str(dict(monthly_discipline_review or {}).get("summary") or "").strip()
    if summary:
        message = f"{message}\nDiscipline month: {summary}".strip()
    return {
        "signature": signature,
        "message": message,
        "items": items,
    }


def build_change_feed(
    *,
    previous_state: Optional[Mapping],
    current_state: Optional[Mapping],
    now: Optional[datetime] = None,
) -> dict:
    previous_state = dict(previous_state or {})
    current_state = dict(current_state or {})
    now = now or datetime.now()
    items = []

    prev_discipline = dict(previous_state.get("discipline_snapshot", {}) or {})
    curr_discipline = dict(current_state.get("discipline_snapshot", {}) or {})
    prev_regime = str(prev_discipline.get("regime") or "").strip().upper()
    curr_regime = str(curr_discipline.get("regime") or "").strip().upper()
    if prev_regime and curr_regime and prev_regime != curr_regime:
        _add_item(
            items,
            priority="HIGH",
            category="discipline",
            title="纪律层状态切换",
            message=f"纪律状态从 {prev_regime} 切换到 {curr_regime}。",
            reason_codes=["discipline_regime_change"],
            before_value=prev_regime,
            after_value=curr_regime,
            explanation_summary=f"纪律层从 {prev_regime} 切到 {curr_regime}，仓位节奏需要同步调整。",
            explanation_bullets=[
                f"昨日纪律状态: {prev_regime}",
                f"今日纪律状态: {curr_regime}",
            ],
        )

    prev_risk = str(prev_discipline.get("risk_regime") or "").strip().upper()
    curr_risk = str(curr_discipline.get("risk_regime") or "").strip().upper()
    if prev_risk and curr_risk and prev_risk != curr_risk:
        _add_item(
            items,
            priority="HIGH",
            category="risk",
            title="风险状态变化",
            message=f"风险状态从 {prev_risk} 切换到 {curr_risk}。",
            reason_codes=["risk_regime_change"],
            before_value=prev_risk,
            after_value=curr_risk,
            explanation_summary=f"市场风险从 {prev_risk} 变成 {curr_risk}，新的仓位建议需要更谨慎。",
            explanation_bullets=[
                f"昨日风险状态: {prev_risk}",
                f"今日风险状态: {curr_risk}",
            ],
        )

    prev_core = _snapshot_map(previous_state.get("core_etf_snapshot"))
    curr_core = _snapshot_map(current_state.get("core_etf_snapshot"))
    for symbol, curr_row in curr_core.items():
        prev_row = prev_core.get(symbol, {})
        prev_action = str(prev_row.get("action") or "").strip().upper()
        curr_action = str(curr_row.get("action") or "").strip().upper()
        if prev_action and curr_action and prev_action != curr_action:
            _add_item(
                items,
                priority="HIGH",
                category="core_etf",
                title=f"{symbol} 动作切换",
                message=f"{symbol} 从 {prev_action} 切换到 {curr_action}。",
                symbol=symbol,
                reason_codes=["core_action_change"],
                before_value=prev_action,
                after_value=curr_action,
                explanation_summary=f"{symbol} 的核心 ETF 动作从 {prev_action} 变成 {curr_action}。",
                explanation_bullets=[
                    f"昨日动作: {prev_action}",
                    f"今日动作: {curr_action}",
                ],
            )
            continue
        prev_target = _safe_float(prev_row.get("target_weight_pct"))
        curr_target = _safe_float(curr_row.get("target_weight_pct"))
        if prev_target is not None and curr_target is not None and abs(curr_target - prev_target) >= 3.0:
            _add_item(
                items,
                priority="MEDIUM",
                category="core_etf",
                title=f"{symbol} 目标权重调整",
                message=f"{symbol} 目标权重从 {prev_target:.1f}% 调整到 {curr_target:.1f}%。",
                symbol=symbol,
                reason_codes=["core_target_weight_change"],
                before_value=prev_target,
                after_value=curr_target,
                explanation_summary=f"{symbol} 目标权重跨过了最小调整阈值，系统建议重新校准仓位。",
                explanation_bullets=[
                    f"昨日目标权重: {prev_target:.1f}%",
                    f"今日目标权重: {curr_target:.1f}%",
                ],
            )

    prev_satellite = dict((previous_state.get("satellite_candidate_snapshot") or {}).get("summary", {}) or {})
    curr_satellite = dict((current_state.get("satellite_candidate_snapshot") or {}).get("summary", {}) or {})
    prev_top = [str(item).strip().upper() for item in list(prev_satellite.get("top_symbols", []) or []) if str(item).strip()]
    curr_top = [str(item).strip().upper() for item in list(curr_satellite.get("top_symbols", []) or []) if str(item).strip()]
    for symbol in [item for item in curr_top if item not in prev_top]:
        _add_item(
            items,
            priority="HIGH",
            category="satellite",
            title=f"{symbol} 新进入 Top 推荐",
            message=f"{symbol} 新进入卫星仓 Top 推荐列表。",
            symbol=symbol,
            reason_codes=["satellite_top_add"],
            explanation_summary=f"{symbol} 新进入 Top 推荐，值得优先复核其卫星仓建仓条件。",
            explanation_bullets=["昨日未在 Top 推荐中", "今日进入 Top 推荐列表"],
        )
    for symbol in [item for item in prev_top if item not in curr_top]:
        _add_item(
            items,
            priority="HIGH",
            category="satellite",
            title=f"{symbol} 移出 Top 推荐",
            message=f"{symbol} 已移出卫星仓 Top 推荐列表。",
            symbol=symbol,
            reason_codes=["satellite_top_remove"],
            explanation_summary=f"{symbol} 已移出 Top 推荐，说明候选优先级下降或风险升高。",
            explanation_bullets=["昨日仍在 Top 推荐中", "今日已移出 Top 推荐列表"],
        )

    prev_satellite_map = _snapshot_map(previous_state.get("satellite_candidate_snapshot"))
    curr_satellite_map = _snapshot_map(current_state.get("satellite_candidate_snapshot"))
    for symbol, curr_row in curr_satellite_map.items():
        prev_row = prev_satellite_map.get(symbol, {})
        prev_status = str(prev_row.get("recommendation_status") or prev_row.get("candidate_state") or "").strip().upper()
        curr_status = str(curr_row.get("recommendation_status") or curr_row.get("candidate_state") or "").strip().upper()
        if prev_status and curr_status and prev_status != curr_status:
            priority = "HIGH" if {prev_status, curr_status} & {"CONFIRMED", "BROKEN"} else "MEDIUM"
            _add_item(
                items,
                priority=priority,
                category="satellite",
                title=f"{symbol} 状态变化",
                message=f"{symbol} 从 {prev_status} 变为 {curr_status}。",
                symbol=symbol,
                reason_codes=["satellite_state_change"],
                before_value=prev_status,
                after_value=curr_status,
                explanation_summary=f"{symbol} 的卫星仓状态从 {prev_status} 变成 {curr_status}。",
                explanation_bullets=[
                    f"昨日状态: {prev_status}",
                    f"今日状态: {curr_status}",
                ],
            )

    prev_plan = dict(previous_state.get("trade_plan", {}) or {})
    curr_plan = dict(current_state.get("trade_plan", {}) or {})
    prev_decision = str(prev_plan.get("decision") or "").strip().upper()
    curr_decision = str(curr_plan.get("decision") or "").strip().upper()
    if prev_decision and curr_decision and prev_decision != curr_decision:
        _add_item(
            items,
            priority="HIGH",
            category="trade_plan",
            title="次日计划模式变化",
            message=f"次日计划从 {prev_decision} 变为 {curr_decision}。",
            reason_codes=["trade_plan_mode_change"],
            before_value=prev_decision,
            after_value=curr_decision,
            explanation_summary=f"次日计划从 {prev_decision} 切到 {curr_decision}，明早执行节奏会随之变化。",
            explanation_bullets=[
                f"昨日计划模式: {prev_decision}",
                f"今日计划模式: {curr_decision}",
            ],
        )
    prev_count = int(_safe_float(prev_plan.get("action_count"), 0) or 0)
    curr_count = int(_safe_float(curr_plan.get("action_count"), 0) or 0)
    if prev_decision == curr_decision and prev_count != curr_count:
        _add_item(
            items,
            priority="MEDIUM",
            category="trade_plan",
            title="次日计划条数变化",
            message=f"次日计划条数从 {prev_count} 变为 {curr_count}。",
            reason_codes=["trade_plan_count_change"],
            before_value=prev_count,
            after_value=curr_count,
            explanation_summary=f"次日计划条数从 {prev_count} 变到 {curr_count}。",
            explanation_bullets=[
                f"昨日计划条数: {prev_count}",
                f"今日计划条数: {curr_count}",
            ],
        )

    prev_monthly = dict(previous_state.get("monthly_discipline_review", {}) or {})
    curr_monthly = dict(current_state.get("monthly_discipline_review", {}) or {})
    prev_monthly_status = str(prev_monthly.get("status") or "").strip().upper()
    curr_monthly_status = str(curr_monthly.get("status") or "").strip().upper()
    if prev_monthly_status and curr_monthly_status and prev_monthly_status != curr_monthly_status:
        priority = "HIGH" if _discipline_month_rank(curr_monthly_status) > _discipline_month_rank(prev_monthly_status) else "MEDIUM"
        _add_item(
            items,
            priority=priority,
            category="discipline_month",
            title="月度纪律状态变化",
            message=f"月度纪律状态从 {prev_monthly_status} 变为 {curr_monthly_status}。",
            reason_codes=["monthly_discipline_status_change"],
            before_value=prev_monthly_status,
            after_value=curr_monthly_status,
            explanation_summary=f"月度纪律状态从 {prev_monthly_status} 变成 {curr_monthly_status}，说明近期执行纪律发生了实质变化。",
            explanation_bullets=[
                f"昨日月度状态: {prev_monthly_status}",
                f"今日月度状态: {curr_monthly_status}",
            ],
        )
    prev_ignore = int(_safe_float(prev_monthly.get("ignore_days"), 0) or 0)
    curr_ignore = int(_safe_float(curr_monthly.get("ignore_days"), 0) or 0)
    prev_follow = int(_safe_float(prev_monthly.get("follow_days"), 0) or 0)
    curr_follow = int(_safe_float(curr_monthly.get("follow_days"), 0) or 0)
    if curr_ignore > prev_ignore:
        delta = curr_ignore - prev_ignore
        priority = "HIGH" if delta >= 2 or curr_ignore > max(curr_follow, 0) else "MEDIUM"
        _add_item(
            items,
            priority=priority,
            category="discipline_month",
            title="月度 IGNORE 天数上升",
            message=f"月度 IGNORE 天数从 {prev_ignore} 上升到 {curr_ignore}，FOLLOW 为 {curr_follow}。",
            reason_codes=["monthly_ignore_days_up"],
            before_value=prev_ignore,
            after_value=curr_ignore,
            explanation_summary=f"月度 IGNORE 天数从 {prev_ignore} 上升到 {curr_ignore}，已经开始压过 FOLLOW 纪律表现。",
            explanation_bullets=[
                f"昨日 IGNORE 天数: {prev_ignore}",
                f"今日 IGNORE 天数: {curr_ignore}",
                f"当前 FOLLOW 天数: {curr_follow}",
            ],
        )
    prev_defensive_override = int(_safe_float(prev_monthly.get("defensive_override_days"), 0) or 0)
    curr_defensive_override = int(_safe_float(curr_monthly.get("defensive_override_days"), 0) or 0)
    if curr_defensive_override > prev_defensive_override:
        _add_item(
            items,
            priority="HIGH",
            category="discipline_month",
            title="防守状态下仍交易",
            message=f"LIGHT/STOP 状态下交易天数从 {prev_defensive_override} 上升到 {curr_defensive_override}。",
            reason_codes=["defensive_override_days_up"],
            before_value=prev_defensive_override,
            after_value=curr_defensive_override,
            explanation_summary="在 LIGHT / STOP 防守状态下仍发生交易的天数继续上升，说明纪律层被持续绕过。",
            explanation_bullets=[
                f"昨日防守状态下交易天数: {prev_defensive_override}",
                f"今日防守状态下交易天数: {curr_defensive_override}",
            ],
        )

    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    items.sort(key=lambda row: (priority_order.get(str(row.get("priority") or "LOW").upper(), 9), row.get("category", ""), row.get("symbol", "") or "", row.get("title", "")))
    high_items = [row for row in items if row.get("priority") == "HIGH"]
    medium_items = [row for row in items if row.get("priority") == "MEDIUM"]
    low_items = [row for row in items if row.get("priority") == "LOW"]
    return {
        "generated_at": now.isoformat(),
        "summary": {
            "high_count": len(high_items),
            "medium_count": len(medium_items),
            "low_count": len(low_items),
            "total_count": len(items),
        },
        "high_items": high_items,
        "medium_items": medium_items,
        "low_items": low_items,
        "items": items,
    }
