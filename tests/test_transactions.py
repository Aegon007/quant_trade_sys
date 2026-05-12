import unittest


class TransactionsSchemaTests(unittest.TestCase):
    def test_normalize_transaction_record_supports_legacy_trade_shape(self):
        from quant_core.ledger.transactions import normalize_transaction_record

        normalized = normalize_transaction_record(
            {
                "date": "2026-05-10 09:30",
                "symbol": "aapl",
                "shares": 1.5,
                "sell_price": 200.0,
                "cost_basis": 150.0,
                "proceeds": 300.0,
                "pl": 75.0,
                "pl_pct": 33.3,
            }
        )

        self.assertEqual(normalized["record_type"], "TRADE")
        self.assertEqual(normalized["event_type"], "SELL")
        self.assertEqual(normalized["side"], "SELL")
        self.assertEqual(normalized["symbol"], "AAPL")
        self.assertEqual(normalized["price"], 200.0)

    def test_filter_transactions_supports_event_side_and_symbol(self):
        from quant_core.ledger.transactions import filter_transactions

        rows = [
            {"record_type": "TRADE", "event_type": "SELL", "side": "SELL", "symbol": "AAPL", "shares": 1.0},
            {"record_type": "PORTFOLIO_EVENT", "event_type": "MOVE_TO_HOLDING", "side": "BUY", "symbol": "MSFT", "shares": 2.0},
            {"record_type": "PORTFOLIO_EVENT", "event_type": "MOVE_TO_WATCH", "side": "SELL", "symbol": "NVDA", "shares": 1.0},
        ]

        self.assertEqual(len(filter_transactions(rows, event_type="MOVE_TO_HOLDING")), 1)
        self.assertEqual(len(filter_transactions(rows, side="SELL")), 2)
        filtered = filter_transactions(rows, symbol="MSFT", side="BUY")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["event_type"], "MOVE_TO_HOLDING")

    def test_summarize_daily_activity_aggregates_realized_pl_and_symbols(self):
        from quant_core.ledger.transactions import summarize_daily_activity

        rows = [
            {
                "record_type": "TRADE",
                "event_type": "BUY",
                "side": "BUY",
                "date": "2026-05-10 09:30",
                "symbol": "AAPL",
                "shares": 1.0,
                "price": 100.0,
            },
            {
                "record_type": "TRADE",
                "event_type": "SELL",
                "side": "SELL",
                "date": "2026-05-10 15:45",
                "symbol": "AAPL",
                "shares": 1.0,
                "price": 110.0,
                "pl": 10.0,
            },
            {
                "record_type": "PORTFOLIO_EVENT",
                "event_type": "MOVE_TO_WATCH",
                "side": "SELL",
                "date": "2026-05-10 15:46",
                "symbol": "MSFT",
                "shares": 2.0,
            },
            {
                "record_type": "TRADE",
                "event_type": "SELL",
                "side": "SELL",
                "date": "2026-05-09 15:45",
                "symbol": "NVDA",
                "shares": 1.0,
                "price": 90.0,
                "pl": -5.0,
            },
        ]

        recap = summarize_daily_activity(rows, day="2026-05-10")

        self.assertEqual(recap["day"], "2026-05-10")
        self.assertEqual(recap["trade_count"], 2)
        self.assertEqual(recap["buy_count"], 1)
        self.assertEqual(recap["sell_count"], 1)
        self.assertEqual(recap["portfolio_event_count"], 1)
        self.assertEqual(recap["realized_pl"], 10.0)
        self.assertEqual(recap["symbols"], ["AAPL", "MSFT"])
        self.assertEqual(recap["largest_win"]["symbol"], "AAPL")

    def test_normalize_transaction_record_preserves_import_metadata(self):
        from quant_core.ledger.transactions import normalize_transaction_record

        normalized = normalize_transaction_record(
            {
                "date": "2026-05-10 09:30",
                "symbol": "AAPL",
                "event_type": "BUY",
                "side": "BUY",
                "shares": 1.0,
                "price": 100.0,
                "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                "import_key": "abc123",
            }
        )

        self.assertEqual(normalized["source"], "ROBINHOOD_ACCOUNT_ACTIVITY_CSV")
        self.assertEqual(normalized["import_key"], "abc123")

    def test_normalize_transaction_record_keeps_cash_event_side_blank(self):
        from quant_core.ledger.transactions import normalize_transaction_record

        normalized = normalize_transaction_record(
            {
                "record_type": "CASH_EVENT",
                "event_type": "CASH_DEPOSIT",
                "date": "2026-05-10 09:00:00",
                "proceeds": 1000.0,
            }
        )

        self.assertEqual(normalized["side"], "")


if __name__ == "__main__":
    unittest.main()
