import tempfile
import unittest
from pathlib import Path

from tests.support import clear_modules, install_fake_yfinance, reload_module


class PortfolioActionsTests(unittest.TestCase):
    def setUp(self):
        install_fake_yfinance()
        clear_modules(
            "share_utils",
            "quant_core.data.storage",
            "quant_core.ledger.transactions",
            "quant_core.portfolio.actions",
        )
        self.data_utils = reload_module("quant_core.data.storage")
        self.transactions = reload_module("quant_core.ledger.transactions")
        self.actions = reload_module("quant_core.portfolio.actions")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)

        self.data_utils.DATA_FILE = str(root / "portfolio_data.json")
        self.data_utils.CACHE_FILE = str(root / "price_cache.json")
        self.data_utils.EDITABLE_DATA_FILE = str(root / "portfolio_input.json")
        self.transactions.TRANS_FILE = str(root / "transactions.json")
        self.actions.du.DATA_FILE = self.data_utils.DATA_FILE
        self.actions.du.CACHE_FILE = self.data_utils.CACHE_FILE
        self.actions.du.EDITABLE_DATA_FILE = self.data_utils.EDITABLE_DATA_FILE
        self.actions.tx.TRANS_FILE = self.transactions.TRANS_FILE

    def test_buy_symbol_moves_watchlist_entry_to_holdings_and_reduces_cash(self):
        self.data_utils.save_data(
            {
                "account": {
                    "total_capital": 10000.0,
                    "cash_available": 3000.0,
                    "min_cash_buffer_pct": 0.1,
                    "max_single_position_pct": 0.2,
                    "max_total_exposure_pct": 1.0,
                },
                "holdings": [],
                "watchlist": [
                    {"symbol": "MSFT", "notes": "watch", "last_price": 310.0}
                ],
            }
        )

        result = self.actions.buy_symbol("MSFT", 1.5)
        data = self.data_utils.load_data()
        transactions = self.transactions.load_transactions()

        self.assertEqual(result["symbol"], "MSFT")
        self.assertEqual(result["shares"], 1.5)
        self.assertEqual(result["price"], 310.0)
        self.assertEqual(data["watchlist"], [])
        self.assertEqual(data["holdings"][0]["symbol"], "MSFT")
        self.assertEqual(data["holdings"][0]["shares"], 1.5)
        self.assertEqual(data["account"]["cash_available"], 2535.0)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]["record_type"], "TRADE")
        self.assertEqual(transactions[0]["event_type"], "BUY")
        self.assertEqual(transactions[0]["side"], "BUY")

    def test_sell_all_symbol_moves_holding_to_watchlist_and_increases_cash(self):
        self.data_utils.save_data(
            {
                "account": {
                    "total_capital": 10000.0,
                    "cash_available": 1000.0,
                    "min_cash_buffer_pct": 0.1,
                    "max_single_position_pct": 0.2,
                    "max_total_exposure_pct": 1.0,
                },
                "holdings": [
                    {"symbol": "AAPL", "shares": 2.0, "cost": 150.0, "current_price": 200.0, "sector": "Tech"}
                ],
                "watchlist": [],
            }
        )

        result = self.actions.sell_all_symbol("AAPL")
        data = self.data_utils.load_data()
        transactions = self.transactions.load_transactions()

        self.assertEqual(result["symbol"], "AAPL")
        self.assertEqual(result["shares"], 2.0)
        self.assertEqual(data["holdings"], [])
        self.assertEqual(data["watchlist"][0]["symbol"], "AAPL")
        self.assertEqual(data["watchlist"][0]["last_price"], 200.0)
        self.assertEqual(data["account"]["cash_available"], 1400.0)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]["symbol"], "AAPL")

    def test_sell_symbol_reduces_shares_and_adds_cash(self):
        self.data_utils.save_data(
            {
                "account": {
                    "total_capital": 10000.0,
                    "cash_available": 500.0,
                    "min_cash_buffer_pct": 0.1,
                    "max_single_position_pct": 0.2,
                    "max_total_exposure_pct": 1.0,
                },
                "holdings": [
                    {"symbol": "NVDA", "shares": 1.5, "cost": 100.0, "current_price": 125.0, "sector": "Tech"}
                ],
                "watchlist": [],
            }
        )

        result = self.actions.sell_symbol("NVDA", 0.5)
        data = self.data_utils.load_data()
        transactions = self.transactions.load_transactions()

        self.assertEqual(result["symbol"], "NVDA")
        self.assertEqual(data["holdings"][0]["shares"], 1.0)
        self.assertEqual(data["account"]["cash_available"], 562.5)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]["shares"], 0.5)

    def test_move_holding_to_watch_adds_portfolio_event_record(self):
        self.data_utils.save_data(
            {
                "account": {
                    "total_capital": 10000.0,
                    "cash_available": 1000.0,
                    "min_cash_buffer_pct": 0.1,
                    "max_single_position_pct": 0.2,
                    "max_total_exposure_pct": 1.0,
                },
                "holdings": [
                    {"symbol": "AAPL", "shares": 1.0, "cost": 150.0, "current_price": 200.0, "sector": "Tech"}
                ],
                "watchlist": [],
            }
        )

        self.actions.move_holding_to_watch("AAPL", notes="manual move")
        transactions = self.transactions.load_transactions()

        self.assertEqual(len(transactions), 2)
        self.assertEqual(transactions[-1]["record_type"], "PORTFOLIO_EVENT")
        self.assertEqual(transactions[-1]["event_type"], "MOVE_TO_WATCH")
        self.assertEqual(transactions[-1]["symbol"], "AAPL")
        self.assertEqual(transactions[-1]["side"], "SELL")

    def test_move_watch_to_holding_adds_portfolio_event_record(self):
        self.data_utils.save_data(
            {
                "account": {
                    "total_capital": 10000.0,
                    "cash_available": 3000.0,
                    "min_cash_buffer_pct": 0.1,
                    "max_single_position_pct": 0.2,
                    "max_total_exposure_pct": 1.0,
                },
                "holdings": [],
                "watchlist": [{"symbol": "MSFT", "notes": "watch", "last_price": 310.0}],
            }
        )

        self.actions.move_watch_to_holding("MSFT", 1.5)
        transactions = self.transactions.load_transactions()

        self.assertEqual(len(transactions), 2)
        self.assertEqual(transactions[0]["record_type"], "TRADE")
        self.assertEqual(transactions[0]["event_type"], "BUY")
        self.assertEqual(transactions[0]["side"], "BUY")
        self.assertEqual(transactions[-1]["record_type"], "PORTFOLIO_EVENT")
        self.assertEqual(transactions[-1]["event_type"], "MOVE_TO_HOLDING")
        self.assertEqual(transactions[-1]["symbol"], "MSFT")
        self.assertEqual(transactions[-1]["side"], "BUY")
        self.assertEqual(transactions[-1]["shares"], 1.5)

    def test_remove_holding_record_removes_position_without_cash_change(self):
        self.data_utils.save_data(
            {
                "account": {
                    "cash_available": 3000.0,
                },
                "holdings": [
                    {"symbol": "AAPL", "shares": 1.0, "cost": 100.0, "current_price": 120.0, "sector": "Tech"}
                ],
                "watchlist": [],
            }
        )

        self.actions.remove_holding_record("AAPL", notes="cleanup")
        data = self.data_utils.load_data()
        transactions = self.transactions.load_transactions()

        self.assertEqual(data["holdings"], [])
        self.assertEqual(data["account"]["cash_available"], 3000.0)
        self.assertEqual(transactions[-1]["event_type"], "REMOVE_HOLDING")

    def test_clear_all_holdings_removes_every_position_without_cash_change(self):
        self.data_utils.save_data(
            {
                "account": {
                    "cash_available": 3500.0,
                },
                "holdings": [
                    {"symbol": "AAPL", "shares": 1.0, "cost": 100.0, "current_price": 120.0, "sector": "Tech"},
                    {"symbol": "MSFT", "shares": 2.0, "cost": 200.0, "current_price": 220.0, "sector": "Tech"},
                ],
                "watchlist": [],
            }
        )

        result = self.actions.clear_all_holdings(notes="reset")
        data = self.data_utils.load_data()
        transactions = self.transactions.load_transactions()

        self.assertEqual(result["count"], 2)
        self.assertEqual(data["holdings"], [])
        self.assertEqual(data["account"]["cash_available"], 3500.0)
        self.assertEqual(len(transactions), 2)
        self.assertTrue(all(row["event_type"] == "REMOVE_HOLDING" for row in transactions))


if __name__ == "__main__":
    unittest.main()
