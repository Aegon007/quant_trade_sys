from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths


DEFAULT_INTRADAY_TACTICAL_CONFIG_FILE = qpaths.INTRADAY_TACTICAL_CONFIG_FILE
DEFAULT_INTRADAY_TACTICAL_SNAPSHOT_FILE = qpaths.INTRADAY_TACTICAL_SNAPSHOT_FILE


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


def default_intraday_tactical_config():
    return {
        "enabled": True,
        "benchmark_symbols": ["QQQ", "SPY"],
        "tactical_symbols": [
            {"symbol": "SQQQ", "role": "nasdaq_inverse_3x", "max_weight_pct": 3.0},
            {"symbol": "PSQ", "role": "nasdaq_inverse_1x", "max_weight_pct": 4.0},
            {"symbol": "SH", "role": "sp500_inverse_1x", "max_weight_pct": 4.0},
        ],
        "thresholds": {
            "qqq_stress_drop_pct": -0.02,
            "qqq_panic_drop_pct": -0.03,
            "spy_stress_drop_pct": -0.015,
            "spy_panic_drop_pct": -0.025,
            "tactical_chase_gain_pct": 0.08,
        },
        "allow_overnight": False,
        "max_tactical_total_weight_pct": 5.0,
    }


def normalize_intraday_tactical_config(config: Optional[Mapping]):
    base = default_intraday_tactical_config()
    config = dict(config or {})
    thresholds = dict(base.get("thresholds", {}) or {})
    thresholds.update(dict(config.get("thresholds", {}) or {}))
    tactical_rows = []
    for row in list(config.get("tactical_symbols", []) or base.get("tactical_symbols", [])):
        symbol = _normalize_symbol(dict(row or {}).get("symbol"))
        if not symbol:
            continue
        tactical_rows.append(
            {
                "symbol": symbol,
                "role": str(dict(row or {}).get("role") or "inverse").strip(),
                "max_weight_pct": float(_safe_float(dict(row or {}).get("max_weight_pct"), 0.0) or 0.0),
            }
        )
    benchmark_symbols = [
        _normalize_symbol(symbol)
        for symbol in list(config.get("benchmark_symbols", []) or base.get("benchmark_symbols", []))
        if _normalize_symbol(symbol)
    ]
    return {
        "enabled": bool(config.get("enabled", base.get("enabled", True))),
        "benchmark_symbols": benchmark_symbols or list(base.get("benchmark_symbols", [])),
        "tactical_symbols": tactical_rows or list(base.get("tactical_symbols", [])),
        "thresholds": thresholds,
        "allow_overnight": bool(config.get("allow_overnight", base.get("allow_overnight", False))),
        "max_tactical_total_weight_pct": float(
            _safe_float(config.get("max_tactical_total_weight_pct"), base.get("max_tactical_total_weight_pct", 5.0))
            or 0.0
        ),
    }


def load_intraday_tactical_config(*, path: str = DEFAULT_INTRADAY_TACTICAL_CONFIG_FILE):
    return normalize_intraday_tactical_config(_read_json(path))


def save_intraday_tactical_config(config: Mapping, *, path: str = DEFAULT_INTRADAY_TACTICAL_CONFIG_FILE):
    normalized = normalize_intraday_tactical_config(config)
    return _write_json(path, normalized)


def load_intraday_tactical_snapshot(*, path: str = DEFAULT_INTRADAY_TACTICAL_SNAPSHOT_FILE):
    return _read_json(path) or {}


def save_intraday_tactical_snapshot(snapshot: Mapping, *, path: str = DEFAULT_INTRADAY_TACTICAL_SNAPSHOT_FILE):
    return _write_json(path, dict(snapshot or {}))


def _mapping_value(payload, key, default=None):
    if payload is None:
        return default
    if isinstance(payload, Mapping):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _price_from_data(data: Mapping, symbol: str):
    symbol = _normalize_symbol(symbol)
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


def _resolve_live_price(symbol: str, *, data: Mapping, price_fetcher):
    price = _price_from_data(data, symbol)
    if price is not None:
        return price
    if callable(price_fetcher):
        try:
            return _safe_float(dict(price_fetcher([symbol]) or {}).get(symbol))
        except Exception:
            return None
    return None


def _previous_close_from_history(symbol: str, *, history_loader, now: datetime):
    if not callable(history_loader):
        return None
    try:
        history = history_loader(symbol, period="5d")
    except Exception:
        return None
    if history is None or getattr(history, "empty", True) or "Close" not in history:
        return None
    close = history["Close"].dropna()
    if close.empty:
        return None
    try:
        last_idx = close.index[-1]
        last_day = last_idx.date() if hasattr(last_idx, "date") else None
    except Exception:
        last_day = None
    if len(close) >= 2 and last_day == now.date():
        return _safe_float(close.iloc[-2])
    return _safe_float(close.iloc[-1])


def _pct_change(current_price, previous_close):
    current_price = _safe_float(current_price)
    previous_close = _safe_float(previous_close)
    if current_price is None or previous_close is None or previous_close <= 0:
        return None
    return current_price / previous_close - 1.0


