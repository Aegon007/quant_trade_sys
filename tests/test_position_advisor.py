import unittest

import pandas as pd


class BacktestGuidanceTests(unittest.TestCase):
    def test_summarize_backtest_guidance_pairs_round_trips(self):
        from position_advisor import summarize_backtest_guidance

        trade_log = [
            {"date": pd.Timestamp("2024-01-01"), "action": "BUY", "price": 100.0, "shares": 1.0},
            {"date": pd.Timestamp("2024-01-06"), "action": "SELL", "price": 110.0, "shares": 1.0},
            {"date": pd.Timestamp("2024-01-10"), "action": "BUY", "price": 100.0, "shares": 1.0},
            {"date": pd.Timestamp("2024-01-13"), "action": "SELL", "price": 95.0, "shares": 1.0},
        ]

        guidance = summarize_backtest_guidance(trade_log, current_price=120.0)

        self.assertEqual(guidance.completed_trades, 2)
        self.assertEqual(guidance.expected_holding_days, 4)
        self.assertAlmostEqual(guidance.expected_return_pct, 0.025)
        self.assertAlmostEqual(guidance.suggested_exit_price, 132.0)


class PositionRecommendationTests(unittest.TestCase):
    def test_recommend_position_action_trims_overweight_holdings(self):
        from position_advisor import recommend_position_action

        advice = recommend_position_action(
            holding={"symbol": "AAPL", "shares": 4.0, "current_price": 100.0},
            portfolio_value=1000.0,
            signal="HOLD",
            signal_reason="趋势中性",
        )

        self.assertEqual(advice.action, "TRIM")
        self.assertAlmostEqual(advice.current_weight_pct, 40.0)
        self.assertAlmostEqual(advice.target_weight_pct, 20.0)
        self.assertAlmostEqual(advice.delta_shares, -2.0)

    def test_recommend_position_action_exits_on_sell_signal(self):
        from position_advisor import recommend_position_action

        advice = recommend_position_action(
            holding={"symbol": "AAPL", "shares": 1.25, "current_price": 100.0},
            portfolio_value=1000.0,
            signal="SELL",
            signal_reason="动能转弱",
        )

        self.assertEqual(advice.action, "EXIT")
        self.assertAlmostEqual(advice.target_weight_pct, 0.0)
        self.assertAlmostEqual(advice.delta_shares, -1.25)

    def test_recommend_position_action_adds_when_buy_signal_has_positive_guidance(self):
        from position_advisor import BacktestGuidance, recommend_position_action

        advice = recommend_position_action(
            holding={"symbol": "AAPL", "shares": 0.5, "current_price": 100.0},
            portfolio_value=1000.0,
            signal="BUY",
            signal_reason="趋势增强",
            guidance=BacktestGuidance(
                completed_trades=5,
                expected_return_pct=0.12,
                expected_holding_days=8,
                suggested_exit_price=112.0,
                median_win_return_pct=0.12,
            ),
        )

        self.assertEqual(advice.action, "ADD")
        self.assertAlmostEqual(advice.target_weight_pct, 15.0)
        self.assertAlmostEqual(advice.delta_shares, 1.0)
        self.assertAlmostEqual(advice.suggested_exit_price, 112.0)


if __name__ == "__main__":
    unittest.main()
