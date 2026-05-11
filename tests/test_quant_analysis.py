import unittest

import pandas as pd

from tests.support import clear_modules, install_fake_yfinance, reload_module


def make_history(close_values):
    index = pd.date_range("2024-01-01", periods=len(close_values), freq="D")
    return pd.DataFrame({"Close": close_values}, index=index)


def make_ohlcv(close_values):
    index = pd.date_range("2024-01-01", periods=len(close_values), freq="D")
    close = pd.Series(close_values, index=index, dtype=float)
    return pd.DataFrame(
        {
            "Open": close * 0.99,
            "High": close * 1.01,
            "Low": close * 0.98,
            "Close": close,
            "Volume": [1_000_000] * len(close),
        },
        index=index,
    )


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

    def test_get_historical_data_falls_back_when_yfinance_history_is_empty(self):
        fallback_history = make_ohlcv([100, 101, 102, 103, 104])
        self.quant_analysis.md.fetch_stooq_history = lambda symbol, period="6mo": fallback_history.copy()
        self.quant_analysis.md.reset_market_data_status()

        history = self.quant_analysis.get_historical_data("QQQ", period="6mo")
        status = self.quant_analysis.md.get_market_data_status_snapshot()

        self.assertFalse(history.empty)
        self.assertEqual(list(history["Close"]), [100.0, 101.0, 102.0, 103.0, 104.0])
        self.assertEqual(status["history"]["fallback_requests"], 1)
        self.assertEqual(status["history"]["last_source"], "stooq")


if __name__ == "__main__":
    unittest.main()
