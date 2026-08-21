import unittest
from datetime import datetime

from quant_core.execution import decision_engine as de


class DecisionEngineTests(unittest.TestCase):
    def test_builds_single_final_decision_from_existing_layers(self):
        snapshot = de.build_final_decision_snapshot(
            account={"cash_available": 1000, "total_capital": 10000, "exposure_pct": 55},
            trade_plan={"decision": "ACTION", "items": [{"symbol": "VOO", "plan_action": "DCA_ACCUMULATE"}]},
            core_snapshot={"symbols": [{"symbol": "VOO", "decision": {"action": "DCA_ACCUMULATE"}}]},
            satellite_snapshot={"top_recommendations": [{"symbol": "MSFT", "decision": {"action": "WATCH"}}]},
            discipline_snapshot={"regime": "NORMAL", "target_exposure_pct": 0.75},
            correlation_snapshot={"summary": {"status": "READY", "high_correlation_pair_count": 1}},
            data_health_snapshot={"status": "OK"},
            now=datetime(2026, 1, 8, 20, 0),
        )
        self.assertEqual(snapshot["system_identity"], "中长期个人交易辅助系统")
        self.assertEqual(snapshot["final_decision"], "ACTION")
        self.assertEqual(snapshot["summary"]["executable_action_count"], 1)
        self.assertEqual(snapshot["strategy_sections"]["core_etf"]["action_count"], 1)
        self.assertEqual(snapshot["strategy_sections"]["weekend_correlation"]["role"], "风险和机会线索")

    def test_bad_data_blocks_new_actions(self):
        snapshot = de.build_final_decision_snapshot(
            account={},
            trade_plan={"decision": "ACTION", "items": [{"symbol": "AAPL", "plan_action": "PROBE"}]},
            data_health_snapshot={"status": "DEGRADED"},
            now=datetime(2026, 1, 8, 20, 0),
        )
        self.assertEqual(snapshot["final_decision"], "WAIT")
        self.assertIn("数据健康", snapshot["top_reasons"][0])


if __name__ == "__main__":
    unittest.main()
