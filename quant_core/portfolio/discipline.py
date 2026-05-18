from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths
from quant_core.analytics import core_etf_rotation as cer
from quant_core.snapshots import system_snapshot as ss


DEFAULT_DISCIPLINE_SNAPSHOT_FILE = qpaths.DISCIPLINE_SNAPSHOT_FILE


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


def load_discipline_snapshot(*, path: str = DEFAULT_DISCIPLINE_SNAPSHOT_FILE):
    return _read_json(path)


def save_discipline_snapshot(snapshot: Mapping, *, path: str = DEFAULT_DISCIPLINE_SNAPSHOT_FILE) -> str:
    return _write_json(path, snapshot)


def _parse_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _resolve_review_month(now=None):
    now = now or datetime.now()
    return now.year, now.month, f"{now.year:04d}-{now.month:02d}"


def _journal_entry_month(entry):
    recap = dict((entry or {}).get("daily_recap", {}) or {})
    for candidate in [recap.get("day"), (entry or {}).get("generated_at")]:
        parsed = _parse_datetime(candidate)
        if parsed is not None:
            return parsed.year, parsed.month
    return None, None


def _classify_discipline_follow_state(entry: Mapping) -> dict:
    entry = dict(entry or {})
    trade_plan = dict(entry.get("trade_plan", {}) or {})
    execution_review = dict(entry.get("execution_review", {}) or {})
    recap = dict(entry.get("daily_recap", {}) or {})
    discipline_snapshot = dict(entry.get("discipline_snapshot", {}) or {})

    has_actions = bool(trade_plan.get("has_actions"))
    trade_count = int(_safe_float(recap.get("trade_count"), 0) or 0)
    executed_count = int(_safe_float(execution_review.get("executed_count"), 0) or 0)
    missed_count = int(_safe_float(execution_review.get("missed_count"), 0) or 0)
    unplanned_trade_count = int(_safe_float(execution_review.get("unplanned_trade_count"), 0) or 0)
    realized_pl = _safe_float(recap.get("realized_pl"), 0.0) or 0.0
    regime = str(discipline_snapshot.get("regime") or "UNKNOWN").upper()

    if has_actions:
        if unplanned_trade_count > 0 or missed_count > 0:
            state = "IGNORE"
        elif executed_count > 0:
            state = "FOLLOW"
        else:
            state = "PENDING"
    else:
        if trade_count > 0:
            state = "IGNORE"
        else:
            state = "FOLLOW"

    return {
        "state": state,
        "has_actions": has_actions,
        "trade_count": trade_count,
        "executed_count": executed_count,
        "missed_count": missed_count,
        "unplanned_trade_count": unplanned_trade_count,
        "realized_pl": realized_pl,
        "regime": regime,
    }


