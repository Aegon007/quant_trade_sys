from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths


DEFAULT_TRADE_PLAN_FILE = qpaths.NEXT_DAY_TRADE_PLAN_FILE
_SELL_ACTIONS = {"TRIM", "EXIT", "RISK_EXIT"}
_BUY_ACTIONS = {"ADD", "ACCUMULATE", "DCA_ACCUMULATE", "PROBE"}


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


def _parse_datetime(value) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _next_trading_day(now: datetime) -> datetime:
    current = now.date() + timedelta(days=1)
    while current.weekday() >= 5:
        current += timedelta(days=1)
    return datetime.combine(current, time(16, 0))


def _normalized_signal(row: Mapping) -> str:
    return str((row or {}).get("signal") or "HOLD").strip().upper()


def _infer_plan_action(row: Mapping) -> Optional[str]:
    row = dict(row or {})
    model_action = str(dict(row.get("decision", {}) or {}).get("action") or "").strip().upper()
    if model_action in _SELL_ACTIONS | _BUY_ACTIONS:
        return model_action
    existing_action = str(row.get("plan_action") or "").strip().upper()
    if existing_action in _SELL_ACTIONS | _BUY_ACTIONS:
        return existing_action

    advice = dict(row.get("position_advice") or {})
    advice_action = str(advice.get("action") or "").strip().upper()
    if advice_action in _SELL_ACTIONS | {"ADD"}:
        return advice_action

    signal = _normalized_signal(row)
    list_type = str(row.get("list_type") or "").strip().lower()
    if signal == "BUY" and list_type == "watchlist":
        return "PROBE"
    if signal == "BUY" and list_type == "holding":
        return "ACCUMULATE"
    if signal == "SELL" and list_type == "holding":
        return "EXIT"
    return None


def _reference_price_from_row(row: Mapping):
    reference_price = _safe_float((row or {}).get("latest_price"))
    if reference_price is None:
        reference_price = _safe_float((row or {}).get("current_price"))
    return reference_price


def _execution_priority(action: str) -> int:
    order = {
        "RISK_EXIT": 1,
        "EXIT": 2,
        "TRIM": 3,
        "ADD": 4,
        "ACCUMULATE": 5,
        "DCA_ACCUMULATE": 5,
        "PROBE": 6,
    }
    return order.get(str(action or "").strip().upper(), 99)


def _plan_delta_pct(row: Mapping, action: str) -> float:
    decision = dict((row or {}).get("decision") or {})
    target_range = list(decision.get("target_weight_range_pct", []) or [])
    current_weight = _safe_float((row or {}).get("current_weight_pct"), 0.0) or 0.0
    if len(target_range) >= 2:
        low = _safe_float(target_range[0], current_weight) or 0.0
        high = _safe_float(target_range[1], current_weight) or 0.0
        if action in _SELL_ACTIONS:
            return max(current_weight - low, 0.0)
        return max(high - current_weight, 0.0)
    advice = dict((row or {}).get("position_advice") or {})
    current_weight = _safe_float(advice.get("current_weight_pct"), 0.0) or 0.0
    target_weight = _safe_float(advice.get("target_weight_pct"), current_weight) or current_weight
    if action in {"PROBE"} and abs(target_weight - current_weight) < 1e-9:
        return 2.0
    if action in _SELL_ACTIONS:
        return max(current_weight - target_weight, 0.0)
    return max(target_weight - current_weight, 0.0)


def _default_plan_levels(reference_price: Optional[float], action: str):
    if reference_price is None or reference_price <= 0:
        return {
            "buy_zone_low": None,
            "buy_zone_high": None,
            "trim_zone_low": None,
            "trim_zone_high": None,
            "max_chase_price": None,
            "risk_break_level": None,
        }

    action = str(action or "").strip().upper()
    if action in _BUY_ACTIONS:
        return {
            "buy_zone_low": round(reference_price * 0.99, 4),
            "buy_zone_high": round(reference_price * 1.01, 4),
            "trim_zone_low": None,
            "trim_zone_high": None,
            "max_chase_price": round(reference_price * 1.02, 4),
            "risk_break_level": round(reference_price * 0.97, 4),
        }
    return {
        "buy_zone_low": None,
        "buy_zone_high": None,
        "trim_zone_low": round(reference_price * 0.99, 4),
        "trim_zone_high": round(reference_price * 1.01, 4),
        "max_chase_price": None,
        "risk_break_level": round(reference_price * 0.97, 4),
    }


