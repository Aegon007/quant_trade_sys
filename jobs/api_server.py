"""Local FastAPI server for the V3 frontend.

The server is intentionally read-mostly. Endpoints return normalized snapshot
DTOs and never run heavy quant computation inside HTTP requests.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from quant_core.api import actions as api_actions
from quant_core.api import snapshot_loader as loader


API_TITLE = "Quant Trade System Local API"
API_VERSION = "0.1.0"


def _missing_fastapi_error() -> RuntimeError:
    return RuntimeError(
        "FastAPI/Uvicorn is not installed. Install requirements.txt in ~/venv, "
        "then run: ~/venv/bin/python -m jobs.api_server"
    )


def _require_fastapi():
    try:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
    except ModuleNotFoundError as exc:
        raise _missing_fastapi_error() from exc
    return FastAPI, CORSMiddleware


def create_app():
    FastAPI, CORSMiddleware = _require_fastapi()
    app = FastAPI(title=API_TITLE, version=API_VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "api_version": API_VERSION,
            "generated_at": loader.now_iso(),
        }

    @app.get("/api/dashboard")
    def dashboard():
        return loader.load_dashboard_response()

    @app.get("/api/portfolio")
    def portfolio():
        return loader.load_portfolio_response()

    @app.get("/api/core-etfs")
    def core_etfs():
        return loader.load_snapshot_response("core-etfs", loader.SNAPSHOT_PATHS["core-etfs"])

    @app.get("/api/satellite-radar")
    def satellite_radar():
        return loader.load_snapshot_response("satellite-radar", loader.SNAPSHOT_PATHS["satellite-radar"])

    @app.get("/api/risk")
    def risk():
        return loader.load_snapshot_response("risk", loader.SNAPSHOT_PATHS["risk"])

    @app.get("/api/market-monitor")
    def market_monitor():
        return loader.load_snapshot_response("market-monitor", loader.SNAPSHOT_PATHS["market-monitor"])

    @app.get("/api/data-health")
    def data_health():
        return loader.load_snapshot_response("data-health", loader.SNAPSHOT_PATHS["data-health"])

    @app.get("/api/plan-quality")
    def plan_quality():
        return loader.load_snapshot_response("plan-quality", loader.SNAPSHOT_PATHS["plan-quality"])

    @app.get("/api/strategy-governance")
    def strategy_governance():
        return loader.load_snapshot_response("strategy-governance", loader.SNAPSHOT_PATHS["strategy-governance"])

    @app.get("/api/strategy-validation")
    def strategy_validation():
        return loader.load_snapshot_response("strategy-validation", loader.SNAPSHOT_PATHS["strategy-validation"])

    @app.get("/api/reports/latest")
    def latest_report():
        return loader.load_snapshot_response("reports-latest", loader.SNAPSHOT_PATHS["reports-latest"])

    @app.get("/api/change-feed")
    def change_feed():
        return loader.load_snapshot_response("change-feed", loader.SNAPSHOT_PATHS["change-feed"])

    @app.get("/api/job-status")
    def job_status():
        return loader.load_job_status_response()

    @app.get("/api/settings")
    def settings():
        return loader.load_settings_response()

    @app.post("/api/actions/refresh-market")
    def refresh_market(payload: dict | None = None):
        payload = dict(payload or {})
        force_source_refresh = bool(payload.get("force_source_refresh", True))
        return api_actions.run_with_job_status(
            "manual-market-refresh",
            lambda: api_actions.refresh_market_data_now(force_source_refresh=force_source_refresh),
            run_async=False,
        )

    @app.post("/api/actions/run-nightly-once")
    def run_nightly_once():
        return api_actions.run_with_job_status(
            "manual-nightly-run",
            api_actions.run_nightly_once,
            run_async=True,
        )

    @app.post("/api/actions/run-weekend-research-once")
    def run_weekend_research_once():
        return api_actions.run_with_job_status(
            "manual-weekend-research",
            api_actions.run_weekend_research_once,
            run_async=True,
        )

    @app.post("/api/actions/import-robinhood-csv")
    def import_robinhood_csv(payload: dict):
        payload = dict(payload or {})
        csv_text = str(payload.get("csv_text") or "")
        filename = str(payload.get("filename") or "")
        replace_existing = bool(payload.get("replace_existing", False))
        return api_actions.run_with_job_status(
            "manual-robinhood-import",
            lambda: api_actions.import_robinhood_csv_text(
                csv_text,
                filename=filename,
                replace_existing=replace_existing,
            ),
            run_async=False,
        )

    @app.post("/api/actions/save-runtime-schedule")
    def save_runtime_schedule(payload: dict):
        return api_actions.run_with_job_status(
            "settings-runtime-schedule",
            lambda: api_actions.save_runtime_schedule(dict(payload or {})),
            run_async=False,
        )

    @app.post("/api/actions/save-notification-config")
    def save_notification_config(payload: dict):
        return api_actions.run_with_job_status(
            "settings-notification-config",
            lambda: api_actions.save_notification_settings(dict(payload or {})),
            run_async=False,
        )

    return app


app = None


def get_app():
    global app
    if app is None:
        app = create_app()
    return app


def run_server(*, host: str = "127.0.0.1", port: int = 8710, app_factory: Callable = get_app):
    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        raise _missing_fastapi_error() from exc
    uvicorn.run(app_factory(), host=host, port=int(port), log_level="info")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Start the local Quant Trade FastAPI server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8710)
    args = parser.parse_args(argv)
    try:
        run_server(host=args.host, port=args.port)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
