from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths
from quant_core.execution import strategy_identity as sid


DEFAULT_FINAL_DECISION_FILE = qpaths.FINAL_DECISION_SNAPSHOT_FILE
_BUY_ACTIONS = {"ADD", "ACCUMULATE", "DCA_ACCUMULATE", "PROBE"}
_SELL_ACTIONS = {"TRIM", "EXIT", "RISK_EXIT", "SELL"}


def _as_dict(value) -> dict:
    return dict(value or {}) if isinstance(value, Mapping) else {}


def _as_list(value) -> list:
    return list(value or []) if isinstance(value, list) else []


def _action(row: Mapping) -> str:
    row = _as_dict(row)
    decision = _as_dict(row.get("decision") or row.get("model_decision"))
    return str(
        row.get("plan_action")
        or decision.get("action")
        or row.get("final_action")
        or row.get("action")
        or "HOLD"
    ).strip().upper()


def _count_actions(rows) -> int:
    return len([row for row in _as_list(rows) if _action(row) not in {"", "HOLD", "WATCH", "PAUSE_BUY"}])


def _data_health_blocks(data_health_snapshot: Mapping) -> bool:
    status = str(_as_dict(data_health_snapshot).get("status") or _as_dict(_as_dict(data_health_snapshot).get("summary")).get("status") or "").upper()
    return status in {"DEGRADED", "FAILED", "MISSING"}


def _core_section(core_snapshot: Mapping) -> dict:
    rows = _as_list(_as_dict(core_snapshot).get("symbols"))
    actions = [_action(row) for row in rows]
    return {
        "strategy_type": sid.CORE_ETF_ALLOCATION,
        "display_name": "核心ETF配置",
        "role": "长期主仓，决定定投、加仓、暂停或回撤等待。",
        "action_count": len([action for action in actions if action in _BUY_ACTIONS | _SELL_ACTIONS]),
        "dca_count": actions.count("DCA_ACCUMULATE"),
        "pause_count": actions.count("PAUSE_BUY"),
        "symbols": [str(_as_dict(row).get("symbol") or "").upper() for row in rows[:8] if _as_dict(row).get("symbol")],
    }


def _satellite_section(satellite_snapshot: Mapping) -> dict:
    rows = _as_list(_as_dict(satellite_snapshot).get("top_recommendations") or _as_dict(satellite_snapshot).get("symbols"))
    actions = [_action(row) for row in rows]
    return {
        "strategy_type": sid.SATELLITE_TREND_RADAR,
        "display_name": "卫星趋势雷达",
        "role": "最多前三个股机会；没有强信号就不交易。",
        "action_count": len([action for action in actions if action in _BUY_ACTIONS | _SELL_ACTIONS]),
        "probe_count": actions.count("PROBE"),
        "top_symbols": [str(_as_dict(row).get("symbol") or "").upper() for row in rows[:3] if _as_dict(row).get("symbol")],
    }


def _risk_section(discipline_snapshot: Mapping, data_health_snapshot: Mapping) -> dict:
    discipline = _as_dict(discipline_snapshot)
    return {
        "strategy_type": sid.RISK_DISCIPLINE_GATE,
        "display_name": "风险纪律门控",
        "role": "最终裁判，决定重仓、轻仓或停手。",
        "regime": str(discipline.get("regime") or "UNKNOWN").upper(),
        "risk_regime": str(discipline.get("risk_regime") or "UNKNOWN").upper(),
        "target_exposure_pct": discipline.get("target_exposure_pct"),
        "data_health_blocks": _data_health_blocks(data_health_snapshot),
    }


def _correlation_section(correlation_snapshot: Mapping) -> dict:
    summary = _as_dict(_as_dict(correlation_snapshot).get("summary"))
    return {
        "strategy_type": sid.WEEKEND_CORRELATION_RESEARCH,
        "display_name": "周末相关性研究",
        "role": "风险和机会线索",
        "status": _as_dict(correlation_snapshot).get("status") or summary.get("status") or "MISSING",
        "high_correlation_pair_count": summary.get("high_correlation_pair_count", 0),
        "portfolio_redundancy_count": summary.get("portfolio_redundancy_count", 0),
        "independent_strength_count": summary.get("independent_strength_count", 0),
    }


