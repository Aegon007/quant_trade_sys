import unittest
from datetime import datetime
import json
import tempfile
from pathlib import Path


class SystemSnapshotTests(unittest.TestCase):
    def test_build_account_snapshot_derives_total_from_cash_and_holdings(self):
        from quant_core.snapshots.system_snapshot import build_account_snapshot

        snapshot = build_account_snapshot(
            {
                "account": {
                    "cash_available": 2500.0,
                    "min_cash_buffer_pct": 0.10,
                    "max_single_position_pct": 0.20,
                    "max_total_exposure_pct": 0.90,
                },
                "holdings": [
                    {"symbol": "AAPL", "shares": 10.0, "cost": 100.0, "current_price": 120.0},
                    {"symbol": "MSFT", "shares": 5.0, "cost": 200.0, "current_price": 220.0},
                ],
                "watchlist": [],
            }
        )

        self.assertAlmostEqual(snapshot["holdings_market_value"], 2300.0)
        self.assertAlmostEqual(snapshot["total_capital"], 4800.0)
        self.assertAlmostEqual(snapshot["cash_available"], 2500.0)
        self.assertAlmostEqual(snapshot["deployable_cash"], 2020.0)
        self.assertAlmostEqual(snapshot["exposure_pct"], 2300.0 / 4800.0 * 100.0)

    def test_build_account_snapshot_uses_dynamic_total_even_when_legacy_total_exists(self):
        from quant_core.snapshots.system_snapshot import build_account_snapshot

        snapshot = build_account_snapshot(
            {
                "account": {
                    "total_capital": 10000.0,
                    "cash_available": 2500.0,
                    "min_cash_buffer_pct": 0.10,
                },
                "holdings": [
                    {"symbol": "AAPL", "shares": 10.0, "cost": 100.0, "current_price": 120.0},
                ],
            }
        )

        self.assertAlmostEqual(snapshot["holdings_market_value"], 1200.0)
        self.assertAlmostEqual(snapshot["total_capital"], 3700.0)
        self.assertAlmostEqual(snapshot["cash_buffer_dollars"], 370.0)
        self.assertAlmostEqual(snapshot["deployable_cash"], 2130.0)

    def test_build_system_snapshot_returns_stable_sections(self):
        from quant_core.snapshots.system_snapshot import build_system_snapshot

        now = datetime(2026, 5, 9, 12, 0, 0)
        snapshot = build_system_snapshot(
            data={
                "account": {
                    "total_capital": 10000.0,
                    "cash_available": 2500.0,
                    "min_cash_buffer_pct": 0.10,
                    "max_single_position_pct": 0.20,
                    "max_total_exposure_pct": 0.90,
                },
                "holdings": [{"symbol": "AAPL", "shares": 10.0, "cost": 100.0, "current_price": 120.0}],
                "watchlist": [{"symbol": "MSFT", "notes": "watch", "last_price": 310.0}],
            },
            holding_records=[{"代码": "AAPL", "信号": "BUY"}],
            watchlist_records=[{"代码": "MSFT", "提示": "可以买入"}],
            risk_gate={"regime": "CAUTION", "risk_score": 3},
            alerts=[{"title": "AAPL 强烈买入"}],
            generated_at=now,
        )

        self.assertEqual(snapshot["generated_at"], now.isoformat())
        self.assertIn("account", snapshot)
        self.assertIn("holdings", snapshot)
        self.assertIn("watchlist", snapshot)
        self.assertIn("risk", snapshot)
        self.assertIn("alerts", snapshot)
        self.assertEqual(snapshot["risk"]["regime"], "CAUTION")
        self.assertEqual(snapshot["holdings"]["count"], 1)
        self.assertEqual(snapshot["watchlist"]["count"], 1)
        self.assertEqual(snapshot["holdings"]["records"][0]["代码"], "AAPL")
        self.assertEqual(snapshot["watchlist"]["records"][0]["代码"], "MSFT")
        self.assertEqual(snapshot["alerts"][0]["title"], "AAPL 强烈买入")

    def test_append_snapshot_journal_writes_jsonl(self):
        from quant_core.snapshots.system_snapshot import append_snapshot_journal

        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "nightly.jsonl"
            snapshot = {"generated_at": "2026-05-10T00:00:00", "alerts": []}
            append_snapshot_journal(snapshot, journal_path=str(journal_path))

            lines = journal_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["generated_at"], "2026-05-10T00:00:00")


if __name__ == "__main__":
    unittest.main()
