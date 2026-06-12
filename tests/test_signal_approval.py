import unittest


class SignalApprovalTests(unittest.TestCase):
    def test_approve_signal_blocks_buy_when_risk_gate_blocks_new_buys(self):
        from quant_core.risk.risk_gate import MarketRiskGateDecision
        from quant_core.common.signal_approval import approve_signal

        approval = approve_signal(
            "BUY",
            risk_gate=MarketRiskGateDecision(
                regime="RISK_OFF",
                risk_score=7,
                block_new_buys=True,
                max_position_weight=0.08,
                reasons=["风险过高"],
            ),
        )

        self.assertEqual(approval.raw_signal, "BUY")
        self.assertEqual(approval.approved_signal, "HOLD")
        self.assertTrue(approval.blocked)
        self.assertIn("风险闸门", approval.reason)

    def test_approve_signal_keeps_sell_when_risk_gate_blocks_new_buys(self):
        from quant_core.risk.risk_gate import MarketRiskGateDecision
        from quant_core.common.signal_approval import approve_signal

        approval = approve_signal(
            "SELL",
            risk_gate=MarketRiskGateDecision(
                regime="RISK_OFF",
                risk_score=7,
                block_new_buys=True,
                max_position_weight=0.08,
                reasons=["风险过高"],
            ),
        )

        self.assertEqual(approval.raw_signal, "SELL")
        self.assertEqual(approval.approved_signal, "SELL")
        self.assertFalse(approval.blocked)

    def test_approve_signal_normalizes_unknown_to_hold(self):
        from quant_core.common.signal_approval import approve_signal

        approval = approve_signal("mystery")

        self.assertEqual(approval.raw_signal, "HOLD")
        self.assertEqual(approval.approved_signal, "HOLD")
        self.assertFalse(approval.blocked)


if __name__ == "__main__":
    unittest.main()
