"""Read-only snapshot loader used by the FastAPI server.

This module must stay light: it reads existing state/config/report files and
normalizes them into stable DTOs. It must not fetch market data, train models,
or run backtests.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Optional

from quant_core import paths as qpaths
from quant_core.api.schemas import build_api_response, now_iso
from quant_core.execution import plan_quality as pq
from quant_core.execution import post_close_review as pcr
from quant_core.jobs import job_registry
from quant_core.ledger import transactions as tx
from quant_core.notifications import notification_config as ncfg
from quant_core.models.multi_horizon import governance as mh_governance
from quant_core.portfolio import risk as portfolio_risk
from quant_core.snapshots import system_snapshot as ss


DEFAULT_SNAPSHOT_MAX_AGE_SECONDS = 36 * 3600


SNAPSHOT_PATHS = {
    "core-etfs": qpaths.CORE_ETF_SNAPSHOT_FILE,
    "satellite-radar": qpaths.SATELLITE_CANDIDATE_POOL_FILE,
    "risk": qpaths.DISCIPLINE_SNAPSHOT_FILE,
    "change-feed": qpaths.CHANGE_FEED_FILE,
    "market-monitor": qpaths.MARKET_MONITOR_SNAPSHOT_FILE,
    "data-health": qpaths.DATA_HEALTH_SNAPSHOT_FILE,
    "plan-quality": qpaths.PLAN_QUALITY_SNAPSHOT_FILE,
    "strategy-governance": qpaths.STRATEGY_REGISTRY_STATE_FILE,
    "strategy-validation": qpaths.STRATEGY_VALIDATION_SNAPSHOT_FILE,
    "foundation-model": qpaths.FOUNDATION_MODEL_SNAPSHOT_FILE,
    "market-sentiment": qpaths.MARKET_SENTIMENT_SNAPSHOT_FILE,
    "systemic-risk": qpaths.SYSTEMIC_RISK_SNAPSHOT_FILE,
    "multi-horizon": qpaths.MULTI_HORIZON_SNAPSHOT_FILE,
    "model-governance": qpaths.MULTI_HORIZON_GOVERNANCE_FILE,
    "news-intelligence": qpaths.NEWS_INTELLIGENCE_FILE,
    "financials-intelligence": qpaths.FINANCIALS_INTELLIGENCE_FILE,
    "decision-brief": qpaths.DECISION_BRIEF_FILE,
    "reports-latest": str(qpaths.PROJECT_ROOT / "reports" / "nightly_report_latest.json"),
}


def _load_gated_multi_horizon_snapshot() -> dict:
    snapshot, _ = safe_read_json(qpaths.MULTI_HORIZON_SNAPSHOT_FILE)
    governance, _ = safe_read_json(qpaths.MULTI_HORIZON_GOVERNANCE_FILE)
    return mh_governance.apply_production_gate(
        snapshot if isinstance(snapshot, dict) else {},
        governance if isinstance(governance, dict) else {},
    )


def _multi_horizon_index(snapshot: Mapping | None) -> dict[str, dict]:
    return {
        str(row.get("symbol") or "").strip().upper(): dict(row or {})
        for row in list(dict(snapshot or {}).get("symbols", []) or [])
        if str(dict(row or {}).get("symbol") or "").strip()
    }


def enrich_rows_with_multi_horizon(rows, snapshot: Mapping | None) -> list[dict]:
    indexed = _multi_horizon_index(snapshot)
    generated_at = dict(snapshot or {}).get("generated_at")
    result = []
    for raw_row in list(rows or []):
        row = dict(raw_row or {})
        if row.get("average_cost") is None and row.get("cost") is not None:
            row["average_cost"] = row.get("cost")
        symbol = str(row.get("symbol") or "").strip().upper()
        model_row = indexed.get(symbol)
        if not model_row:
            result.append(row)
            continue
        long_horizon = dict(model_row.get("long_horizon", {}) or {})
        timing = dict(model_row.get("timing", {}) or {})
        decision = dict(model_row.get("decision", {}) or {})
        row.update(
            {
                "multi_horizon": model_row,
                "long_horizon_state": long_horizon.get("state"),
                "long_horizon_rank": long_horizon.get("blended_rank"),
                "timing_state": timing.get("state"),
                "model_decision": decision,
                "final_action": decision.get("action"),
                "target_weight_range_pct": decision.get("target_weight_range_pct"),
                "model_generated_at": generated_at,
            }
        )
        result.append(row)
    return result


def _live_position_context(data: Mapping | None) -> tuple[dict, dict[str, dict]]:
    data = dict(data or {})
    account = ss.build_account_snapshot(data) if data else {}
    total_capital = float(account.get("total_capital") or 0.0)
    positions = {}
    for raw_row in list(data.get("holdings", []) or []):
        row = dict(raw_row or {})
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        shares = float(row.get("shares") or 0.0)
        average_cost = row.get("average_cost")
        if average_cost is None:
            average_cost = row.get("cost")
        average_cost = float(average_cost) if average_cost is not None else None
        price = row.get("current_price")
        price = float(price) if price is not None else None
        current_value = shares * price if price is not None else None
        positions[symbol] = {
            **row,
            "symbol": symbol,
            "average_cost": average_cost,
            "is_held": True,
            "current_shares": shares,
            "current_value": current_value,
            "current_weight_pct": (
                current_value / total_capital * 100.0
                if current_value is not None and total_capital > 0
                else 0.0
            ),
        }
    return account, positions


def overlay_live_positions(rows, *, positions: Mapping[str, Mapping]) -> list[dict]:
    result = []
    for raw_row in list(rows or []):
        row = dict(raw_row or {})
        symbol = str(row.get("symbol") or "").strip().upper()
        position = dict(positions.get(symbol, {}) or {})
        average_cost = position.get("average_cost") if position else row.get("average_cost")
        if average_cost is None:
            average_cost = row.get("cost")
        row.update(
            {
                "is_held": bool(position),
                "current_shares": float(position.get("current_shares") or 0.0),
                "current_value": position.get("current_value"),
                "current_weight_pct": float(position.get("current_weight_pct") or 0.0),
                "average_cost": average_cost,
            }
        )
        if position.get("current_price") is not None:
            row["current_price"] = position["current_price"]
        result.append(row)
    return result


def add_average_cost_alias(rows: Iterable[Mapping]) -> list[dict]:
    normalized = []
    for raw_row in list(rows or []):
        row = dict(raw_row or {})
        if row.get("average_cost") is None and row.get("cost") is not None:
            row["average_cost"] = row.get("cost")
        normalized.append(row)
    return normalized


def _parse_iso_datetime(value) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def read_json_file(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def safe_read_json(path: str) -> tuple[object, list[str]]:
    try:
        return read_json_file(path), []
    except FileNotFoundError:
        return {}, [f"Missing file: {path}"]
    except Exception as exc:
        return {}, [f"Failed to read JSON {path}: {exc}"]


def _extract_generated_at(payload) -> Optional[str]:
    if not isinstance(payload, Mapping):
        return None
    for key in ("generated_at", "updated_at", "last_updated", "prices_last_updated"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def _age_seconds(generated_at: Optional[str], *, now: Optional[datetime] = None) -> Optional[float]:
    parsed = _parse_iso_datetime(generated_at)
    if parsed is None:
        return None
    if now is None:
        now = datetime.now(tz=parsed.tzinfo) if parsed.tzinfo else datetime.now()
    if parsed.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=parsed.tzinfo)
    elif parsed.tzinfo is None and now.tzinfo is not None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    return max((now - parsed).total_seconds(), 0.0)


def _extract_summary(payload) -> dict:
    if not isinstance(payload, Mapping):
        return {}
    summary = payload.get("summary")
    if isinstance(summary, Mapping):
        return dict(summary)
    return {}


def _extract_items(payload) -> list:
    if not isinstance(payload, Mapping):
        return []
    for key in ("items", "high_items", "symbols", "top_recommendations", "changes", "alerts", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def load_snapshot_response(
    name: str,
    path: str,
    *,
    max_age_seconds: Optional[int] = DEFAULT_SNAPSHOT_MAX_AGE_SECONDS,
    now: Optional[datetime] = None,
) -> dict:
    payload, errors = safe_read_json(path)
    source = str(path)
    if errors:
        return build_api_response(
            name=name,
            source=source,
            freshness_status="MISSING",
            is_stale=True,
            errors=errors,
            data_quality={"status": "MISSING", "missing": True},
            payload={},
            generated_at=now_iso(now),
        )

    generated_at = _extract_generated_at(payload)
    age = _age_seconds(generated_at, now=now)
    is_stale = bool(max_age_seconds is not None and age is not None and age > max_age_seconds)
    freshness_status = "STALE" if is_stale else ("UNKNOWN" if generated_at is None else "OK")
    warnings = []
    if generated_at is None:
        warnings.append("Snapshot does not include generated_at/updated_at.")
    return build_api_response(
        name=name,
        source=source,
        freshness_status=freshness_status,
        is_stale=is_stale,
        summary=_extract_summary(payload),
        items=_extract_items(payload),
        warnings=warnings,
        data_quality={
            "status": freshness_status,
            "age_seconds": age,
            "has_generated_at": generated_at is not None,
        },
        payload=payload,
        generated_at=generated_at or now_iso(now),
    )


def load_model_enriched_snapshot_response(
    name: str,
    path: str,
    *,
    row_keys: tuple[str, ...],
    max_age_seconds: Optional[int] = DEFAULT_SNAPSHOT_MAX_AGE_SECONDS,
    now: Optional[datetime] = None,
) -> dict:
    response = load_snapshot_response(
        name,
        path,
        max_age_seconds=max_age_seconds,
        now=now,
    )
    model_snapshot = _load_gated_multi_horizon_snapshot()
    portfolio_data = _load_portfolio_payload()
    account, positions = _live_position_context(portfolio_data)
    payload = dict(response.get("payload", {}) or {})
    for key in row_keys:
        if isinstance(payload.get(key), list):
            payload[key] = enrich_rows_with_multi_horizon(payload[key], model_snapshot)
    if name == "satellite-radar" and list(model_snapshot.get("satellite_top3", []) or []):
        payload["top_recommendations"] = list(model_snapshot["satellite_top3"])
        payload["candidate_pool"] = list(model_snapshot.get("satellite_ranked_pool", []) or [])
        payload["model_ranked"] = True
    if name == "core-etfs" and list(model_snapshot.get("core_etfs", []) or []):
        existing = {
            str(row.get("symbol") or "").strip().upper(): dict(row or {})
            for row in list(payload.get("symbols", []) or [])
        }
        payload["symbols"] = [
            {**existing.get(str(row.get("symbol") or "").strip().upper(), {}), **dict(row or {})}
            for row in list(model_snapshot.get("core_etfs", []) or [])
        ]
        payload["model_ranked"] = True
    for key in row_keys:
        if isinstance(payload.get(key), list):
            payload[key] = overlay_live_positions(payload[key], positions=positions)
    payload["portfolio_context"] = account
    if name == "core-etfs":
        core_symbols = {
            str(row.get("symbol") or "").strip().upper()
            for row in list(payload.get("symbols", []) or [])
        }
        payload["unrepresented_holdings"] = [
            dict(position)
            for symbol, position in positions.items()
            if symbol not in core_symbols
        ]
    if name == "satellite-radar":
        core_config, _ = safe_read_json(qpaths.CORE_ETF_UNIVERSE_FILE)
        core_symbols = {
            str(row.get("symbol") or "").strip().upper()
            for row in list(dict(core_config or {}).get("etfs", []) or [])
            if bool(dict(row or {}).get("enabled", True))
        }
        model_index = _multi_horizon_index(model_snapshot)
        payload["current_holdings"] = [
            {
                **dict(position),
                **dict(model_index.get(symbol, {}) or {}),
                **dict(position),
            }
            for symbol, position in positions.items()
            if symbol not in core_symbols
        ]
    response["payload"] = payload
    response["summary"] = _extract_summary(payload)
    response["items"] = _extract_items(payload)
    return response


def load_risk_response(*, now: Optional[datetime] = None) -> dict:
    data = _load_portfolio_payload()
    account, positions = _live_position_context(data)
    discipline, errors = safe_read_json(qpaths.DISCIPLINE_SNAPSHOT_FILE)
    market_sentiment, market_sentiment_errors = safe_read_json(qpaths.MARKET_SENTIMENT_SNAPSHOT_FILE)
    systemic_risk, systemic_risk_errors = safe_read_json(qpaths.SYSTEMIC_RISK_SNAPSHOT_FILE)
    financials_intelligence, financials_errors = safe_read_json(qpaths.FINANCIALS_INTELLIGENCE_FILE)
    discipline = discipline if isinstance(discipline, dict) else {}
    market_sentiment = market_sentiment if isinstance(market_sentiment, dict) else {}
    systemic_risk = systemic_risk if isinstance(systemic_risk, dict) else {}
    financials_intelligence = financials_intelligence if isinstance(financials_intelligence, dict) else {}
    holdings = list(positions.values())
    analyzed = portfolio_risk.analyze_portfolio_risk(holdings)
    max_single = float(account.get("max_single_position_pct") or 0.0)
    max_exposure = float(account.get("max_total_exposure_pct") or 0.0)
    exposure = float(account.get("exposure_pct") or 0.0)
    risk_items = []
    for position in sorted(
        holdings,
        key=lambda row: float(row.get("current_weight_pct") or 0.0),
        reverse=True,
    ):
        weight = float(position.get("current_weight_pct") or 0.0)
        if max_single > 0 and weight > max_single:
            risk_items.append(
                {
                    "level": "HIGH",
                    "category": "POSITION_CONCENTRATION",
                    "symbol": position.get("symbol"),
                    "message": f"{position.get('symbol')} is {weight:.1f}% of total capital, above the {max_single:.1f}% limit.",
                    "action": "TRIM_OR_HOLD",
                }
            )
    if max_exposure > 0 and exposure > max_exposure:
        risk_items.append(
            {
                "level": "HIGH",
                "category": "TOTAL_EXPOSURE",
                "message": f"Portfolio exposure is {exposure:.1f}%, above the {max_exposure:.1f}% limit.",
                "action": "REDUCE_EXPOSURE",
            }
        )
    risk_items.extend(
        {
            "level": "CAUTION",
            "category": "PORTFOLIO_RISK",
            "message": message,
            "action": "REVIEW",
        }
        for message in analyzed.recommendations
    )
    payload = {
        **discipline,
        "account": account,
        "holdings": holdings,
        "portfolio_risk": {
            "total_invested_value": analyzed.total_value,
            "sector_exposures": [
                {
                    "sector": row.sector,
                    "value": row.value,
                    "weight_pct": row.weight_pct,
                }
                for row in analyzed.sector_exposures
            ],
            "unpriced_symbols": analyzed.unpriced_symbols,
        },
        "risk_items": risk_items,
        "market_sentiment": market_sentiment,
        "systemic_risk": systemic_risk,
        "financials_intelligence": financials_intelligence,
    }
    return build_api_response(
        name="risk",
        source="composed:discipline+live_portfolio",
        freshness_status="OK" if not errors else "PARTIAL",
        is_stale=False,
        summary={
            "regime": discipline.get("regime"),
            "risk_regime": discipline.get("risk_regime"),
            "target_exposure_pct": discipline.get("target_exposure_pct"),
            "actual_exposure_pct": account.get("exposure_pct"),
            "cash_available": account.get("cash_available"),
            "total_capital": account.get("total_capital"),
            "concentration_alert_count": len([
                row for row in risk_items if row.get("category") == "POSITION_CONCENTRATION"
            ]),
        },
        items=risk_items,
        warnings=[*errors, *market_sentiment_errors, *systemic_risk_errors, *financials_errors],
        data_quality={"status": "OK" if not errors else "PARTIAL"},
        payload=payload,
        generated_at=now_iso(now),
    )


def _load_portfolio_payload() -> dict:
    payload, errors = safe_read_json(qpaths.PORTFOLIO_DATA_FILE)
    if errors or not isinstance(payload, dict):
        return {}
    return payload


def _top_satellite_symbols(snapshot: Mapping) -> list[str]:
    summary = dict(snapshot.get("summary", {}) or {})
    symbols = list(summary.get("top_symbols", []) or [])
    if symbols:
        return [str(symbol).upper() for symbol in symbols[:3]]
    rows = list(snapshot.get("top_recommendations", []) or snapshot.get("symbols", []) or [])
    return [str(dict(row or {}).get("symbol") or "").upper() for row in rows[:3] if dict(row or {}).get("symbol")]


def _parse_record_dt(record: Mapping):
    try:
        return pcr._parse_datetime(dict(record or {}).get("date"))
    except Exception:
        return None


def _recent_transactions(records, *, limit: int = 50) -> list[dict]:
    rows = [dict(row or {}) for row in tx.normalize_transactions(records)]
    rows.sort(key=lambda row: _parse_record_dt(row) or datetime.min, reverse=True)
    return rows[: max(int(limit), 0)]


def _latest_transaction_day(records) -> Optional[str]:
    latest = None
    for row in tx.normalize_transactions(records):
        parsed = _parse_record_dt(row)
        if parsed is None:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    return latest.date().isoformat() if latest is not None else None


def load_portfolio_response(*, now: Optional[datetime] = None) -> dict:
    data = _load_portfolio_payload()
    account = ss.build_account_snapshot(data) if data else {}
    transaction_rows = tx.load_transactions()
    recent_transactions = _recent_transactions(transaction_rows, limit=50)
    latest_day = _latest_transaction_day(transaction_rows)
    daily_activity = tx.summarize_daily_activity(transaction_rows, day=latest_day) if latest_day else {}
    post_close_review = pcr.load_post_close_review() or {}
    plan_quality_snapshot = pq.load_plan_quality_snapshot()
    multi_horizon_payload = _load_gated_multi_horizon_snapshot()

    holdings = enrich_rows_with_multi_horizon(
        list(data.get("holdings", []) or []) if isinstance(data, Mapping) else [],
        multi_horizon_payload,
    )
    holdings = add_average_cost_alias(holdings)
    watchlist = enrich_rows_with_multi_horizon(
        list(data.get("watchlist", []) or []) if isinstance(data, Mapping) else [],
        multi_horizon_payload,
    )
    summary = {
        "holding_count": len(holdings),
        "watchlist_count": len(watchlist),
        "transaction_count": len(transaction_rows),
        "recent_transaction_count": len(recent_transactions),
        "latest_transaction_day": latest_day,
        "latest_trade_count": daily_activity.get("trade_count"),
        "latest_buy_count": daily_activity.get("buy_count"),
        "latest_sell_count": daily_activity.get("sell_count"),
        "latest_realized_pl": daily_activity.get("realized_pl"),
        "post_close_review_status": post_close_review.get("status"),
        "unplanned_trade_count": post_close_review.get("unplanned_trade_count"),
        "plan_quality_status": plan_quality_snapshot.get("status") or dict(plan_quality_snapshot.get("summary", {}) or {}).get("status"),
        "multi_horizon_status": multi_horizon_payload.get("status"),
        "multi_horizon_generated_at": multi_horizon_payload.get("generated_at"),
        "multi_horizon_is_stale": bool(
            (_age_seconds(multi_horizon_payload.get("generated_at"), now=now) or 0) > DEFAULT_SNAPSHOT_MAX_AGE_SECONDS
        ),
    }
    payload = {
        "account": account,
        "holdings": holdings,
        "watchlist": watchlist,
        "recent_transactions": recent_transactions,
        "daily_activity": daily_activity,
        "post_close_review": post_close_review,
        "plan_quality_snapshot": plan_quality_snapshot,
        "multi_horizon_snapshot": multi_horizon_payload,
    }
    return build_api_response(
        name="portfolio",
        source="composed:portfolio+transactions",
        freshness_status="OK",
        is_stale=False,
        summary=summary,
        items=recent_transactions,
        data_quality={"status": "OK"},
        payload=payload,
        generated_at=now_iso(now),
    )


def load_dashboard_response(*, now: Optional[datetime] = None) -> dict:
    data = _load_portfolio_payload()
    account = ss.build_account_snapshot(data) if data else {}
    core_payload, _ = safe_read_json(qpaths.CORE_ETF_SNAPSHOT_FILE)
    satellite_payload, _ = safe_read_json(qpaths.SATELLITE_CANDIDATE_POOL_FILE)
    discipline_payload, _ = safe_read_json(qpaths.DISCIPLINE_SNAPSHOT_FILE)
    change_payload, _ = safe_read_json(qpaths.CHANGE_FEED_FILE)
    data_health_payload, _ = safe_read_json(qpaths.DATA_HEALTH_SNAPSHOT_FILE)
    trade_plan_payload, _ = safe_read_json(qpaths.NEXT_DAY_TRADE_PLAN_FILE)
    plan_quality_payload, _ = safe_read_json(qpaths.PLAN_QUALITY_SNAPSHOT_FILE)
    market_monitor_payload, _ = safe_read_json(qpaths.MARKET_MONITOR_SNAPSHOT_FILE)
    strategy_governance_payload, _ = safe_read_json(qpaths.STRATEGY_REGISTRY_STATE_FILE)
    news_intelligence_payload, _ = safe_read_json(qpaths.NEWS_INTELLIGENCE_FILE)
    financials_intelligence_payload, _ = safe_read_json(qpaths.FINANCIALS_INTELLIGENCE_FILE)
    decision_brief_payload, _ = safe_read_json(qpaths.DECISION_BRIEF_FILE)
    market_sentiment_payload, _ = safe_read_json(qpaths.MARKET_SENTIMENT_SNAPSHOT_FILE)
    systemic_risk_payload, _ = safe_read_json(qpaths.SYSTEMIC_RISK_SNAPSHOT_FILE)
    multi_horizon_payload = _load_gated_multi_horizon_snapshot()
    job_status = job_registry.load_job_status()

    core_payload = core_payload if isinstance(core_payload, dict) else {}
    satellite_payload = satellite_payload if isinstance(satellite_payload, dict) else {}
    discipline_payload = discipline_payload if isinstance(discipline_payload, dict) else {}
    change_payload = change_payload if isinstance(change_payload, dict) else {}
    data_health_payload = data_health_payload if isinstance(data_health_payload, dict) else {}
    trade_plan_payload = trade_plan_payload if isinstance(trade_plan_payload, dict) else {}
    plan_quality_payload = plan_quality_payload if isinstance(plan_quality_payload, dict) else {}
    market_monitor_payload = market_monitor_payload if isinstance(market_monitor_payload, dict) else {}
    strategy_governance_payload = strategy_governance_payload if isinstance(strategy_governance_payload, dict) else {}
    news_intelligence_payload = news_intelligence_payload if isinstance(news_intelligence_payload, dict) else {}
    financials_intelligence_payload = financials_intelligence_payload if isinstance(financials_intelligence_payload, dict) else {}
    decision_brief_payload = decision_brief_payload if isinstance(decision_brief_payload, dict) else {}
    market_sentiment_payload = market_sentiment_payload if isinstance(market_sentiment_payload, dict) else {}
    systemic_risk_payload = systemic_risk_payload if isinstance(systemic_risk_payload, dict) else {}

    change_items = []
    for key in ("high_items", "medium_items", "items"):
        change_items.extend(list(change_payload.get(key, []) or []))
    core_rows = list(core_payload.get("symbols", []) or [])
    core_rows = enrich_rows_with_multi_horizon(core_rows, multi_horizon_payload)
    satellite_rows = enrich_rows_with_multi_horizon(
        list(satellite_payload.get("top_recommendations", []) or satellite_payload.get("symbols", []) or []),
        multi_horizon_payload,
    )
    if list(multi_horizon_payload.get("satellite_top3", []) or []):
        satellite_rows = list(multi_horizon_payload.get("satellite_top3", []) or [])
    core_payload["symbols"] = core_rows
    satellite_payload["top_recommendations"] = satellite_rows
    actionable_core = [
        row for row in core_rows
        if str(
            dict(dict(row or {}).get("decision", {}) or {}).get("action")
            or dict(row or {}).get("final_action")
            or dict(row or {}).get("action")
            or ""
        ).upper() not in ("", "HOLD", "WATCH")
    ]
    model_candidate_actions = [
        row for row in list(multi_horizon_payload.get("symbols", []) or [])
        if str(dict(dict(row or {}).get("decision", {}) or {}).get("action") or "").strip().upper()
        in ("ACCUMULATE", "PROBE", "TRIM", "EXIT")
    ]
    executable_plan_items = list(trade_plan_payload.get("items", []) or [])
    blocked_plan_items = list(trade_plan_payload.get("blocked_items", []) or [])
    trade_plan_decision = str(trade_plan_payload.get("decision") or "").strip().upper() or "UNKNOWN"
    if executable_plan_items:
        recommendation_consistency_status = "EXECUTABLE_ACTIONS"
        recommendation_consistency_message = f"{len(executable_plan_items)} item(s) passed the nightly execution planner."
    elif model_candidate_actions and blocked_plan_items:
        recommendation_consistency_status = "CANDIDATES_BLOCKED"
        recommendation_consistency_message = (
            f"{len(model_candidate_actions)} model candidate action(s), but execution planner blocked them via discipline/risk gates."
        )
    elif model_candidate_actions:
        recommendation_consistency_status = "CANDIDATES_ONLY"
        recommendation_consistency_message = (
            f"{len(model_candidate_actions)} model candidate action(s), but no executable next-day plan was produced."
        )
    else:
        recommendation_consistency_status = "NO_ACTION"
        recommendation_consistency_message = "No model candidate action and no executable next-day trade plan."
    summary = {
        "total_capital": account.get("total_capital"),
        "cash_available": account.get("cash_available"),
        "exposure_pct": account.get("exposure_pct"),
        "holding_count": len(list(data.get("holdings", []) or [])),
        "watchlist_count": len(list(data.get("watchlist", []) or [])),
        "discipline_regime": discipline_payload.get("regime"),
        "risk_regime": discipline_payload.get("risk_regime"),
        "actionable_core_count": len(actionable_core),
        "top_satellite_symbols": _top_satellite_symbols(satellite_payload),
        "high_change_count": len(list(change_payload.get("high_items", []) or [])),
        "running_job_count": len([
            row for row in dict(job_status.get("jobs", {}) or {}).values()
            if str(dict(row or {}).get("state") or "").lower() == "started"
        ]),
        "data_health_status": data_health_payload.get("status") or dict(data_health_payload.get("summary", {}) or {}).get("status"),
        "data_health_reason": dict(data_health_payload.get("summary", {}) or {}).get("health_reason"),
        "data_health_action_required": dict(data_health_payload.get("summary", {}) or {}).get("action_required"),
        "data_health_fallback_only": dict(data_health_payload.get("summary", {}) or {}).get("fallback_only"),
        "missing_price_count": dict(data_health_payload.get("summary", {}) or {}).get("missing_price_count"),
        "invalid_price_count": dict(data_health_payload.get("summary", {}) or {}).get("invalid_price_count"),
        "stale_price_count": dict(data_health_payload.get("summary", {}) or {}).get("stale_price_count"),
        "plan_quality_status": plan_quality_payload.get("status") or dict(plan_quality_payload.get("summary", {}) or {}).get("status"),
        "plan_execution_rate": dict(plan_quality_payload.get("summary", {}) or {}).get("execution_rate"),
        "market_monitor_status": market_monitor_payload.get("status"),
        "market_monitor_action": dict(market_monitor_payload.get("summary", {}) or {}).get("recommended_action"),
        "strategy_governance_status": strategy_governance_payload.get("status") or dict(strategy_governance_payload.get("summary", {}) or {}).get("status"),
        "multi_horizon_status": (
            "STALE"
            if bool((_age_seconds(multi_horizon_payload.get("generated_at"), now=now) or 0) > DEFAULT_SNAPSHOT_MAX_AGE_SECONDS)
            else multi_horizon_payload.get("status") or dict(multi_horizon_payload.get("model", {}) or {}).get("status")
        ),
        "multi_horizon_is_stale": bool(
            (_age_seconds(multi_horizon_payload.get("generated_at"), now=now) or 0) > DEFAULT_SNAPSHOT_MAX_AGE_SECONDS
        ),
        "multi_horizon_conflict_count": dict(multi_horizon_payload.get("summary", {}) or {}).get("conflict_count"),
        "multi_horizon_action_counts": dict(multi_horizon_payload.get("summary", {}) or {}).get("action_counts", {}),
        "news_intelligence_status": news_intelligence_payload.get("status"),
        "news_market_risk_level": news_intelligence_payload.get("market_risk_level"),
        "news_impact_count": len(list(news_intelligence_payload.get("portfolio_impacts", []) or [])),
        "financials_intelligence_status": financials_intelligence_payload.get("status"),
        "financials_covered_count": dict(financials_intelligence_payload.get("summary", {}) or {}).get("covered_count"),
        "financials_stress_count": dict(financials_intelligence_payload.get("summary", {}) or {}).get("stress_count"),
        "risk_appetite_state": market_sentiment_payload.get("risk_appetite_state"),
        "market_sentiment_score": market_sentiment_payload.get("market_sentiment_score"),
        "ai_capex_stress": systemic_risk_payload.get("ai_capex_stress"),
        "systemic_risk_score": systemic_risk_payload.get("systemic_risk_score"),
        "decision_brief_status": decision_brief_payload.get("status"),
        "decision_brief_generated_at": decision_brief_payload.get("generated_at"),
        "model_candidate_action_count": len(model_candidate_actions),
        "executable_plan_action_count": len(executable_plan_items),
        "blocked_plan_count": len(blocked_plan_items),
        "trade_plan_decision": trade_plan_decision,
        "recommendation_consistency_status": recommendation_consistency_status,
        "recommendation_consistency_message": recommendation_consistency_message,
    }
    payload = {
        "account": account,
        "core_etf_snapshot": core_payload,
        "satellite_candidate_snapshot": satellite_payload,
        "discipline_snapshot": discipline_payload,
        "change_feed": change_payload,
        "data_health_snapshot": data_health_payload,
        "trade_plan": trade_plan_payload,
        "plan_quality_snapshot": plan_quality_payload,
        "market_monitor_snapshot": market_monitor_payload,
        "strategy_governance_snapshot": strategy_governance_payload,
        "multi_horizon_snapshot": multi_horizon_payload,
        "news_intelligence": news_intelligence_payload,
        "financials_intelligence": financials_intelligence_payload,
        "market_sentiment": market_sentiment_payload,
        "systemic_risk": systemic_risk_payload,
        "decision_brief": decision_brief_payload,
        "job_status": job_status,
    }
    generated_at = now_iso(now)
    return build_api_response(
        name="dashboard",
        source="composed:storage/state",
        freshness_status="OK",
        is_stale=False,
        summary=summary,
        items=change_items[:10],
        data_quality={"status": "OK"},
        payload=payload,
        generated_at=generated_at,
    )


def default_runtime_schedule() -> dict:
    return {
        "schema_version": 1,
        "timezone": "America/New_York",
        "trading_hours": {
            "enabled": True,
            "market_monitor_interval_seconds": 1800,
            "tactical_watchlist_interval_seconds": 600,
            "data_health_interval_seconds": 1800,
            "market_hours_only": True,
        },
        "nightly": {
            "enabled": True,
            "poll_seconds": 300,
            "run_window_local": {"start": "23:00", "end": "01:00"},
        },
        "weekend_research": {
            "enabled": True,
            "run_window_local": {"day": "Saturday", "start": "10:00", "end": "18:00"},
        },
        "notifications": {
            "send_market_summary": True,
            "send_market_summary_market_hours_only": True,
            "send_nightly_digest": True,
            "send_weekend_digest": True,
        },
    }


def _positive_int(value, default: int, *, minimum: int = 1) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = int(default)
    return max(int(parsed), int(minimum))


def normalize_runtime_schedule(schedule: Mapping | None = None) -> dict:
    defaults = default_runtime_schedule()
    merged = dict(defaults)
    for key, value in dict(schedule or {}).items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = {**dict(merged[key]), **dict(value)}
        else:
            merged[key] = value
    trading = dict(merged.get("trading_hours", {}) or {})
    trading["market_monitor_interval_seconds"] = _positive_int(
        trading.get("market_monitor_interval_seconds"),
        defaults["trading_hours"]["market_monitor_interval_seconds"],
        minimum=60,
    )
    trading["tactical_watchlist_interval_seconds"] = _positive_int(
        trading.get("tactical_watchlist_interval_seconds"),
        defaults["trading_hours"]["tactical_watchlist_interval_seconds"],
        minimum=60,
    )
    trading["data_health_interval_seconds"] = _positive_int(
        trading.get("data_health_interval_seconds"),
        defaults["trading_hours"]["data_health_interval_seconds"],
        minimum=300,
    )
    trading["enabled"] = bool(trading.get("enabled", True))
    trading["market_hours_only"] = bool(trading.get("market_hours_only", True))
    merged["trading_hours"] = trading

    nightly = dict(merged.get("nightly", {}) or {})
    nightly["poll_seconds"] = _positive_int(nightly.get("poll_seconds"), defaults["nightly"]["poll_seconds"], minimum=60)
    nightly["enabled"] = bool(nightly.get("enabled", True))
    merged["nightly"] = nightly
    return merged


def load_runtime_schedule(*, path: str = qpaths.RUNTIME_SCHEDULE_CONFIG_FILE) -> dict:
    payload, errors = safe_read_json(path)
    if errors or not isinstance(payload, dict):
        return default_runtime_schedule()
    return normalize_runtime_schedule(payload)


def save_runtime_schedule(schedule: Mapping, *, path: str = qpaths.RUNTIME_SCHEDULE_CONFIG_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(normalize_runtime_schedule(schedule), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(target)


def _sanitize_notification_config(payload) -> dict:
    payload = ncfg.normalize_notification_config(dict(payload or {}))
    slack = dict(payload.get("slack", {}) or {})
    email = dict(payload.get("email", {}) or {})
    llm = dict(payload.get("llm", {}) or {})
    local_slm = dict(payload.get("local_slm", {}) or {})
    return {
        "slack": {
            "enabled": bool(slack.get("enabled")),
            "webhook_url": "",
            "webhook_configured": bool(str(slack.get("webhook_url") or "").strip()),
        },
        "email": {
            "enabled": bool(email.get("enabled")),
            "smtp_host": email.get("smtp_host"),
            "smtp_port": email.get("smtp_port"),
            "use_starttls": bool(email.get("use_starttls")),
            "username": email.get("username"),
            "password": "",
            "from_email": email.get("from_email"),
            "to_emails": list(email.get("to_emails", []) or []),
            "smtp_host_configured": bool(str(email.get("smtp_host") or "").strip()),
            "password_configured": bool(str(email.get("password") or "").strip()),
        },
        "llm": {
            "enabled": bool(llm.get("enabled")),
            "provider": llm.get("provider"),
            "base_url": llm.get("base_url"),
            "api_key": "",
            "model": llm.get("model"),
            "temperature": llm.get("temperature"),
            "max_tokens": llm.get("max_tokens"),
            "context_window_tokens": llm.get("context_window_tokens"),
            "timeout_seconds": llm.get("timeout_seconds"),
            "site_url": llm.get("site_url"),
            "app_name": llm.get("app_name"),
            "api_key_configured": bool(str(llm.get("api_key") or "").strip()),
        },
        "local_slm": {
            "enabled": bool(local_slm.get("enabled")),
            "provider": local_slm.get("provider"),
            "base_url": local_slm.get("base_url"),
            "api_key": "",
            "model": local_slm.get("model"),
            "temperature": local_slm.get("temperature"),
            "max_tokens": local_slm.get("max_tokens"),
            "timeout_seconds": local_slm.get("timeout_seconds"),
            "api_key_configured": bool(str(local_slm.get("api_key") or "").strip()),
        },
        "alert_settings": dict(payload.get("alert_settings", {}) or {}),
    }


def load_settings_response(*, now: Optional[datetime] = None) -> dict:
    schedule = load_runtime_schedule()
    notification_config = ncfg.load_notification_config()
    model_registry, _ = safe_read_json(qpaths.MODEL_REGISTRY_CONFIG_FILE)
    foundation_config, _ = safe_read_json(qpaths.FOUNDATION_MODEL_CONFIG_FILE)
    financials_config, _ = safe_read_json(qpaths.FINANCIALS_CONFIG_FILE)
    core_etf_universe, _ = safe_read_json(qpaths.CORE_ETF_UNIVERSE_FILE)
    event_source_config, _ = safe_read_json(qpaths.EVENT_SOURCES_CONFIG_FILE)
    event_source_status, _ = safe_read_json(qpaths.EVENT_SOURCE_STATUS_FILE)
    analyst_consensus_status, _ = safe_read_json(qpaths.ANALYST_CONSENSUS_CACHE_FILE)
    settings_payload = {
        "runtime_schedule": schedule,
        "notification_config": _sanitize_notification_config(notification_config if isinstance(notification_config, dict) else {}),
        "model_registry": model_registry if isinstance(model_registry, dict) else {},
        "foundation_model_config": foundation_config if isinstance(foundation_config, dict) else {},
        "financials_config": financials_config if isinstance(financials_config, dict) else {},
        "core_etf_universe": core_etf_universe if isinstance(core_etf_universe, dict) else {},
        "event_source_config": event_source_config if isinstance(event_source_config, dict) else {},
        "event_source_status": event_source_status if isinstance(event_source_status, dict) else {},
        "analyst_consensus_status": analyst_consensus_status if isinstance(analyst_consensus_status, dict) else {},
    }
    return build_api_response(
        name="settings",
        source="storage/config",
        freshness_status="OK",
        is_stale=False,
        summary={
            "timezone": schedule.get("timezone"),
            "market_monitor_interval_seconds": dict(schedule.get("trading_hours", {}) or {}).get("market_monitor_interval_seconds"),
        },
        data_quality={"status": "OK"},
        payload=settings_payload,
        generated_at=now_iso(now),
    )


def load_research_models_response(*, now: Optional[datetime] = None) -> dict:
    snapshot, snapshot_errors = safe_read_json(qpaths.MULTI_HORIZON_SNAPSHOT_FILE)
    foundation_snapshot, foundation_errors = safe_read_json(qpaths.FOUNDATION_MODEL_SNAPSHOT_FILE)
    validation, validation_errors = safe_read_json(qpaths.MULTI_HORIZON_VALIDATION_FILE)
    registry, registry_errors = safe_read_json(qpaths.MODEL_REGISTRY_CONFIG_FILE)
    foundation_config, foundation_config_errors = safe_read_json(qpaths.FOUNDATION_MODEL_CONFIG_FILE)
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    foundation_snapshot = foundation_snapshot if isinstance(foundation_snapshot, dict) else {}
    validation = validation if isinstance(validation, dict) else {}
    registry = registry if isinstance(registry, dict) else {}
    foundation_config = foundation_config if isinstance(foundation_config, dict) else {}
    errors = [
        *snapshot_errors,
        *foundation_errors,
        *validation_errors,
        *registry_errors,
        *foundation_config_errors,
    ]
    model_age = _age_seconds(snapshot.get("generated_at"), now=now)
    model_stale = bool(model_age is not None and model_age > DEFAULT_SNAPSHOT_MAX_AGE_SECONDS)
    return build_api_response(
        name="research-models",
        source="composed:model-registry+multi-horizon",
        freshness_status="MISSING" if snapshot_errors else ("STALE" if model_stale else "OK"),
        is_stale=bool(snapshot_errors or model_stale),
        summary={
            "model_status": snapshot.get("status") or dict(snapshot.get("model", {}) or {}).get("status"),
            "validation_status": validation.get("status"),
            "fold_count": validation.get("fold_count"),
            "symbol_count": dict(snapshot.get("summary", {}) or {}).get("symbol_count"),
            "automatic_promotion": False,
        },
        errors=errors,
        data_quality={"status": "MISSING" if snapshot_errors else "OK"},
        payload={
            "multi_horizon_snapshot": snapshot,
            "foundation_model_snapshot": foundation_snapshot,
            "validation": validation,
            "model_registry": registry,
            "foundation_config": foundation_config,
        },
        generated_at=snapshot.get("generated_at") or validation.get("generated_at") or now_iso(now),
    )


def load_job_status_response(*, now: Optional[datetime] = None) -> dict:
    payload = job_registry.mark_stale_jobs(job_registry.load_job_status(), now=now)
    jobs = dict(payload.get("jobs", {}) or {})
    return build_api_response(
        name="job-status",
        source=job_registry.DEFAULT_JOB_STATUS_FILE,
        freshness_status="OK",
        is_stale=False,
        summary={
            "job_count": len(jobs),
            "active_count": len([
                row
                for row in jobs.values()
                if str(dict(row or {}).get("state") or "").lower() in {"started", "running", "queued"}
            ]),
            "completed_count": len([row for row in jobs.values() if str(dict(row or {}).get("state") or "").lower() == "completed"]),
            "failed_count": len([row for row in jobs.values() if str(dict(row or {}).get("state") or "").lower() == "failed"]),
        },
        items=list(jobs.values()),
        data_quality={"status": "OK"},
        payload=payload,
        generated_at=payload.get("updated_at") or now_iso(now),
    )
