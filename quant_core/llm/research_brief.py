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
    trends = list(dict(recommendations or {}).get("trend_signals", []) or [])
    trend_leaders = [row for row in trends if str(row.get("recommendation")) in {"TREND_CONFIRMED", "WAIT_FOR_PULLBACK"}]
    etfs = list(dict(recommendations or {}).get("etf_allocations", []) or [])
    raw_regime = str(dict(market_risk or {}).get("regime") or "未知")
    regime = REGIME_LABELS.get(raw_regime, raw_regime)
    if not actionable:
        trend_text = "" if not trend_leaders else " 趋势雷达关注" + "、".join(str(row.get("symbol")) for row in trend_leaders[:4]) + "，其中过热标的只等待回撤。"
        etf_text = "" if not etfs else " 核心ETF按" + "、".join(f"{row.get('symbol')}：{row.get('action')}" for row in etfs[:4]) + "执行配置节奏。"
        return f"当前市场风险状态为{regime}。价值反转筛选没有发现通过全部校验的强机会，不为制造交易而降低门槛。{trend_text}{etf_text}"
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
                "latest_filing_form", "latest_filing_date", "filing_summary", "fundamental_signals", "filing_risks",
            )
        }
        for row in rows[:15]
    ]
    trend_compact = list(dict(recommendations or {}).get("trend_signals", []) or [])[:12]
    etf_compact = list(dict(recommendations or {}).get("etf_allocations", []) or [])[:8]
    trend_actionable_count = sum(1 for row in trend_compact if row.get("actionable"))
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
                    "请形成今日三引擎研究摘要：分别说明价值反转、趋势加速、核心ETF配置，再说明主要风险和不行动原因。不要把趋势强等同于低估，也不要把ETF配置节奏写成精确价格预测。\n"
                    + json.dumps({"market_risk": dict(market_risk or {}), "value_reversal": compact, "trend_signals": trend_compact, "etf_allocation": etf_compact}, ensure_ascii=False, default=str)
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
        "headline": "发现强机会" if any(row.get("actionable") for row in rows) or trend_actionable_count else "当前无强信号",
        "summary_text": text,
        "market_regime": dict(market_risk or {}).get("regime"),
        "actionable_count": sum(1 for row in rows if row.get("actionable")) + trend_actionable_count,
        "llm": llm_meta,
    }


def save_research_brief(payload: Mapping, path: str = qpaths.DECISION_BRIEF_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload or {}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(target)
