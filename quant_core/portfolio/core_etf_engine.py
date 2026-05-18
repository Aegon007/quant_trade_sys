from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths
from quant_core.analytics import core_etf_rotation as cer


DEFAULT_CORE_ETF_SNAPSHOT_FILE = qpaths.CORE_ETF_SNAPSHOT_FILE


def _safe_float(value, default=None):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value, low, high):
    return max(low, min(high, value))


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


def load_core_etf_snapshot(*, path: str = DEFAULT_CORE_ETF_SNAPSHOT_FILE):
    return _read_json(path)


def save_core_etf_snapshot(snapshot: Mapping, *, path: str = DEFAULT_CORE_ETF_SNAPSHOT_FILE) -> str:
    return _write_json(path, snapshot)


def _core_holding_map(data: Mapping):
    mapped = {}
    for row in list((data or {}).get("holdings", []) or []):
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        shares = _safe_float(row.get("shares"), 0.0) or 0.0
        price = _safe_float(row.get("current_price"))
        value = shares * price if price is not None else 0.0
        mapped[symbol] = {
            "shares": shares,
            "price": price,
            "value": value,
            "sector": row.get("sector"),
        }
    return mapped


def _previous_row_map(previous_snapshot: Optional[Mapping]):
    rows = {}
    for row in list((previous_snapshot or {}).get("symbols", []) or []):
        symbol = str((row or {}).get("symbol") or "").strip().upper()
        if symbol:
            rows[symbol] = dict(row or {})
    return rows


def _range_for_role(role: str, policy: Mapping):
    ranges = dict((policy or {}).get("core_etf_weight_ranges", {}) or {})
    return dict(ranges.get(str(role or "other").strip().lower(), ranges.get("other", {"min_pct": 0.0, "max_pct": 15.0})))


def _adjust_weight_range(base_range: Mapping, *, role: str, risk_regime: str, allocation_regime: str):
    min_pct = _safe_float((base_range or {}).get("min_pct"), 0.0) or 0.0
    max_pct = _safe_float((base_range or {}).get("max_pct"), min_pct) or min_pct
    role = str(role or "other").strip().lower()
    risk_regime = str(risk_regime or "NORMAL").strip().upper()
    allocation_regime = str(allocation_regime or "NORMAL").strip().upper()

    if role == "growth":
        if risk_regime == "RISK_OFF" or allocation_regime == "STOP":
            min_pct = 0.0
            max_pct *= 0.25
        elif risk_regime == "CAUTION" or allocation_regime == "LIGHT":
            max_pct *= 0.65
        elif allocation_regime == "HEAVY":
            max_pct *= 1.10
    elif role in {"dividend_quality", "quality"}:
        if risk_regime == "RISK_OFF" or allocation_regime == "STOP":
            min_pct *= 1.10
            max_pct *= 1.20
        elif risk_regime == "CAUTION" or allocation_regime == "LIGHT":
            max_pct *= 1.10
    elif role == "cash_substitute":
        if risk_regime == "RISK_OFF" or allocation_regime == "STOP":
            min_pct = max(min_pct, 10.0)
            max_pct *= 1.50
        elif risk_regime == "CAUTION" or allocation_regime == "LIGHT":
            max_pct *= 1.20
        elif allocation_regime == "HEAVY":
            max_pct *= 0.60
    elif role == "broad_market":
        if risk_regime == "RISK_OFF" or allocation_regime == "STOP":
            max_pct *= 0.70
        elif allocation_regime == "HEAVY":
            min_pct *= 1.05
            max_pct *= 1.05

    max_pct = max(min_pct, max_pct)
    return {"min_pct": round(min_pct, 4), "max_pct": round(max_pct, 4)}


def _regime_alignment(role: str, *, risk_regime: str, allocation_regime: str):
    role = str(role or "other").strip().lower()
    risk_regime = str(risk_regime or "NORMAL").strip().upper()
    allocation_regime = str(allocation_regime or "NORMAL").strip().upper()
    score = 0.0
    if risk_regime == "RISK_OFF" or allocation_regime == "STOP":
        if role == "cash_substitute":
            score = 1.0
        elif role in {"dividend_quality", "quality"}:
            score = 0.4
        elif role == "growth":
            score = -1.0
        else:
            score = -0.4
    elif risk_regime == "CAUTION" or allocation_regime == "LIGHT":
        if role == "cash_substitute":
            score = 0.7
        elif role in {"dividend_quality", "quality"}:
            score = 0.4
        elif role == "growth":
            score = -0.4
        else:
            score = 0.1
    elif allocation_regime == "HEAVY":
        if role == "growth":
            score = 0.8
        elif role == "broad_market":
            score = 0.5
        elif role == "cash_substitute":
            score = -0.6
    label = "NEUTRAL"
    if score >= 0.45:
        label = "POSITIVE"
    elif score <= -0.45:
        label = "NEGATIVE"
    return score, label


