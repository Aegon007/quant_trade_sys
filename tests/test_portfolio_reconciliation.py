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

    def test_build_robinhood_reconciled_portfolio_handles_same_day_sell_before_buys(self):
        from quant_core.portfolio.reconciliation import build_robinhood_reconciled_portfolio

        records = [
            {
                "record_type": "TRADE",
                "event_type": "SELL",
                "side": "SELL",
                "date": "2026-04-07 00:00:00",
                "symbol": "SQQQ",
                "shares": 0.7,
                "price": 77.2,
                "proceeds": 54.04,
                "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
            },
            {
                "record_type": "TRADE",
                "event_type": "BUY",
                "side": "BUY",
                "date": "2026-04-07 00:00:00",
                "symbol": "SQQQ",
                "shares": 0.2,
                "price": 79.06,
                "cost_basis": 79.06,
                "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
            },
            {
                "record_type": "TRADE",
                "event_type": "BUY",
                "side": "BUY",
                "date": "2026-04-07 00:00:00",
                "symbol": "SQQQ",
                "shares": 0.3,
                "price": 78.64,
                "cost_basis": 78.64,
                "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
            },
            {
                "record_type": "TRADE",
                "event_type": "BUY",
                "side": "BUY",
                "date": "2026-04-07 00:00:00",
                "symbol": "SQQQ",
                "shares": 0.2,
                "price": 77.23,
                "cost_basis": 77.23,
                "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
            },
        ]

        result = build_robinhood_reconciled_portfolio(
            records,
            existing_data={
                "account": {},
                "holdings": [{"symbol": "SQQQ", "shares": 0.7, "cost": 78.0, "current_price": 77.2, "sector": ""}],
                "watchlist": [],
            },
        )

        self.assertEqual(result["holdings"], [])
        self.assertEqual([row["symbol"] for row in result["watchlist"]], ["SQQQ"])
        self.assertEqual(result["issues"], [])

    def test_build_robinhood_reconciled_portfolio_preserves_cash_when_cash_events_are_missing(self):
        from quant_core.portfolio.reconciliation import build_robinhood_reconciled_portfolio

        result = build_robinhood_reconciled_portfolio(
            [
                {
                    "record_type": "TRADE",
                    "event_type": "BUY",
                    "side": "BUY",
                    "date": "2026-04-07 00:00:00",
                    "symbol": "SQQQ",
                    "shares": 0.7,
                    "price": 79.0,
                    "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                },
                {
                    "record_type": "TRADE",
                    "event_type": "SELL",
                    "side": "SELL",
                    "date": "2026-04-08 00:00:00",
                    "symbol": "SQQQ",
                    "shares": 0.7,
                    "price": 78.0,
                    "proceeds": 54.6,
                    "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                },
                {
                    "record_type": "TRADE",
                    "event_type": "BUY",
                    "side": "BUY",
                    "date": "2026-04-09 00:00:00",
                    "symbol": "AAPL",
                    "shares": 1.0,
                    "price": 200.0,
                    "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                },
            ],
            existing_data={
                "account": {"cash_available": 123.45},
                "holdings": [{"symbol": "SQQQ", "shares": 0.7, "cost": 79.0, "current_price": 78.0, "sector": ""}],
                "watchlist": [],
            },
        )

        self.assertEqual(result["cash_mode"], "trade_flows_only")
        self.assertEqual(result["cash_available"], 123.45)
        self.assertLess(result["trade_cash_flow"], 0)
        self.assertEqual([row["symbol"] for row in result["holdings"]], ["AAPL"])
        self.assertEqual([row["symbol"] for row in result["watchlist"]], ["SQQQ"])

    def test_build_robinhood_reconciled_portfolio_preserves_cash_when_imported_cash_is_negative(self):
        from quant_core.portfolio.reconciliation import build_robinhood_reconciled_portfolio

        result = build_robinhood_reconciled_portfolio(
            [
                {
                    "record_type": "CASH_EVENT",
                    "event_type": "CASH_WITHDRAWAL",
                    "side": "",
                    "date": "2026-04-07 00:00:00",
                    "symbol": "",
                    "shares": None,
                    "price": None,
                    "proceeds": -1000.0,
                    "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                },
                {
                    "record_type": "TRADE",
                    "event_type": "BUY",
                    "side": "BUY",
                    "date": "2026-04-08 00:00:00",
                    "symbol": "AAPL",
                    "shares": 1.0,
                    "price": 200.0,
                    "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                },
            ],
            existing_data={
                "account": {"cash_available": 321.0},
                "holdings": [],
                "watchlist": [],
            },
        )

        self.assertEqual(result["cash_mode"], "cash_preserved_incomplete_csv")
        self.assertEqual(result["cash_available"], 321.0)
        self.assertLess(result["trade_cash_flow"], 0)
        self.assertEqual([row["symbol"] for row in result["holdings"]], ["AAPL"])
        self.assertTrue(any("preserved existing cash_available" in issue for issue in result["issues"]))

    def test_build_robinhood_reconciled_portfolio_applies_reverse_split_actions(self):
        from quant_core.portfolio.reconciliation import build_robinhood_reconciled_portfolio

        result = build_robinhood_reconciled_portfolio(
            [
                {
                    "record_type": "TRADE",
                    "event_type": "BUY",
                    "side": "BUY",
                    "date": "2025-10-28 00:00:00",
                    "symbol": "TSLZ",
                    "shares": 300.0,
                    "price": 0.62,
                    "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                },
                {
                    "record_type": "CORPORATE_ACTION",
                    "event_type": "SHARE_DECREASE",
                    "side": "REMOVE",
                    "date": "2025-10-29 00:00:00",
                    "symbol": "TSLZ",
                    "shares": 300.0,
                    "price": None,
                    "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                },
                {
                    "record_type": "CORPORATE_ACTION",
                    "event_type": "SHARE_INCREASE",
                    "side": "ADD",
                    "date": "2025-10-29 00:00:00",
                    "symbol": "TSLZ",
                    "shares": 15.0,
                    "price": None,
                    "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                },
                {
                    "record_type": "TRADE",
                    "event_type": "SELL",
                    "side": "SELL",
                    "date": "2025-11-07 00:00:00",
                    "symbol": "TSLZ",
                    "shares": 15.0,
                    "price": 14.0,
                    "proceeds": 210.0,
                    "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                },
            ],
            existing_data={"account": {"cash_available": 0.0}, "holdings": [], "watchlist": []},
        )

        self.assertEqual(result["holdings"], [])
        self.assertEqual([row["symbol"] for row in result["watchlist"]], ["TSLZ"])

    def test_build_robinhood_reconciled_portfolio_uses_net_shares_to_close_false_residuals(self):
        from quant_core.portfolio.reconciliation import build_robinhood_reconciled_portfolio

        result = build_robinhood_reconciled_portfolio(
            [
                {
                    "record_type": "TRADE",
                    "event_type": "SELL",
                    "side": "SELL",
                    "date": "2026-01-03 00:00:00",
                    "symbol": "AMD",
                    "shares": 0.1,
                    "price": 100.0,
                    "proceeds": 10.0,
                    "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                },
                {
                    "record_type": "TRADE",
                    "event_type": "BUY",
                    "side": "BUY",
                    "date": "2026-01-04 00:00:00",
                    "symbol": "AMD",
                    "shares": 0.1,
                    "price": 101.0,
                    "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                },
            ],
            existing_data={
                "account": {"cash_available": 0.0},
                "holdings": [{"symbol": "AMD", "shares": 0.1, "cost": 100.0, "current_price": 101.0, "sector": ""}],
                "watchlist": [],
            },
        )

        self.assertEqual(result["holdings"], [])
        self.assertEqual([row["symbol"] for row in result["watchlist"]], ["AMD"])

    def test_build_robinhood_reconciled_portfolio_suppresses_dust_value_positions(self):
        from quant_core.portfolio.reconciliation import build_robinhood_reconciled_portfolio

        result = build_robinhood_reconciled_portfolio(
            [
                {
                    "record_type": "TRADE",
                    "event_type": "BUY",
                    "side": "BUY",
                    "date": "2026-01-04 00:00:00",
                    "symbol": "SPY",
                    "shares": 0.002,
                    "price": 600.0,
                    "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                },
                {
                    "record_type": "TRADE",
                    "event_type": "BUY",
                    "side": "BUY",
                    "date": "2026-01-04 00:00:00",
                    "symbol": "MSFT",
                    "shares": 0.05,
                    "price": 400.0,
                    "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                },
            ],
            existing_data={"account": {"cash_available": 0.0}, "holdings": [], "watchlist": []},
        )

        self.assertEqual([row["symbol"] for row in result["holdings"]], ["MSFT"])
        self.assertIn("SPY", [row["symbol"] for row in result["watchlist"]])
        self.assertTrue(any("Suppressed dust-level" in issue for issue in result["issues"]))


if __name__ == "__main__":
    unittest.main()
