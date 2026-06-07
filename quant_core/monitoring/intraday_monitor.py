from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Optional

from quant_core import paths as qpaths


DEFAULT_INTRADAY_EVENT_ALERT_STATE_FILE = qpaths.INTRADAY_EVENT_ALERT_STATE_FILE
_BUY_ACTIONS = {"ADD", "ACCUMULATE", "PROBE"}
_SELL_ACTIONS = {"TRIM", "EXIT", "RISK_EXIT"}


def _safe_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


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


def _normalize_symbol(value) -> str:
    return str(value or "").strip().upper()


def _mapping_value(payload, key, default=None):
    if payload is None:
        return default
    if isinstance(payload, Mapping):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _priority_rank(value: str) -> int:
    normalized = str(value or "").strip().lower()
    return {"high": 0, "medium": 1, "low": 2}.get(normalized, 9)


def _normalize_plan_map(trade_plan: Optional[Mapping]) -> dict:
    plan = dict(trade_plan or {})
    mapped = {}
    for item in list(plan.get("items", []) or []):
        row = dict(item or {})
        symbol = _normalize_symbol(row.get("symbol"))
        if symbol:
            mapped[symbol] = row
    return mapped


def _price_for_symbol(data: Mapping, symbol: str):
    symbol = _normalize_symbol(symbol)
    if not symbol:
        return None
    for row in list((data or {}).get("holdings", []) or []):
        if _normalize_symbol(row.get("symbol")) == symbol:
            price = _safe_float(row.get("current_price"))
            if price is not None:
                return price
    for row in list((data or {}).get("watchlist", []) or []):
        if _normalize_symbol(row.get("symbol")) == symbol:
            price = _safe_float(row.get("last_price"))
            if price is not None:
                return price
    return None


def load_intraday_event_alert_state(*, path: str = DEFAULT_INTRADAY_EVENT_ALERT_STATE_FILE):
    payload = _read_json(path) or {}
    day = str(payload.get("day") or "").strip()
    sent_signatures = [
        str(item).strip()
        for item in list(payload.get("sent_signatures", []) or [])
        if str(item).strip()
    ]
    return {
        "day": day,
        "sent_signatures": sent_signatures,
    }


def save_intraday_event_alert_state(state: Mapping, *, path: str = DEFAULT_INTRADAY_EVENT_ALERT_STATE_FILE) -> str:
    payload = {
        "day": str(dict(state or {}).get("day") or "").strip(),
        "sent_signatures": [
            str(item).strip()
            for item in list(dict(state or {}).get("sent_signatures", []) or [])
            if str(item).strip()
        ],
    }
    return _write_json(path, payload)


def should_send_intraday_alert_signature(
    signature: str,
    *,
    now: Optional[datetime] = None,
    path: str = DEFAULT_INTRADAY_EVENT_ALERT_STATE_FILE,
) -> bool:
    signature = str(signature or "").strip()
    if not signature:
        return False
    now = now or datetime.now()
    state = load_intraday_event_alert_state(path=path)
    if str(state.get("day") or "").strip() != now.date().isoformat():
        return True
    return signature not in set(state.get("sent_signatures", []) or [])


def mark_intraday_alert_sent(
    signature: str,
    *,
    now: Optional[datetime] = None,
    path: str = DEFAULT_INTRADAY_EVENT_ALERT_STATE_FILE,
) -> str:
    signature = str(signature or "").strip()
    if not signature:
        return path
    now = now or datetime.now()
    state = load_intraday_event_alert_state(path=path)
    if str(state.get("day") or "").strip() != now.date().isoformat():
        state = {
            "day": now.date().isoformat(),
            "sent_signatures": [],
        }
    sent_signatures = [
        str(item).strip()
        for item in list(state.get("sent_signatures", []) or [])
        if str(item).strip()
    ]
    if signature not in sent_signatures:
        sent_signatures.append(signature)
    state["sent_signatures"] = sent_signatures[-50:]
    return save_intraday_event_alert_state(state, path=path)