def _build_plan_item(row: Mapping, *, plan_valid_until: datetime) -> Optional[dict]:
    row = dict(row or {})
    action = _infer_plan_action(row)
    if not action:
        return None

    reference_price = _reference_price_from_row(row)
    levels = _default_plan_levels(reference_price, action)
    guidance = dict(row.get("guidance") or {})
    advice = dict(row.get("position_advice") or {})
    signal_reason = str(row.get("signal_reason") or "").strip()
    recommendation_reason = str(row.get("recommendation_reason") or "").strip()
    decision = dict(row.get("decision", {}) or {})
    reason_codes = list(decision.get("reason_codes", []) or [])
    long_horizon = dict(row.get("long_horizon", {}) or {})
    timing = dict(row.get("timing", {}) or {})
    suggested_exit_price = _safe_float(guidance.get("suggested_exit_price"))
    delta_pct = _plan_delta_pct(row, action)

    if action in _BUY_ACTIONS:
        entry_condition = (
            f"若价格进入参考区间 {levels['buy_zone_low']:.2f} - {levels['buy_zone_high']:.2f}，"
            "可按计划分批执行。"
            if levels["buy_zone_low"] is not None and levels["buy_zone_high"] is not None
            else "若次日价格接近参考价，可按计划分批执行。"
        )
        invalid_condition = (
            f"若价格高于 {levels['max_chase_price']:.2f}，本次建议作废，等待回调。"
            if levels["max_chase_price"] is not None
            else "若次日明显偏离参考价，本次建议作废，等待下一次夜间评估。"
        )
        if action == "PROBE":
            reason_prefix = "观察名单出现买入信号，建议小仓试探。"
        else:
            reason_prefix = "当前信号支持继续增配。"
    else:
        entry_condition = (
            f"若价格位于 {levels['trim_zone_low']:.2f} - {levels['trim_zone_high']:.2f}，"
            "可按计划减仓/退出。"
            if levels["trim_zone_low"] is not None and levels["trim_zone_high"] is not None
            else "若次日仍维持当前弱势结构，可按计划减仓/退出。"
        )
        invalid_condition = "若次日未成交，则保留仓位并等待下一次夜间评估。"
        reason_prefix = "当前信号偏弱，建议以风险控制优先。"

    reason_parts = [
        part
        for part in [
            reason_prefix,
            f"Long horizon={long_horizon.get('state')}" if long_horizon else "",
            f"Timing={timing.get('state')}" if timing else "",
            ", ".join(str(code) for code in reason_codes),
            advice.get("reason"),
            recommendation_reason,
            signal_reason,
        ]
        if str(part or "").strip()
    ]
    return {
        "symbol": str(row.get("symbol") or "").strip().upper(),
        "list_type": str(row.get("list_type") or "").strip().lower(),
        "signal": _normalized_signal(row),
        "plan_action": action,
        "reference_price": reference_price,
        "plan_weight_delta_pct": round(delta_pct, 4),
        "buy_zone_low": levels["buy_zone_low"],
        "buy_zone_high": levels["buy_zone_high"],
        "trim_zone_low": levels["trim_zone_low"],
        "trim_zone_high": levels["trim_zone_high"],
        "max_chase_price": levels["max_chase_price"],
        "risk_break_level": levels["risk_break_level"],
        "suggested_exit_price": suggested_exit_price,
        "entry_condition": entry_condition,
        "invalid_condition": invalid_condition,
        "plan_valid_until": plan_valid_until.isoformat(),
        "execution_priority": _execution_priority(action),
        "reason": " ".join(str(part).strip() for part in reason_parts if str(part).strip()),
        "model_id": str(dict(row.get("model", {}) or {}).get("model_id") or row.get("model_id") or "").strip() or None,
        "long_horizon_state": long_horizon.get("state"),
        "timing_state": timing.get("state"),
        "reason_codes": reason_codes,
    }


