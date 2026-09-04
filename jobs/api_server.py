"""FastAPI server for the valuation-dislocation research UI."""

from __future__ import annotations

import argparse
import io
from typing import Callable

from quant_core.api import actions, snapshot_loader
from quant_core.diagnostics import build_diagnostics_bundle


API_TITLE = "估值与超跌机会研究系统"
API_VERSION = "1.0.0"


def _require_fastapi():
    try:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
    except ModuleNotFoundError as exc:
        raise RuntimeError("请在 ~/venv 中安装 requirements.txt 后再启动API") from exc
    return FastAPI, CORSMiddleware


def create_app():
    FastAPI, CORSMiddleware = _require_fastapi()
    app = FastAPI(title=API_TITLE, version=API_VERSION)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.get("/api/health")
    def health():
        return {"status": "ok", "api_version": API_VERSION, "generated_at": snapshot_loader.now_iso()}

    @app.get("/api/dashboard")
    def dashboard():
        return snapshot_loader.load_dashboard_response()

    @app.get("/api/opportunities")
    def opportunities():
        return snapshot_loader.load_opportunities_response()

    @app.get("/api/valuations")
    def valuations(symbol: str = ""):
        return snapshot_loader.load_valuations_response(symbol)

    @app.get("/api/market-risk")
    def market_risk():
        return snapshot_loader.load_market_risk_response()

    @app.get("/api/watchlist")
    def watchlist():
        return snapshot_loader.load_watchlist_response()

    @app.get("/api/data-health")
    def data_health():
        return snapshot_loader.load_snapshot_response("data-health", snapshot_loader.qpaths.DATA_HEALTH_SNAPSHOT_FILE)

    @app.get("/api/change-feed")
    def change_feed():
        return snapshot_loader.load_snapshot_response("change-feed", snapshot_loader.qpaths.CHANGE_FEED_FILE)

    @app.get("/api/calibration")
    def calibration():
        return snapshot_loader.load_snapshot_response("calibration", snapshot_loader.qpaths.VALUATION_CALIBRATION_FILE, max_age_seconds=8 * 86400)

    @app.get("/api/job-status")
    def job_status():
        return snapshot_loader.load_job_status_response()

    @app.get("/api/research-manifest")
    def research_manifest():
        return snapshot_loader.load_snapshot_response(
            "research-manifest",
            snapshot_loader.qpaths.RESEARCH_MANIFEST_FILE,
            max_age_seconds=8 * 86400,
        )

    @app.get("/api/settings")
    def settings():
        return snapshot_loader.load_settings_response()

    @app.get("/api/reports/latest")
    def report():
        return snapshot_loader.load_snapshot_response("latest-report", snapshot_loader.qpaths.VALUATION_REPORT_LATEST_JSON)

    @app.get("/api/downloads/diagnostics-bundle")
    def diagnostics():
        from fastapi.responses import StreamingResponse
        return StreamingResponse(io.BytesIO(build_diagnostics_bundle()), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="valuation-diagnostics.zip"'})

    @app.post("/api/actions/refresh-market")
    def refresh_market(payload: dict | None = None):
        payload = dict(payload or {})
        return actions.run_with_job_status("manual-market-refresh", lambda: actions.refresh_market_data_now(force_source_refresh=bool(payload.get("force_source_refresh", True))), run_async=True)

    @app.post("/api/actions/run-nightly-once")
    def nightly():
        return actions.run_with_job_status("manual-nightly-run", actions.run_nightly_once, run_async=True)

    @app.post("/api/actions/run-weekend-research-once")
    def weekend():
        return actions.run_with_job_status("manual-weekend-research", actions.run_weekend_research_once, run_async=True)

    @app.post("/api/actions/test-llm")
    def test_llm(payload: dict):
        submitted = dict(payload or {})
        return actions.run_with_job_status("settings-llm-test", lambda: actions.test_llm_settings(route=str(submitted.get("route") or "llm"), submitted_config=submitted.get("config")), run_async=False)

    @app.post("/api/actions/test-notification")
    def test_notification(payload: dict):
        channel = str(dict(payload or {}).get("channel") or "")
        return actions.run_with_job_status(
            f"settings-{channel}-test",
            lambda: actions.test_notification_channel(channel, submitted_config=dict(payload or {}).get("config")),
            run_async=False,
        )

    @app.post("/api/actions/explain-security")
    def explain_security(payload: dict):
        return actions.explain_security(str(dict(payload or {}).get("symbol") or ""))

    @app.post("/api/actions/watchlist")
    def watchlist_action(payload: dict):
        return actions.update_watchlist(str(dict(payload or {}).get("symbol") or ""), remove=bool(dict(payload or {}).get("remove")))

    @app.post("/api/settings/notifications")
    def save_notifications(payload: dict):
        return actions.save_notification_settings(payload)

    @app.post("/api/settings/runtime-schedule")
    def save_schedule(payload: dict):
        return actions.save_runtime_schedule(payload)

    @app.post("/api/settings/research-universe")
    def save_universe(payload: dict):
        return actions.save_research_universe(payload)

    @app.post("/api/settings/valuation-policy")
    def save_policy(payload: dict):
        return actions.save_valuation_settings(payload)

    return app


_APP = None


def get_app():
    global _APP
    if _APP is None:
        _APP = create_app()
    return _APP


def run_server(*, host="127.0.0.1", port=8710, app_factory: Callable = get_app):
    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        raise RuntimeError("uvicorn is not installed") from exc
    uvicorn.run(app_factory(), host=host, port=int(port))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8710)
    args = parser.parse_args(argv)
    run_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