def build_monthly_discipline_review(
    *,
    discipline_snapshot: Optional[Mapping] = None,
    scoreboard=None,
    latest_post_close_review: Optional[Mapping] = None,
    snapshot_journal=None,
    journal_path: str = ss.DEFAULT_NIGHTLY_JOURNAL_FILE,
    now: Optional[datetime] = None,
):
    year, month, month_key = _resolve_review_month(now=now)
    entries = list(snapshot_journal or ss.load_snapshot_journal(journal_path=journal_path))
    month_entries = []
    for entry in entries:
        entry_year, entry_month = _journal_entry_month(entry)
        if entry_year == year and entry_month == month:
            month_entries.append(dict(entry or {}))

    follow_days = 0
    ignore_days = 0
    pending_days = 0
    follow_action_days = 0
    ignore_action_days = 0
    follow_idle_days = 0
    ignore_idle_days = 0
    defensive_override_days = 0
    follow_realized_pl = 0.0
    ignore_realized_pl = 0.0
    reviewed_symbols = set()

    for entry in month_entries:
        recap = dict(entry.get("daily_recap", {}) or {})
        for symbol in list(recap.get("symbols", []) or []):
            text = str(symbol or "").strip().upper()
            if text:
                reviewed_symbols.add(text)

        classified = _classify_discipline_follow_state(entry)
        state = classified["state"]
        has_actions = classified["has_actions"]
        realized_pl = classified["realized_pl"]
        regime = classified["regime"]
        trade_count = classified["trade_count"]

        if state == "FOLLOW":
            follow_days += 1
            follow_realized_pl += realized_pl
            if has_actions:
                follow_action_days += 1
            else:
                follow_idle_days += 1
        elif state == "IGNORE":
            ignore_days += 1
            ignore_realized_pl += realized_pl
            if has_actions:
                ignore_action_days += 1
            else:
                ignore_idle_days += 1
            if regime in {"LIGHT", "STOP"} and trade_count > 0:
                defensive_override_days += 1
        else:
            pending_days += 1

    expectancy = getattr(scoreboard, "expectancy_return_pct", None) if scoreboard is not None else None
    win_rate = getattr(scoreboard, "win_rate", None) if scoreboard is not None else None
    latest_post_close_review = dict(latest_post_close_review or {})
    executed_count = int(_safe_float(latest_post_close_review.get("executed_count"), 0) or 0)
    missed_count = int(_safe_float(latest_post_close_review.get("missed_count"), 0) or 0)
    unplanned_trade_count = int(_safe_float(latest_post_close_review.get("unplanned_trade_count"), 0) or 0)
    current_regime = str((discipline_snapshot or {}).get("regime") or "UNKNOWN").upper()

    status = "MONITOR"
    summary = "当前月度纪律复盘样本仍不足，先继续观察。"
    notes = []

    if not month_entries:
        status = "MONITOR"
        summary = "当前月份还没有夜间复盘样本，月度纪律评估会随着 nightly 日志逐步充实。"
        notes.append("请继续使用 nightly 计划 / 收盘复盘闭环，系统会自动积累 follow / ignore 样本。")
    elif ignore_days == 0 and follow_days > 0:
        status = "ALIGNED"
        summary = "本月已有的计划执行整体保持纪律，没有检测到明显的偏离日。"
        notes.append(f"FOLLOW 天数 {follow_days}，其中有动作执行 {follow_action_days} 天，无动作保持空手 {follow_idle_days} 天。")
    elif ignore_days > 0 and ignore_days >= follow_days:
        status = "CAUTION"
        summary = "本月纪律偏离天数偏多，系统建议优先减少计划外交易与防守状态下的手动加仓。"
        notes.append(f"IGNORE 天数 {ignore_days}，高于或等于 FOLLOW 天数 {follow_days}。")
    else:
        status = "MONITOR"
        summary = "本月纪律执行整体可控，但仍存在少量偏离，需要继续观察。"
        notes.append(f"FOLLOW {follow_days} 天，IGNORE {ignore_days} 天，PENDING {pending_days} 天。")

    if defensive_override_days > 0:
        notes.append(f"在 LIGHT/STOP 防守状态下仍发生交易的天数为 {defensive_override_days} 天。")
    if unplanned_trade_count > 0:
        notes.append(f"最近一次收盘复盘仍检测到 {unplanned_trade_count} 笔计划外交易。")
    elif missed_count > 0:
        notes.append(f"最近一次收盘复盘显示错过 {missed_count} 条计划内动作。")
    elif executed_count > 0:
        notes.append(f"最近一次收盘复盘显示执行了 {executed_count} 条计划内动作。")

    rows = [
        {"检查项": "当前纪律状态", "观察": current_regime},
        {"检查项": "FOLLOW 天数", "观察": str(follow_days)},
        {"检查项": "IGNORE 天数", "观察": str(ignore_days)},
        {"检查项": "PENDING 天数", "观察": str(pending_days)},
        {"检查项": "有动作且遵守", "观察": str(follow_action_days)},
        {"检查项": "无动作且不交易", "观察": str(follow_idle_days)},
        {"检查项": "有动作但偏离", "观察": str(ignore_action_days)},
        {"检查项": "无动作却交易", "观察": str(ignore_idle_days)},
        {"检查项": "防守状态下仍交易", "观察": str(defensive_override_days)},
        {"检查项": "FOLLOW 组已实现盈亏", "观察": f"${follow_realized_pl:+,.2f}"},
        {"检查项": "IGNORE 组已实现盈亏", "观察": f"${ignore_realized_pl:+,.2f}"},
        {"检查项": "最近一次计划执行", "观察": f"执行 {executed_count} / 错过 {missed_count} / 计划外 {unplanned_trade_count}"},
        {"检查项": "实时信号胜率", "观察": f"{float(win_rate):.2%}" if win_rate is not None else "—"},
        {"检查项": "实时期望收益", "观察": f"{float(expectancy):+.2%}" if expectancy is not None else "—"},
    ]

    return {
        "month": month_key,
        "status": status,
        "summary": summary,
        "notes": notes,
        "follow_days": follow_days,
        "ignore_days": ignore_days,
        "pending_days": pending_days,
        "follow_action_days": follow_action_days,
        "ignore_action_days": ignore_action_days,
        "follow_idle_days": follow_idle_days,
        "ignore_idle_days": ignore_idle_days,
        "defensive_override_days": defensive_override_days,
        "follow_realized_pl": round(follow_realized_pl, 4),
        "ignore_realized_pl": round(ignore_realized_pl, 4),
        "reviewed_symbols": sorted(reviewed_symbols),
        "executed_count": executed_count,
        "missed_count": missed_count,
        "unplanned_trade_count": unplanned_trade_count,
        "rows": rows,
    }


