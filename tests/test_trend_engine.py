import unittest

import pandas as pd

from quant_core.trend.engine import analyze_trend, score_trend_candidate


def history(values):
    return pd.DataFrame(
        {"Close": values, "Volume": [1_000_000 + index * 2_000 for index in range(len(values))]},
        index=pd.date_range("2025-01-01", periods=len(values), freq="B"),
    )


class TrendEngineTests(unittest.TestCase):
    def test_accelerating_stock_is_detected_even_without_a_selloff(self):
        market = history([100 + index * 0.08 for index in range(260)])
        stock = history(
            [80 + index * 0.04 for index in range(190)]
            + [87.6 + index * 0.42 for index in range(70)]
        )

        result = analyze_trend(stock, market_history=market, sector_history=market)

        self.assertEqual(result["status"], "READY")
        self.assertGreaterEqual(result["trend_score"], 65)
        self.assertIn(result["trend_state"], {"ACCELERATING", "TREND_CONFIRMED", "EXTENDED"})
        self.assertGreater(result["relative_return_20d"], 0)
        self.assertTrue(result["reason_codes"])

    def test_fundamental_overlay_does_not_require_a_valuation_or_llm_route(self):
        trend = {
            "status": "READY",
            "trend_score": 82,
            "trend_state": "TREND_CONFIRMED",
            "extension_from_ma50": 0.06,
            "reason_codes": ["RELATIVE_STRENGTH", "ABOVE_LONG_TERM_TREND"],
        }

        result = score_trend_candidate(
            trend,
            fundamentals={"status": "READY", "quality_score": 78, "damage_score": 12, "distress_probability": 0.03},
            market_risk={"risk_score": 25},
        )

        self.assertTrue(result["actionable"])
        self.assertEqual(result["recommendation"], "TREND_CONFIRMED")
        self.assertNotIn("valuation", result["components"])

    def test_extended_trend_is_visible_but_not_a_chase_signal(self):
        result = score_trend_candidate(
            {
                "status": "READY",
                "trend_score": 91,
                "trend_state": "EXTENDED",
                "extension_from_ma50": 0.24,
                "reason_codes": ["NEAR_52W_HIGH", "PRICE_EXTENDED"],
            },
            fundamentals={"status": "READY", "quality_score": 85, "damage_score": 8, "distress_probability": 0.01},
            market_risk={"risk_score": 20},
        )

        self.assertFalse(result["actionable"])
        self.assertEqual(result["recommendation"], "WAIT_FOR_PULLBACK")


if __name__ == "__main__":
    unittest.main()