def _zones(current_price, ma50, action):
    if current_price is None or current_price <= 0:
        return {
            "recommended_buy_zone_low": None,
            "recommended_buy_zone_high": None,
            "max_chase_price": None,
            "trim_zone_low": None,
            "trim_zone_high": None,
            "risk_break_level": None,
        }
    anchor = current_price
    if ma50 is not None and ma50 > 0:
        anchor = (current_price * 0.7) + (float(ma50) * 0.3)
    action = str(action or "HOLD").upper()
    buy_low = round(anchor * 0.985, 4)
    buy_high = round(anchor * 1.005, 4)
    trim_low = round(current_price * 1.00, 4)
    trim_high = round(current_price * 1.03, 4)
    risk_break = round(min(current_price * 0.95, (float(ma50) * 0.985) if ma50 else current_price * 0.95), 4)
    if action == "TRIM":
        buy_low = None
        buy_high = None
    if action in {"HOLD", "PAUSE_BUY"}:
        trim_low = None
        trim_high = None
    return {
        "recommended_buy_zone_low": buy_low,
        "recommended_buy_zone_high": buy_high,
        "max_chase_price": round(current_price * 1.02, 4),
        "trim_zone_low": trim_low,
        "trim_zone_high": trim_high,
        "risk_break_level": risk_break,
    }


def _proposed_action(
    *,
    current_weight_pct: float,
    target_weight_pct: float,
    rotation_score: float,
    current_price: Optional[float],
    minimum_trade_value: float,
    total_capital: float,
    min_weight_change_pct: float,
    block_new_buys: bool,
    risk_regime: str,
    role: str,
) -> tuple[str, str]:
    delta_pct = float(target_weight_pct or 0.0) - float(current_weight_pct or 0.0)
    trade_value = abs(delta_pct) * max(total_capital, 0.0) / 100.0
    if current_price is None or current_price <= 0:
        return "HOLD", "缺少最新价格，暂不生成 ETF 动作。"
    if block_new_buys and delta_pct > 0:
        return "PAUSE_BUY", "当前纪律层不允许新增仓位。"
    if risk_regime == "RISK_OFF" and role == "growth" and current_weight_pct > 0.0:
        return "RISK_EXIT", "风险状态偏高，成长型 ETF 进入风险退出模式。"
    if trade_value < minimum_trade_value:
        return "HOLD", "目标权重变化对应金额过小，避免无意义微调。"
    if delta_pct >= min_weight_change_pct:
        if rotation_score >= 72.0:
            return "ACCUMULATE", "趋势、轮动评分与仓位节奏一致，允许继续增配。"
        return "PAUSE_BUY", "目标权重略高于当前，但评分尚不足以追价。"
    if delta_pct <= -min_weight_change_pct:
        return "TRIM", "目标权重低于当前，建议逐步回落到目标区间。"
    if rotation_score < 45.0 and current_weight_pct > 0.0:
        return "TRIM", "轮动评分偏弱，持仓可考虑向下收敛。"
    if rotation_score < 50.0:
        return "PAUSE_BUY", "轮动评分偏弱，当前不建议新追价。"
    return "HOLD", "当前权重已接近目标区间。"


def _confirmed_action(
    *,
    symbol: str,
    proposed_action: str,
    action_reason: str,
    previous_snapshot: Optional[Mapping],
    confirmation_days: int,
) -> tuple[str, int, str]:
    previous_row = _previous_row_map(previous_snapshot).get(symbol, {})
    previous_proposed = str(previous_row.get("proposed_action") or previous_row.get("action") or "HOLD").upper()
    previous_support_days = int(_safe_float(previous_row.get("action_support_days"), 0) or 0)
    support_days = previous_support_days + 1 if previous_proposed == proposed_action else 1
    if proposed_action in {"TRIM", "RISK_EXIT", "HOLD"}:
        return proposed_action, support_days, action_reason
    if proposed_action == "PAUSE_BUY":
        return ("PAUSE_BUY" if support_days >= confirmation_days else "HOLD"), support_days, action_reason
    if proposed_action == "ACCUMULATE":
        if support_days >= confirmation_days:
            return "ACCUMULATE", support_days, action_reason
        return "HOLD", support_days, f"{action_reason} 仍在确认期（{support_days}/{confirmation_days}）。"
    return "HOLD", support_days, action_reason


def _target_weight_pct(score: float, weight_range: Mapping, alignment_score: float):
    low = _safe_float((weight_range or {}).get("min_pct"), 0.0) or 0.0
    high = _safe_float((weight_range or {}).get("max_pct"), low) or low
    normalized_score = _clamp((float(score or 0.0) + (alignment_score * 12.0)) / 100.0, 0.0, 1.0)
    return round(low + ((high - low) * normalized_score), 4)


