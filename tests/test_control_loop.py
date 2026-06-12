import unittest

from quant_core.analytics.signal_scoreboard import SignalScoreboard
from quant_core.risk.risk_gate import MarketRiskGateDecision


class ControlLoopTests(unittest.TestCase):
    def test_risk_off_forces_stop_regime(self):
        from quant_core.portfolio.control_loop import evaluate_allocation_regime

        scoreboard = SignalScoreboard(
            completed_trades=20,
            win_rate=0.70,
            avg_return_pct=0.03,
            avg_win_return_pct=0.06,
            avg_loss_return_pct=-0.02,
            payoff_ratio=3.0,
            expectancy_return_pct=0.02,
            profit_factor=2.0,
            median_holding_days=5,
            cumulative_return_pct=0.25,
            max_drawdown_pct=-0.06,
            regime_breakdown=[],
        )
        risk_gate = MarketRiskGateDecision(
            regime="RISK_OFF",
            risk_score=6,
            block_new_buys=True,
            max_position_weight=0.08,
            reasons=["vol spike"],
        )
        account_snapshot = {"exposure_pct": 45.0, "deployable_cash": 1000.0}

        decision = evaluate_allocation_regime(scoreboard, risk_gate=risk_gate, account_snapshot=account_snapshot)

        self.assertEqual(decision.regime, "STOP")
        self.assertTrue(decision.block_new_buys)
        self.assertLessEqual(decision.risk_multiplier, 0.1)

    def test_strong_scoreboard_can_recommend_heavy_regime(self):
        from quant_core.portfolio.control_loop import evaluate_allocation_regime

        scoreboard = SignalScoreboard(
            completed_trades=18,
            win_rate=0.67,
            avg_return_pct=0.025,
            avg_win_return_pct=0.05,
            avg_loss_return_pct=-0.02,
            payoff_ratio=2.5,
            expectancy_return_pct=0.018,
            profit_factor=1.9,
            median_holding_days=6,
            cumulative_return_pct=0.30,
            max_drawdown_pct=-0.08,
            regime_breakdown=[],
        )
        risk_gate = MarketRiskGateDecision(
            regime="NORMAL",
            risk_score=1,
            block_new_buys=False,
            max_position_weight=0.20,
            reasons=["stable"],
        )
        account_snapshot = {"exposure_pct": 52.0, "deployable_cash": 8000.0}

        decision = evaluate_allocation_regime(scoreboard, risk_gate=risk_gate, account_snapshot=account_snapshot)

        self.assertEqual(decision.regime, "HEAVY")
        self.assertFalse(decision.block_new_buys)
        self.assertGreater(decision.risk_multiplier, 1.0)

    def test_weak_scoreboard_degrades_to_light_regime(self):
        from quant_core.portfolio.control_loop import evaluate_allocation_regime

        scoreboard = SignalScoreboard(
            completed_trades=12,
            win_rate=0.40,
            avg_return_pct=-0.01,
            avg_win_return_pct=0.03,
            avg_loss_return_pct=-0.03,
            payoff_ratio=1.0,
            expectancy_return_pct=-0.006,
            profit_factor=0.8,
            median_holding_days=3,
            cumulative_return_pct=-0.05,
            max_drawdown_pct=-0.22,
            regime_breakdown=[],
        )
        risk_gate = MarketRiskGateDecision(
            regime="NORMAL",
            risk_score=0,
            block_new_buys=False,
            max_position_weight=0.20,
            reasons=[],
        )
        account_snapshot = {"exposure_pct": 70.0, "deployable_cash": 3000.0}

        decision = evaluate_allocation_regime(scoreboard, risk_gate=risk_gate, account_snapshot=account_snapshot)

        self.assertEqual(decision.regime, "LIGHT")
        self.assertLess(decision.risk_multiplier, 1.0)


if __name__ == "__main__":
    unittest.main()
