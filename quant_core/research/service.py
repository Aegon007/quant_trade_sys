from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths
from quant_core.data.data_health import build_data_health_snapshot, save_data_health_snapshot
from quant_core.data.prices import get_history
from quant_core.fundamentals.provider import load_financial_profile
from quant_core.llm.research_brief import build_research_brief, save_research_brief
from quant_core.notifications import notification_config
from quant_core.notifications.change_feed import build_change_feed, save_change_feed
from quant_core.opportunities.event_analysis import analyze_event_context, fetch_recent_news_context
from quant_core.research.universe import build_research_universe, load_universe_config
from quant_core.research.valuation_pipeline import run_valuation_research
from quant_core.research.calibration import record_recommendations
from quant_core.research.manifest import ResearchManifest
from quant_core.risk.market_regime import build_market_risk_snapshot, save_market_risk_snapshot
from quant_core.valuation.router import route_valuation_model


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

DEFAULT_VALUATION_POLICY = {
    "schema_version": 1,
    "history_period": "2y",
    "simulation_count": 1200,
    "minimum_margin_of_safety": 0.15,
    "strong_margin_of_safety": 0.25,
    "minimum_valuation_confidence": 0.45,
    "maximum_damage_score": 60,
    "maximum_distress_probability": 0.35,
    "maximum_valuation_dispersion": 0.8,
    "recommendation_horizons_months": [3, 6, 12, 24],
    "require_llm_route_for_action": True,
    "sec_user_agent": "personal-valuation-research contact@example.com",
}


def _read_json(path: str) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: str, payload: Mapping) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload or {}), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return str(target)


def load_valuation_policy(path: str = qpaths.VALUATION_POLICY_FILE) -> dict:
    example = _read_json(qpaths.VALUATION_POLICY_EXAMPLE_FILE) if Path(path) == Path(qpaths.VALUATION_POLICY_FILE) else {}
    return {**DEFAULT_VALUATION_POLICY, **example, **_read_json(path)}


def save_valuation_policy(policy: Mapping, path: str = qpaths.VALUATION_POLICY_FILE) -> str:
    return _write_json(path, policy)