def _decision_signature(*, plan_date: str, decision: str, items, allocation_regime: Mapping):
    payload = {
        "plan_date": str(plan_date or "").strip(),
        "decision": str(decision or "").strip().upper(),
        "allocation_regime": str(dict(allocation_regime or {}).get("regime") or "").strip().upper(),
        "items": [
            {
                "symbol": str(item.get("symbol") or "").strip().upper(),
                "plan_action": str(item.get("plan_action") or "").strip().upper(),
                "plan_weight_delta_pct": _safe_float(item.get("plan_weight_delta_pct"), 0.0) or 0.0,
                "buy_zone_low": _safe_float(item.get("buy_zone_low")),
                "buy_zone_high": _safe_float(item.get("buy_zone_high")),
                "trim_zone_low": _safe_float(item.get("trim_zone_low")),
                "trim_zone_high": _safe_float(item.get("trim_zone_high")),
                "risk_break_level": _safe_float(item.get("risk_break_level")),
            }
            for item in list(items or [])
        ],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _apply_discipline_constraints(items, *, discipline_snapshot: Optional[Mapping] = None):
    snapshot = dict(discipline_snapshot or {})
    regime = str(snapshot.get("regime") or "").strip().upper()
    can_open_core = bool(snapshot.get("can_open_new_core_positions", True))
    can_open_satellite = bool(snapshot.get("can_open_new_satellite_positions", True))

    if not items:
        return [], []

    filtered = []
    blocked = []
    for item in list(items or []):
        row = dict(item or {})
        action = str(row.get("plan_action") or "").strip().upper()
        list_type = str(row.get("list_type") or "").strip().lower()
        is_buy = action in _BUY_ACTIONS
        blocked_reason = ""

        if regime == "STOP" and is_buy:
            blocked_reason = "discipline_stop"
        elif is_buy and list_type in {"candidate_pool", "watchlist"} and not can_open_satellite:
            blocked_reason = "discipline_blocks_new_satellite"
        elif is_buy and list_type in {"holding", "core"} and not can_open_core:
            blocked_reason = "discipline_blocks_new_core"

        if blocked_reason:
            row["blocked_reason"] = blocked_reason
            blocked.append(row)
            continue
        filtered.append(row)
    return filtered, blocked


def build_next_day_trade_plan(
    snapshot: Mapping,
    *,
    satellite_candidate_snapshot: Optional[Mapping] = None,
    discipline_snapshot: Optional[Mapping] = None,
    now: Optional[datetime] = None,
    max_items: int = 12,
) -> dict:
    snapshot = dict(snapshot or {})
    now = now or _parse_datetime(snapshot.get("generated_at")) or datetime.now()
    plan_valid_until = _next_trading_day(now)

    items = []
    seen_symbols = set()
    for row in list(snapshot.get("symbols", []) or []):
        item = _build_plan_item(row, plan_valid_until=plan_valid_until)
        if item is not None:
            items.append(item)
            seen_symbols.add(item["symbol"])

    candidate_snapshot = dict(satellite_candidate_snapshot or {})
    for row in list(candidate_snapshot.get("top_recommendations", []) or []):
        symbol = str((row or {}).get("symbol") or "").strip().upper()
        if not symbol or symbol in seen_symbols:
            continue
        item = _build_plan_item(
            {
                **dict(row or {}),
                "list_type": str((row or {}).get("list_type") or "candidate_pool").strip().lower(),
                "latest_price": _reference_price_from_row(row),
            },
            plan_valid_until=plan_valid_until,
        )
        if item is not None:
            items.append(item)
            seen_symbols.add(item["symbol"])
    items.sort(key=lambda row: (row["execution_priority"], row["symbol"]))
    items = items[: max(0, int(max_items or 0))]
    items, blocked_items = _apply_discipline_constraints(items, discipline_snapshot=discipline_snapshot)

    allocation_regime = dict(snapshot.get("allocation_regime", {}) or {})
    has_actions = bool(items)
    if has_actions:
        summary_reason = f"明日有 {len(items)} 条可执行计划。"
        if blocked_items:
            summary_reason += f" 另有 {len(blocked_items)} 条因纪律层限制被压制。"
        decision = "ACTION"
    else:
        reasons = list(allocation_regime.get("reasons", []) or [])
        discipline_regime = str(dict(discipline_snapshot or {}).get("regime") or "").strip().upper()
        if blocked_items and discipline_regime == "STOP":
            trailing = " 原因：纪律层当前为 STOP，所有新建仓动作已被压制。"
        elif blocked_items:
            trailing = f" 原因：纪律层压制了 {len(blocked_items)} 条建仓建议。"
        else:
            trailing = f" 原因：{'；'.join(reasons[:2])}" if reasons else ""
        summary_reason = f"当前无强信号，建议持仓不动。{trailing}".strip()
        decision = "NO_ACTION"
    decision_signature = _decision_signature(
        plan_date=plan_valid_until.date().isoformat(),
        decision=decision,
        items=items,
        allocation_regime=dict(snapshot.get("allocation_regime", {}) or {}),
    )

    return {
        "generated_at": now.isoformat(),
        "plan_date": plan_valid_until.date().isoformat(),
        "decision": decision,
        "decision_signature": decision_signature,
        "has_actions": has_actions,
        "summary_reason": summary_reason,
        "items": items,
        "blocked_items": blocked_items,
        "blocked_count": len(blocked_items),
        "action_count": len(items),
    }


def build_premarket_brief(plan: Mapping, *, execution_review: Optional[Mapping] = None) -> str:
    plan = dict(plan or {})
    lines = [
        "盘前简报",
        f"生成时间：{str(plan.get('generated_at') or '')}",
        f"明日建议：{'有动作' if plan.get('has_actions') else '无动作'}",
        f"计划签名：{str(plan.get('decision_signature') or '—')}",
        str(plan.get("summary_reason") or "").strip(),
    ]

    if plan.get("items"):
        lines.append("")
        lines.append("计划单：")
        for item in list(plan.get("items", []) or []):
            action = str(item.get("plan_action") or "").strip().upper()
            symbol = str(item.get("symbol") or "").strip().upper()
            lines.append(f"- {symbol} | 动作={action} | 参考价={item.get('reference_price')}")
            zone_low = item.get("buy_zone_low")
            zone_high = item.get("buy_zone_high")
            if zone_low is not None and zone_high is not None:
                lines.append(f"  买入区间：{zone_low:.2f} - {zone_high:.2f}")
            trim_low = item.get("trim_zone_low")
            trim_high = item.get("trim_zone_high")
            if trim_low is not None and trim_high is not None:
                lines.append(f"  减仓区间：{trim_low:.2f} - {trim_high:.2f}")
            lines.append(f"  建议仓位变化：{float(item.get('plan_weight_delta_pct') or 0.0):.1f}%")
            lines.append(f"  失效条件：{item.get('invalid_condition')}")
            if item.get("risk_break_level") is not None:
                lines.append(f"  风险破坏位：{float(item['risk_break_level']):.2f}")
            if item.get("reason"):
                lines.append(f"  原因：{item.get('reason')}")

    if execution_review:
        review = dict(execution_review or {})
        lines.append("")
        lines.append("执行复盘：")
        lines.append(
            f"复盘日={review.get('review_day')} | "
            f"已执行={int(review.get('executed_count') or 0)} | "
            f"未执行={int(review.get('missed_count') or 0)} | "
            f"计划外交易={int(review.get('unplanned_trade_count') or 0)}"
        )

    return "\n".join(line for line in lines if str(line).strip())


def save_next_day_trade_plan(plan: Mapping, *, path: Optional[str] = None) -> str:
    target = Path(path or DEFAULT_TRADE_PLAN_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(plan or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def load_next_day_trade_plan(*, path: Optional[str] = None):
    target = Path(path or DEFAULT_TRADE_PLAN_FILE)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
