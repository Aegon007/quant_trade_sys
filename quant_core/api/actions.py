"""Small action adapters for the local FastAPI server.

HTTP handlers call these helpers to trigger existing jobs or write config. The
helpers keep status updates consistent without moving quant computation into
the frontend layer.
"""

from __future__ import annotations

import traceback
import shutil
from datetime import datetime
from pathlib import Path
from threading import Thread
from typing import Callable, Mapping, Optional

from quant_core import paths as qpaths
from quant_core.api import snapshot_loader
from quant_core.data import data_health
from quant_core.data import market_data
from quant_core.data import storage as data_storage
from quant_core.analytics import core_etf_rotation
from quant_core.events import event_fetcher
from quant_core.execution import nightly_planner
from quant_core.execution import plan_quality
from quant_core.execution import post_close_review
from quant_core.jobs import job_registry
from quant_core.ledger import transactions
from quant_core.notifications import notification_config
from quant_core.llm import openai_compatible
from quant_core.llm import explainer as llm_explainer
from quant_core.llm import decision_brief
from quant_core.models.multi_horizon import config as multi_horizon_config
from quant_core.models.multi_horizon import governance as multi_horizon_governance
from quant_core.models.multi_horizon import snapshot as multi_horizon_snapshot
from quant_core.portfolio import actions as portfolio_actions
from quant_core.snapshots import system_snapshot


def _safe_detail(payload) -> str:
    if isinstance(payload, Mapping):
        return str(payload.get("message") or payload.get("reason") or payload.get("status") or "completed")
    return "completed"


