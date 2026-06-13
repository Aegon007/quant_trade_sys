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
            "/api/portfolio",
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

    def test_robinhood_import_followup_updates_review_and_plan_quality(self):
        review_saved = []
        quality_saved = []
        original_load_transactions = self.actions.transactions.load_transactions
        original_load_plan = self.actions.nightly_planner.load_next_day_trade_plan
        original_save_review = self.actions.post_close_review.save_post_close_review
        original_save_quality = self.actions.plan_quality.save_plan_quality_snapshot
        self.addCleanup(setattr, self.actions.transactions, "load_transactions", original_load_transactions)
        self.addCleanup(setattr, self.actions.nightly_planner, "load_next_day_trade_plan", original_load_plan)
        self.addCleanup(setattr, self.actions.post_close_review, "save_post_close_review", original_save_review)
        self.addCleanup(setattr, self.actions.plan_quality, "save_plan_quality_snapshot", original_save_quality)
        self.actions.transactions.load_transactions = lambda: [
            {
                "record_type": "TRADE",
                "event_type": "BUY",
                "side": "BUY",
                "date": "2026-06-10 09:30",
                "symbol": "AAPL",
                "shares": 1.0,
                "price": 100.0,
            }
        ]
        self.actions.nightly_planner.load_next_day_trade_plan = lambda: {
            "plan_date": "2026-06-10",
            "decision_signature": "abc",
            "items": [
                {
                    "symbol": "AAPL",
                    "plan_action": "PROBE",
                    "buy_zone_low": 95.0,
                    "buy_zone_high": 105.0,
                }
            ],
        }
        self.actions.post_close_review.save_post_close_review = lambda review: review_saved.append(review) or "review.json"
        self.actions.plan_quality.save_plan_quality_snapshot = lambda quality: quality_saved.append(quality) or "quality.json"

        followup = self.actions.build_robinhood_import_followup(
            {
                "records": [
                    {
                        "record_type": "TRADE",
                        "event_type": "BUY",
                        "side": "BUY",
                        "date": "2026-06-10 09:30",
                        "symbol": "AAPL",
                        "shares": 1.0,
                        "price": 100.0,
                    }
                ]
            }
        )

        self.assertTrue(followup["post_close_review_updated"])
        self.assertTrue(followup["plan_quality_updated"])
        self.assertEqual(followup["review_day"], "2026-06-10")
        self.assertEqual(review_saved[0]["executed_count"], 1)
        self.assertEqual(quality_saved[0]["summary"]["executed_count"], 1)


if __name__ == "__main__":
    unittest.main()
