import unittest

import pandas as pd

from quant_core.etf.allocation import analyze_etf_allocation


def history(start=100.0, daily_step=0.12, count=300):
    values = [start + index * daily_step for index in range(count)]
    return pd.DataFrame(
        {"Close": values, "Volume": [2_000_000] * count},
        index=pd.date_range("2025-01-01", periods=count, freq="B"),
    )


class EtfAllocationTests(unittest.TestCase):
    def test_core_etf_uses_allocation_language_not_fake_point_fair_value(self):
        result = analyze_etf_allocation(
            {"symbol": "VOO", "asset_type": "etf", "role": "broad_market"},
            history(),
            financials={"earnings_yield": 0.038, "historical_earnings_yield": 0.042},
            market_risk={"risk_score": 28, "regime": "NORMAL"},
        )

        self.assertEqual(result["status"], "READY")
        self.assertIn(result["action"], {"ACCUMULATE_MORE", "REGULAR_DCA", "REDUCE_PACE"})
        self.assertIn("expected_annual_return", result)
        self.assertIn("regular_buy", result["price_zones"])
        self.assertNotIn("fair_value", result)
        self.assertNotIn("margin_of_safety", result)

    def test_etf_result_is_independent_of_llm_availability(self):
        result = analyze_etf_allocation(
            {"symbol": "QQQM", "asset_type": "etf", "role": "growth"},
            history(daily_step=0.18),
            financials={"earnings_yield": 0.03, "historical_earnings_yield": 0.035},
            market_risk={"risk_score": 35, "regime": "NORMAL"},
        )

        self.assertEqual(result["engine"], "deterministic_etf_allocation")
        self.assertGreater(result["allocation_score"], 0)
        self.assertNotIn("llm", result)


if __name__ == "__main__":
    unittest.main()