def _best_tactical_symbol(rows):
    ranked = [dict(row or {}) for row in list(rows or []) if row.get("symbol")]
    ranked.sort(key=lambda row: _safe_float(row.get("change_pct"), -999.0), reverse=True)
    return ranked[0] if ranked else {}


def build_intraday_tactical_snapshot(
    *,
    data: Mapping,
    config: Optional[Mapping] = None,
    risk_gate=None,
    event_decision=None,
    active_events=None,
    now: Optional[datetime] = None,
    price_fetcher=None,
    history_loader=None,
):
    now = now if isinstance(now, datetime) else datetime.now()
    config = normalize_intraday_tactical_config(config)
    if not config.get("enabled", True):
        return {
            "generated_at": now.isoformat(),
            "enabled": False,
            "state": "DISABLED",
            "recommended_action": "NONE",
            "message": "Intraday tactical overlay is disabled.",
            "benchmark_rows": [],
            "tactical_rows": [],
            "reason_codes": ["disabled"],
            "explanation_bullets": [],
        }

    thresholds = dict(config.get("thresholds", {}) or {})
    benchmark_rows = []
    for symbol in list(config.get("benchmark_symbols", []) or []):
        current_price = _resolve_live_price(symbol, data=data, price_fetcher=price_fetcher)
        previous_close = _previous_close_from_history(symbol, history_loader=history_loader, now=now)
        benchmark_rows.append(
            {
                "symbol": _normalize_symbol(symbol),
                "current_price": current_price,
                "previous_close": previous_close,
                "change_pct": _pct_change(current_price, previous_close),
            }
        )

    tactical_rows = []
    for row in list(config.get("tactical_symbols", []) or []):
        symbol = _normalize_symbol(dict(row or {}).get("symbol"))
        if not symbol:
            continue
        current_price = _resolve_live_price(symbol, data=data, price_fetcher=price_fetcher)
        previous_close = _previous_close_from_history(symbol, history_loader=history_loader, now=now)
        tactical_rows.append(
            {
                "symbol": symbol,
                "role": str(dict(row or {}).get("role") or "").strip(),
                "max_weight_pct": float(_safe_float(dict(row or {}).get("max_weight_pct"), 0.0) or 0.0),
                "current_price": current_price,
                "previous_close": previous_close,
                "change_pct": _pct_change(current_price, previous_close),
            }
        )

    qqq_move = next((row.get("change_pct") for row in benchmark_rows if row.get("symbol") == "QQQ"), None)
    spy_move = next((row.get("change_pct") for row in benchmark_rows if row.get("symbol") == "SPY"), None)
    best_tactical = _best_tactical_symbol(tactical_rows)
    best_tactical_move = _safe_float(best_tactical.get("change_pct"))

    risk_regime = str(_mapping_value(risk_gate, "regime", "") or "").strip().upper()
    event_regime = str(_mapping_value(event_decision, "regime", "") or "").strip().upper()
    high_severity_events = [
        row for row in list(active_events or [])
        if str(_mapping_value(row, "severity", "") or "").strip().lower() == "high"
    ]

    state = "NORMAL"
    reason_codes = []
    explanation_bullets = []

    if qqq_move is not None and qqq_move <= float(thresholds.get("qqq_stress_drop_pct", -0.02)):
        state = "STRESS_BUILDING"
        reason_codes.append("qqq_stress")
        explanation_bullets.append(f"QQQ 当日变动 {qqq_move:.2%}")
    if spy_move is not None and spy_move <= float(thresholds.get("spy_stress_drop_pct", -0.015)):
        state = "STRESS_BUILDING"
        reason_codes.append("spy_stress")
        explanation_bullets.append(f"SPY 当日变动 {spy_move:.2%}")
    if risk_regime == "CAUTION" or event_regime == "CAUTION":
        state = "STRESS_BUILDING" if state == "NORMAL" else state
        reason_codes.append("risk_caution")
    if high_severity_events:
        state = "STRESS_BUILDING" if state == "NORMAL" else state
        reason_codes.append("high_impact_events")
        explanation_bullets.append(f"高影响事件 {len(high_severity_events)} 条")

    panic = False
    if qqq_move is not None and qqq_move <= float(thresholds.get("qqq_panic_drop_pct", -0.03)):
        panic = True
        reason_codes.append("qqq_panic")
    if spy_move is not None and spy_move <= float(thresholds.get("spy_panic_drop_pct", -0.025)):
        panic = True
        reason_codes.append("spy_panic")
    if risk_regime == "RISK_OFF" or event_regime == "RISK_OFF":
        panic = True
        reason_codes.append("risk_off")
    if panic:
        state = "PANIC"

    chase_gain_threshold = float(thresholds.get("tactical_chase_gain_pct", 0.08))
    if state == "PANIC" and best_tactical_move is not None and best_tactical_move >= chase_gain_threshold:
        state = "CAPITULATION"
        reason_codes.append("tactical_tool_extended")
        explanation_bullets.append(f"{best_tactical.get('symbol')} 当日已上涨 {best_tactical_move:.2%}")

    recommended_action = "NONE"
    recommended_symbol = None
    suggested_weight_pct = None
    action_side = None
    summary = "盘中没有额外战术动作。"

    if state == "STRESS_BUILDING":
        recommended_action = "REDUCE_RISK"
        action_side = "SELL"
        summary = "市场进入压力累积阶段，优先减风险，不急着追反向 ETF。"
    elif state == "PANIC":
        recommended_action = "TACTICAL_HEDGE"
        action_side = "BUY"
        if qqq_move is not None and qqq_move <= float(thresholds.get("qqq_panic_drop_pct", -0.03)):
            recommended_symbol = "SQQQ"
        elif spy_move is not None and spy_move <= float(thresholds.get("spy_panic_drop_pct", -0.025)):
            recommended_symbol = "SH"
        else:
            recommended_symbol = best_tactical.get("symbol") or "PSQ"
        recommended_row = next((row for row in tactical_rows if row.get("symbol") == recommended_symbol), {})
        cap = float(_safe_float(recommended_row.get("max_weight_pct"), 0.0) or 0.0)
        suggested_weight_pct = min(cap or 2.0, float(config.get("max_tactical_total_weight_pct", 5.0) or 5.0))
        summary = f"市场进入恐慌阶段，可考虑用 {recommended_symbol} 做小仓位战术对冲。"
        explanation_bullets.append(
            f"建议仓位上限 {suggested_weight_pct:.1f}% | {'不隔夜' if not config.get('allow_overnight', False) else '允许隔夜'}"
        )
    elif state == "CAPITULATION":
        recommended_action = "DO_NOT_CHASE"
        action_side = "SELL"
        recommended_symbol = best_tactical.get("symbol")
        summary = f"{recommended_symbol or '反向工具'} 已明显扩张，优先减风险，不追高战术仓。"

    return {
        "generated_at": now.isoformat(),
        "enabled": True,
        "state": state,
        "risk_regime": risk_regime or None,
        "event_regime": event_regime or None,
        "recommended_action": recommended_action,
        "recommended_symbol": recommended_symbol,
        "suggested_weight_pct": suggested_weight_pct,
        "action_side": action_side,
        "allow_overnight": bool(config.get("allow_overnight", False)),
        "max_tactical_total_weight_pct": float(config.get("max_tactical_total_weight_pct", 5.0) or 5.0),
        "message": summary,
        "reason_codes": reason_codes,
        "explanation_bullets": explanation_bullets,
        "benchmark_rows": benchmark_rows,
        "tactical_rows": tactical_rows,
    }


