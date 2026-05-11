import unittest
import pandas as pd


class RiskGateTests(unittest.TestCase):
    def test_evaluate_market_risk_gate_detects_risk_off(self):
        from quant_core.risk.risk_gate import MarketRiskSnapshot, evaluate_market_risk_gate

        decision = evaluate_market_risk_gate(
            MarketRiskSnapshot(
                vix=35.0,
                benchmark_drawdown=-0.14,
                benchmark_volatility=0.45,
                sector_alert_count=1,
                correlation_alert_count=2,
            )
        )

        self.assertEqual(decision.regime, "RISK_OFF")
        self.assertTrue(decision.block_new_buys)
        self.assertLessEqual(decision.max_position_weight, 0.08)

    def test_evaluate_market_risk_gate_detects_caution(self):
        from quant_core.risk.risk_gate import MarketRiskSnapshot, evaluate_market_risk_gate

        decision = evaluate_market_risk_gate(
            MarketRiskSnapshot(
                vix=24.0,
                benchmark_drawdown=-0.06,
                benchmark_volatility=0.30,
            )
        )

        self.assertEqual(decision.regime, "CAUTION")
        self.assertFalse(decision.block_new_buys)
        self.assertAlmostEqual(decision.max_position_weight, 0.12)

    def test_evaluate_market_risk_gate_detects_normal(self):
        from quant_core.risk.risk_gate import MarketRiskSnapshot, evaluate_market_risk_gate

        decision = evaluate_market_risk_gate(
            MarketRiskSnapshot(vix=16.0, benchmark_drawdown=-0.03, benchmark_volatility=0.18)
        )

        self.assertEqual(decision.regime, "NORMAL")
        self.assertFalse(decision.block_new_buys)
        self.assertAlmostEqual(decision.max_position_weight, 0.20)

    def test_build_market_risk_snapshot_from_histories_extracts_metrics(self):
        from quant_core.risk.risk_gate import build_market_risk_snapshot_from_histories

        benchmark_history = pd.DataFrame(
            {"Close": [100.0, 110.0, 105.0, 108.0]},
            index=pd.date_range("2026-01-01", periods=4, freq="D"),
        )
        vix_history = pd.DataFrame(
            {"Close": [18.0, 19.5]},
            index=pd.date_range("2026-01-01", periods=2, freq="D"),
        )

        snapshot = build_market_risk_snapshot_from_histories(
            benchmark_history=benchmark_history,
            vix_history=vix_history,
            sector_alert_count=1,
            correlation_alert_count=2,
        )

        self.assertAlmostEqual(snapshot.vix, 19.5)
        self.assertAlmostEqual(snapshot.benchmark_drawdown, (108.0 / 110.0) - 1.0)
        self.assertIsNotNone(snapshot.benchmark_volatility)
        self.assertEqual(snapshot.sector_alert_count, 1)
        self.assertEqual(snapshot.correlation_alert_count, 2)

    def test_build_market_risk_snapshot_from_histories_handles_missing_data(self):
        from quant_core.risk.risk_gate import build_market_risk_snapshot_from_histories

        snapshot = build_market_risk_snapshot_from_histories(
            benchmark_history=pd.DataFrame(),
            vix_history=None,
            sector_alert_count=0,
            correlation_alert_count=0,
        )

        self.assertIsNone(snapshot.vix)
        self.assertIsNone(snapshot.benchmark_drawdown)
        self.assertIsNone(snapshot.benchmark_volatility)

    def test_merge_risk_gate_decisions_takes_stricter_controls(self):
        from quant_core.risk.risk_gate import MarketRiskGateDecision, merge_risk_gate_decisions

        base = MarketRiskGateDecision(
            regime="CAUTION",
            risk_score=3,
            block_new_buys=False,
            max_position_weight=0.12,
            reasons=["base risk"],
        )
        override = MarketRiskGateDecision(
            regime="RISK_OFF",
            risk_score=5,
            block_new_buys=True,
            max_position_weight=0.08,
            reasons=["event brake"],
        )

        merged = merge_risk_gate_decisions(base, override)

        self.assertEqual(merged.regime, "RISK_OFF")
        self.assertTrue(merged.block_new_buys)
        self.assertAlmostEqual(merged.max_position_weight, 0.08)
        self.assertGreaterEqual(merged.risk_score, 5)
        self.assertIn("base risk", " ".join(merged.reasons))
        self.assertIn("event brake", " ".join(merged.reasons))


if __name__ == "__main__":
    unittest.main()