def classify_intraday_event(
    *,
    event_type: str,
    priority: str = "high",
    symbol: Optional[str] = None,
    title: str = "",
    message: str = "",
    trigger_reason: str = "",
    should_notify: Optional[bool] = None,
    plan_action: Optional[str] = None,
    action_side: Optional[str] = None,
    payload: Optional[Mapping] = None,
    reason_codes=None,
    explanation_summary: str = "",
    explanation_bullets=None,
) -> dict:
    normalized_priority = str(priority or "high").strip().lower()
    notify = bool(should_notify) if should_notify is not None else normalized_priority == "high"
    return {
        "event_type": str(event_type or "").strip().upper(),
        "priority": normalized_priority,
        "symbol": _normalize_symbol(symbol) or None,
        "title": str(title or "").strip(),
        "message": str(message or "").strip(),
        "trigger_reason": str(trigger_reason or "").strip(),
        "should_notify": notify,
        "plan_action": str(plan_action or "").strip().upper() or None,
        "action_side": str(action_side or "").strip().upper() or None,
        "payload": dict(payload or {}),
        "reason_codes": [
            str(item).strip()
            for item in list(reason_codes or [])
            if str(item).strip()
        ],
        "explanation_summary": str(explanation_summary or "").strip(),
        "explanation_bullets": [
            str(item).strip()
            for item in list(explanation_bullets or [])
            if str(item).strip()
        ],
    }


def classify_intraday_events(
    *,
    data: Mapping,
    trade_plan: Optional[Mapping] = None,
    risk_gate=None,
    discipline_snapshot: Optional[Mapping] = None,
    active_events: Optional[Iterable[Mapping]] = None,
    event_decision=None,
    now: Optional[datetime] = None,
    sharp_drop_threshold_pct: float = 0.07,
) -> list[dict]:
    now = now or datetime.now()
    data = dict(data or {})
    discipline_snapshot = dict(discipline_snapshot or {})
    holdings = list(data.get("holdings", []) or [])
    plan_map = _normalize_plan_map(trade_plan)
    events = []

    risk_regime = str(_mapping_value(risk_gate, "regime", "") or "").strip().upper()
    event_regime = str(_mapping_value(event_decision, "regime", "") or "").strip().upper()
    can_open_satellite = bool(discipline_snapshot.get("can_open_new_satellite_positions", True))
    can_open_core = bool(discipline_snapshot.get("can_open_new_core_positions", True))
    regime_payload = {
        "risk_regime": risk_regime or None,
        "event_regime": event_regime or None,
        "discipline_regime": str(discipline_snapshot.get("regime") or "").strip() or None,
    }

    if event_regime == "RISK_OFF" and holdings:
        events.append(
            classify_intraday_event(
                event_type="MARKET_RISK_OFF",
                priority="high",
                title="盘中风险切换到 RISK_OFF",
                message="事件风控已切换到 RISK_OFF，盘中优先检查减仓/退出计划。",
                trigger_reason="event_risk_off",
                should_notify=True,
                action_side="SELL",
                payload={
                    "active_event_count": len(list(active_events or [])),
                    **regime_payload,
                },
                reason_codes=["event_risk_off", "reduce_exposure"],
                explanation_summary="高影响事件把盘中风险切到了 RISK_OFF，系统建议优先检查减仓或退出。",
                explanation_bullets=[
                    f"高影响事件数量: {len(list(active_events or []))}",
                    f"当前风险状态: {risk_regime or 'UNKNOWN'}",
                ],
            )
        )

    for row in holdings:
        symbol = _normalize_symbol(row.get("symbol"))
        current_price = _safe_float(row.get("current_price"))
        cost = _safe_float(row.get("cost"))
        if not symbol or current_price is None or current_price <= 0:
            continue

        plan_row = dict(plan_map.get(symbol, {}) or {})
        risk_break_level = _safe_float(plan_row.get("risk_break_level"))
        if risk_break_level is not None and current_price <= risk_break_level:
            events.append(
                classify_intraday_event(
                    event_type="PLAN_RISK_BREAK",
                    priority="high",
                    symbol=symbol,
                    title=f"{symbol} 跌破风险破坏位",
                    message=f"{symbol} 当前价格 {current_price:.2f} 已跌破风险破坏位 {risk_break_level:.2f}。",
                    trigger_reason="risk_break",
                    should_notify=True,
                    plan_action=plan_row.get("plan_action"),
                    action_side="SELL",
                        payload={
                            **regime_payload,
                            "trigger_price": current_price,
                            "risk_break_level": risk_break_level,
                            "reference_price": _safe_float(plan_row.get("reference_price")),
                        },
                    reason_codes=["risk_break", "sell_signal"],
                    explanation_summary=f"{symbol} 已跌破夜间计划里的风险破坏位，优先考虑减仓或退出。",
                    explanation_bullets=[
                        f"当前价格 {current_price:.2f}",
                        f"风险破坏位 {risk_break_level:.2f}",
                    ],
                )
            )
            continue

        if cost is not None and cost > 0:
            return_pct = current_price / cost - 1.0
            if return_pct <= -abs(float(sharp_drop_threshold_pct or 0.07)):
                events.append(
                    classify_intraday_event(
                        event_type="POSITION_SHARP_DROP",
                        priority="high",
                        symbol=symbol,
                        title=f"{symbol} 盘中大幅走弱",
                        message=f"{symbol} 相对成本位回撤 {return_pct:.2%}，盘中需要优先检查风险。",
                        trigger_reason="sharp_drop",
                        should_notify=True,
                        action_side="SELL",
                        payload={
                            **regime_payload,
                            "trigger_price": current_price,
                            "cost_basis": cost,
                            "return_pct": return_pct,
                        },
                        reason_codes=["sharp_drop", "drawdown"],
                        explanation_summary=f"{symbol} 相对成本位已经出现较大回撤，盘中需要优先检查风险。",
                        explanation_bullets=[
                            f"当前价格 {current_price:.2f}",
                            f"成本价 {cost:.2f}",
                            f"回撤 {return_pct:.2%}",
                        ],
                    )
                )

    for symbol, plan_row in plan_map.items():
        plan_action = str(plan_row.get("plan_action") or "").strip().upper()
        if plan_action not in _BUY_ACTIONS:
            continue
        current_price = _price_for_symbol(data, symbol)
        buy_zone_low = _safe_float(plan_row.get("buy_zone_low"))
        buy_zone_high = _safe_float(plan_row.get("buy_zone_high"))
        if current_price is None or buy_zone_low is None or buy_zone_high is None:
            continue
        if not (buy_zone_low <= current_price <= buy_zone_high):
            continue
        if plan_action == "PROBE":
            can_open = can_open_satellite
        else:
            can_open = can_open_core
        if not can_open or event_regime == "RISK_OFF":
            continue
        events.append(
            classify_intraday_event(
                event_type="PLAN_BUY_ZONE_TRIGGER",
                priority="high",
                symbol=symbol,
                title=f"{symbol} 进入买入区间",
                message=f"{symbol} 当前价格 {current_price:.2f} 已进入计划买入区间 {buy_zone_low:.2f}-{buy_zone_high:.2f}。",
                trigger_reason="buy_zone",
                should_notify=True,
                plan_action=plan_action,
                action_side="BUY",
                payload={
                    **regime_payload,
                    "trigger_price": current_price,
                    "buy_zone_low": buy_zone_low,
                    "buy_zone_high": buy_zone_high,
                    "reference_price": _safe_float(plan_row.get("reference_price")),
                },
                reason_codes=["buy_zone", "planned_entry"],
                explanation_summary=f"{symbol} 已进入夜间计划定义的可执行买入区间。",
                explanation_bullets=[
                    f"当前价格 {current_price:.2f}",
                    f"买入区间 {buy_zone_low:.2f}-{buy_zone_high:.2f}",
                    f"计划动作 {plan_action}",
                ],
            )
        )

    events.sort(
        key=lambda row: (
            _priority_rank(row.get("priority")),
            str(row.get("event_type") or ""),
            str(row.get("symbol") or ""),
        )
    )
    return events


