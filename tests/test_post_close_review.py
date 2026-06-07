import unittest

from tests.support import clear_modules, reload_module


class PostCloseReviewTests(unittest.TestCase):
    def setUp(self):
        clear_modules("quant_core.execution.post_close_review")
        self.module = reload_module("quant_core.execution.post_close_review")

    def test_build_execution_review_matches_plan_items_to_trades(self):
        review = self.module.build_execution_review(
            {
                "plan_date": "2026-05-13",
                "decision_signature": "sig-123",
                "items": [
                    {
                        "symbol": "AAPL",
                        "plan_action": "ADD",
                        "buy_zone_low": 99.0,
                        "buy_zone_high": 101.0,
                    },
                    {
                        "symbol": "TSLA",
                        "plan_action": "EXIT",
                        "trim_zone_low": 200.0,
                        "trim_zone_high": 204.0,
                    },
                ],
            },
            [
                {"record_type": "TRADE", "side": "BUY", "date": "2026-05-13 10:00", "symbol": "AAPL", "shares": 1.0, "price": 100.0},
                {"record_type": "TRADE", "side": "SELL", "date": "2026-05-13 15:00", "symbol": "NVDA", "shares": 1.0, "price": 900.0},
            ],
            day="2026-05-13",
            market_day_ranges={
                "AAPL": {"open": 100.5, "high": 101.2, "low": 99.4, "close": 100.8},
                "TSLA": {"open": 195.0, "high": 198.0, "low": 191.0, "close": 192.0},
            },
        )

        self.assertEqual(review["executed_count"], 1)
        self.assertEqual(review["decision_signature"], "sig-123")
        self.assertEqual(review["missed_count"], 1)
        self.assertEqual(review["unplanned_trade_count"], 1)
        self.assertEqual(review["items"][0]["status"], "EXECUTED")
        self.assertTrue(review["items"][0]["executed_in_plan_zone"])
        self.assertEqual(review["items"][0]["opportunity_status"], "EXECUTED")
        self.assertEqual(review["items"][1]["status"], "MISSED")
        self.assertEqual(review["items"][1]["opportunity_status"], "UNREACHABLE")
        self.assertEqual(review["price_failure_count"], 1)
        self.assertEqual(review["unplanned_trades"][0]["symbol"], "NVDA")

    def test_build_execution_review_handles_missing_plan(self):
        review = self.module.build_execution_review(None, [], day="2026-05-13")

        self.assertEqual(review["status"], "NO_PLAN")
        self.assertIsNone(review["decision_signature"])
        self.assertEqual(review["executed_count"], 0)
        self.assertEqual(review["items"], [])

    def test_build_execution_review_marks_buy_plan_invalidated_when_gap_above_max_chase(self):
        review = self.module.build_execution_review(
            {
                "plan_date": "2026-05-13",
                "decision_signature": "sig-456",
                "items": [
                    {
                        "symbol": "QQQ",
                        "plan_action": "ACCUMULATE",
                        "buy_zone_low": 480.0,
                        "buy_zone_high": 485.0,
                        "max_chase_price": 489.0,
                    }
                ],
            },
            [],
            day="2026-05-13",
            market_day_ranges={"QQQ": {"open": 495.0, "high": 501.0, "low": 492.0, "close": 499.0}},
        )

        self.assertEqual(review["missed_count"], 1)
        self.assertEqual(review["invalidated_count"], 1)
        self.assertEqual(review["price_failure_count"], 1)
        self.assertEqual(review["items"][0]["opportunity_status"], "INVALIDATED")


if __name__ == "__main__":
    unittest.main()
