import unittest
from types import SimpleNamespace


class CapitalAllocatorTests(unittest.TestCase):
    def test_recommend_buy_uses_signal_strength_and_account_limits(self):
        from capital_allocator import recommend_allocation

        plan = recommend_allocation(
            symbol="AAPL",
            current_price=100.0,
            signal="BUY",
            account={
                "total_capital": 10000.0,
                "cash_available": 4000.0,
                "min_cash_buffer_pct": 0.10,
                "max_single_position_pct": 0.20,
                "max_total_exposure_pct": 1.0,
            },
            current_shares=5.0,
            signal_profile=SimpleNamespace(probability=0.72, expected_return_pct=0.12),
        )

        self.assertEqual(plan.action, "BUY")
        self.assertAlmostEqual(plan.target_weight_pct, 20.0)
        self.assertAlmostEqual(plan.recommended_dollars, 1500.0)
        self.assertAlmostEqual(plan.recommended_shares, 15.0)
        self.assertAlmostEqual(plan.cash_buffer_dollars, 1000.0)
        self.assertIn("上涨概率", plan.reason)

    def test_recommend_buy_blocks_when_risk_gate_stops_new_buys(self):
        from capital_allocator import recommend_allocation
        from risk_gate import MarketRiskGateDecision

        plan = recommend_allocation(
            symbol="AAPL",
            current_price=100.0,
            signal="BUY",
            account={
                "total_capital": 10000.0,
                "cash_available": 4000.0,
                "min_cash_buffer_pct": 0.10,
                "max_single_position_pct": 0.20,
                "max_total_exposure_pct": 1.0,
            },
            signal_profile=SimpleNamespace(probability=0.70, expected_return_pct=0.10),
            risk_gate=MarketRiskGateDecision(
                regime="RISK_OFF",
                risk_score=7,
                block_new_buys=True,
                max_position_weight=0.08,
                reasons=["风险过高"],
            ),
        )

        self.assertEqual(plan.action, "HOLD")
        self.assertAlmostEqual(plan.recommended_dollars, 0.0)
        self.assertAlmostEqual(plan.recommended_shares, 0.0)
        self.assertIn("风险闸门", plan.reason)

    def test_recommend_buy_scales_down_in_caution_regime(self):
        from capital_allocator import recommend_allocation
        from risk_gate import MarketRiskGateDecision

        plan = recommend_allocation(
            symbol="MSFT",
            current_price=100.0,
            signal="BUY",
            account={
                "total_capital": 10000.0,
                "cash_available": 5000.0,
                "min_cash_buffer_pct": 0.10,
                "max_single_position_pct": 0.20,
                "max_total_exposure_pct": 1.0,
            },
            signal_profile=SimpleNamespace(probability=0.60, expected_return_pct=0.03),
            risk_gate=MarketRiskGateDecision(
                regime="CAUTION",
                risk_score=3,
                block_new_buys=False,
                max_position_weight=0.20,
                reasons=["大盘位置偏高"],
            ),
        )

        self.assertEqual(plan.action, "BUY")
        self.assertAlmostEqual(plan.target_weight_pct, 9.6)
        self.assertAlmostEqual(plan.recommended_dollars, 960.0)
        self.assertAlmostEqual(plan.recommended_shares, 9.6)


if __name__ == "__main__":
    unittest.main()
