import unittest
from datetime import datetime

import pandas as pd

from quant_core.research import correlation_research as cr


class CorrelationResearchTests(unittest.TestCase):
    def _history(self, closes):
        return pd.DataFrame({"Close": closes}, index=pd.date_range("2026-01-01", periods=len(closes), freq="D"))

    def test_builds_redundancy_and_independent_strength(self):
        histories = {
            "A": self._history([100, 101, 102, 103, 104, 105]),
            "B": self._history([50, 50.5, 51, 51.5, 52, 52.5]),
            "C": self._history([30, 29, 31, 28, 32, 27]),
            "SPY": self._history([100, 100.2, 100.3, 100.4, 100.5, 100.6]),
        }
        snapshot = cr.build_correlation_research_snapshot(
            symbols=["A", "B", "C"],
            holdings=[
                {"symbol": "A", "shares": 1, "current_price": 105},
                {"symbol": "B", "shares": 1, "current_price": 52.5},
            ],
            load_history_fn=lambda symbol, period="2y": histories[symbol],
            now=datetime(2026, 1, 8),
        )
        self.assertEqual(snapshot["status"], "READY")
        self.assertTrue(snapshot["high_correlation_pairs"])
        self.assertEqual(snapshot["high_correlation_pairs"][0]["left"], "A")
        self.assertIn("independent_strength", snapshot)
        self.assertIn("research_stages", snapshot)
        self.assertIn("correlation_clusters", snapshot)
        self.assertIn("simple_correlation_cluster_mining", snapshot["algorithms"])
        self.assertEqual(snapshot["summary"]["research_role"], "RISK_AND_OPPORTUNITY_CLUES")


if __name__ == "__main__":
    unittest.main()