def select_notifiable_intraday_events(events: Iterable[Mapping], *, limit: int = 3) -> list[dict]:
    candidates = [
        dict(row or {})
        for row in list(events or [])
        if bool(dict(row or {}).get("should_notify"))
    ]
    candidates.sort(
        key=lambda row: (
            _priority_rank(row.get("priority")),
            str(row.get("event_type") or ""),
            str(row.get("symbol") or ""),
        )
    )
    return candidates[: max(int(limit or 0), 0)]


def build_intraday_alert(events: Iterable[Mapping], *, now: Optional[datetime] = None):
    rows = select_notifiable_intraday_events(events, limit=3)
    if not rows:
        return None
    now = now or datetime.now()
    parts = []
    for row in rows:
        symbol_prefix = f"[{row.get('symbol')}] " if row.get("symbol") else ""
        parts.append(f"{symbol_prefix}{row.get('title')}: {row.get('message')}")
    signature = "||".join(
        [
            now.date().isoformat(),
            *[
                "|".join(
                    [
                        str(row.get("event_type") or "").strip(),
                        str(row.get("symbol") or "").strip(),
                        str(row.get("trigger_reason") or "").strip(),
                    ]
                )
                for row in rows
            ],
        ]
    )
    return {
        "generated_at": now.isoformat(),
        "signature": signature,
        "message": "\n".join(parts),
        "events": rows,
    }
