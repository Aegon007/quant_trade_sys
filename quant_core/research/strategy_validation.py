from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Optional

from quant_core import paths as qpaths


DEFAULT_STRATEGY_VALIDATION_SNAPSHOT_FILE = qpaths.STRATEGY_VALIDATION_SNAPSHOT_FILE
DEFAULT_STRATEGY_EXPERIMENT_JOURNAL_FILE = qpaths.STRATEGY_EXPERIMENT_JOURNAL_FILE


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


def _safe_int(value, default=0):
    try:
        if value is None:
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


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


def load_strategy_validation_snapshot(*, path: str = DEFAULT_STRATEGY_VALIDATION_SNAPSHOT_FILE):
    return _read_json(path) or {}


def save_strategy_validation_snapshot(snapshot: Mapping, *, path: str = DEFAULT_STRATEGY_VALIDATION_SNAPSHOT_FILE):
    return _write_json(path, snapshot)


def load_strategy_experiment_journal(*, journal_path: str = DEFAULT_STRATEGY_EXPERIMENT_JOURNAL_FILE, limit=None):
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


def append_strategy_experiment_journal(
    snapshot: Mapping,
    *,
    journal_path: str = DEFAULT_STRATEGY_EXPERIMENT_JOURNAL_FILE,
):
    snapshot = dict(snapshot or {})
    summary = dict(snapshot.get("summary", {}) or {})
    entry = {
        "generated_at": snapshot.get("generated_at"),
        "history_period": snapshot.get("history_period"),
        "source": snapshot.get("source"),
        "default_strategy_id": dict(snapshot.get("default_strategy", {}) or {}).get("id"),
        "default_strategy_name": dict(snapshot.get("default_strategy", {}) or {}).get("name"),
        "status": summary.get("status"),
        "symbol_count": int(_safe_int(summary.get("symbol_count"), 0) or 0),
        "validated_count": int(_safe_int(summary.get("validated_count"), 0) or 0),
        "low_sample_count": int(_safe_int(summary.get("low_sample_count"), 0) or 0),
        "caution_count": int(_safe_int(summary.get("caution_count"), 0) or 0),
        "review_count": int(_safe_int(summary.get("review_count"), 0) or 0),
        "avg_default_rank": _safe_float(summary.get("avg_default_rank")),
        "avg_score_gap": _safe_float(summary.get("avg_score_gap")),
        "warning_symbols": list(summary.get("warning_symbols", []) or []),
        "message": summary.get("message"),
    }
    target = Path(journal_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return str(target)


def _normalize_strategy_row(row: Mapping) -> dict:
    row = dict(row or {})
    metric = row.get("composite_score")
    return {
        "strategy_id": str(row.get("strategy_id") or "").strip(),
        "strategy_name": str(row.get("strategy_name") or row.get("strategy") or row.get("name") or "").strip(),
        "composite_score": _safe_float(metric),
        "completed_trades": _safe_int(row.get("completed_trades"), 0),
        "total_return": _safe_float(row.get("total_return")),
        "win_rate": _safe_float(row.get("win_rate")),
        "profit_factor": _safe_float(row.get("profit_factor")),
        "expectancy_return_pct": _safe_float(row.get("expectancy_return_pct")),
        "error": str(row.get("error") or "").strip(),
    }


def build_symbol_strategy_validation(
    *,
    symbol: str,
    comparison_rows: Iterable[Mapping],
    default_strategy: Mapping,
    focus_role: str = "satellite",
):
    rows = [_normalize_strategy_row(row) for row in list(comparison_rows or [])]
    default_strategy = dict(default_strategy or {})
    default_strategy_id = str(default_strategy.get("id") or "").strip()
    default_strategy_name = str(default_strategy.get("name") or default_strategy_id or "default").strip()

    if not rows:
        return {
            "symbol": str(symbol or "").strip().upper(),
            "focus_role": str(focus_role or "satellite").strip().lower(),
            "status": "UNVALIDATED",
            "default_strategy_id": default_strategy_id,
            "default_strategy_name": default_strategy_name,
            "default_rank": None,
            "default_score": None,
            "best_strategy_id": None,
            "best_strategy_name": None,
            "best_score": None,
            "score_gap_vs_best": None,
            "completed_trades": 0,
            "message": "缺少可比较的策略结果。",
        }

    best_row = dict(rows[0] or {})
    default_index = next((index for index, row in enumerate(rows) if row.get("strategy_id") == default_strategy_id), None)
    default_row = dict(rows[default_index] or {}) if default_index is not None else {}
    default_rank = (default_index + 1) if default_index is not None else None
    best_score = _safe_float(best_row.get("composite_score"))
    default_score = _safe_float(default_row.get("composite_score"))
    score_gap = None
    if default_score is not None and best_score is not None:
        score_gap = default_score - best_score
    completed_trades = int(_safe_int(default_row.get("completed_trades"), 0) or 0)

    status = "REVIEW"
    message = "默认策略在该标的上并非当前最优，建议复核。"
    if default_rank is None:
        status = "REVIEW"
        message = "默认策略未出现在当前比较结果中。"
    elif str(default_row.get("error") or "").strip():
        status = "REVIEW"
        message = "默认策略比较失败，需要优先排查。"
    elif default_rank == 1 and completed_trades >= 5:
        status = "VALIDATED"
        message = "默认策略在该标的上领先且样本数足够。"
    elif default_rank == 1:
        status = "LOW_SAMPLE"
        message = "默认策略当前领先，但完成交易样本仍偏少。"
    elif str(focus_role or "satellite").strip().lower() == "core":
        status = "REVIEW"
        message = "默认策略在核心标的上未能保持领先，下周执行前应优先复核。"
    elif default_rank <= 2 and (score_gap is None or score_gap >= -1.0):
        status = "CAUTION"
        message = "默认策略接近领先，但优势不够稳，需要继续观察。"

    return {
        "symbol": str(symbol or "").strip().upper(),
        "focus_role": str(focus_role or "satellite").strip().lower(),
        "status": status,
        "default_strategy_id": default_strategy_id,
        "default_strategy_name": default_strategy_name,
        "default_rank": default_rank,
        "default_score": default_score,
        "best_strategy_id": best_row.get("strategy_id"),
        "best_strategy_name": best_row.get("strategy_name"),
        "best_score": best_score,
        "score_gap_vs_best": score_gap,
        "completed_trades": completed_trades,
        "message": message,
        "top_rows": rows[:3],
    }


def build_strategy_validation_snapshot(
    *,
    now: datetime,
    history_period: str,
    default_strategy: Mapping,
    strategy_research_rows: Iterable[Mapping],
    source: str = "weekend_research",
):
    default_strategy = dict(default_strategy or {})
    rows = []
    for row in list(strategy_research_rows or []):
        item = dict(row or {})
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        comparisons = list(item.get("comparison_rows", []) or item.get("top_rows", []) or [])
        rows.append(
            build_symbol_strategy_validation(
                symbol=symbol,
                comparison_rows=comparisons,
                default_strategy=default_strategy,
                focus_role=item.get("focus_role") or "satellite",
            )
        )

    counts = {"VALIDATED": 0, "LOW_SAMPLE": 0, "CAUTION": 0, "REVIEW": 0, "UNVALIDATED": 0}
    warning_symbols = []
    ranks = []
    score_gaps = []
    for row in rows:
        status = str(row.get("status") or "UNVALIDATED").strip().upper()
        counts[status] = counts.get(status, 0) + 1
        if status in {"CAUTION", "REVIEW"}:
            warning_symbols.append(str(row.get("symbol") or "").strip().upper())
        if row.get("default_rank") is not None:
            ranks.append(float(row.get("default_rank")))
        if row.get("score_gap_vs_best") is not None:
            score_gaps.append(float(row.get("score_gap_vs_best")))

    if not rows:
        summary_status = "NO_DATA"
        message = "当前还没有足够的策略比较结果来验证默认策略。"
    elif counts["REVIEW"] > 0:
        summary_status = "REVIEW"
        message = "默认策略在部分关键标的上明显落后，建议在下周执行前优先复核。"
    elif counts["CAUTION"] > 0 or counts["LOW_SAMPLE"] > 0:
        summary_status = "CAUTION"
        message = "默认策略整体仍可用，但领先优势不够稳或样本偏少。"
    else:
        summary_status = "READY"
        message = "默认策略在当前重点标的上整体领先，可继续作为主执行策略。"

    return {
        "generated_at": now.isoformat(),
        "history_period": str(history_period or "2y").strip() or "2y",
        "source": str(source or "weekend_research").strip() or "weekend_research",
        "default_strategy": {
            "id": str(default_strategy.get("id") or "").strip(),
            "name": str(default_strategy.get("name") or "").strip(),
        },
        "summary": {
            "status": summary_status,
            "symbol_count": len(rows),
            "validated_count": counts.get("VALIDATED", 0),
            "low_sample_count": counts.get("LOW_SAMPLE", 0),
            "caution_count": counts.get("CAUTION", 0),
            "review_count": counts.get("REVIEW", 0),
            "unvalidated_count": counts.get("UNVALIDATED", 0),
            "avg_default_rank": (sum(ranks) / len(ranks)) if ranks else None,
            "avg_score_gap": (sum(score_gaps) / len(score_gaps)) if score_gaps else None,
            "warning_symbols": warning_symbols,
            "message": message,
        },
        "symbols": rows,
    }
