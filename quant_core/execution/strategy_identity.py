from __future__ import annotations

from typing import Mapping


CORE_ETF_ALLOCATION = "CORE_ETF_ALLOCATION"
SATELLITE_TREND_RADAR = "SATELLITE_TREND_RADAR"
MEAN_REVERSION_ENTRY = "MEAN_REVERSION_ENTRY"
RISK_DISCIPLINE_GATE = "RISK_DISCIPLINE_GATE"
WEEKEND_CORRELATION_RESEARCH = "WEEKEND_CORRELATION_RESEARCH"
LLM_NEWS_EXPLANATION = "LLM_NEWS_EXPLANATION"
UNKNOWN_EVIDENCE = "UNKNOWN_EVIDENCE"


_DISPLAY = {
    CORE_ETF_ALLOCATION: "核心ETF配置",
    SATELLITE_TREND_RADAR: "卫星趋势雷达",
    MEAN_REVERSION_ENTRY: "均值回归入场辅助",
    RISK_DISCIPLINE_GATE: "风险纪律门控",
    WEEKEND_CORRELATION_RESEARCH: "周末相关性研究",
    LLM_NEWS_EXPLANATION: "LLM新闻/解释层",
    UNKNOWN_EVIDENCE: "未分类证据",
}

_ROLE = {
    CORE_ETF_ALLOCATION: "长期主仓配置与定投节奏",
    SATELLITE_TREND_RADAR: "寻找少数中长期超额机会",
    MEAN_REVERSION_ENTRY: "只辅助买入区间，不单独产生交易",
    RISK_DISCIPLINE_GATE: "最终否决与仓位纪律",
    WEEKEND_CORRELATION_RESEARCH: "风险和机会线索，不直接下交易建议",
    LLM_NEWS_EXPLANATION: "解释和摘要，不直接下交易建议",
    UNKNOWN_EVIDENCE: "仅供参考",
}


def _text(value) -> str:
    return str(value or "").strip()


def _upper(value) -> str:
    return _text(value).upper()


def classify_signal(row: Mapping | None) -> str:
    row = dict(row or {})
    source = _upper(row.get("strategy_source") or row.get("source") or row.get("kind"))
    list_type = _upper(row.get("list_type"))
    category = _upper(row.get("category") or row.get("type"))
    action = _upper(row.get("plan_action") or row.get("action"))

    if source in {"CORE_ETF", "CORE_ETF_ALLOCATION"} or list_type == "CORE":
        return CORE_ETF_ALLOCATION
    if source in {"SATELLITE", "SATELLITE_RADAR"} or list_type in {"CANDIDATE_POOL", "WATCHLIST"}:
        return SATELLITE_TREND_RADAR
    if source in {"MEAN_REVERSION", "ENTRY_ZONE"} or action in {"DIP_BUY", "WAIT_FOR_PULLBACK"}:
        return MEAN_REVERSION_ENTRY
    if "RISK" in category or "DISCIPLINE" in category or source in {"RISK_GATE", "DISCIPLINE"}:
        return RISK_DISCIPLINE_GATE
    if source in {"CORRELATION_RESEARCH", "WEEKEND_CORRELATION"} or "CORRELATION" in category:
        return WEEKEND_CORRELATION_RESEARCH
    if source in {"NEWS_INTELLIGENCE", "LLM", "FINANCIALS_INTELLIGENCE"} or "NEWS" in category:
        return LLM_NEWS_EXPLANATION
    return UNKNOWN_EVIDENCE


def build_signal_identity(row: Mapping | None) -> dict:
    strategy_type = classify_signal(row)
    can_create_trade_plan = strategy_type in {CORE_ETF_ALLOCATION, SATELLITE_TREND_RADAR, RISK_DISCIPLINE_GATE}
    if strategy_type == RISK_DISCIPLINE_GATE:
        can_create_trade_plan = False
    return {
        "strategy_type": strategy_type,
        "display_name": _DISPLAY.get(strategy_type, _DISPLAY[UNKNOWN_EVIDENCE]),
        "role": _ROLE.get(strategy_type, _ROLE[UNKNOWN_EVIDENCE]),
        "can_create_trade_plan": can_create_trade_plan,
    }


def attach_signal_identity(row: Mapping | None) -> dict:
    payload = dict(row or {})
    payload["signal_identity"] = build_signal_identity(payload)
    return payload

