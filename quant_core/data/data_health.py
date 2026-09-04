from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths
from quant_core.data.prices import cache_status


def build_data_health_snapshot(
    *,
    opportunities: Optional[Mapping] = None,
    valuations: Optional[Mapping] = None,
    market_risk: Optional[Mapping] = None,
    now: Optional[datetime] = None,
    require_llm_route: bool = False,
) -> dict:
    now = now or datetime.now()
    opportunities = dict(opportunities or {})
    valuations = dict(valuations or {})
    market_risk = dict(market_risk or {})
    price_health = cache_status()
    opportunity_rows = list(opportunities.get("opportunities", []) or [])
    valuation_rows = list(valuations.get("valuations", []) or [])
    source_counts = {}
    llm_routes = 0
    for row in valuation_rows:
        source = str(row.get("financial_source") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        if str(row.get("route_source") or "") == "llm":
            llm_routes += 1
    errors = list(opportunities.get("errors", []) or [])
    opportunity_summary = dict(opportunities.get("summary", {}) or {})
    has_research_payload = bool(opportunity_summary or opportunity_rows or errors)
    analyzed = len(opportunity_rows)
    requested = int(opportunity_summary.get("deep_analysis_count") or analyzed or 1)
    scanned = int(opportunity_summary.get("scanned_count") or 0)
    universe_count = int(opportunity_summary.get("universe_count") or scanned or requested)
    coverage = analyzed / max(requested, 1)
    error_ratio = len(errors) / max(universe_count, 1)
    status = "OK"
    reasons = []
    warnings = []
    if price_health.get("status") != "OK" and scanned <= 0:
        status = "DEGRADED"
        reasons.append("价格缓存缺失或过期")
    elif price_health.get("status") != "OK":
        warnings.append("最新价缓存缺失或过期，但本次研究历史行情完整")
    if market_risk.get("status") not in {"READY", "OK"}:
        status = "DEGRADED"
        reasons.append("市场风险数据不完整")
    if has_research_payload and coverage < 0.7:
        status = "DEGRADED"
        reasons.append("深度估值完成率低于70%")
    if has_research_payload and error_ratio > 0.15:
        status = "DEGRADED"
        reasons.append("标的处理失败比例超过15%")
    elif has_research_payload and errors:
        warnings.append(f"{len(errors)}条标的级错误未达到全局降级阈值")
    if has_research_payload and require_llm_route and analyzed and llm_routes / analyzed < 0.5:
        status = "DEGRADED"
        reasons.append("多数标的缺少LLM估值路由确认")
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "status": status,
        "summary": {
            "status": status,
            "reason": "；".join(reasons) if reasons else "价格、财报、估值与风险快照正常",
            "warnings": "；".join(warnings),
            "price_cache": price_health,
            "history_source_counts": dict(opportunity_summary.get("price_source_counts", {}) or {}),
            "scan_count": scanned,
            "analyzed_count": analyzed,
            "valuation_count": len(valuation_rows),
            "llm_route_count": llm_routes,
            "financial_source_counts": source_counts,
            "error_count": len(errors),
            "error_ratio": round(error_ratio, 4),
        },
        "errors": errors,
    }


def save_data_health_snapshot(snapshot: Mapping, path: str = qpaths.DATA_HEALTH_SNAPSHOT_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(snapshot or {}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(target)
