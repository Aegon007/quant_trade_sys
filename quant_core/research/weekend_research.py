from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths
from quant_core.research import strategy_validation as sval


DEFAULT_WEEKEND_RESEARCH_SNAPSHOT_FILE = qpaths.WEEKEND_RESEARCH_SNAPSHOT_FILE
DEFAULT_WEEKEND_RESEARCH_STATE_FILE = qpaths.WEEKEND_RESEARCH_STATE_FILE
DEFAULT_WEEKEND_REPORTS_DIR = str(qpaths.PROJECT_ROOT / "reports")
_WEEKDAY_INDEX = {"saturday": 5, "sunday": 6}


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
    target.write_text(json.dumps(dict(payload or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def normalize_weekend_research_schedule(alert_settings: Optional[Mapping]):
    payload = dict(alert_settings or {})
    day = str(payload.get("weekend_research_day_local") or "sunday").strip().lower()
    if day not in _WEEKDAY_INDEX:
        day = "sunday"
    hour = max(0, min(23, int(_safe_float(payload.get("weekend_research_hour_local"), 11) or 11)))
    minute = max(0, min(59, int(_safe_float(payload.get("weekend_research_minute_local"), 0) or 0)))
    history_period = str(payload.get("weekend_research_history_period") or "5y").strip() or "5y"
    return {
        "enabled": bool(payload.get("enable_weekend_research", True)),
        "send_summary": bool(payload.get("send_weekend_research_summary", True)),
        "day": day,
        "hour": hour,
        "minute": minute,
        "history_period": history_period,
    }


def weekend_cycle_key(now: datetime, *, day: str = "sunday") -> str:
    day = str(day or "sunday").strip().lower()
    target_idx = _WEEKDAY_INDEX.get(day, 6)
    delta_days = (now.weekday() - target_idx) % 7
    target_date = (now - timedelta(days=delta_days)).date()
    return f"{day}:{target_date.isoformat()}"


def load_weekend_research_snapshot(*, path: str = DEFAULT_WEEKEND_RESEARCH_SNAPSHOT_FILE):
    return _read_json(path) or {}


def save_weekend_research_snapshot(snapshot: Mapping, *, path: str = DEFAULT_WEEKEND_RESEARCH_SNAPSHOT_FILE):
    return _write_json(path, snapshot)


def load_weekend_research_state(*, path: str = DEFAULT_WEEKEND_RESEARCH_STATE_FILE):
    return _read_json(path) or {}


def save_weekend_research_state(state: Mapping, *, path: str = DEFAULT_WEEKEND_RESEARCH_STATE_FILE):
    return _write_json(path, state)


def should_run_weekend_research(
    *,
    now: Optional[datetime] = None,
    alert_settings: Optional[Mapping] = None,
    state_path: str = DEFAULT_WEEKEND_RESEARCH_STATE_FILE,
) -> bool:
    now = now or datetime.now()
    schedule = normalize_weekend_research_schedule(alert_settings)
    if not schedule["enabled"]:
        return False
    if now.weekday() != _WEEKDAY_INDEX[schedule["day"]]:
        return False
    if (now.hour, now.minute) < (schedule["hour"], schedule["minute"]):
        return False
    cycle_key = weekend_cycle_key(now, day=schedule["day"])
    state = load_weekend_research_state(path=state_path)
    return str(state.get("last_cycle_key") or "").strip() != cycle_key


def mark_weekend_research_done(
    *,
    now: Optional[datetime] = None,
    alert_settings: Optional[Mapping] = None,
    snapshot: Optional[Mapping] = None,
    state_path: str = DEFAULT_WEEKEND_RESEARCH_STATE_FILE,
):
    now = now or datetime.now()
    schedule = normalize_weekend_research_schedule(alert_settings)
    payload = {
        "last_cycle_key": weekend_cycle_key(now, day=schedule["day"]),
        "last_run_at": now.isoformat(),
        "last_history_period": schedule["history_period"],
        "last_bias": str(dict(snapshot or {}).get("summary", {}).get("next_week_bias") or "").strip(),
    }
    return save_weekend_research_state(payload, path=state_path)


def build_weekend_research_snapshot(
    *,
    now: datetime,
    history_period: str,
    risk_gate=None,
    allocation_regime=None,
    core_rotation_snapshot: Optional[Mapping] = None,
    core_snapshot: Optional[Mapping] = None,
    satellite_snapshot: Optional[Mapping] = None,
    strategy_research_rows=None,
    strategy_validation_snapshot: Optional[Mapping] = None,
):
    core_rotation_snapshot = dict(core_rotation_snapshot or {})
    core_snapshot = dict(core_snapshot or {})
    satellite_snapshot = dict(satellite_snapshot or {})
    strategy_research_rows = list(strategy_research_rows or [])
    strategy_validation_snapshot = dict(strategy_validation_snapshot or {})
    validation_summary = dict(strategy_validation_snapshot.get("summary", {}) or {})

    risk_regime = str(getattr(risk_gate, "regime", "") or dict(risk_gate or {}).get("regime") or "UNKNOWN").strip().upper()
    allocation_name = str(getattr(allocation_regime, "regime", "") or dict(allocation_regime or {}).get("regime") or "UNKNOWN").strip().upper()
    core_summary = dict(core_snapshot.get("summary", {}) or {})
    satellite_summary = dict(satellite_snapshot.get("summary", {}) or {})
    focus_symbols = list(core_rotation_snapshot.get("summary", {}).get("focus_symbols", []) or [])
    top_recommendations = [dict(row or {}) for row in list(satellite_snapshot.get("top_recommendations", []) or [])]

    next_week_bias = "BALANCED"
    if risk_regime == "RISK_OFF" or allocation_name == "STOP":
        next_week_bias = "DEFENSIVE"
    elif risk_regime == "CAUTION" or allocation_name == "LIGHT":
        next_week_bias = "CAUTION"
    elif int(core_summary.get("accumulate_count", 0) or 0) >= 2 or int(satellite_summary.get("confirmed_count", 0) or 0) >= 2:
        next_week_bias = "RISK_ON"
    validation_status = str(validation_summary.get("status") or "").strip().upper()
    if validation_status == "REVIEW" and next_week_bias in {"RISK_ON", "BALANCED"}:
        next_week_bias = "CAUTION"
    elif validation_status == "CAUTION" and next_week_bias == "RISK_ON":
        next_week_bias = "BALANCED"

    recommendations = []
    if core_summary.get("focus_symbols"):
        recommendations.append(f"核心 ETF 焦点: {', '.join(list(core_summary.get('focus_symbols', []) or [])[:3])}")
    if top_recommendations:
        recommendations.append(f"卫星候选 Top: {', '.join([str(row.get('symbol') or '') for row in top_recommendations[:3] if row.get('symbol')])}")
    if strategy_research_rows:
        first = dict(strategy_research_rows[0] or {})
        if first.get("best_strategy_name") and first.get("symbol"):
            recommendations.append(f"{first['symbol']} 周末策略对比领先: {first['best_strategy_name']}")
    if validation_status:
        recommendations.append(
            f"默认策略验证: {validation_status}（覆盖 {int(validation_summary.get('symbol_count', 0) or 0)}，预警 {len(list(validation_summary.get('warning_symbols', []) or []))}）"
        )

    summary_message = {
        "DEFENSIVE": "下周优先防守，减少主动进攻和高波动新仓。",
        "CAUTION": "下周以谨慎和轻仓为主，只执行高确定性计划单。",
        "BALANCED": "下周维持平衡执行，核心仓按计划微调，卫星仓严格挑选。",
        "RISK_ON": "下周允许更积极地执行核心增配和高质量卫星候选，但仍需遵守纪律层。",
    }.get(next_week_bias, "下周以结构化计划和纪律层结论为准。")

    return {
        "generated_at": now.isoformat(),
        "history_period": history_period,
        "summary": {
            "risk_regime": risk_regime,
            "allocation_regime": allocation_name,
            "next_week_bias": next_week_bias,
            "strategy_validation_status": validation_status or "NO_DATA",
            "core_focus_count": len(focus_symbols),
            "satellite_top_count": len(top_recommendations),
            "strategy_compare_count": len(strategy_research_rows),
            "message": summary_message,
        },
        "core_rotation_snapshot": core_rotation_snapshot,
        "core_snapshot": core_snapshot,
        "satellite_snapshot": satellite_snapshot,
        "strategy_research_rows": strategy_research_rows,
        "strategy_validation_snapshot": strategy_validation_snapshot,
        "recommendations": recommendations,
    }


def build_weekend_research_report(snapshot: Mapping) -> str:
    snapshot = dict(snapshot or {})
    summary = dict(snapshot.get("summary", {}) or {})
    lines = [
        "# Weekend Research Report",
        "",
        f"- Generated at: {snapshot.get('generated_at') or '—'}",
        f"- History period: {snapshot.get('history_period') or '—'}",
        f"- Next-week bias: {summary.get('next_week_bias') or '—'}",
        f"- Risk regime: {summary.get('risk_regime') or '—'}",
        f"- Allocation regime: {summary.get('allocation_regime') or '—'}",
        "",
        summary.get("message") or "",
        "",
    ]
    recommendations = [str(item).strip() for item in list(snapshot.get("recommendations", []) or []) if str(item).strip()]
    if recommendations:
        lines.append("## Recommendations")
        lines.append("")
        lines.extend([f"- {item}" for item in recommendations])
        lines.append("")
    strategy_rows = list(snapshot.get("strategy_research_rows", []) or [])
    if strategy_rows:
        lines.append("## Strategy Compare Highlights")
        lines.append("")
        for row in strategy_rows[:5]:
            lines.append(
                f"- {row.get('symbol')}: {row.get('best_strategy_name') or '—'} "
                f"(score {float(_safe_float(row.get('best_strategy_score'), 0.0) or 0.0):.2f})"
            )
        lines.append("")
    validation_snapshot = dict(snapshot.get("strategy_validation_snapshot", {}) or {})
    validation_summary = dict(validation_snapshot.get("summary", {}) or {})
    if validation_summary:
        lines.append("## Strategy Validation")
        lines.append("")
        lines.append(
            "- "
            f"Status: {validation_summary.get('status') or '—'} | "
            f"Coverage: {int(_safe_float(validation_summary.get('symbol_count'), 0) or 0)} | "
            f"Validated: {int(_safe_float(validation_summary.get('validated_count'), 0) or 0)} | "
            f"Warnings: {len(list(validation_summary.get('warning_symbols', []) or []))}"
        )
        message = str(validation_summary.get("message") or "").strip()
        if message:
            lines.append(f"- Summary: {message}")
        warnings = ", ".join(list(validation_summary.get("warning_symbols", []) or []))
        if warnings:
            lines.append(f"- Warning symbols: {warnings}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def save_weekend_research_report_files(
    snapshot: Mapping,
    *,
    report_text: Optional[str] = None,
    reports_dir: str = DEFAULT_WEEKEND_REPORTS_DIR,
):
    report_text = report_text or build_weekend_research_report(snapshot)
    target_dir = Path(reports_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    generated_at = str(dict(snapshot or {}).get("generated_at") or datetime.now().isoformat()).replace(":", "").replace("-", "")
    generated_at = generated_at.replace("T", "_")[:15]
    timestamp_base = target_dir / f"weekend_research_{generated_at}"
    latest_base = target_dir / "weekend_research_latest"
    json_payload = json.dumps(dict(snapshot or {}), ensure_ascii=False, indent=2)
    (timestamp_base.with_suffix(".md")).write_text(report_text, encoding="utf-8")
    (timestamp_base.with_suffix(".json")).write_text(json_payload, encoding="utf-8")
    (latest_base.with_suffix(".md")).write_text(report_text, encoding="utf-8")
    (latest_base.with_suffix(".json")).write_text(json_payload, encoding="utf-8")
    return {
        "markdown_path": str(latest_base.with_suffix(".md")),
        "json_path": str(latest_base.with_suffix(".json")),
        "timestamp_markdown_path": str(timestamp_base.with_suffix(".md")),
        "timestamp_json_path": str(timestamp_base.with_suffix(".json")),
    }
