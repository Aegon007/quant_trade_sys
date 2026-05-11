import unittest

import pandas as pd

from tests.support import clear_modules, install_fake_yfinance, reload_module


def make_history(close_values):
    index = pd.date_range("2024-01-01", periods=len(close_values), freq="D")
    return pd.DataFrame({"Close": close_values}, index=index)


class PortfolioBetaTests(unittest.TestCase):
    def setUp(self):
        histories = {
            "AAPL": make_history([100, 103, 101, 106, 108]),
            "MSFT": make_history([200, 198, 201, 205, 207]),
            "SPY": make_history([300, 303, 302, 306, 309]),
        }
        install_fake_yfinance(histories)
        clear_modules("quant_core.analytics.quant_analysis")
        self.quant_analysis = reload_module("quant_core.analytics.quant_analysis")

    def test_calculate_portfolio_beta_aggregates_duplicate_symbols(self):
        holdings = [
            {"symbol": "AAPL", "shares": 1, "current_price": 100.0},
            {"symbol": "AAPL", "shares": 3, "current_price": 100.0},
            {"symbol": "MSFT", "shares": 1, "current_price": 200.0},
        ]

        portfolio_beta, betas = self.quant_analysis.calculate_portfolio_beta(holdings)

        returns = pd.DataFrame(
            {
                "AAPL": [100, 103, 101, 106, 108],
                "MSFT": [200, 198, 201, 205, 207],
                "SPY": [300, 303, 302, 306, 309],
            }
        ).pct_change().dropna()
        beta_aapl = returns["AAPL"].cov(returns["SPY"]) / returns["SPY"].var()
        beta_msft = returns["MSFT"].cov(returns["SPY"]) / returns["SPY"].var()
        expected = (400.0 / 600.0) * beta_aapl + (200.0 / 600.0) * beta_msft

        self.assertAlmostEqual(betas["AAPL"], beta_aapl)
        self.assertAlmostEqual(betas["MSFT"], beta_msft)
        self.assertAlmostEqual(portfolio_beta, expected)

    def test_calculate_portfolio_beta_requires_at_least_one_priced_holding(self):
        holdings = [{"symbol": "AAPL", "shares": 1, "current_price": None}]

        with self.assertRaises(ValueError):
            self.quant_analysis.calculate_portfolio_beta(holdings)

    def test_rsi_signal_treats_numeric_period_param_as_rsi_window(self):
        captured = {}

        def fake_get_historical_data(symbol, period="6mo"):
            captured["period"] = period
            return pd.DataFrame(
                {"Close": [100, 98, 97, 99, 101, 103, 102, 104, 106, 105, 107, 109, 108, 110, 112, 111]},
                index=pd.date_range("2024-01-01", periods=16, freq="D"),
            )

        self.quant_analysis.get_historical_data = fake_get_historical_data

        signal, reason = self.quant_analysis.get_signal_for_strategy(
            "AAPL",
            {"id": "rsi", "params": {"period": 14, "oversold": 30, "overbought": 70}},
        )

        self.assertEqual(captured["period"], "3mo")
        self.assertIn(signal, {"BUY", "SELL", "HOLD"})
        self.assertTrue(reason)


if __name__ == "__main__":
    unittest.main()
