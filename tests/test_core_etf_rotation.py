import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from tests.support import clear_modules, reload_module


def _history_from_prices(prices):
    index = pd.date_range("2025-01-01", periods=len(prices), freq="B")
    return pd.DataFrame({"Close": prices}, index=index)


class CoreEtfRotationTests(unittest.TestCase):
    def setUp(self):
        clear_modules("quant_core.analytics.core_etf_rotation")
        self.module = reload_module("quant_core.analytics.core_etf_rotation")

    def test_load_missing_universe_returns_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self.module.load_core_etf_universe(str(Path(temp_dir) / "missing.json"))

        symbols = [row["symbol"] for row in config["etfs"]]
        self.assertIn("VOO", symbols)
        self.assertIn("QQQ", symbols)

    def test_build_core_etf_rotation_snapshot_scores_symbols_and_backtest(self):
        histories = {
            "VOO": _history_from_prices([100 + idx for idx in range(260)]),
            "QQQ": _history_from_prices([100 + (idx * 1.8) for idx in range(260)]),
            "SGOV": _history_from_prices([100 + (idx * 0.05) for idx in range(260)]),
        }

        def load_history(symbol, period="2y"):
            return histories[symbol].copy()

        snapshot = self.module.build_core_etf_rotation_snapshot(
            data={"holdings": [], "watchlist": []},
            history_period="2y",
            load_historical_data_fn=load_history,
            universe={
                "etfs": [
                    {"symbol": "VOO", "enabled": True, "role": "broad_market", "priority": 1, "long_term_core": True},
                    {"symbol": "QQQ", "enabled": True, "role": "growth", "priority": 2, "long_term_core": True},
                    {"symbol": "SGOV", "enabled": True, "role": "cash_substitute", "priority": 3, "long_term_core": True},
                ]
            },
            now=datetime(2026, 5, 13, 22, 0, 0),
        )

        self.assertEqual(snapshot["generated_at"], "2026-05-13T22:00:00")
        self.assertEqual(snapshot["summary"]["enabled_count"], 3)
        self.assertTrue(snapshot["summary"]["top_symbol"] in {"QQQ", "VOO"})
        first_row = snapshot["symbols"][0]
        self.assertIn("rotation_score", first_row)
        self.assertIn("rotation_backtest", first_row)
        self.assertIn("strategy_total_return", first_row["rotation_backtest"])
        self.assertIn("expected_return_12m", first_row)


if __name__ == "__main__":
    unittest.main()
