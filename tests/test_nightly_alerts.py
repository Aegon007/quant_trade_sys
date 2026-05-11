import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

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
            result = self.module.run_nightly_alerts(
                now=datetime(2026, 5, 10, 23, 30, 0),
                dry_run=False,
                snapshot_journal_path=str(journal_path),
                report_output_dir=str(report_dir),
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
            self.assertEqual(payload["data_sources"]["history"]["last_source"], "stooq")
            self.assertEqual(len(result["report_results"]), 1)
            self.assertEqual(result["report_results"][0]["channel"], "slack")
            self.assertEqual(sent_reports[0][1], "https://hooks.slack.com/services/test")
            self.assertTrue(Path(result["report_files"]["markdown_path"]).exists())
            self.assertTrue(Path(result["report_files"]["json_path"]).exists())


if __name__ == "__main__":
    unittest.main()
