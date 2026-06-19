import json
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from tests.support import clear_modules, reload_module


class ApiSnapshotLoaderTests(unittest.TestCase):
    def setUp(self):
        clear_modules("quant_core.api.snapshot_loader", "quant_core.jobs.job_registry")
        self.loader = reload_module("quant_core.api.snapshot_loader")
        self.registry = reload_module("quant_core.jobs.job_registry")

    def test_load_snapshot_response_marks_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "missing.json"

            response = self.loader.load_snapshot_response("core-etfs", str(missing_path))

        self.assertEqual(response["freshness_status"], "MISSING")
        self.assertTrue(response["is_stale"])
        self.assertTrue(response["errors"])
        self.assertEqual(response["payload"], {})

    def test_load_snapshot_response_extracts_summary_and_items(self):
        now = datetime.fromisoformat("2026-06-11T12:00:00")
        generated_at = (now - timedelta(minutes=10)).isoformat()
        payload = {
            "generated_at": generated_at,
            "summary": {"risk_regime": "NORMAL"},
            "symbols": [{"symbol": "VOO", "action": "HOLD"}],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "snapshot.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            response = self.loader.load_snapshot_response("core-etfs", str(path), now=now)

        self.assertEqual(response["freshness_status"], "OK")
        self.assertFalse(response["is_stale"])
        self.assertEqual(response["summary"], {"risk_regime": "NORMAL"})
        self.assertEqual(response["items"], [{"symbol": "VOO", "action": "HOLD"}])

    def test_load_runtime_schedule_merges_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "runtime_schedule.json"
            path.write_text(
                json.dumps({"trading_hours": {"market_monitor_interval_seconds": 900}}),
                encoding="utf-8",
            )

            schedule = self.loader.load_runtime_schedule(path=str(path))

        self.assertEqual(schedule["trading_hours"]["market_monitor_interval_seconds"], 900)
        self.assertEqual(schedule["trading_hours"]["tactical_watchlist_interval_seconds"], 600)
        self.assertIn("nightly", schedule)

    def test_normalize_runtime_schedule_clamps_invalid_intervals(self):
        schedule = self.loader.normalize_runtime_schedule(
            {
                "trading_hours": {
                    "market_monitor_interval_seconds": 0,
                    "data_health_interval_seconds": -1,
                },
                "nightly": {"poll_seconds": "bad"},
            }
        )

        self.assertEqual(schedule["trading_hours"]["market_monitor_interval_seconds"], 60)
        self.assertEqual(schedule["trading_hours"]["data_health_interval_seconds"], 300)
        self.assertEqual(schedule["nightly"]["poll_seconds"], 300)

    def test_sanitize_notification_config_fills_default_alert_settings(self):
        sanitized = self.loader._sanitize_notification_config(
            {
                "slack": {"enabled": True, "webhook_url": ""},
                "alert_settings": {"send_hourly_market_summary": True},
            }
        )

        self.assertTrue(sanitized["alert_settings"]["send_hourly_market_summary"])
        self.assertTrue(sanitized["alert_settings"]["send_premarket_brief"])
        self.assertTrue(sanitized["alert_settings"]["enable_weekend_research"])
        self.assertEqual(sanitized["alert_settings"]["weekend_research_day_local"], "saturday")
        self.assertEqual(sanitized["alert_settings"]["weekend_research_hour_local"], 10)

    def test_job_registry_updates_status_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "job_status.json"

            payload = self.registry.update_job_status(
                "api-server",
                state="started",
                detail="python -m jobs.api_server",
                pid=1234,
                metadata={"stage": "startup", "progress_pct": 25},
                path=str(path),
                now=datetime.fromisoformat("2026-06-11T12:00:00"),
            )
            loaded = self.registry.load_job_status(path=str(path))

        self.assertEqual(payload["jobs"]["api-server"]["state"], "started")
        self.assertEqual(loaded["jobs"]["api-server"]["pid"], 1234)
        self.assertEqual(loaded["jobs"]["api-server"]["stage"], "startup")
        self.assertEqual(loaded["jobs"]["api-server"]["progress_pct"], 25)

    def test_load_portfolio_response_includes_holdings_transactions_and_reviews(self):
        original_load_portfolio_payload = self.loader._load_portfolio_payload
        original_load_transactions = self.loader.tx.load_transactions
        original_load_review = self.loader.pcr.load_post_close_review
        original_load_quality = self.loader.pq.load_plan_quality_snapshot
        original_safe_read_json = self.loader.safe_read_json
        self.addCleanup(setattr, self.loader, "_load_portfolio_payload", original_load_portfolio_payload)
        self.addCleanup(setattr, self.loader.tx, "load_transactions", original_load_transactions)
        self.addCleanup(setattr, self.loader.pcr, "load_post_close_review", original_load_review)
        self.addCleanup(setattr, self.loader.pq, "load_plan_quality_snapshot", original_load_quality)
        self.addCleanup(setattr, self.loader, "safe_read_json", original_safe_read_json)
        self.loader._load_portfolio_payload = lambda: {
            "account": {"cash_available": 1000.0},
            "holdings": [{"symbol": "AAPL", "shares": 1.5, "cost": 100.0, "current_price": 110.0}],
            "watchlist": [{"symbol": "MSFT", "last_price": 300.0}],
        }
        self.loader.tx.load_transactions = lambda: [
            {
                "record_type": "TRADE",
                "event_type": "BUY",
                "side": "BUY",
                "date": "2026-06-10 09:30",
                "symbol": "AAPL",
                "shares": 1.5,
                "price": 100.0,
            }
        ]
        self.loader.pcr.load_post_close_review = lambda: {"status": "NO_PLAN", "unplanned_trade_count": 1}
        self.loader.pq.load_plan_quality_snapshot = lambda: {"status": "DEGRADED", "summary": {"status": "DEGRADED"}}
        self.loader.safe_read_json = lambda path: ({"generated_at": "2026-06-10T20:00:00", "summary": {"buy_count": 1}}, [])

        response = self.loader.load_portfolio_response(now=datetime.fromisoformat("2026-06-11T12:00:00"))

        self.assertEqual(response["name"], "portfolio")
        self.assertEqual(response["summary"]["holding_count"], 1)
        self.assertEqual(response["summary"]["transaction_count"], 1)
        self.assertEqual(response["summary"]["post_close_review_status"], "NO_PLAN")
        self.assertEqual(response["summary"]["plan_quality_status"], "DEGRADED")
        self.assertEqual(response["payload"]["holdings"][0]["symbol"], "AAPL")
        self.assertEqual(response["payload"]["recent_transactions"][0]["symbol"], "AAPL")

    def test_multi_horizon_snapshot_enriches_portfolio_rows(self):
        snapshot = {
            "generated_at": "2026-06-18T20:00:00",
            "status": "READY",
            "symbols": [
                {
                    "symbol": "MSFT",
                    "long_horizon": {"state": "ATTRACTIVE", "blended_rank": 0.84},
                    "timing": {"state": "DETERIORATING"},
                    "decision": {
                        "action": "HOLD",
                        "target_weight_range_pct": [4.0, 7.0],
                        "reason_codes": ["LONG_TERM_ATTRACTIVE", "WAIT_TO_ADD"],
                    },
                }
            ],
        }

        rows = self.loader.enrich_rows_with_multi_horizon(
            [{"symbol": "MSFT", "shares": 0.05}],
            snapshot,
        )

        self.assertEqual(rows[0]["model_decision"]["action"], "HOLD")
        self.assertEqual(rows[0]["long_horizon_state"], "ATTRACTIVE")
        self.assertEqual(rows[0]["timing_state"], "DETERIORATING")
        self.assertEqual(rows[0]["model_generated_at"], "2026-06-18T20:00:00")


if __name__ == "__main__":
    unittest.main()
