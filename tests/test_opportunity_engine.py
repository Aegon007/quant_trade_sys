import unittest

import pandas as pd

from quant_core.opportunities.dislocation import measure_dislocation
from quant_core.opportunities.scoring import score_opportunity


def history(prices):
    return pd.DataFrame(
        {"Close": prices, "Volume": [1_000_000] * len(prices)},
        index=pd.date_range("2026-01-01", periods=len(prices), freq="B"),
    )


class OpportunityEngineTests(unittest.TestCase):
    def test_dislocation_removes_market_and_sector_move(self):
        stock = history([100 + index * 0.2 for index in range(55)] + [108, 102, 94, 88, 86])
        market = history([100 + index * 0.1 for index in range(55)] + [105, 104, 103, 102, 101])
        sector = history([100 + index * 0.15 for index in range(55)] + [107, 105, 103, 101, 100])

        result = measure_dislocation(stock, market_history=market, sector_history=sector)

        self.assertLess(result["return_20d"], -0.1)
        self.assertLess(result["abnormal_return_20d"], -0.08)
        self.assertGreater(result["dislocation_score"], 50)

    def test_structural_damage_blocks_cheap_stock(self):
        result = score_opportunity(
            dislocation={"dislocation_score": 88, "stabilization_score": 70},
            valuation={"margin_of_safety": 0.42, "confidence": 0.85, "dispersion": 0.25},
            fundamentals={"quality_score": 82, "damage_score": 85, "distress_probability": 0.1},
            event={"transience_probability": 0.2, "catalyst_score": 30},
            market_risk={"risk_score": 20},
        )

        self.assertEqual(result["recommendation"], "FUNDAMENTALS_DAMAGED")
        self.assertFalse(result["actionable"])

    def test_temporary_selloff_with_margin_of_safety_is_actionable(self):
        result = score_opportunity(
            dislocation={"dislocation_score": 82, "stabilization_score": 66},
            valuation={"margin_of_safety": 0.31, "confidence": 0.82, "dispersion": 0.22},
            fundamentals={"quality_score": 84, "damage_score": 18, "distress_probability": 0.04},
            event={"transience_probability": 0.81, "catalyst_score": 65},
            market_risk={"risk_score": 25},
        )

        self.assertTrue(result["actionable"])
        self.assertIn(result["recommendation"], {"ACCUMULATE", "STRONG_OPPORTUNITY"})
        self.assertGreaterEqual(result["opportunity_score"], 65)

    def test_configured_margin_threshold_is_enforced(self):
        inputs = dict(
            dislocation={"dislocation_score": 90, "stabilization_score": 80},
            valuation={"margin_of_safety": 0.26, "confidence": 0.9, "dispersion": 0.1},
            fundamentals={"quality_score": 90, "damage_score": 5, "distress_probability": 0.01},
            event={"transience_probability": 0.9, "catalyst_score": 80},
            market_risk={"risk_score": 20},
        )
        result = score_opportunity(**inputs, policy={"minimum_margin_of_safety": 0.30, "strong_margin_of_safety": 0.40})
        self.assertFalse(result["actionable"])
        self.assertEqual(result["recommendation"], "WATCH")


if __name__ == "__main__":
    unittest.main()
