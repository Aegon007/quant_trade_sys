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
from quant_core.jobs import job_registry
from quant_core.ledger import transactions
from quant_core.notifications import notification_config
from quant_core.portfolio import actions as portfolio_actions


def _safe_detail(payload) -> str:
    if isinstance(payload, Mapping):
        return str(payload.get("message") or payload.get("reason") or payload.get("status") or "completed")
    return "completed"


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
                now=now_func(),
            )
            return result
        except Exception as exc:  # pragma: no cover - defensive status path
            job_registry.update_job_status(
                normalized_name,
                state="failed",
                detail=f"{type(exc).__name__}: {exc}",
                now=now_func(),
            )
            raise

    job_registry.update_job_status(
        normalized_name,
        state="started",
        detail="manual trigger accepted",
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


def import_robinhood_csv_text(csv_text: str, *, filename: str = "") -> dict:
    if not str(csv_text or "").strip():
        raise ValueError("CSV content is empty.")
    imported = transactions.import_robinhood_activity_csv(csv_text, filename=filename)
    reconciled: Optional[dict] = None
    reconcile_error = ""
    try:
        reconciled = portfolio_actions.reconcile_portfolio_from_robinhood_imports(force_price_refresh=False)
    except Exception as exc:
        reconcile_error = f"{type(exc).__name__}: {exc}"
    return {
        "message": "robinhood csv imported",
        "import": imported,
        "reconciliation": reconciled or {},
        "reconciliation_error": reconcile_error,
    }


def save_runtime_schedule(schedule: Mapping) -> dict:
    path = snapshot_loader.save_runtime_schedule(schedule)
    return {
        "message": "runtime schedule saved",
        "path": path,
        "runtime_schedule": snapshot_loader.load_runtime_schedule(path=path),
    }


def save_notification_settings(config: Mapping) -> dict:
    saved = notification_config.save_notification_config(dict(config or {}))
    return {
        "message": "notification config saved",
        "notification_config": saved,
    }
