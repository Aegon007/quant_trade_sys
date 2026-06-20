"""Small action adapters for the local FastAPI server.

HTTP handlers call these helpers to trigger existing jobs or write config. The
helpers keep status updates consistent without moving quant computation into
the frontend layer.
"""

from __future__ import annotations

import traceback
from datetime import datetime
from threading import Thread
from typing import Callable, Mapping, Optional

from quant_core.api import snapshot_loader
from quant_core.data import data_health
from quant_core.data import market_data
from quant_core.data import storage as data_storage
from quant_core.execution import nightly_planner
from quant_core.execution import plan_quality
from quant_core.execution import post_close_review
from quant_core.jobs import job_registry
from quant_core.ledger import transactions
from quant_core.notifications import notification_config
from quant_core.models.multi_horizon import config as multi_horizon_config
from quant_core.models.multi_horizon import governance as multi_horizon_governance
from quant_core.models.multi_horizon import snapshot as multi_horizon_snapshot
from quant_core.portfolio import actions as portfolio_actions
from quant_core.snapshots import system_snapshot


def _safe_detail(payload) -> str:
    if isinstance(payload, Mapping):
        return str(payload.get("message") or payload.get("reason") or payload.get("status") or "completed")
    return "completed"


def build_job_progress_callback(
    job_name: str,
    *,
    logger: Callable[[str], object] | None = None,
    now_func: Callable[[], datetime] = datetime.now,
) -> Callable[[Mapping], None]:
    normalized_name = str(job_name or "").strip() or "manual-job"

    def _report(event: Mapping) -> None:
        payload = dict(event or {})
        detail = str(payload.pop("detail", "") or payload.get("stage") or "working")
        stage = str(payload.get("stage") or "running")
        progress = payload.get("progress_pct")
        progress_text = f" {float(progress):.0f}%" if progress is not None else ""
        message = f"[{normalized_name}] {stage}{progress_text} - {detail}"
        if logger is None:
            print(message, flush=True)
        else:
            logger(message)
        job_registry.update_job_status(
            normalized_name,
            state="completed" if stage == "completed" else "failed" if stage == "failed" else "running",
            detail=detail,
            metadata=payload,
            now=now_func(),
        )

    return _report


def run_with_job_status(
    job_name: str,
    runner: Callable[[], object],
    *,
    run_async: bool = True,
    now_func: Callable[[], datetime] = datetime.now,
) -> dict:
    """Run a local job and update the file-backed job registry."""

    normalized_name = str(job_name or "").strip() or "manual-job"

    def _execute():
        try:
            result = runner()
            job_registry.update_job_status(
                normalized_name,
                state="completed",
                detail=_safe_detail(result),
                metadata={"stage": "completed", "progress_pct": 100},
                now=now_func(),
            )
            return result
        except Exception as exc:  # pragma: no cover - defensive status path
            job_registry.update_job_status(
                normalized_name,
                state="failed",
                detail=f"{type(exc).__name__}: {exc}",
                metadata={"stage": "failed"},
                now=now_func(),
            )
            if run_async:
                traceback.print_exc()
            raise

    job_registry.update_job_status(
        normalized_name,
        state="started",
        detail="manual trigger accepted",
        metadata={"stage": "queued", "progress_pct": 0},
        now=now_func(),
    )
    if run_async:
        thread = Thread(target=_execute, daemon=True, name=normalized_name)
        thread.start()
        return {
            "accepted": True,
            "job_name": normalized_name,
            "mode": "background",
            "message": f"{normalized_name} started in background.",
        }

    try:
        result = _execute()
        return {
            "accepted": True,
            "job_name": normalized_name,
            "mode": "inline",
            "result": result,
        }
    except Exception as exc:
        return {
            "accepted": False,
            "job_name": normalized_name,
            "mode": "inline",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=4),
        }


