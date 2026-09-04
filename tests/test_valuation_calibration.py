import unittest

import pandas as pd
from pathlib import Path
from tempfile import TemporaryDirectory

from quant_core.research.calibration import calibrate_recommendations, record_recommendations


class ValuationCalibrationTests(unittest.TestCase):
    def test_calibration_scores_matured_recommendation_against_risk_free_and_market(self):
        index = pd.date_range("2025-01-01", periods=300, freq="B")
        security = pd.DataFrame({"Close": [100 + index * 0.2 for index in range(300)]}, index=index)
        market = pd.DataFrame({"Close": [100 + index * 0.1 for index in range(300)]}, index=index)
        risk_free = pd.DataFrame({"Close": [100 + index * 0.02 for index in range(300)]}, index=index)
        journal = [{"generated_at": "2025-01-02T20:00:00", "symbol": "ACME", "recommendation": "ACCUMULATE", "current_price": 100.2, "margin_of_safety": 0.25}]

        result = calibrate_recommendations(
            journal,
            history_loader=lambda symbol, period="5y": {"ACME": security, "SPY": market, "SGOV": risk_free}[symbol],
            horizons=(63, 126, 252),
        )

        self.assertGreaterEqual(result["summary"]["matured_observation_count"], 3)
        self.assertEqual(result["benchmarks"], {"market": "SPY", "risk_free": "SGOV"})
        self.assertGreater(result["horizons"]["63"]["median_excess_over_market"], 0)
        self.assertGreater(result["horizons"]["63"]["median_excess_over_risk_free"], 0)
        self.assertGreater(result["observations"][0]["excess_over_risk_free"], result["observations"][0]["excess_over_market"])

    def test_journal_keeps_one_observation_per_symbol_and_day(self):
        with TemporaryDirectory() as temp:
            path = str(Path(temp) / "journal.jsonl")
            record_recommendations({"generated_at": "2026-07-01T20:00:00", "recommendations": [{"symbol": "MSFT", "recommendation": "WATCH"}]}, path=path)
            record_recommendations({"generated_at": "2026-07-01T23:00:00", "recommendations": [{"symbol": "MSFT", "recommendation": "ACCUMULATE"}]}, path=path)
            rows = [line for line in Path(path).read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual(len(rows), 1)
        self.assertIn("ACCUMULATE", rows[0])


if __name__ == "__main__":
    unittest.main()
