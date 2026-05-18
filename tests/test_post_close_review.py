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
        )

        self.assertEqual(review["executed_count"], 1)
        self.assertEqual(review["missed_count"], 1)
        self.assertEqual(review["unplanned_trade_count"], 1)
        self.assertEqual(review["items"][0]["status"], "EXECUTED")
        self.assertTrue(review["items"][0]["executed_in_plan_zone"])
        self.assertEqual(review["items"][1]["status"], "MISSED")
        self.assertEqual(review["unplanned_trades"][0]["symbol"], "NVDA")

    def test_build_execution_review_handles_missing_plan(self):
        review = self.module.build_execution_review(None, [], day="2026-05-13")

        self.assertEqual(review["status"], "NO_PLAN")
        self.assertEqual(review["executed_count"], 0)
        self.assertEqual(review["items"], [])


if __name__ == "__main__":
    unittest.main()
