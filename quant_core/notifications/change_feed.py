from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths


RECOMMENDATION_LABELS = {
    "STRONG_OPPORTUNITY": "强估值机会",
    "ACCUMULATE": "可分批研究",
    "WATCH": "继续观察",
    "WAIT_FOR_STABILIZATION": "等待企稳",
    "FUNDAMENTALS_DAMAGED": "基本面受损",
    "VALUE_TRAP_RISK": "价值陷阱风险",
    "INSUFFICIENT_DATA": "数据不足",
    "OVERVALUED": "估值偏高",
    "FAIR_VALUE_NOT_OVERSOLD": "未明显超跌",
    "LLM_REVIEW_REQUIRED": "等待模型复核",
}


def _label(value: str) -> str:
    return RECOMMENDATION_LABELS.get(value, value or "未覆盖")


def build_change_feed(previous: Optional[Mapping], current: Optional[Mapping], *, now: Optional[datetime] = None) -> dict:
    previous_rows = {str(row.get("symbol") or "").upper(): dict(row) for row in list(dict(previous or {}).get("recommendations", []) or [])}
    current_rows = {str(row.get("symbol") or "").upper(): dict(row) for row in list(dict(current or {}).get("recommendations", []) or [])}
    items = []
    for symbol, row in current_rows.items():
        old = previous_rows.get(symbol, {})
        before = str(old.get("recommendation") or "")
        after = str(row.get("recommendation") or "")
        if row.get("actionable") and not old.get("actionable"):
            items.append({"priority": "HIGH", "category": "new_opportunity", "symbol": symbol, "title": f"{symbol}出现新的估值机会", "message": f"结论变为{_label(after)}，安全边际{float(row.get('margin_of_safety') or 0):.1%}。"})
        elif after in {"FUNDAMENTALS_DAMAGED", "VALUE_TRAP_RISK"} and before != after:
            items.append({"priority": "HIGH", "category": "fundamental_risk", "symbol": symbol, "title": f"{symbol}基本面风险升级", "message": f"结论从{_label(before)}变为{_label(after)}。"})
        elif before and before != after:
            items.append({"priority": "MEDIUM", "category": "recommendation_change", "symbol": symbol, "title": f"{symbol}结论变化", "message": f"{_label(before)} → {_label(after)}"})
        elif old and abs(float(row.get("opportunity_score") or 0) - float(old.get("opportunity_score") or 0)) >= 10:
            items.append({"priority": "LOW", "category": "score_change", "symbol": symbol, "title": f"{symbol}机会分变化", "message": f"{old.get('opportunity_score')} → {row.get('opportunity_score')}"})
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    items.sort(key=lambda row: priority_order.get(row["priority"], 3))
    return {
        "schema_version": 1,
        "generated_at": (now or datetime.now()).isoformat(),
        "status": "READY",
        "summary": {
            "high_count": sum(row["priority"] == "HIGH" for row in items),
            "medium_count": sum(row["priority"] == "MEDIUM" for row in items),
            "low_count": sum(row["priority"] == "LOW" for row in items),
        },
        "items": items,
        "high_items": [row for row in items if row["priority"] == "HIGH"],
        "medium_items": [row for row in items if row["priority"] == "MEDIUM"],
        "low_items": [row for row in items if row["priority"] == "LOW"],
    }


def save_change_feed(feed: Mapping, path: str = qpaths.CHANGE_FEED_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(feed or {}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(target)