def refresh_market_data_now(*, force_source_refresh: bool = True) -> dict:
    before = data_storage.load_data()
    refreshed = data_storage.refresh_market_data(
        before,
        force_source_refresh=bool(force_source_refresh),
    )
    data_storage.save_data(refreshed)
    health_snapshot = data_health.build_data_health_snapshot(
        refreshed,
        data_sources=market_data.get_market_data_status_snapshot(),
    )
    data_health.save_data_health_snapshot(health_snapshot)
    holdings = list(refreshed.get("holdings", []) or [])
    watchlist = list(refreshed.get("watchlist", []) or [])
    priced_holdings = [row for row in holdings if row.get("current_price") is not None]
    priced_watchlist = [row for row in watchlist if row.get("last_price") is not None]
    return {
        "message": "market data refreshed",
        "symbol_count": len({str(row.get("symbol") or "").upper() for row in holdings + watchlist if row.get("symbol")}),
        "priced_count": len(priced_holdings) + len(priced_watchlist),
        "holdings_count": len(holdings),
        "watchlist_count": len(watchlist),
        "prices_last_updated": refreshed.get("prices_last_updated"),
        "data_health_status": health_snapshot.get("status"),
    }


def run_nightly_once() -> dict:
    from jobs.nightly_alerts import run_nightly_alerts

    result = run_nightly_alerts(force=True, dry_run=False)
    return result if isinstance(result, dict) else {"message": "nightly run completed", "result": result}


def run_weekend_research_once() -> dict:
    from jobs.weekend_research import run_weekend_research

    result = run_weekend_research(force=True)
    return result if isinstance(result, dict) else {"message": "weekend research completed", "result": result}


def train_multi_horizon_model() -> dict:
    from quant_core.models.multi_horizon.pipeline import run_multi_horizon_job

    result = run_multi_horizon_job(
        train=True,
        progress_callback=build_job_progress_callback("manual-multi-horizon-training"),
    )
    if not isinstance(result, dict):
        return {"message": "multi-horizon training completed", "result": result}
    if result.get("status") == "READY":
        multi_horizon_governance.append_prediction_journal(result)
    governance = multi_horizon_governance.refresh_model_governance(result)
    gated = multi_horizon_governance.apply_production_gate(result, governance)
    multi_horizon_snapshot.save_multi_horizon_snapshot(gated)
    return gated


def promote_multi_horizon_model() -> dict:
    snapshot = multi_horizon_snapshot.load_multi_horizon_snapshot()
    governance = multi_horizon_governance.load_model_governance_snapshot()
    promoted = multi_horizon_governance.approve_model_for_production(snapshot, governance)
    gated = multi_horizon_governance.apply_production_gate(snapshot, promoted)
    multi_horizon_snapshot.save_multi_horizon_snapshot(gated)
    return {
        "message": "multi-horizon model promoted to production",
        "model_version": promoted.get("approved_model_version"),
        "governance": promoted,
    }


def import_robinhood_csv_text(csv_text: str, *, filename: str = "", replace_existing: bool = False) -> dict:
    if not str(csv_text or "").strip():
        raise ValueError("CSV content is empty.")
    if replace_existing:
        imported = transactions.replace_with_robinhood_activity_csv(csv_text, filename=filename, backup=True)
    else:
        imported = transactions.import_robinhood_activity_csv(csv_text, filename=filename)
    reconciled: Optional[dict] = None
    reconcile_error = ""
    try:
        reconciled = portfolio_actions.reconcile_portfolio_from_robinhood_imports(force_price_refresh=False)
    except Exception as exc:
        reconcile_error = f"{type(exc).__name__}: {exc}"
    followup = build_robinhood_import_followup(imported)
    return {
        "message": "robinhood csv imported",
        "mode": "replace" if replace_existing else "append",
        "import": imported,
        "reconciliation": reconciled or {},
        "reconciliation_error": reconcile_error,
        "followup": followup,
    }


def _latest_trade_day(records) -> Optional[str]:
    latest = None
    for record in transactions.normalize_transactions(records):
        if str(record.get("record_type") or "").strip().upper() != "TRADE":
            continue
        parsed = post_close_review._parse_datetime(record.get("date"))
        if parsed is None:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    return latest.date().isoformat() if latest is not None else None