def _result_summary(payload) -> dict:
    if not isinstance(payload, Mapping):
        return {"result": str(payload)}
    preferred_keys = (
        "message",
        "status",
        "symbol_count",
        "priced_count",
        "holdings_count",
        "watchlist_count",
        "data_health_status",
        "dry_run",
        "snapshot_journal_path",
        "decision",
        "action_count",
        "generated_at",
    )
    summary = {
        key: payload.get(key)
        for key in preferred_keys
        if payload.get(key) not in (None, "", [], {})
    }
    if "snapshot" in payload and isinstance(payload.get("snapshot"), Mapping):
        snapshot = dict(payload.get("snapshot") or {})
        summary.setdefault("generated_at", snapshot.get("generated_at"))
        summary["alert_count"] = len(list(snapshot.get("alerts", []) or []))
        summary["decision_brief_status"] = dict(snapshot.get("decision_brief", {}) or {}).get("status")
    if "report_files" in payload and isinstance(payload.get("report_files"), Mapping):
        summary["report_path"] = dict(payload.get("report_files") or {}).get("latest_markdown_path")
    return summary or {"message": _safe_detail(payload)}


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
            job_registry.update_job_status(
                normalized_name,
                state="running",
                detail="job is running",
                metadata={"stage": "running", "progress_pct": 1},
                now=now_func(),
            )
            result = runner()
            job_registry.update_job_status(
                normalized_name,
                state="completed",
                detail=_safe_detail(result),
                metadata={
                    "stage": "completed",
                    "progress_pct": 100,
                    "result_summary": _result_summary(result),
                },
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


def promote_multi_horizon_model(*, allow_initial_override: bool = False) -> dict:
    snapshot = multi_horizon_snapshot.load_multi_horizon_snapshot()
    governance = multi_horizon_governance.load_model_governance_snapshot()
    config = multi_horizon_config.load_multi_horizon_config()
    artifacts = dict(config.get("artifacts", {}) or {})
    def artifact_path(value) -> Path:
        path = Path(str(value))
        return path if path.is_absolute() else qpaths.PROJECT_ROOT / path

    candidate_path = artifact_path(artifacts["checkpoint_path"])
    production_path = artifact_path(
        artifacts.get("production_checkpoint_path") or qpaths.MULTI_HORIZON_PRODUCTION_CHECKPOINT_FILE
    )
    if not candidate_path.exists():
        raise ValueError("Candidate model checkpoint is missing; train the model before deployment.")
    production_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_production_path = production_path.with_suffix(production_path.suffix + ".pending")
    shutil.copy2(candidate_path, temporary_production_path)
    try:
        promoted = multi_horizon_governance.approve_model_for_production(
            snapshot,
            governance,
            allow_initial_override=allow_initial_override,
        )
        temporary_production_path.replace(production_path)
    finally:
        temporary_production_path.unlink(missing_ok=True)
    gated = multi_horizon_governance.apply_production_gate(snapshot, promoted)
    multi_horizon_snapshot.save_multi_horizon_snapshot(gated)
    return {
        "message": "multi-horizon model promoted to production",
        "model_version": promoted.get("approved_model_version"),
        "approval_mode": promoted.get("approval_mode"),
        "production_checkpoint_path": str(production_path),
        "governance": promoted,
    }


def test_llm_settings(*, route: str) -> dict:
    config = notification_config.apply_environment_overrides(
        notification_config.load_notification_config()
    )
    route = str(route or "").strip().lower()
    if route == "remote":
        ok, message = openai_compatible.test_llm_connection(config.get("llm", {}))
    elif route == "local":
        ok, message = openai_compatible.test_local_narration(config.get("local_slm", {}))
    else:
        raise ValueError("Unknown LLM test route.")
    return {
        "message": message,
        "ok": bool(ok),
        "route": route,
    }


def _llm_config() -> dict:
    return notification_config.apply_environment_overrides(
        notification_config.load_notification_config()
    )


def _find_symbol_row(rows, symbol: str) -> dict:
    normalized = str(symbol or "").strip().upper()
    for row in list(rows or []):
        row = dict(row or {})
        if str(row.get("symbol") or "").strip().upper() == normalized:
            return row
    raise ValueError(f"Symbol {normalized or '-'} is not present in the latest snapshot.")


def explain_core_etf(symbol: str) -> dict:
    response = snapshot_loader.load_model_enriched_snapshot_response(
        "core-etfs",
        snapshot_loader.SNAPSHOT_PATHS["core-etfs"],
        row_keys=("symbols",),
    )
    row = _find_symbol_row(dict(response.get("payload", {}) or {}).get("symbols", []), symbol)
    discipline, _ = snapshot_loader.safe_read_json(qpaths.DISCIPLINE_SNAPSHOT_FILE)
    change_feed, _ = snapshot_loader.safe_read_json(qpaths.CHANGE_FEED_FILE)
    ok, text, meta = llm_explainer.explain_core_etf_decision(
        symbol_row=row,
        notification_config=_llm_config(),
        discipline_snapshot=discipline,
        change_feed=change_feed,
    )
    return {"ok": ok, "text": text, "meta": meta, "symbol": str(symbol).upper()}


def explain_satellite(symbol: str) -> dict:
    response = snapshot_loader.load_model_enriched_snapshot_response(
        "satellite-radar",
        snapshot_loader.SNAPSHOT_PATHS["satellite-radar"],
        row_keys=("top_recommendations", "symbols", "candidate_pool"),
    )
    payload = dict(response.get("payload", {}) or {})
    rows = (
        list(payload.get("top_recommendations", []) or [])
        + list(payload.get("candidate_pool", []) or [])
        + list(payload.get("current_holdings", []) or [])
    )
    row = _find_symbol_row(rows, symbol)
    discipline, _ = snapshot_loader.safe_read_json(qpaths.DISCIPLINE_SNAPSHOT_FILE)
    change_feed, _ = snapshot_loader.safe_read_json(qpaths.CHANGE_FEED_FILE)
    ok, text, meta = llm_explainer.explain_satellite_candidate(
        candidate_row=row,
        notification_config=_llm_config(),
        discipline_snapshot=discipline,
        change_feed=change_feed,
    )
    return {"ok": ok, "text": text, "meta": meta, "symbol": str(symbol).upper()}


def explain_risk() -> dict:
    risk_response = snapshot_loader.load_risk_response()
    news_intelligence, _ = snapshot_loader.safe_read_json(qpaths.NEWS_INTELLIGENCE_FILE)
    ok, text, meta = llm_explainer.explain_portfolio_risk(
        risk_payload=dict(risk_response.get("payload", {}) or {}),
        news_intelligence=news_intelligence,
        notification_config=_llm_config(),
    )
    return {"ok": ok, "text": text, "meta": meta}


def explain_training_analysis() -> dict:
    snapshot, _ = snapshot_loader.safe_read_json(qpaths.MULTI_HORIZON_SNAPSHOT_FILE)
    validation, _ = snapshot_loader.safe_read_json(qpaths.MULTI_HORIZON_VALIDATION_FILE)
    governance, _ = snapshot_loader.safe_read_json(qpaths.MULTI_HORIZON_GOVERNANCE_FILE)
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    validation = validation if isinstance(validation, dict) else {}
    governance = governance if isinstance(governance, dict) else {}
    if "promotion_blockers" not in governance:
        governance["promotion_blockers"] = multi_horizon_governance.promotion_blockers(validation)
    payload = {
        "snapshot": {
            "status": snapshot.get("status"),
            "model": dict(snapshot.get("model", {}) or {}),
            "summary": dict(snapshot.get("summary", {}) or {}),
        },
        "validation": validation,
        "governance": governance,
        "promotion_blockers": list(governance.get("promotion_blockers", []) or []),
    }
    ok, text, meta = llm_explainer.explain_training_analysis(
        training_payload=payload,
        notification_config=_llm_config(),
    )
    return {"ok": ok, "text": text, "meta": meta}


def refresh_decision_brief_now() -> dict:
    config = _llm_config()
    context = decision_brief.build_current_decision_context()
    result = decision_brief.refresh_decision_brief(
        context=context,
        notification_config=config,
        trigger="MANUAL",
        force=True,
    )
    return {
        "message": "LLM decision brief refreshed",
        "decision_brief": result,
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


def save_core_etf_universe_settings(config: Mapping) -> dict:
    path = core_etf_rotation.save_core_etf_universe(dict(config or {}))
    return {
        "message": "core ETF universe saved; rerun nightly analysis to refresh model outputs",
        "path": path,
        "core_etf_universe": core_etf_rotation.load_core_etf_universe(path=path),
    }


def save_event_source_settings(config: Mapping) -> dict:
    path = event_fetcher.save_event_source_config(dict(config or {}))
    return {
        "message": "financial news source configuration saved",
        "path": path,
        "event_source_config": event_fetcher.load_event_source_config(path=path),
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
