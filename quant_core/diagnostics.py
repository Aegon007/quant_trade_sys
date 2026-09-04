from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from quant_core import paths as qpaths
from quant_core.data.prices import cache_status


DIAGNOSTIC_FILES = {
    "opportunities.json": qpaths.OPPORTUNITY_SNAPSHOT_FILE,
    "valuations.json": qpaths.VALUATION_SNAPSHOT_FILE,
    "recommendations.json": qpaths.RECOMMENDATION_SNAPSHOT_FILE,
    "market_risk.json": qpaths.MARKET_RISK_SNAPSHOT_FILE,
    "data_health.json": qpaths.DATA_HEALTH_SNAPSHOT_FILE,
    "change_feed.json": qpaths.CHANGE_FEED_FILE,
    "calibration.json": qpaths.VALUATION_CALIBRATION_FILE,
    "research_manifest.json": qpaths.RESEARCH_MANIFEST_FILE,
    "job_status.json": qpaths.JOB_STATUS_FILE,
    "research_universe.json": qpaths.RESEARCH_UNIVERSE_FILE,
    "valuation_policy.json": qpaths.VALUATION_POLICY_FILE,
}


def _read(path: str) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def build_diagnostics_summary(*, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now()
    recommendations = _read(qpaths.RECOMMENDATION_SNAPSHOT_FILE)
    health = _read(qpaths.DATA_HEALTH_SNAPSHOT_FILE)
    risk = _read(qpaths.MARKET_RISK_SNAPSHOT_FILE)
    jobs = _read(qpaths.JOB_STATUS_FILE)
    return {
        "generated_at": now.isoformat(),
        "research": dict(recommendations.get("summary", {}) or {}),
        "data_health": {"status": health.get("status"), "score": health.get("score"), **dict(health.get("summary", {}) or {})},
        "market_risk": {"regime": risk.get("regime"), "risk_score": risk.get("risk_score")},
        "price_cache": cache_status(),
        "jobs": {name: {"state": row.get("state"), "updated_at": row.get("updated_at"), "detail": row.get("detail")} for name, row in dict(jobs.get("jobs", {}) or {}).items()},
    }


def build_diagnostics_bundle(*, now: Optional[datetime] = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics_summary.json", json.dumps(build_diagnostics_summary(now=now), ensure_ascii=False, indent=2, default=str))
        archive.writestr("README.txt", "估值研究系统诊断包。仅包含研究快照和脱敏运行状态，不包含任何密钥。\n")
        for name, path in DIAGNOSTIC_FILES.items():
            target = Path(path)
            if target.exists():
                archive.write(target, f"snapshots/{name}")
    return buffer.getvalue()