def build_intraday_tactical_events(snapshot: Optional[Mapping]):
    snapshot = dict(snapshot or {})
    if not snapshot or not snapshot.get("enabled", True):
        return []
    state = str(snapshot.get("state") or "NORMAL").strip().upper()
    action = str(snapshot.get("recommended_action") or "NONE").strip().upper()
    symbol = _normalize_symbol(snapshot.get("recommended_symbol"))
    payload = {
        "action_side": snapshot.get("action_side"),
        "recommended_action": action,
        "suggested_weight_pct": snapshot.get("suggested_weight_pct"),
        "state": state,
        "reason_codes": list(snapshot.get("reason_codes", []) or []),
    }
    explanation_summary = str(snapshot.get("message") or "").strip()
    explanation_bullets = list(snapshot.get("explanation_bullets", []) or [])
    if action == "TACTICAL_HEDGE" and symbol:
        return [
            {
                "event_type": "TACTICAL_HEDGE_TRIGGER",
                "priority": "high",
                "symbol": symbol,
                "title": f"{symbol} 盘中战术对冲触发",
                "message": explanation_summary,
                "trigger_reason": "tactical_hedge",
                "should_notify": True,
                "plan_action": action,
                "action_side": "BUY",
                "payload": payload,
                "reason_codes": list(snapshot.get("reason_codes", []) or []),
                "explanation_summary": explanation_summary,
                "explanation_bullets": explanation_bullets,
            }
        ]
    if action == "DO_NOT_CHASE":
        return [
            {
                "event_type": "TACTICAL_DO_NOT_CHASE",
                "priority": "high",
                "symbol": symbol or None,
                "title": f"{symbol or '反向工具'} 不宜追高",
                "message": explanation_summary,
                "trigger_reason": "tactical_do_not_chase",
                "should_notify": True,
                "plan_action": action,
                "action_side": "SELL",
                "payload": payload,
                "reason_codes": list(snapshot.get("reason_codes", []) or []),
                "explanation_summary": explanation_summary,
                "explanation_bullets": explanation_bullets,
            }
        ]
    if action == "REDUCE_RISK":
        return [
            {
                "event_type": "TACTICAL_REDUCE_RISK",
                "priority": "medium",
                "symbol": None,
                "title": "盘中风险升温",
                "message": explanation_summary,
                "trigger_reason": "tactical_reduce_risk",
                "should_notify": False,
                "plan_action": action,
                "action_side": "SELL",
                "payload": payload,
                "reason_codes": list(snapshot.get("reason_codes", []) or []),
                "explanation_summary": explanation_summary,
                "explanation_bullets": explanation_bullets,
            }
        ]
    return []
