import unittest

from quant_core.notifications.change_feed import build_change_feed


class MultiEngineChangeFeedTests(unittest.TestCase):
    def test_trend_confirmation_and_etf_pacing_changes_are_published(self):
        previous = {
            "recommendations": [],
            "trend_signals": [{"symbol": "MU", "recommendation": "TREND_WATCH", "actionable": False}],
            "etf_allocations": [{"symbol": "QQQM", "action": "REGULAR_DCA"}],
        }
        current = {
            "recommendations": [],
            "trend_signals": [{"symbol": "MU", "recommendation": "TREND_CONFIRMED", "actionable": True, "signal_score": 76}],
            "etf_allocations": [{"symbol": "QQQM", "action": "REDUCE_PACE"}],
        }

        feed = build_change_feed(previous, current)

        categories = {row["category"] for row in feed["items"]}
        self.assertIn("new_trend_signal", categories)
        self.assertIn("etf_pacing_change", categories)
        self.assertEqual(feed["summary"]["high_count"], 1)


if __name__ == "__main__":
    unittest.main()
