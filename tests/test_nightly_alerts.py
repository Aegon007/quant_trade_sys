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
        self.module.ncfg.load_notification_config = lambda _path: {"slack": {"enabled": False}, "email": {"enabled": False}}
        self.module.tx.load_transactions = lambda: []
        self.module.tx.normalize_transactions = lambda rows: rows

        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "nightly_snapshot_journal.jsonl"
            result = self.module.run_nightly_alerts(
                now=datetime(2026, 5, 10, 23, 30, 0),
                dry_run=False,
                snapshot_journal_path=str(journal_path),
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
            self.assertEqual(payload["data_sources"]["history"]["last_source"], "stooq")


if __name__ == "__main__":
    unittest.main()
