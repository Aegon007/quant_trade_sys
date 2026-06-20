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

    def test_training_progress_updates_job_registry_and_console_logger(self):
        updates = []
        messages = []
        self.actions.job_registry.update_job_status = (
            lambda name, **kwargs: updates.append((name, kwargs)) or {}
        )

        callback = self.actions.build_job_progress_callback(
            "manual-multi-horizon-training",
            logger=messages.append,
        )
        callback(
            {
                "stage": "supervised_training",
                "detail": "Epoch 3/30",
                "progress_pct": 72,
                "epoch": 3,
                "epochs": 30,
                "loss": 0.1234,
                "device": "mps",
            }
        )

        self.assertEqual(updates[0][0], "manual-multi-horizon-training")
        self.assertEqual(updates[0][1]["state"], "running")
        self.assertEqual(updates[0][1]["metadata"]["progress_pct"], 72)
        self.assertIn("Epoch 3/30", messages[0])

    def test_training_progress_marks_terminal_event_completed(self):
        updates = []
        self.actions.job_registry.update_job_status = (
            lambda name, **kwargs: updates.append((name, kwargs)) or {}
        )
        callback = self.actions.build_job_progress_callback("training")

        callback({"stage": "completed", "detail": "Training complete", "progress_pct": 100})

        self.assertEqual(updates[0][1]["state"], "completed")

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
            "/api/research-models",
            "/api/multi-horizon",
            "/api/reports/latest",
            "/api/actions/refresh-market",
            "/api/actions/import-robinhood-csv",
            "/api/actions/save-account-calibration",
            "/api/actions/run-nightly-once",
            "/api/actions/run-weekend-research-once",
            "/api/actions/train-multi-horizon",
            "/api/actions/promote-multi-horizon",
            "/api/actions/save-multi-horizon-config",
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

    def test_import_robinhood_csv_text_can_replace_existing_ledger(self):
        calls = []
        original_replace = self.actions.transactions.replace_with_robinhood_activity_csv
        original_import = self.actions.transactions.import_robinhood_activity_csv
        original_reconcile = self.actions.portfolio_actions.reconcile_portfolio_from_robinhood_imports
        original_followup = self.actions.build_robinhood_import_followup
        self.addCleanup(setattr, self.actions.transactions, "replace_with_robinhood_activity_csv", original_replace)
        self.addCleanup(setattr, self.actions.transactions, "import_robinhood_activity_csv", original_import)
        self.addCleanup(setattr, self.actions.portfolio_actions, "reconcile_portfolio_from_robinhood_imports", original_reconcile)
        self.addCleanup(setattr, self.actions, "build_robinhood_import_followup", original_followup)

        def fake_replace(csv_text, *, filename="", backup=True):
            calls.append(("replace", csv_text, filename, backup))
            return {"mode": "replace", "records": [{"date": "2026-06-10", "symbol": "AAPL"}]}

        def fake_import(csv_text, *, filename=""):
            calls.append(("append", csv_text, filename))
            return {"mode": "append", "records": []}

        self.actions.transactions.replace_with_robinhood_activity_csv = fake_replace
        self.actions.transactions.import_robinhood_activity_csv = fake_import
        self.actions.portfolio_actions.reconcile_portfolio_from_robinhood_imports = lambda **kwargs: {"holdings": []}
        self.actions.build_robinhood_import_followup = lambda imported: {"message": "updated"}

        result = self.actions.import_robinhood_csv_text("csv", filename="activity.csv", replace_existing=True)

        self.assertEqual(result["mode"], "replace")
        self.assertEqual(result["import"]["mode"], "replace")
        self.assertEqual(calls, [("replace", "csv", "activity.csv", True)])

    def test_save_account_calibration_can_infer_cash_from_broker_total(self):
        saved = []
        original_load_data = self.actions.data_storage.load_data
        original_save_data = self.actions.data_storage.save_data
        self.addCleanup(setattr, self.actions.data_storage, "load_data", original_load_data)
        self.addCleanup(setattr, self.actions.data_storage, "save_data", original_save_data)
        self.actions.data_storage.load_data = lambda: {
            "account": {
                "cash_available": 100.0,
                "min_cash_buffer_pct": 0.05,
                "max_single_position_pct": 0.2,
                "max_total_exposure_pct": 1.0,
            },
            "holdings": [
                {"symbol": "AAPL", "shares": 2.0, "cost": 150.0, "current_price": 200.0},
            ],
            "watchlist": [],
        }
        self.actions.data_storage.save_data = lambda data: saved.append(data)

        result = self.actions.save_account_calibration({"broker_total_capital": 1000.0})

        self.assertTrue(result["inferred_cash_from_broker_total"])
        self.assertEqual(saved[0]["account"]["cash_available"], 600.0)
        self.assertIsNone(saved[0]["account"]["total_capital"])
        self.assertEqual(result["account"]["total_capital"], 1000.0)


if __name__ == "__main__":
    unittest.main()