def build_core_etf_snapshot(
    *,
    data: Mapping,
    account_snapshot: Mapping,
    rotation_snapshot: Mapping,
    risk_gate=None,
    allocation_regime=None,
    previous_snapshot: Optional[Mapping] = None,
    policy: Optional[Mapping] = None,
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.now()
    policy = cer.normalize_engine_policy(policy or cer.load_engine_policy())
    holdings_map = _core_holding_map(data)
    total_capital = _safe_float((account_snapshot or {}).get("total_capital"), 0.0) or 0.0
    risk_regime = str(getattr(risk_gate, "regime", "NORMAL") or "NORMAL").upper() if risk_gate is not None else "NORMAL"
    allocation_name = str(getattr(allocation_regime, "regime", "NORMAL") or "NORMAL").upper() if allocation_regime is not None else "NORMAL"
    block_new_buys = bool(getattr(risk_gate, "block_new_buys", False)) or bool(
        getattr(allocation_regime, "block_new_buys", False)
    )
    confirmation_days = int(policy.get("action_confirmation_days", 2) or 2)
    min_weight_change_pct = float(policy.get("min_weight_change_pct", 3.0) or 3.0)
    minimum_trade_value = float(policy.get("minimum_trade_value", 250.0) or 250.0)

    rows = []
    for rotation_row in list((rotation_snapshot or {}).get("symbols", []) or []):
        symbol = str(rotation_row.get("symbol") or "").strip().upper()
        role = str(rotation_row.get("role") or "other").strip().lower()
        current_price = _safe_float(rotation_row.get("current_price"))
        holding = holdings_map.get(symbol, {})
        current_value = _safe_float(holding.get("value"), 0.0) or 0.0
        current_weight_pct = (current_value / total_capital * 100.0) if total_capital > 0 else 0.0
        base_range = _range_for_role(role, policy)
        adjusted_range = _adjust_weight_range(
            base_range,
            role=role,
            risk_regime=risk_regime,
            allocation_regime=allocation_name,
        )
        alignment_score, alignment_label = _regime_alignment(
            role,
            risk_regime=risk_regime,
            allocation_regime=allocation_name,
        )
        target_weight_pct = _target_weight_pct(
            float(rotation_row.get("rotation_score") or 0.0),
            adjusted_range,
            alignment_score,
        )
        proposed_action, action_reason = _proposed_action(
            current_weight_pct=current_weight_pct,
            target_weight_pct=target_weight_pct,
            rotation_score=float(rotation_row.get("rotation_score") or 0.0),
            current_price=current_price,
            minimum_trade_value=minimum_trade_value,
            total_capital=total_capital,
            min_weight_change_pct=min_weight_change_pct,
            block_new_buys=block_new_buys,
            risk_regime=risk_regime,
            role=role,
        )
        action, action_support_days, action_reason = _confirmed_action(
            symbol=symbol,
            proposed_action=proposed_action,
            action_reason=action_reason,
            previous_snapshot=previous_snapshot,
            confirmation_days=confirmation_days,
        )
        zones = _zones(current_price, rotation_row.get("ma50"), action)
        rows.append(
            {
                "symbol": symbol,
                "enabled": bool(rotation_row.get("enabled", True)),
                "role": role,
                "current_price": current_price,
                "signal": rotation_row.get("rotation_status"),
                "signal_reason": action_reason,
                "current_shares": _safe_float(holding.get("shares"), 0.0) or 0.0,
                "current_value": current_value,
                "current_weight_pct": round(current_weight_pct, 4),
                "target_weight_pct": target_weight_pct,
                "target_weight_range_low_pct": adjusted_range["min_pct"],
                "target_weight_range_high_pct": adjusted_range["max_pct"],
                "action": action,
                "proposed_action": proposed_action,
                "action_support_days": action_support_days,
                "expected_return_3m": rotation_row.get("expected_return_3m"),
                "expected_return_12m": rotation_row.get("expected_return_12m"),
                "confidence": rotation_row.get("confidence"),
                "regime_alignment": alignment_label,
                "regime_alignment_score": round(alignment_score, 4),
                "rotation_score": rotation_row.get("rotation_score"),
                "rotation_backtest": dict(rotation_row.get("rotation_backtest", {}) or {}),
                "analysis_freshness": "fresh",
                **zones,
            }
        )

    rows.sort(
        key=lambda row: (
            {"ACCUMULATE": 0, "TRIM": 1, "PAUSE_BUY": 2, "HOLD": 3, "RISK_EXIT": -1}.get(str(row.get("action") or "HOLD"), 9),
            -float(row.get("rotation_score") or 0.0),
            row["symbol"],
        )
    )
    accumulate = [row["symbol"] for row in rows if row.get("action") == "ACCUMULATE"]
    trims = [row["symbol"] for row in rows if row.get("action") in {"TRIM", "RISK_EXIT"}]
    return {
        "generated_at": now.isoformat(),
        "risk_regime": risk_regime,
        "allocation_regime": allocation_name,
        "summary": {
            "total_symbols": len(rows),
            "accumulate_count": len(accumulate),
            "trim_count": len(trims),
            "focus_symbols": accumulate[:5],
            "defensive_symbols": trims[:5],
        },
        "symbols": rows,
    }
