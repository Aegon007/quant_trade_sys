import unittest
from datetime import datetime

from tests.support import clear_modules, reload_module


class ApiActionsTests(unittest.TestCase):
    def setUp(self):
        clear_modules("quant_core.api.actions")
        self.actions = reload_module("quant_core.api.actions")

    def test_run_with_job_status_records_inline_success(self):
        updates = []
        self.actions.job_registry.update_job_status = (
            lambda name, **kwargs: updates.append((name, kwargs["state"], kwargs["detail"])) or {}
        )

        result = self.actions.run_with_job_status(
            "manual-test",
            lambda: {"message": "finished cleanly"},
            run_async=False,
            now_func=lambda: datetime.fromisoformat("2026-06-11T12:00:00"),
        )

        self.assertTrue(result["accepted"])
        self.assertEqual(result["result"], {"message": "finished cleanly"})
        self.assertEqual(
            updates,
            [
                ("manual-test", "started", "manual trigger accepted"),
                ("manual-test", "completed", "finished cleanly"),
            ],
        )

    def test_run_with_job_status_records_inline_failure(self):
        updates = []
        self.actions.job_registry.update_job_status = (
            lambda name, **kwargs: updates.append((name, kwargs["state"], kwargs["detail"])) or {}
        )

        def boom():
            raise RuntimeError("boom")

        result = self.actions.run_with_job_status("manual-test", boom, run_async=False)

        self.assertFalse(result["accepted"])
        self.assertIn("RuntimeError: boom", result["error"])
        self.assertEqual(updates[0], ("manual-test", "started", "manual trigger accepted"))
        self.assertEqual(updates[1], ("manual-test", "failed", "RuntimeError: boom"))

    def test_api_server_exposes_daily_workflow_routes(self):
        server = reload_module("jobs.api_server")
        app = server.create_app()
        route_paths = {getattr(route, "path", "") for route in app.routes}

        for path in [
            "/api/dashboard",
            "/api/core-etfs",
            "/api/satellite-radar",
            "/api/risk",
            "/api/market-monitor",
            "/api/data-health",
            "/api/plan-quality",
            "/api/strategy-governance",
            "/api/reports/latest",
            "/api/actions/refresh-market",
            "/api/actions/import-robinhood-csv",
            "/api/actions/run-nightly-once",
            "/api/actions/run-weekend-research-once",
        ]:
            self.assertIn(path, route_paths)


if __name__ == "__main__":
    unittest.main()