def build_robinhood_import_followup(imported: Mapping) -> dict:
    """Update lightweight review snapshots after Robinhood CSV import."""

    imported = dict(imported or {})
    transaction_rows = transactions.load_transactions()
    latest_day = _latest_trade_day(imported.get("records") or transaction_rows)
    if not latest_day:
        return {
            "message": "no trade day found",
            "post_close_review_updated": False,
            "plan_quality_updated": False,
        }

    trade_plan = nightly_planner.load_next_day_trade_plan() or {}
    review = post_close_review.build_execution_review(
        trade_plan,
        transaction_rows,
        day=latest_day,
    )
    post_close_review.save_post_close_review(review)
    quality = plan_quality.build_plan_quality_snapshot(
        trade_plan=trade_plan,
        latest_review=review,
    )
    plan_quality.save_plan_quality_snapshot(quality)
    return {
        "message": "post-close review and plan quality updated",
        "review_day": latest_day,
        "post_close_review_updated": True,
        "plan_quality_updated": True,
        "review": {
            "status": review.get("status"),
            "executed_count": review.get("executed_count"),
            "missed_count": review.get("missed_count"),
            "unplanned_trade_count": review.get("unplanned_trade_count"),
        },
        "plan_quality": dict(quality.get("summary", {}) or {}),
    }


def save_runtime_schedule(schedule: Mapping) -> dict:
    path = snapshot_loader.save_runtime_schedule(schedule)
    return {
        "message": "runtime schedule saved",
        "path": path,
        "runtime_schedule": snapshot_loader.load_runtime_schedule(path=path),
    }


def save_notification_settings(config: Mapping) -> dict:
    existing = notification_config.load_notification_config()
    merged = notification_config.preserve_unsubmitted_secrets(dict(config or {}), existing)
    saved = notification_config.save_notification_config(merged)
    return {
        "message": "notification config saved",
        "notification_config": snapshot_loader._sanitize_notification_config(saved),
    }


def save_multi_horizon_settings(config: Mapping) -> dict:
    path = multi_horizon_config.save_multi_horizon_config(config)
    return {
        "message": "multi-horizon model config saved",
        "path": path,
        "multi_horizon_config": multi_horizon_config.load_multi_horizon_config(path=path),
    }


def _optional_float_from_payload(payload: Mapping, key: str):
    value = payload.get(key)
    if value in (None, ""):
        return None
    return float(value)


def save_account_calibration(payload: Mapping) -> dict:
    payload = dict(payload or {})
    data = data_storage.load_data()
    account = dict(data.get("account", {}) or {})
    before_snapshot = system_snapshot.build_account_snapshot(data)
    holdings_value = float(before_snapshot.get("holdings_market_value") or 0.0)

    broker_total = _optional_float_from_payload(payload, "broker_total_capital")
    cash_available = _optional_float_from_payload(payload, "cash_available")
    inferred_from_broker_total = False
    if broker_total is not None:
        cash_available = round(float(broker_total) - holdings_value, 4)
        inferred_from_broker_total = True
        if cash_available < 0:
            raise ValueError(
                "broker_total_capital is below current holdings market value; "
                "enter cash_available directly if the broker account includes margin or stale prices."
            )

    if cash_available is not None:
        if cash_available < 0:
            raise ValueError("cash_available must be >= 0")
        account["cash_available"] = round(float(cash_available), 4)

    for key in ("min_cash_buffer_pct", "max_single_position_pct", "max_total_exposure_pct"):
        value = payload.get(key)
        if value not in (None, ""):
            account[key] = float(value)

    # Keep total capital dynamic: cash + current holdings market value.
    account["total_capital"] = None
    data["account"] = account
    data_storage.save_data(data)
    snapshot = system_snapshot.build_account_snapshot(data)
    return {
        "message": "account calibration saved",
        "account": snapshot,
        "inferred_cash_from_broker_total": inferred_from_broker_total,
        "holdings_market_value": holdings_value,
    }
