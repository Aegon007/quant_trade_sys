import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from tests.support import clear_modules, install_fake_yfinance, reload_module


class NightlyAlertsTests(unittest.TestCase):
    def setUp(self):
        install_fake_yfinance()
        clear_modules("jobs.nightly_alerts")
        self.module = reload_module("jobs.nightly_alerts")

    def test_run_nightly_alerts_writes_snapshot_journal(self):
        self.module.du.load_data = lambda: {"account": {}, "holdings": [], "watchlist": []}
        self.module.md.get_market_data_status_snapshot = lambda: {"history": {"last_source": "stooq"}, "prices": {}}
        self.module.ac.should_run_nightly_consensus_update = lambda now=None: False
        self.module.ac.load_analyst_consensus_cache = lambda: {}
        self.module.ae.collect_alerts = lambda **kwargs: []
        self.module.ae.alerts_to_dicts = lambda alerts: []
        self.module.ae.send_new_alerts = lambda *args, **kwargs: []
        self.module.qa.get_historical_data = lambda symbol, period="2y": pd.DataFrame()
        self.module.ncfg.load_notification_config = lambda _path: {
            "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/services/test"},
            "email": {"enabled": False},
            "alert_settings": {"send_daily_summary": True},
        }
        self.module.tx.load_transactions = lambda: [
            {"record_type": "TRADE", "event_type": "BUY", "side": "BUY", "date": "2026-05-08 09:30", "symbol": "AAPL", "shares": 1.0, "price": 100.0},
            {"record_type": "TRADE", "event_type": "SELL", "side": "SELL", "date": "2026-05-08 15:30", "symbol": "AAPL", "shares": 1.0, "price": 108.0, "pl": 8.0},
        ]
        self.module.tx.normalize_transactions = lambda rows: rows
        sent_reports = []

        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "nightly_snapshot_journal.jsonl"
            report_dir = Path(temp_dir) / "reports"
            manifest_path = Path(temp_dir) / "nightly_run_manifest.json"
            change_feed_path = Path(temp_dir) / "change_feed_latest.json"
            model_snapshot_path = Path(temp_dir) / "multi_horizon_snapshot.json"
            model_journal_path = Path(temp_dir) / "multi_horizon_predictions.jsonl"
            model_governance_path = Path(temp_dir) / "multi_horizon_governance.json"
            model_validation_path = Path(temp_dir) / "multi_horizon_validation.json"
            result = self.module.run_nightly_alerts(
                now=datetime(2026, 5, 8, 23, 30, 0),
                dry_run=False,
                snapshot_journal_path=str(journal_path),
                report_output_dir=str(report_dir),
                manifest_path=str(manifest_path),
                change_feed_path=str(change_feed_path),
                multi_horizon_snapshot_path=str(model_snapshot_path),
                model_prediction_journal_path=str(model_journal_path),
                model_governance_path=str(model_governance_path),
                model_validation_path=str(model_validation_path),
                multi_horizon_runner=lambda **kwargs: {
                    "status": "READY",
                    "generated_at": "2026-05-08T23:30:00",
                    "model": {"model_id": "finance_multi_asset_transformer", "status": "SHADOW"},
                    "summary": {"symbol_count": 0, "action_counts": {}, "conflict_count": 0},
                    "symbols": [],
                },
                slack_sender=lambda text, url: (sent_reports.append((text, url)) or True, "ok"),
            )

            self.assertEqual(result["snapshot_journal_path"], str(journal_path))
            self.assertTrue(journal_path.exists())
            lines = journal_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertIn("generated_at", payload)
            self.assertIn("account", payload)
            self.assertIn("data_sources", payload)
            self.assertIn("performance", payload)
            self.assertIn("allocation_regime", payload)
            self.assertIn("daily_recap", payload)
            self.assertIn("signal_attribution", payload)
            self.assertIn("trade_plan", payload)
            self.assertIn("execution_review", payload)
            self.assertIn("monthly_discipline_review", payload)
            self.assertIn("multi_horizon_snapshot", payload)
            self.assertIn("change_feed", payload)
            self.assertIn("nightly_manifest", payload)
            self.assertEqual(payload["data_sources"]["history"]["last_source"], "stooq")
            self.assertEqual(len(result["report_results"]), 2)
            self.assertEqual(result["report_results"][0]["channel"], "slack")
            self.assertEqual(len(result["premarket_brief_results"]), 2)
            self.assertEqual(sent_reports[0][1], "https://hooks.slack.com/services/test")
            self.assertIn("Discipline month:", sent_reports[0][0])
            self.assertIn("盘前简报", result["premarket_brief_text"])
            self.assertTrue(manifest_path.exists())
            self.assertTrue(change_feed_path.exists())
            self.assertTrue(Path(result["report_files"]["markdown_path"]).exists())
            self.assertTrue(Path(result["report_files"]["json_path"]).exists())
            self.assertEqual(result["multi_horizon_snapshot"]["status"], "READY")
            self.assertIn("execution_review", payload["nightly_manifest"]["steps"])
            self.assertIn("change_feed", payload["nightly_manifest"]["steps"])
            self.assertIn("snapshot_journal", payload["nightly_manifest"]["steps"])
            self.assertIn("report_files", payload["nightly_manifest"]["steps"])
            self.assertIn("notifications", payload["nightly_manifest"]["steps"])

    def test_run_nightly_alerts_applies_env_webhook_overrides_for_report_delivery(self):
        self.module.du.load_data = lambda: {"account": {}, "holdings": [], "watchlist": []}
        self.module.md.get_market_data_status_snapshot = lambda: {"history": {"last_source": "stooq"}, "prices": {}}
        self.module.ac.should_run_nightly_consensus_update = lambda now=None: False
        self.module.ac.load_analyst_consensus_cache = lambda: {}
        self.module.ae.collect_alerts = lambda **kwargs: []
        self.module.ae.alerts_to_dicts = lambda alerts: []
        self.module.ae.send_new_alerts = lambda *args, **kwargs: []
        self.module.qa.get_historical_data = lambda symbol, period="2y": pd.DataFrame()
        self.module.ncfg.load_notification_config = lambda _path: {
            "slack": {"enabled": False, "webhook_url": ""},
            "email": {"enabled": False},
            "alert_settings": {"send_daily_summary": True},
        }
        self.module.tx.load_transactions = lambda: []
        self.module.tx.normalize_transactions = lambda rows: rows
        sent_reports = []

        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.module.run_nightly_alerts(
                now=datetime(2026, 5, 8, 23, 30, 0),
                dry_run=False,
                report_output_dir=temp_dir,
                multi_horizon_snapshot_path=str(Path(temp_dir) / "multi_horizon_snapshot.json"),
                model_prediction_journal_path=str(Path(temp_dir) / "multi_horizon_predictions.jsonl"),
                model_governance_path=str(Path(temp_dir) / "multi_horizon_governance.json"),
                model_validation_path=str(Path(temp_dir) / "multi_horizon_validation.json"),
                multi_horizon_runner=lambda **kwargs: {
                    "status": "MODEL_NOT_READY",
                    "generated_at": "2026-05-08T23:30:00",
                    "model": {"model_id": "finance_multi_asset_transformer", "status": "RESEARCH"},
                    "summary": {"symbol_count": 0, "action_counts": {}, "conflict_count": 0},
                    "symbols": [],
                },
                environ={"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/from-env"},
                slack_sender=lambda text, url: (sent_reports.append((text, url)) or True, "ok"),
            )

            self.assertFalse(result["dry_run"])
            self.assertEqual(len(sent_reports), 2)
            self.assertIn("Nightly Portfolio Report", sent_reports[0][0])
            self.assertIn("Discipline month:", sent_reports[0][0])
            self.assertEqual(sent_reports[0][1], "https://hooks.slack.com/services/from-env")
            self.assertIn("盘前简报", sent_reports[1][0])
            self.assertEqual(sent_reports[1][1], "https://hooks.slack.com/services/from-env")

    def test_run_nightly_alerts_uses_multi_horizon_snapshot_for_trade_plan(self):
        self.module.du.load_data = lambda: {"account": {}, "holdings": [], "watchlist": []}
        self.module.md.get_market_data_status_snapshot = lambda: {"history": {"last_source": "stooq"}, "prices": {}}
        self.module.ac.should_run_nightly_consensus_update = lambda now=None: False
        self.module.ac.load_analyst_consensus_cache = lambda: {}
        self.module.ae.collect_alerts = lambda **kwargs: []
        self.module.ae.alerts_to_dicts = lambda alerts: []
        self.module.ae.send_new_alerts = lambda *args, **kwargs: []
        self.module.qa.get_historical_data = lambda symbol, period="2y": pd.DataFrame()
        self.module.ncfg.load_notification_config = lambda _path: {
            "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/services/test"},
            "email": {"enabled": False},
            "alert_settings": {"send_daily_summary": True},
        }
        self.module.tx.load_transactions = lambda: []
        self.module.tx.normalize_transactions = lambda rows: rows
        self.module.discipline.build_discipline_snapshot = lambda **kwargs: {
            "regime": "NORMAL",
            "can_open_new_core_positions": True,
            "can_open_new_satellite_positions": True,
        }

        sent_messages = []
        changed_snapshot = {
            "status": "READY",
            "generated_at": "2026-05-08T23:30:00",
            "model": {
                "model_id": "finance_multi_asset_transformer",
                "status": "SHADOW",
                "version": "validated-v1",
            },
            "summary": {"symbol_count": 1, "action_counts": {"ACCUMULATE": 1}, "conflict_count": 0},
            "symbols": [{
                "symbol": "AAPL",
                "list_type": "holding",
                "latest_price": 100.0,
                "current_weight_pct": 2.0,
                "long_horizon": {"state": "ATTRACTIVE"},
                "timing": {"state": "CONFIRMED"},
                "decision": {
                    "action": "ACCUMULATE",
                    "target_weight_range_pct": [4.0, 7.0],
                    "reason_codes": ["LONG_TERM_ATTRACTIVE", "TIMING_CONFIRMED"],
                },
            }],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "nightly_run_manifest.json"
            change_feed_path = Path(temp_dir) / "change_feed_latest.json"
            validation_path = Path(temp_dir) / "multi_horizon_validation.json"
            governance_path = Path(temp_dir) / "multi_horizon_governance.json"
            validation_path.write_text(
                json.dumps({"status": "PASS", "governance": {"moe_collapsed": False}}),
                encoding="utf-8",
            )
            governance_path.write_text(
                json.dumps(
                    {
                        "status": "PRODUCTION",
                        "production_authorized": True,
                        "approved_model_version": "validated-v1",
                    }
                ),
                encoding="utf-8",
            )
            result = self.module.run_nightly_alerts(
                now=datetime(2026, 5, 8, 23, 30, 0),
                dry_run=False,
                report_output_dir=temp_dir,
                manifest_path=str(manifest_path),
                change_feed_path=str(change_feed_path),
                multi_horizon_snapshot_path=str(Path(temp_dir) / "multi_horizon_snapshot.json"),
                model_prediction_journal_path=str(Path(temp_dir) / "multi_horizon_predictions.jsonl"),
                model_governance_path=str(governance_path),
                model_validation_path=str(validation_path),
                multi_horizon_runner=lambda **kwargs: changed_snapshot,
                slack_sender=lambda text, url: (sent_messages.append((text, url)) or True, "ok"),
            )

            self.assertFalse(result["dry_run"])
            self.assertEqual(result["trade_plan"]["items"][0]["symbol"], "AAPL")
            self.assertEqual(result["trade_plan"]["items"][0]["plan_action"], "ACCUMULATE")
            self.assertIn("AAPL", result["premarket_brief_text"])


if __name__ == "__main__":
    unittest.main()