def build_final_decision_snapshot(
    *,
    account: Optional[Mapping] = None,
    trade_plan: Optional[Mapping] = None,
    core_snapshot: Optional[Mapping] = None,
    satellite_snapshot: Optional[Mapping] = None,
    discipline_snapshot: Optional[Mapping] = None,
    correlation_snapshot: Optional[Mapping] = None,
    data_health_snapshot: Optional[Mapping] = None,
    news_intelligence: Optional[Mapping] = None,
    now: Optional[datetime] = None,
) -> dict:
    now = now or datetime.now()
    account = _as_dict(account)
    trade_plan = _as_dict(trade_plan)
    core_snapshot = _as_dict(core_snapshot)
    satellite_snapshot = _as_dict(satellite_snapshot)
    discipline_snapshot = _as_dict(discipline_snapshot)
    correlation_snapshot = _as_dict(correlation_snapshot)
    data_health_snapshot = _as_dict(data_health_snapshot)
    news_intelligence = _as_dict(news_intelligence)

    plan_items = _as_list(trade_plan.get("items"))
    executable_count = len(plan_items)
    blocked_by_data = _data_health_blocks(data_health_snapshot)
    discipline_regime = str(discipline_snapshot.get("regime") or "").upper()
    top_reasons = []

    if blocked_by_data:
        final_decision = "WAIT"
        top_reasons.append("数据健康度下降，建议先刷新/修复数据，再参考仓位建议。")
    elif discipline_regime == "STOP":
        final_decision = "STOP"
        top_reasons.append("纪律层处于停手状态，禁止新增仓位。")
    elif executable_count:
        final_decision = "ACTION"
        top_reasons.append(f"执行计划器确认 {executable_count} 条明日计划。")
    else:
        final_decision = "NO_ACTION"
        top_reasons.append(str(trade_plan.get("summary_reason") or "没有强信号，保持仓位不动。"))

    correlation_summary = _as_dict(correlation_snapshot.get("summary"))
    if int(correlation_summary.get("portfolio_redundancy_count") or 0) > 0:
        top_reasons.append("周末相关性研究显示组合存在重复押注，新增仓位需要更谨慎。")
    if str(news_intelligence.get("market_risk_level") or "").upper() == "HIGH":
        top_reasons.append("新闻情报显示市场风险偏高，LLM摘要只作为解释层。")

    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "system_identity": "中长期个人交易辅助系统",
        "system_scope": {
            "primary": "核心ETF配置 + 卫星仓趋势/基本面雷达 + 风险纪律层",
            "excluded": ["高频交易", "把统计套利作为主交易引擎"],
            "weekend_research_role": "相关性研究只输出风险和机会线索",
        },
        "final_decision": final_decision,
        "top_reasons": top_reasons[:5],
        "capital": {
            "cash_available": account.get("cash_available"),
            "total_capital": account.get("total_capital"),
            "exposure_pct": account.get("exposure_pct"),
        },
        "summary": {
            "executable_action_count": executable_count,
            "blocked_action_count": len(_as_list(trade_plan.get("blocked_items"))),
            "core_action_count": _count_actions(_as_list(core_snapshot.get("symbols"))),
            "satellite_action_count": _count_actions(_as_list(satellite_snapshot.get("top_recommendations") or satellite_snapshot.get("symbols"))),
            "data_health_blocks": blocked_by_data,
            "discipline_regime": discipline_regime or "UNKNOWN",
        },
        "strategy_sections": {
            "core_etf": _core_section(core_snapshot),
            "satellite": _satellite_section(satellite_snapshot),
            "risk_discipline": _risk_section(discipline_snapshot, data_health_snapshot),
            "weekend_correlation": _correlation_section(correlation_snapshot),
            "llm_news": {
                "strategy_type": sid.LLM_NEWS_EXPLANATION,
                "display_name": "LLM新闻/解释层",
                "role": "用于总结解释，不直接产生交易指令。",
                "status": news_intelligence.get("status") or "UNKNOWN",
                "market_risk_level": news_intelligence.get("market_risk_level"),
            },
        },
        "trade_plan_items": plan_items,
    }


def save_final_decision_snapshot(snapshot: Mapping, *, path: str = DEFAULT_FINAL_DECISION_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(snapshot or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def load_final_decision_snapshot(*, path: str = DEFAULT_FINAL_DECISION_FILE) -> dict:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}