def build_discipline_snapshot(
    *,
    account_snapshot: Mapping,
    risk_gate=None,
    allocation_regime=None,
    analysis_freshness_alert: Optional[Mapping] = None,
    core_etf_snapshot: Optional[Mapping] = None,
    policy: Optional[Mapping] = None,
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.now()
    policy = cer.normalize_engine_policy(policy or cer.load_engine_policy())
    analysis_freshness_alert = dict(analysis_freshness_alert or {})
    expired_symbols = list(analysis_freshness_alert.get("expired_symbols", []) or [])
    missing_symbols = list(analysis_freshness_alert.get("missing_symbols", []) or [])
    stale_symbols = list(analysis_freshness_alert.get("stale_symbols", []) or [])

    risk_regime = str(getattr(risk_gate, "regime", "NORMAL") or "NORMAL").upper() if risk_gate is not None else "NORMAL"
    allocation_name = str(getattr(allocation_regime, "regime", "NORMAL") or "NORMAL").upper() if allocation_regime is not None else "NORMAL"
    base_regime = allocation_name if allocation_name in {"HEAVY", "NORMAL", "LIGHT", "STOP"} else "NORMAL"
    reasons = list(getattr(allocation_regime, "reasons", []) or []) if allocation_regime is not None else []
    risk_reasons = list(getattr(risk_gate, "reasons", []) or []) if risk_gate is not None else []
    warnings = []

    if risk_regime == "RISK_OFF":
        base_regime = "STOP"
        warnings.append("市场风险处于 RISK_OFF，新增仓位暂停。")
    elif risk_regime == "CAUTION" and base_regime == "HEAVY":
        base_regime = "LIGHT"
        warnings.append("市场风险处于 CAUTION，重仓建议自动降级。")

    if expired_symbols or missing_symbols:
        if base_regime == "HEAVY":
            base_regime = "LIGHT"
        warnings.append("持仓全量分析存在过期或缺失，暂停依赖高仓位建议。")

    deployable_cash = _safe_float((account_snapshot or {}).get("deployable_cash"), 0.0) or 0.0
    exposure_pct = _safe_float((account_snapshot or {}).get("exposure_pct"), 0.0) or 0.0
    target_exposure_min_pct = _safe_float(
        getattr(allocation_regime, "target_exposure_min_pct", None) if allocation_regime is not None else None,
        20.0,
    ) or 20.0
    target_exposure_max_pct = _safe_float(
        getattr(allocation_regime, "target_exposure_max_pct", None) if allocation_regime is not None else None,
        85.0,
    ) or 85.0

    if deployable_cash <= 0.0:
        warnings.append("可部署现金不足，默认不建议新增仓位。")
    if exposure_pct >= target_exposure_max_pct:
        warnings.append("当前总暴露已接近上限，优先考虑减仓而不是继续加仓。")
        if base_regime == "HEAVY":
            base_regime = "LIGHT"

    core_rows = list((core_etf_snapshot or {}).get("symbols", []) or [])
    accumulate_symbols = [row.get("symbol") for row in core_rows if row.get("action") == "ACCUMULATE"]
    trim_symbols = [row.get("symbol") for row in core_rows if row.get("action") in {"TRIM", "RISK_EXIT"}]
    pause_symbols = [row.get("symbol") for row in core_rows if row.get("action") == "PAUSE_BUY"]

    can_open_new_core_positions = base_regime not in {"STOP"} and deployable_cash > 0.0
    can_open_new_satellite_positions = base_regime in {"HEAVY", "NORMAL"} and deployable_cash > 0.0 and not (expired_symbols or missing_symbols)
    if risk_regime == "CAUTION":
        can_open_new_satellite_positions = False
        warnings.append("警戒行情下暂停新开卫星仓。")

    headline_map = {
        "HEAVY": "当前可偏重仓，但仍需遵守单仓与暴露上限。",
        "NORMAL": "当前可正常执行计划，但不建议无计划追价。",
        "LIGHT": "当前以轻仓与防守为主，只执行高确定性动作。",
        "STOP": "当前应停手或仅执行风险退出动作。",
    }
    summary = headline_map.get(base_regime, "当前以纪律层结论为准。")
    if warnings:
        summary += " " + " ".join(warnings[:2])

    return {
        "generated_at": now.isoformat(),
        "regime": base_regime,
        "risk_regime": risk_regime,
        "allocation_regime": allocation_name,
        "summary": summary,
        "can_open_new_core_positions": can_open_new_core_positions,
        "can_open_new_satellite_positions": can_open_new_satellite_positions,
        "satellite_max_total_weight_pct": float(policy.get("satellite_max_total_weight_pct", 15.0) or 15.0),
        "satellite_max_single_weight_pct": float(policy.get("satellite_max_single_weight_pct", 5.0) or 5.0),
        "deployable_cash": deployable_cash,
        "exposure_pct": exposure_pct,
        "target_exposure_min_pct": target_exposure_min_pct,
        "target_exposure_max_pct": target_exposure_max_pct,
        "warnings": warnings,
        "reasons": list(dict.fromkeys(reasons + risk_reasons)),
        "analysis_stale_symbols": stale_symbols,
        "analysis_expired_symbols": expired_symbols,
        "analysis_missing_symbols": missing_symbols,
        "core_accumulate_symbols": [symbol for symbol in accumulate_symbols if symbol],
        "core_trim_symbols": [symbol for symbol in trim_symbols if symbol],
        "core_pause_symbols": [symbol for symbol in pause_symbols if symbol],
    }
