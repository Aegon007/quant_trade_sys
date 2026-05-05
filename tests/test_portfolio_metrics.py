import unittest


class PortfolioSummaryTests(unittest.TestCase):
    def test_summarize_holdings_tracks_missing_prices_without_distorting_pl(self):
        from portfolio_metrics import summarize_holdings

        summary = summarize_holdings(
            [
                {"symbol": "AAPL", "shares": 10, "cost": 100.0, "current_price": 110.0},
                {"symbol": "MSFT", "shares": 5, "cost": 200.0, "current_price": None},
            ]
        )

        self.assertEqual(summary.total_cost, 2000.0)
        self.assertEqual(summary.priced_cost, 1000.0)
        self.assertEqual(summary.total_value, 1100.0)
        self.assertEqual(summary.total_pl, 100.0)
        self.assertEqual(summary.total_pl_pct, 10.0)
        self.assertEqual(summary.missing_price_count, 1)


if __name__ == "__main__":
    unittest.main()

