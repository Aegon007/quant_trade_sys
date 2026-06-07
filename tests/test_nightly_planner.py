import unittest
from datetime import datetime

from tests.support import clear_modules, reload_module


class NightlyPlannerTests(unittest.TestCase):
    def setUp(self):
        clear_modules("quant_core.execution.nightly_planner")
        self.module = reload_module("quant_core.execution.nightly_planner")

    def test_build_next_day_trade_plan_returns_no_action_when_all_hold(self):
        plan = self.module.build_next_day_trade_plan(
            {
                "generated_at": "2026-05-13T23:00:00",
                "allocation_regime": {"regime": "LIGHT", "reasons": ["risk elevated"]},
                "symbols": [
                    {"symbol": "VOO", "list_type": "holding", "signal": "HOLD", "signal_reason": "trend neutral", "latest_price": 500.0},
                    {"symbol": "MSFT", "list_type": "watchlist", "signal": "HOLD", "signal_reason": "waiting", "latest_price": 300.0},
                ],
            },
            now=datetime(2026, 5, 13, 23, 0, 0),
        )

        self.assertFalse(plan["has_actions"])
        self.assertEqual(plan["decision"], "NO_ACTION")
        self.assertTrue(plan["decision_signature"])
        self.assertIn("无强信号", plan["summary_reason"])
        self.assertEqual(plan["items"], [])

    def test_build_next_day_trade_plan_builds_action_items(self):
        plan = self.module.build_next_day_trade_plan(
            {
                "generated_at": "2026-05-13T23:00:00",
                "symbols": [
                    {
                        "symbol": "AAPL",
                        "list_type": "holding",
                        "signal": "BUY",
                        "signal_reason": "趋势增强",
                        "latest_price": 100.0,
                        "guidance": {"suggested_exit_price": 112.0},
                        "position_advice": {
                            "action": "ADD",
                            "current_weight_pct": 8.0,
                            "target_weight_pct": 15.0,
                            "delta_shares": 1.5,
                            "reason": "建议加仓",
                        },
                    },
                    {
                        "symbol": "MSFT",
                        "list_type": "watchlist",
                        "signal": "BUY",
                        "signal_reason": "breakout",
                        "latest_price": 300.0,
                        "monte_carlo": {"expected_return": 0.05},
                    },
                ],
            },
            now=datetime(2026, 5, 13, 23, 0, 0),
        )

        self.assertTrue(plan["has_actions"])
        self.assertEqual(plan["decision"], "ACTION")
        self.assertTrue(plan["decision_signature"])
        self.assertEqual(len(plan["items"]), 2)
        first = plan["items"][0]
        second = plan["items"][1]

        self.assertEqual(first["symbol"], "AAPL")
        self.assertEqual(first["plan_action"], "ADD")
        self.assertAlmostEqual(first["reference_price"], 100.0)
        self.assertIsNotNone(first["buy_zone_low"])
        self.assertIn("建议加仓", first["reason"])
        self.assertIn("作废", first["invalid_condition"])

        self.assertEqual(second["symbol"], "MSFT")
        self.assertEqual(second["plan_action"], "PROBE")
        self.assertAlmostEqual(second["plan_weight_delta_pct"], 2.0)
        self.assertIn("观察", second["reason"])

    def test_build_premarket_brief_includes_execution_review(self):
        brief = self.module.build_premarket_brief(
            {
                "generated_at": "2026-05-13T23:00:00",
                "decision": "ACTION",
                "decision_signature": "abc123sig",
                "has_actions": True,
                "summary_reason": "明日有 1 条计划。",
                "items": [
                    {
                        "symbol": "VOO",
                        "plan_action": "ACCUMULATE",
                        "reference_price": 500.0,
                        "buy_zone_low": 495.0,
                        "buy_zone_high": 505.0,
                        "plan_weight_delta_pct": 3.0,
                        "invalid_condition": "若高开超过 510，本次建议作废。",
                        "risk_break_level": 485.0,
                        "reason": "趋势改善",
                    }
                ],
            },
            execution_review={
                "review_day": "2026-05-13",
                "executed_count": 1,
                "missed_count": 0,
                "unplanned_trade_count": 0,
            },
        )

        self.assertIn("盘前简报", brief)
        self.assertIn("明日建议：有动作", brief)
        self.assertIn("计划签名：abc123sig", brief)
        self.assertIn("VOO", brief)
        self.assertIn("执行复盘", brief)

    def test_build_next_day_trade_plan_includes_top_satellite_candidates(self):
        plan = self.module.build_next_day_trade_plan(
            {
                "generated_at": "2026-05-13T23:00:00",
                "symbols": [],
            },
            satellite_candidate_snapshot={
                "top_recommendations": [
                    {
                        "symbol": "MU",
                        "recommendation_status": "CONFIRMED",
                        "plan_action": "ACCUMULATE",
                        "current_price": 120.0,
                        "signal": "BUY",
                        "recommendation_reason": "趋势、模型与回测共同确认。",
                    },
                    {
                        "symbol": "TSLA",
                        "recommendation_status": "WATCH",
                        "plan_action": "WATCH",
                        "current_price": 200.0,
                        "signal": "HOLD",
                    },
                ]
            },
            now=datetime(2026, 5, 13, 23, 0, 0),
        )

        self.assertTrue(plan["has_actions"])
        self.assertEqual(plan["items"][0]["symbol"], "MU")
        self.assertEqual(plan["items"][0]["plan_action"], "ACCUMULATE")
        self.assertIn("趋势、模型与回测共同确认", plan["items"][0]["reason"])

    def test_build_next_day_trade_plan_blocks_new_entries_when_discipline_stop(self):
        plan = self.module.build_next_day_trade_plan(
            {
                "generated_at": "2026-05-13T23:00:00",
                "symbols": [
                    {
                        "symbol": "AAPL",
                        "list_type": "holding",
                        "signal": "BUY",
                        "signal_reason": "趋势增强",
                        "latest_price": 100.0,
                        "position_advice": {
                            "action": "ADD",
                            "current_weight_pct": 8.0,
                            "target_weight_pct": 15.0,
                            "reason": "建议加仓",
                        },
                    }
                ],
            },
            discipline_snapshot={"regime": "STOP", "can_open_new_core_positions": False, "can_open_new_satellite_positions": False},
            now=datetime(2026, 5, 13, 23, 0, 0),
        )

        self.assertFalse(plan["has_actions"])
        self.assertEqual(plan["decision"], "NO_ACTION")
        self.assertEqual(plan["blocked_count"], 1)
        self.assertEqual(plan["blocked_items"][0]["blocked_reason"], "discipline_stop")
        self.assertIn("STOP", plan["summary_reason"])


if __name__ == "__main__":
    unittest.main()
