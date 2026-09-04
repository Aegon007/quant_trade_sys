from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths
from quant_core.llm.openai_compatible import call_openai_compatible_chat


REGIME_LABELS = {"NORMAL": "正常", "CAUTION": "谨慎", "HIGH_RISK": "高风险"}


def _fallback(recommendations: Mapping, market_risk: Mapping) -> str:
    rows = list(dict(recommendations or {}).get("recommendations", []) or [])
    actionable = [row for row in rows if row.get("actionable")]
    raw_regime = str(dict(market_risk or {}).get("regime") or "未知")
    regime = REGIME_LABELS.get(raw_regime, raw_regime)
    if not actionable:
        return f"当前市场风险状态为{regime}。估值与超跌筛选没有发现通过全部校验的强机会，今天的明确结论是不追涨、不勉强交易。"
    leaders = "、".join(
        f"{row.get('symbol')}（安全边际{float(row.get('margin_of_safety') or 0):.0%}）"
        for row in actionable[:5]
    )
    return f"当前市场风险状态为{regime}。通过估值、基本面损伤和企稳校验的候选包括{leaders}；仍应按建议区间分批观察，并以各自失效条件为准。"


def build_research_brief(
    recommendations: Mapping,
    market_risk: Mapping,
    *,
    llm_config: Optional[Mapping] = None,
    llm_runner=None,
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.now()
    rows = list(dict(recommendations or {}).get("recommendations", []) or [])
    compact = [
        {
            key: row.get(key)
            for key in (
                "symbol", "recommendation", "actionable", "opportunity_score", "current_price", "fair_value",
                "margin_of_safety", "valuation_confidence", "valuation_model", "archetype", "quality_score",
                "damage_score", "distress_probability", "reason_codes", "event",
            )
        }
        for row in rows[:15]
    ]
    config = dict(llm_config or {})
    text = ""
    llm_meta = {"status": "SKIPPED"}
    if config.get("enabled"):
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the narration layer of a valuation research system. Write concise, natural Chinese. "
                    "Use only supplied structured results, preserve recommendation labels, distinguish facts from uncertainty, "
                    "and never invent prices, events, or trade actions."
                ),
            },
            {
                "role": "user",
                "content": (
                    "请形成今日市场估值与超跌机会摘要。先给结论，再解释最重要机会、主要风险和为什么其他标的不行动。\n"
                    + json.dumps({"market_risk": dict(market_risk or {}), "recommendations": compact}, ensure_ascii=False, default=str)
                ),
            },
        ]
        route = {**config, "max_tokens": max(int(config.get("max_tokens") or 300), 1600)}
        ok, response = (llm_runner or call_openai_compatible_chat)(messages, route)
        if ok:
            text = str(response).strip()
            llm_meta = {"status": "READY", "model": route.get("model")}
        else:
            llm_meta = {"status": "FAILED", "error": str(response), "model": route.get("model")}
    text = text or _fallback(recommendations, market_risk)
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "status": "READY",
        "headline": "发现强机会" if any(row.get("actionable") for row in rows) else "当前无强信号",
        "summary_text": text,
        "market_regime": dict(market_risk or {}).get("regime"),
        "actionable_count": sum(1 for row in rows if row.get("actionable")),
        "llm": llm_meta,
    }


def save_research_brief(payload: Mapping, path: str = qpaths.DECISION_BRIEF_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload or {}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(target)
