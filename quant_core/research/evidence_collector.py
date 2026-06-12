from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths


DEFAULT_WEEKEND_RESEARCH_JOURNAL_FILE = qpaths.WEEKEND_RESEARCH_JOURNAL_FILE


def build_evidence_layer(
    *,
    core_snapshot: Optional[Mapping] = None,
    satellite_snapshot: Optional[Mapping] = None,
    strategy_validation_snapshot: Optional[Mapping] = None,
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.now()
    core_snapshot = dict(core_snapshot or {})
    satellite_snapshot = dict(satellite_snapshot or {})
    strategy_validation_snapshot = dict(strategy_validation_snapshot or {})
    evidence = []

    core_summary = dict(core_snapshot.get("summary", {}) or {})
    if core_summary:
        evidence.append(
            {
                "evidence_id": "core_etf_summary",
                "source": "core_etf_snapshot",
                "confidence": "medium",
                "freshness": core_snapshot.get("generated_at"),
                "summary": f"Core focus={', '.join(core_summary.get('focus_symbols', []) or []) or '-'}; accumulate={core_summary.get('accumulate_count', 0)}; trim={core_summary.get('trim_count', 0)}",
            }
        )

    satellite_summary = dict(satellite_snapshot.get("summary", {}) or {})
    if satellite_summary:
        evidence.append(
            {
                "evidence_id": "satellite_top_summary",
                "source": "satellite_candidate_pool",
                "confidence": "medium",
                "freshness": satellite_snapshot.get("generated_at"),
                "summary": f"Satellite top={', '.join(satellite_summary.get('top_symbols', []) or []) or '-'}; pool={satellite_summary.get('candidate_count', 0)}",
            }
        )

    validation_summary = dict(strategy_validation_snapshot.get("summary", {}) or {})
    if validation_summary:
        confidence = "high" if validation_summary.get("status") == "READY" else "medium"
        evidence.append(
            {
                "evidence_id": "strategy_validation_summary",
                "source": "strategy_validation_snapshot",
                "confidence": confidence,
                "freshness": strategy_validation_snapshot.get("generated_at"),
                "summary": str(validation_summary.get("message") or ""),
            }
        )

    return {
        "generated_at": now.isoformat(),
        "evidence_count": len(evidence),
        "evidence": evidence,
        "constraints": [
            "Evidence can influence candidate priority, but cannot bypass risk gate.",
            "LLM summaries are evidence only; they do not directly create trade actions.",
        ],
    }


def append_weekend_research_journal(snapshot: Mapping, *, journal_path: str = DEFAULT_WEEKEND_RESEARCH_JOURNAL_FILE):
    target = Path(journal_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(snapshot or {}), ensure_ascii=False) + "\n")
    return str(target)
