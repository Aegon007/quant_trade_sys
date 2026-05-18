import unittest


class PortfolioReconciliationTests(unittest.TestCase):
    def test_build_robinhood_reconciled_portfolio_reconstructs_holdings_watchlist_and_cash(self):
        from quant_core.portfolio.reconciliation import build_robinhood_reconciled_portfolio

        records = [
            {
                "record_type": "CASH_EVENT",
                "event_type": "CASH_DEPOSIT",
                "side": "",
                "date": "2026-05-10 09:00:00",
                "symbol": "",
                "shares": None,
                "price": None,
                "proceeds": 1000.0,
                "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
            },
            {
                "record_type": "TRADE",
                "event_type": "BUY",
                "side": "BUY",
                "date": "2026-05-10 09:30:00",
                "symbol": "AAPL",
                "shares": 2.0,
                "price": 100.0,
                "cost_basis": 100.0,
                "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
            },
            {
                "record_type": "TRADE",
                "event_type": "BUY",
                "side": "BUY",
                "date": "2026-05-10 10:30:00",
                "symbol": "MSFT",
                "shares": 1.0,
                "price": 200.0,
                "cost_basis": 200.0,
                "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
            },
            {
                "record_type": "TRADE",
                "event_type": "SELL",
                "side": "SELL",
                "date": "2026-05-10 15:45:00",
                "symbol": "AAPL",
                "shares": 0.5,
                "price": 120.0,
                "proceeds": 60.0,
                "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
            },
            {
                "record_type": "CASH_EVENT",
                "event_type": "DIVIDEND",
                "side": "",
                "date": "2026-05-10 16:00:00",
                "symbol": "AAPL",
                "shares": None,
                "price": None,
                "proceeds": 5.0,
                "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
            },
        ]

        existing_data = {
            "account": {
                "cash_available": 123.0,
                "min_cash_buffer_pct": 0.1,
                "max_single_position_pct": 0.2,
                "max_total_exposure_pct": 0.9,
            },
            "holdings": [
                {"symbol": "AAPL", "shares": 1.0, "cost": 90.0, "current_price": 130.0, "sector": "Tech"}
            ],
            "watchlist": [
                {"symbol": "MSFT", "notes": "watch", "last_price": 210.0},
                {"symbol": "TSLA", "notes": "keep", "last_price": 300.0},
            ],
        }

        result = build_robinhood_reconciled_portfolio(records, existing_data=existing_data)

        self.assertAlmostEqual(result["cash_available"], 665.0)
        self.assertEqual(result["cash_mode"], "imported_cash_events")
        self.assertEqual([row["symbol"] for row in result["holdings"]], ["AAPL", "MSFT"])
        self.assertAlmostEqual(result["holdings"][0]["shares"], 1.5)
        self.assertAlmostEqual(result["holdings"][0]["cost"], 100.0)
        self.assertEqual(result["holdings"][0]["current_price"], 130.0)
        self.assertEqual(result["holdings"][0]["sector"], "Tech")
        self.assertEqual(result["holdings"][1]["current_price"], 210.0)
        self.assertEqual([row["symbol"] for row in result["watchlist"]], ["TSLA"])
        self.assertEqual(result["issues"], [])

    def test_build_robinhood_reconciled_portfolio_reports_oversell_issue_for_partial_history(self):
        from quant_core.portfolio.reconciliation import build_robinhood_reconciled_portfolio

        records = [
            {
                "record_type": "TRADE",
                "event_type": "SELL",
                "side": "SELL",
                "date": "2026-05-10 15:45:00",
                "symbol": "AAPL",
                "shares": 1.0,
                "price": 120.0,
                "proceeds": 120.0,
                "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
            }
        ]

        result = build_robinhood_reconciled_portfolio(records, existing_data={"holdings": [], "watchlist": [], "account": {}})

        self.assertTrue(any("AAPL" in issue for issue in result["issues"]))
        self.assertEqual(result["holdings"], [])

    def test_build_robinhood_reconciled_portfolio_moves_fully_sold_symbol_back_to_watchlist(self):
        from quant_core.portfolio.reconciliation import build_robinhood_reconciled_portfolio

        records = [
            {
                "record_type": "TRADE",
                "event_type": "BUY",
                "side": "BUY",
                "date": "2026-05-10 09:30:00",
                "symbol": "AAPL",
                "shares": 1.0,
                "price": 100.0,
                "cost_basis": 100.0,
                "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
            },
            {
                "record_type": "TRADE",
                "event_type": "SELL",
                "side": "SELL",
                "date": "2026-05-10 15:45:00",
                "symbol": "AAPL",
                "shares": 1.0,
                "price": 120.0,
                "proceeds": 120.0,
                "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
            },
        ]

        result = build_robinhood_reconciled_portfolio(
            records,
            existing_data={
                "account": {},
                "holdings": [{"symbol": "AAPL", "shares": 1.0, "cost": 90.0, "current_price": 118.0, "sector": "Tech"}],
                "watchlist": [],
            },
        )

        self.assertEqual(result["holdings"], [])
        self.assertEqual([row["symbol"] for row in result["watchlist"]], ["AAPL"])
        self.assertEqual(result["watchlist"][0]["last_price"], 118.0)


if __name__ == "__main__":
    unittest.main()
