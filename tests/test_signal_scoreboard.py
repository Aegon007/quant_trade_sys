import unittest

import pandas as pd


class SignalScoreboardTests(unittest.TestCase):
    def test_build_signal_scoreboard_summarizes_round_trips(self):
        from signal_scoreboard import build_signal_scoreboard

        trade_log = [
            {"date": pd.Timestamp("2026-01-02"), "action": "BUY", "price": 100.0, "shares": 1.0},
            {"date": pd.Timestamp("2026-01-07"), "action": "SELL", "price": 110.0, "shares": 1.0},
            {"date": pd.Timestamp("2026-01-10"), "action": "BUY", "price": 200.0, "shares": 1.0},
            {"date": pd.Timestamp("2026-01-14"), "action": "SELL", "price": 180.0, "shares": 1.0},
        ]

        scoreboard = build_signal_scoreboard(
            trade_log,
            equity_curve=[100000.0, 101000.0, 99000.0, 102000.0],
        )

        self.assertEqual(scoreboard.completed_trades, 2)
        self.assertAlmostEqual(scoreboard.win_rate, 0.5)
        self.assertAlmostEqual(scoreboard.avg_return_pct, 0.0)
        self.assertAlmostEqual(scoreboard.avg_win_return_pct, 0.10)
        self.assertAlmostEqual(scoreboard.avg_loss_return_pct, -0.10)
        self.assertAlmostEqual(scoreboard.payoff_ratio, 1.0)
        self.assertAlmostEqual(scoreboard.expectancy_return_pct, 0.0)
        self.assertAlmostEqual(scoreboard.profit_factor, 1.0)
        self.assertAlmostEqual(scoreboard.cumulative_return_pct, 0.02)
        self.assertLess(scoreboard.max_drawdown_pct, 0.0)
        self.assertEqual(len(scoreboard.regime_breakdown), 1)
        self.assertEqual(scoreboard.regime_breakdown[0].regime, "ALL")

    def test_build_signal_scoreboard_handles_empty_trade_log(self):
        from signal_scoreboard import build_signal_scoreboard

        scoreboard = build_signal_scoreboard([], equity_curve=[100000.0])

        self.assertEqual(scoreboard.completed_trades, 0)
        self.assertIsNone(scoreboard.win_rate)
        self.assertIsNone(scoreboard.avg_return_pct)
        self.assertIsNone(scoreboard.payoff_ratio)
        self.assertIsNone(scoreboard.expectancy_return_pct)
        self.assertIsNone(scoreboard.max_drawdown_pct)
        self.assertEqual(scoreboard.regime_breakdown, [])

    def test_build_signal_scoreboard_includes_volatility_regime_breakdown(self):
        from signal_scoreboard import build_signal_scoreboard

        trade_log = [
            {"date": pd.Timestamp("2026-01-05"), "action": "BUY", "price": 100.0, "shares": 1.0},
            {"date": pd.Timestamp("2026-01-08"), "action": "SELL", "price": 103.0, "shares": 1.0},
        ]
        benchmark_history = pd.DataFrame(
            {"Close": [100.0, 100.2, 100.3, 100.4, 100.5, 100.6, 100.7, 100.8]},
            index=pd.date_range("2025-12-30", periods=8, freq="D"),
        )

        scoreboard = build_signal_scoreboard(
            trade_log,
            benchmark_history=benchmark_history,
            volatility_window=3,
            low_vol_threshold=0.20,
            high_vol_threshold=0.40,
        )

        self.assertEqual(scoreboard.completed_trades, 1)
        self.assertEqual(len(scoreboard.regime_breakdown), 1)
        self.assertEqual(scoreboard.regime_breakdown[0].regime, "LOW_VOL")
        self.assertEqual(scoreboard.regime_breakdown[0].trades, 1)

    def test_build_signal_scoreboard_supports_transaction_records_shape(self):
        from signal_scoreboard import build_signal_scoreboard

        trade_log = [
            {
                "record_type": "TRADE",
                "event_type": "BUY",
                "side": "BUY",
                "date": "2026-01-02 10:00",
                "symbol": "AAPL",
                "shares": 1.0,
                "price": 100.0,
            },
            {
                "record_type": "TRADE",
                "event_type": "SELL",
                "side": "SELL",
                "date": "2026-01-05 10:00",
                "symbol": "AAPL",
                "shares": 1.0,
                "price": 108.0,
            },
        ]

        scoreboard = build_signal_scoreboard(trade_log)

        self.assertEqual(scoreboard.completed_trades, 1)
        self.assertAlmostEqual(scoreboard.win_rate, 1.0)
        self.assertGreater(scoreboard.avg_return_pct, 0.0)


if __name__ == "__main__":
    unittest.main()
