"""Read-only snapshot loader used by the FastAPI server.

This module must stay light: it reads existing state/config/report files and
normalizes them into stable DTOs. It must not fetch market data, train models,
or run backtests.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths
from quant_core.api.schemas import build_api_response, now_iso
from quant_core.execution import plan_quality as pq
from quant_core.execution import post_close_review as pcr
from quant_core.jobs import job_registry
from quant_core.ledger import transactions as tx
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
    "reports-latest": str(qpaths.PROJECT_ROOT / "reports" / "nightly_report_latest.json"),
}


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
    quant_analysis_payload, _ = safe_read_json(qpaths.QUANT_ANALYSIS_SNAPSHOT_FILE)
    quant_analysis_payload = quant_analysis_payload if isinstance(quant_analysis_payload, dict) else {}

    holdings = list(data.get("holdings", []) or []) if isinstance(data, Mapping) else []
    watchlist = list(data.get("watchlist", []) or []) if isinstance(data, Mapping) else []
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
        "quant_analysis_generated_at": quant_analysis_payload.get("generated_at"),
    }
    payload = {
        "account": account,
        "holdings": holdings,
        "watchlist": watchlist,
        "recent_transactions": recent_transactions,
        "daily_activity": daily_activity,
        "post_close_review": post_close_review,
        "plan_quality_snapshot": plan_quality_snapshot,
        "quant_analysis_snapshot": quant_analysis_payload,
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
    plan_quality_payload, _ = safe_read_json(qpaths.PLAN_QUALITY_SNAPSHOT_FILE)
    market_monitor_payload, _ = safe_read_json(qpaths.MARKET_MONITOR_SNAPSHOT_FILE)
    strategy_governance_payload, _ = safe_read_json(qpaths.STRATEGY_REGISTRY_STATE_FILE)
    job_status = job_registry.load_job_status()

    core_payload = core_payload if isinstance(core_payload, dict) else {}
    satellite_payload = satellite_payload if isinstance(satellite_payload, dict) else {}
    discipline_payload = discipline_payload if isinstance(discipline_payload, dict) else {}
    change_payload = change_payload if isinstance(change_payload, dict) else {}
    data_health_payload = data_health_payload if isinstance(data_health_payload, dict) else {}
    plan_quality_payload = plan_quality_payload if isinstance(plan_quality_payload, dict) else {}
    market_monitor_payload = market_monitor_payload if isinstance(market_monitor_payload, dict) else {}
    strategy_governance_payload = strategy_governance_payload if isinstance(strategy_governance_payload, dict) else {}

    change_items = []
    for key in ("high_items", "medium_items", "items"):
        change_items.extend(list(change_payload.get(key, []) or []))
    core_rows = list(core_payload.get("symbols", []) or [])
    actionable_core = [
        row for row in core_rows
        if str(dict(row or {}).get("action") or "").upper() not in ("", "HOLD", "WATCH")
    ]
    summary = {
        "total_capital": account.get("total_capital"),
        "cash_available": account.get("cash_available"),
        "exposure_pct": account.get("exposure_pct"),
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
        "missing_price_count": dict(data_health_payload.get("summary", {}) or {}).get("missing_price_count"),
        "invalid_price_count": dict(data_health_payload.get("summary", {}) or {}).get("invalid_price_count"),
        "plan_quality_status": plan_quality_payload.get("status") or dict(plan_quality_payload.get("summary", {}) or {}).get("status"),
        "plan_execution_rate": dict(plan_quality_payload.get("summary", {}) or {}).get("execution_rate"),
        "market_monitor_status": market_monitor_payload.get("status"),
        "market_monitor_action": dict(market_monitor_payload.get("summary", {}) or {}).get("recommended_action"),
        "strategy_governance_status": strategy_governance_payload.get("status") or dict(strategy_governance_payload.get("summary", {}) or {}).get("status"),
    }
    payload = {
        "account": account,
        "core_etf_snapshot": core_payload,
        "satellite_candidate_snapshot": satellite_payload,
        "discipline_snapshot": discipline_payload,
        "change_feed": change_payload,
        "data_health_snapshot": data_health_payload,
        "plan_quality_snapshot": plan_quality_payload,
        "market_monitor_snapshot": market_monitor_payload,
        "strategy_governance_snapshot": strategy_governance_payload,
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
    payload = dict(payload or {})
    slack = dict(payload.get("slack", {}) or {})
    email = dict(payload.get("email", {}) or {})
    llm = dict(payload.get("llm", {}) or {})
    local_slm = dict(payload.get("local_slm", {}) or {})
    return {
        "slack": {
            "enabled": bool(slack.get("enabled")),
            "webhook_configured": bool(str(slack.get("webhook_url") or "").strip()),
        },
        "email": {
            "enabled": bool(email.get("enabled")),
            "to_emails": list(email.get("to_emails", []) or []),
            "smtp_host_configured": bool(str(email.get("smtp_host") or "").strip()),
            "password_configured": bool(str(email.get("password") or "").strip()),
        },
        "llm": {
            "enabled": bool(llm.get("enabled")),
            "base_url": llm.get("base_url"),
            "model": llm.get("model"),
            "api_key_configured": bool(str(llm.get("api_key") or "").strip()),
        },
        "local_slm": {
            "enabled": bool(local_slm.get("enabled")),
            "base_url": local_slm.get("base_url"),
            "model": local_slm.get("model"),
        },
        "alert_settings": dict(payload.get("alert_settings", {}) or {}),
    }


def load_settings_response(*, now: Optional[datetime] = None) -> dict:
    schedule = load_runtime_schedule()
    notification_config, _ = safe_read_json(qpaths.CONFIG_DIR / "notification_config.json")
    if not notification_config:
        notification_config, _ = safe_read_json(qpaths.NOTIFICATION_CONFIG_FILE)
    model_registry, _ = safe_read_json(qpaths.MODEL_REGISTRY_CONFIG_FILE)
    settings_payload = {
        "runtime_schedule": schedule,
        "notification_config": _sanitize_notification_config(notification_config if isinstance(notification_config, dict) else {}),
        "model_registry": model_registry if isinstance(model_registry, dict) else {},
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


def load_job_status_response(*, now: Optional[datetime] = None) -> dict:
    payload = job_registry.load_job_status()
    jobs = dict(payload.get("jobs", {}) or {})
    return build_api_response(
        name="job-status",
        source=job_registry.DEFAULT_JOB_STATUS_FILE,
        freshness_status="OK",
        is_stale=False,
        summary={
            "job_count": len(jobs),
            "started_count": len([row for row in jobs.values() if str(dict(row or {}).get("state") or "").lower() == "started"]),
            "failed_count": len([row for row in jobs.values() if str(dict(row or {}).get("state") or "").lower() == "failed"]),
        },
        items=list(jobs.values()),
        data_quality={"status": "OK"},
        payload=payload,
        generated_at=payload.get("updated_at") or now_iso(now),
    )
