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


if __name__ == "__main__":
    unittest.main()
