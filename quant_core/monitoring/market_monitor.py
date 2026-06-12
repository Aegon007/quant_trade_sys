from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths
from quant_core.monitoring import intraday_tactical


DEFAULT_MARKET_MONITOR_SNAPSHOT_FILE = qpaths.MARKET_MONITOR_SNAPSHOT_FILE
DEFAULT_MONITOR_SYMBOLS = ["SPY", "QQQ", "VOO", "SCHD"]
DEFAULT_TACTICAL_SYMBOLS = ["SQQQ", "PSQ", "SH"]


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


def load_market_monitor_snapshot(*, path: str = DEFAULT_MARKET_MONITOR_SNAPSHOT_FILE):
    return _read_json(path) or {}


def save_market_monitor_snapshot(snapshot: Mapping, *, path: str = DEFAULT_MARKET_MONITOR_SNAPSHOT_FILE):
    return _write_json(path, snapshot)


def _row_status(change_pct):
    value = _safe_float(change_pct)
    if value is None:
        return "UNKNOWN"
    if value <= -0.03:
        return "PANIC"
    if value <= -0.015:
        return "STRESS"
    if value >= 0.015:
        return "RISK_ON"
    return "NORMAL"


def _normalize_rows(rows, *, symbols=None, row_type="benchmark"):
    wanted = [str(symbol or "").strip().upper() for symbol in list(symbols or []) if str(symbol or "").strip()]
    mapped = {str((row or {}).get("symbol") or "").strip().upper(): dict(row or {}) for row in list(rows or [])}
    output = []
    for symbol in wanted or sorted(mapped):
        row = dict(mapped.get(symbol, {}) or {})
        change_pct = _safe_float(row.get("change_pct"))
        output.append(
            {
                "symbol": symbol,
                "row_type": row_type,
                "role": row.get("role"),
                "current_price": _safe_float(row.get("current_price")),
                "previous_close": _safe_float(row.get("previous_close")),
                "change_pct": change_pct,
                "status": _row_status(change_pct),
            }
        )
    return output


def build_market_monitor_snapshot(
    *,
    tactical_snapshot: Optional[Mapping] = None,
    data_health_snapshot: Optional[Mapping] = None,
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.now()
    tactical_snapshot = dict(tactical_snapshot or {})
    if not tactical_snapshot:
        tactical_snapshot = intraday_tactical.load_intraday_tactical_snapshot()
    data_health_snapshot = dict(data_health_snapshot or {})

    benchmark_rows = _normalize_rows(
        tactical_snapshot.get("benchmark_rows", []),
        symbols=DEFAULT_MONITOR_SYMBOLS,
        row_type="benchmark",
    )
    tactical_rows = _normalize_rows(
        tactical_snapshot.get("tactical_rows", []),
        symbols=DEFAULT_TACTICAL_SYMBOLS,
        row_type="tactical",
    )
    state = str(tactical_snapshot.get("state") or "UNKNOWN").strip().upper()
    recommended_action = str(tactical_snapshot.get("recommended_action") or "NONE").strip().upper()
    urgent = recommended_action in {"TACTICAL_HEDGE", "DO_NOT_CHASE"} or state in {"PANIC", "CAPITULATION"}
    pressure_score = 0
    for row in benchmark_rows:
        status = str(row.get("status") or "UNKNOWN")
        pressure_score += {"PANIC": 3, "STRESS": 2, "NORMAL": 0, "RISK_ON": -1}.get(status, 1)
    data_health_status = str(data_health_snapshot.get("status") or "").strip().upper()
    if data_health_status in {"DEGRADED", "BROKEN"}:
        pressure_score += 1

    return {
        "generated_at": now.isoformat(),
        "status": "URGENT" if urgent else ("STRESS" if pressure_score >= 2 else "OK"),
        "summary": {
            "state": state,
            "recommended_action": recommended_action,
            "recommended_symbol": tactical_snapshot.get("recommended_symbol"),
            "urgent": urgent,
            "pressure_score": pressure_score,
            "data_health_status": data_health_status or None,
            "message": tactical_snapshot.get("message") or "Market monitor snapshot is available.",
        },
        "benchmark_rows": benchmark_rows,
        "tactical_rows": tactical_rows,
        "events": intraday_tactical.build_intraday_tactical_events(tactical_snapshot),
        "tactical_snapshot": tactical_snapshot,
        "data_health_snapshot": data_health_snapshot,
    }
