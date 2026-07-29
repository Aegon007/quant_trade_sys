import json
import os
from datetime import datetime
from typing import Iterable, Mapping, Optional

from quant_core.portfolio.metrics import summarize_holdings

DEFAULT_NIGHTLY_JOURNAL_FILE = os.path.join("reports", "nightly_snapshot_journal.jsonl")


def build_account_snapshot(data: Mapping) -> dict:
    data = data or {}
    account = dict(data.get("account", {}) or {})
    summary = summarize_holdings(data.get("holdings", []))
    legacy_total_capital = float(account.get("total_capital") or 0.0)
    cash_available = account.get("cash_available")
    cash_available = None if cash_available is None else float(cash_available)
    if cash_available is not None:
        total_capital = cash_available + summary.total_value
    elif legacy_total_capital > 0:
        total_capital = legacy_total_capital
    else:
        total_capital = summary.total_value
    min_cash_buffer_pct = float(account.get("min_cash_buffer_pct") or 0.0)
    cash_buffer_dollars = total_capital * min_cash_buffer_pct if total_capital > 0 else 0.0
    deployable_cash = 0.0
    if cash_available is not None:
        deployable_cash = max(cash_available - cash_buffer_dollars, 0.0)
    exposure_pct = (summary.total_value / total_capital * 100.0) if total_capital > 0 else 0.0

    return {
        "total_capital": total_capital if total_capital > 0 else None,
        "cash_available": cash_available,
        "cash_buffer_dollars": cash_buffer_dollars,
        "deployable_cash": deployable_cash,
        "holdings_market_value": summary.total_value,
        "holdings_value": summary.total_value,
        "holdings_cost_basis": summary.total_cost,
        "unrealized_pl": summary.total_pl,
        "unrealized_pl_pct": summary.total_pl_pct,
        "exposure_pct": exposure_pct,
        "max_single_position_pct": float(account.get("max_single_position_pct") or 0.0) * 100.0,
        "max_total_exposure_pct": float(account.get("max_total_exposure_pct") or 0.0) * 100.0,
    }


def build_system_snapshot(
    *,
    data: Mapping,
    holding_records: Optional[Iterable[Mapping]] = None,
    watchlist_records: Optional[Iterable[Mapping]] = None,
    risk_gate=None,
    alerts: Optional[Iterable[Mapping]] = None,
    data_sources: Optional[Mapping] = None,
    performance: Optional[Mapping] = None,
    allocation_regime: Optional[Mapping] = None,
    daily_recap: Optional[Mapping] = None,
    signal_attribution: Optional[Mapping] = None,
    trade_plan: Optional[Mapping] = None,
    execution_review: Optional[Mapping] = None,
    core_etf_snapshot: Optional[Mapping] = None,
    satellite_candidate_snapshot: Optional[Mapping] = None,
    discipline_snapshot: Optional[Mapping] = None,
    monthly_discipline_review: Optional[Mapping] = None,
    strategy_validation_snapshot: Optional[Mapping] = None,
    data_health_snapshot: Optional[Mapping] = None,
    plan_quality_snapshot: Optional[Mapping] = None,
    market_monitor_snapshot: Optional[Mapping] = None,
    strategy_governance_snapshot: Optional[Mapping] = None,
    multi_horizon_snapshot: Optional[Mapping] = None,
    news_intelligence: Optional[Mapping] = None,
    financials_intelligence: Optional[Mapping] = None,
    decision_brief: Optional[Mapping] = None,
    intraday_event_summary: Optional[Mapping] = None,
    change_feed: Optional[Mapping] = None,
    nightly_manifest: Optional[Mapping] = None,
    generated_at: Optional[datetime] = None,
) -> dict:
    generated_at = generated_at or datetime.now()
    risk_payload = {}
    if isinstance(risk_gate, Mapping):
        risk_payload = dict(risk_gate)
    elif risk_gate is not None:
        risk_payload = {
            "regime": getattr(risk_gate, "regime", None),
            "risk_score": getattr(risk_gate, "risk_score", None),
            "block_new_buys": getattr(risk_gate, "block_new_buys", None),
            "max_position_weight": getattr(risk_gate, "max_position_weight", None),
            "reasons": list(getattr(risk_gate, "reasons", []) or []),
        }

    return {
        "generated_at": generated_at.isoformat(),
        "account": build_account_snapshot(data),
        "holdings": {
            "count": len(data.get("holdings", [])),
            "raw": list(data.get("holdings", [])),
            "records": list(holding_records or []),
        },
        "watchlist": {
            "count": len(data.get("watchlist", [])),
            "raw": list(data.get("watchlist", [])),
            "records": list(watchlist_records or []),
        },
        "risk": risk_payload,
        "alerts": list(alerts or []),
        "data_sources": dict(data_sources or {}),
        "performance": dict(performance or {}),
        "allocation_regime": dict(allocation_regime or {}),
        "daily_recap": dict(daily_recap or {}),
        "signal_attribution": dict(signal_attribution or {}),
        "trade_plan": dict(trade_plan or {}),
        "decision_signature": str(dict(trade_plan or {}).get("decision_signature") or "").strip() or None,
        "execution_review": dict(execution_review or {}),
        "core_etf_snapshot": dict(core_etf_snapshot or {}),
        "satellite_candidate_snapshot": dict(satellite_candidate_snapshot or {}),
        "discipline_snapshot": dict(discipline_snapshot or {}),
        "monthly_discipline_review": dict(monthly_discipline_review or {}),
        "strategy_validation_snapshot": dict(strategy_validation_snapshot or {}),
        "data_health_snapshot": dict(data_health_snapshot or {}),
        "plan_quality_snapshot": dict(plan_quality_snapshot or {}),
        "market_monitor_snapshot": dict(market_monitor_snapshot or {}),
        "strategy_governance_snapshot": dict(strategy_governance_snapshot or {}),
        "multi_horizon_snapshot": dict(multi_horizon_snapshot or {}),
        "news_intelligence": dict(news_intelligence or {}),
        "financials_intelligence": dict(financials_intelligence or {}),
        "decision_brief": dict(decision_brief or {}),
        "intraday_event_summary": dict(intraday_event_summary or {}),
        "change_feed": dict(change_feed or {}),
        "nightly_manifest": dict(nightly_manifest or {}),
    }


def append_snapshot_journal(snapshot, journal_path=DEFAULT_NIGHTLY_JOURNAL_FILE):
    journal_dir = os.path.dirname(journal_path)
    if journal_dir:
        os.makedirs(journal_dir, exist_ok=True)
    with open(journal_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    return journal_path


def load_snapshot_journal(*, journal_path=DEFAULT_NIGHTLY_JOURNAL_FILE, limit=None):
    if not os.path.exists(journal_path):
        return []
    rows = []
    with open(journal_path, "r", encoding="utf-8") as f:
        for line in f:
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
