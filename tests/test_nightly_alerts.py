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
            {"record_type": "TRADE", "event_type": "BUY", "side": "BUY", "date": "2026-05-10 09:30", "symbol": "AAPL", "shares": 1.0, "price": 100.0},
            {"record_type": "TRADE", "event_type": "SELL", "side": "SELL", "date": "2026-05-10 15:30", "symbol": "AAPL", "shares": 1.0, "price": 108.0, "pl": 8.0},
        ]
        self.module.tx.normalize_transactions = lambda rows: rows
        sent_reports = []

        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "nightly_snapshot_journal.jsonl"
            report_dir = Path(temp_dir) / "reports"
            manifest_path = Path(temp_dir) / "nightly_run_manifest.json"
            change_feed_path = Path(temp_dir) / "change_feed_latest.json"
            result = self.module.run_nightly_alerts(
                now=datetime(2026, 5, 10, 23, 30, 0),
                dry_run=False,
                snapshot_journal_path=str(journal_path),
                report_output_dir=str(report_dir),
                manifest_path=str(manifest_path),
                change_feed_path=str(change_feed_path),
                quant_analysis_snapshot_builder=lambda **kwargs: {
                    "generated_at": "2026-05-10T23:30:00",
                    "strategy": {"id": "deep_tcn", "name": "TCN"},
                    "engine": {"name": "backtrader"},
                    "history_period": "2y",
                    "summary": {"total_symbols": 0, "analyzed_symbols": 0, "buy_count": 0, "sell_count": 0, "hold_count": 0, "error_count": 0, "top_buy_symbols": []},
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
            self.assertIn("quant_analysis_summary", payload["performance"])
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
            self.assertTrue(Path(result["quant_analysis_report_files"]["pdf_path"]).exists())
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
            "alert_settings": {
                "send_daily_summary": True,
                "send_quant_analysis_change_summary": False,
            },
        }
        self.module.tx.load_transactions = lambda: []
        self.module.tx.normalize_transactions = lambda rows: rows
        sent_reports = []

        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.module.run_nightly_alerts(
                now=datetime(2026, 5, 10, 23, 30, 0),
                dry_run=False,
                report_output_dir=temp_dir,
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

    def test_run_nightly_alerts_sends_quant_change_summary_only_when_snapshot_changes(self):
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
            "alert_settings": {
                "send_daily_summary": True,
                "send_quant_analysis_change_summary": True,
            },
        }
        self.module.tx.load_transactions = lambda: []
        self.module.tx.normalize_transactions = lambda rows: rows

        sent_messages = []
        changed_snapshot = {
            "generated_at": "2026-05-10T23:30:00",
            "strategy": {"id": "deep_tcn", "name": "TCN"},
            "engine": {"name": "backtrader"},
            "history_period": "2y",
            "summary": {"total_symbols": 1, "analyzed_symbols": 1, "buy_count": 1, "sell_count": 0, "hold_count": 0, "error_count": 0, "top_buy_symbols": ["AAPL"]},
            "symbols": [{"symbol": "AAPL", "signal": "BUY", "position_advice": {"action": "ADD"}}],
        }
        previous_snapshot = {
            "generated_at": "2026-05-09T23:30:00",
            "summary": {"top_buy_symbols": []},
            "symbols": [{"symbol": "AAPL", "signal": "HOLD", "position_advice": {"action": "HOLD"}}],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir) / "quant_analysis_snapshot.json"
            manifest_path = Path(temp_dir) / "nightly_run_manifest.json"
            change_feed_path = Path(temp_dir) / "change_feed_latest.json"
            snapshot_path.write_text(json.dumps(previous_snapshot), encoding="utf-8")
            result = self.module.run_nightly_alerts(
                now=datetime(2026, 5, 10, 23, 30, 0),
                dry_run=False,
                report_output_dir=temp_dir,
                quant_analysis_snapshot_path=str(snapshot_path),
                manifest_path=str(manifest_path),
                change_feed_path=str(change_feed_path),
                quant_analysis_snapshot_builder=lambda **kwargs: changed_snapshot,
                slack_sender=lambda text, url: (sent_messages.append((text, url)) or True, "ok"),
            )

            self.assertFalse(result["dry_run"])
            self.assertGreaterEqual(len(result["quant_analysis_change_results"]), 1)
            self.assertTrue(any(row["ok"] for row in result["quant_analysis_change_results"]))
            self.assertEqual(sent_messages[-1][1], "https://hooks.slack.com/services/test")
            self.assertIn("AAPL", sent_messages[-1][0])


if __name__ == "__main__":
    unittest.main()
