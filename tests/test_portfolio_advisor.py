import unittest

import pandas as pd


class PortfolioAdvisorTests(unittest.TestCase):
    def test_analyze_portfolio_flags_sector_concentration(self):
        from quant_core.portfolio.risk import analyze_portfolio_risk

        advice = analyze_portfolio_risk(
            holdings=[
                {"symbol": "AAPL", "shares": 4.0, "current_price": 100.0, "sector": "Technology"},
                {"symbol": "MSFT", "shares": 2.0, "current_price": 100.0, "sector": "Technology"},
                {"symbol": "JNJ", "shares": 4.0, "current_price": 100.0, "sector": "Healthcare"},
            ],
            sector_limit=0.50,
        )

        self.assertEqual(advice.total_value, 1000.0)
        self.assertEqual(len(advice.sector_alerts), 1)
        self.assertEqual(advice.sector_alerts[0].sector, "Technology")
        self.assertAlmostEqual(advice.sector_alerts[0].weight_pct, 60.0)
        self.assertIn("Technology", advice.recommendations[0])

    def test_analyze_portfolio_flags_high_correlation_pairs(self):
        from quant_core.portfolio.risk import analyze_portfolio_risk

        correlation = pd.DataFrame(
            {
                "AAPL": {"AAPL": 1.0, "MSFT": 0.84, "JNJ": 0.12},
                "MSFT": {"AAPL": 0.84, "MSFT": 1.0, "JNJ": 0.18},
                "JNJ": {"AAPL": 0.12, "MSFT": 0.18, "JNJ": 1.0},
            }
        )

        advice = analyze_portfolio_risk(
            holdings=[
                {"symbol": "AAPL", "shares": 4.0, "current_price": 100.0, "sector": "Technology"},
                {"symbol": "MSFT", "shares": 2.0, "current_price": 100.0, "sector": "Technology"},
                {"symbol": "JNJ", "shares": 4.0, "current_price": 100.0, "sector": "Healthcare"},
            ],
            correlation_matrix=correlation,
            correlation_threshold=0.75,
        )

        self.assertEqual(len(advice.correlation_alerts), 1)
        self.assertEqual(advice.correlation_alerts[0].symbols, ("AAPL", "MSFT"))
        self.assertAlmostEqual(advice.correlation_alerts[0].correlation, 0.84)
        self.assertAlmostEqual(advice.correlation_alerts[0].combined_weight_pct, 60.0)

    def test_analyze_portfolio_handles_missing_prices(self):
        from quant_core.portfolio.risk import analyze_portfolio_risk

        advice = analyze_portfolio_risk(
            holdings=[
                {"symbol": "AAPL", "shares": 1.0, "current_price": None, "sector": "Technology"},
                {"symbol": "JNJ", "shares": 2.0, "current_price": 100.0, "sector": "Healthcare"},
            ]
        )

        self.assertEqual(advice.total_value, 200.0)
        self.assertEqual(advice.unpriced_symbols, ["AAPL"])


if __name__ == "__main__":
    unittest.main()