def _report_markdown(recommendations: Mapping, market_risk: Mapping, brief: Mapping) -> str:
    rows = list(dict(recommendations or {}).get("recommendations", []) or [])
    lines = [
        "# 市场估值与超跌机会报告",
        "",
        f"生成时间：{recommendations.get('generated_at', '-')}",
        f"市场风险：{market_risk.get('regime', 'UNKNOWN')}（{market_risk.get('risk_score', '-')}）",
        "",
        "## 今日结论",
        "",
        str(brief.get("summary_text") or "暂无摘要"),
        "",
        "## 候选排名",
        "",
        "| 标的 | 结论 | 机会分 | 当前价 | 合理价值中位数 | 安全边际 | 基本面损伤 | 最新申报 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows[:30]:
        fair = dict(row.get("fair_value", {}) or {})
        lines.append(
            f"| {row.get('symbol')} | {RECOMMENDATION_LABELS.get(str(row.get('recommendation')), row.get('recommendation'))} | {row.get('opportunity_score')} | "
            f"{row.get('current_price')} | {fair.get('p50')} | {float(row.get('margin_of_safety') or 0):.1%} | "
            f"{row.get('damage_score')} | {row.get('latest_filing_form') or '-'} {row.get('latest_filing_date') or ''} |"
        )
    return "\n".join(lines) + "\n"


def _run_full_valuation_research(
    *,
    now: Optional[datetime] = None,
    force: bool = False,
    progress=None,
    notify: bool = False,
) -> dict:
    now = now or datetime.now()
    universe_config = load_universe_config()
    policy = {**load_valuation_policy(), "max_deep_analysis": universe_config.get("max_deep_analysis", 30), "minimum_dislocation_score": universe_config.get("minimum_dislocation_score", 35)}
    universe = build_research_universe(universe_config)
    by_symbol = {str(row.get("symbol") or "").upper(): row for row in universe}
    if progress:
        progress("market_regime", 2, "更新市场风险环境")
    market_histories = {symbol: get_history(symbol, period=str(policy.get("history_period") or "2y")) for symbol in ("SPY", "QQQ", "^VIX")}
    market_risk = build_market_risk_snapshot(market_histories, now=now)
    save_market_risk_snapshot(market_risk)
    config = notification_config.apply_environment_overrides(notification_config.load_notification_config())
    llm_config = dict(config.get("llm", {}) or {})
    event_cache = {}

    def financial_loader(symbol):
        row = by_symbol.get(symbol, {})
        return load_financial_profile(
            symbol,
            asset_type=str(row.get("asset_type") or "equity"),
            metadata=row,
            force=force,
            now=now,
            user_agent=str(policy.get("sec_user_agent") or ""),
        )

    def event_loader(symbol):
        if symbol not in event_cache:
            event_cache[symbol] = analyze_event_context(
                symbol,
                fetch_recent_news_context(symbol),
                llm_config=llm_config,
            )
        return event_cache[symbol]

    def route_loader(*, symbol, asset_type, financials, event_context, **_kwargs):
        return route_valuation_model(
            symbol=symbol,
            asset_type=asset_type,
            financials=financials,
            filing_evidence=financials.get("evidence", []),
            event_context=event_context,
            llm_config=llm_config,
        )

    previous_recommendations = _read_json(qpaths.RECOMMENDATION_SNAPSHOT_FILE)
    snapshot = run_valuation_research(
        universe=universe,
        history_loader=get_history,
        financial_loader=financial_loader,
        route_loader=route_loader,
        event_loader=event_loader,
        market_risk=market_risk,
        snapshot_path=qpaths.OPPORTUNITY_SNAPSHOT_FILE,
        valuation_path=qpaths.VALUATION_SNAPSHOT_FILE,
        recommendation_path=qpaths.RECOMMENDATION_SNAPSHOT_FILE,
        now=now,
        progress=progress,
        policy=policy,
    )
    recommendations = _read_json(qpaths.RECOMMENDATION_SNAPSHOT_FILE)
    valuations = _read_json(qpaths.VALUATION_SNAPSHOT_FILE)
    change_feed = build_change_feed(previous_recommendations, recommendations, now=now)
    save_change_feed(change_feed)
    data_health = build_data_health_snapshot(
        opportunities=snapshot,
        valuations=valuations,
        market_risk=market_risk,
        now=now,
        require_llm_route=bool(policy.get("require_llm_route_for_action", False)),
    )
    save_data_health_snapshot(data_health)
    brief = build_research_brief(recommendations, market_risk, llm_config=llm_config, now=now)
    save_research_brief(brief)
    record_recommendations(recommendations)
    report = _report_markdown(recommendations, market_risk, brief)
    _write_json(qpaths.VALUATION_REPORT_LATEST_JSON, {"recommendations": recommendations, "market_risk": market_risk, "brief": brief})
    Path(qpaths.VALUATION_REPORT_LATEST_MD).parent.mkdir(parents=True, exist_ok=True)
    Path(qpaths.VALUATION_REPORT_LATEST_MD).write_text(report, encoding="utf-8")
    delivery = []
    if notify:
        from quant_core.notifications.delivery_router import deliver_message

        delivery = deliver_message("nightly_valuation", subject="市场估值与超跌机会日报", body=str(brief.get("summary_text") or report), config=config)
    return {
        "ran": True,
        "generated_at": now.isoformat(),
        "status": snapshot.get("status"),
        "summary": snapshot.get("summary", {}),
        "brief": brief,
        "market_risk": market_risk,
        "data_health": data_health,
        "change_feed": change_feed,
        "delivery": delivery,
    }


def run_full_valuation_research(
    *,
    now: Optional[datetime] = None,
    force: bool = False,
    progress=None,
    notify: bool = False,
) -> dict:
    manifest = ResearchManifest(run_id=(now or datetime.now()).strftime("%Y%m%dT%H%M%S"))
    manifest.start()
    last_progress = {"stage": "", "pct": -10}

    def tracked(stage: str, progress_pct: int, detail: str, **metadata):
        if stage != last_progress["stage"] or int(progress_pct) - int(last_progress["pct"]) >= 2 or int(progress_pct) >= 100:
            manifest.step(stage, progress_pct, detail, **metadata)
            last_progress.update({"stage": stage, "pct": int(progress_pct)})
        if progress:
            progress(stage, progress_pct, detail, **metadata)

    try:
        result = _run_full_valuation_research(now=now, force=force, progress=tracked, notify=notify)
    except Exception as exc:
        manifest.fail(exc)
        raise
    manifest.complete(summary=result.get("summary", {}))
    return result
