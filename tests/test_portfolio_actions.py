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

    def test_refresh_all_market_data_can_force_source_refresh(self):
        calls = []
        self.actions.du.load_data = lambda: {"holdings": [{"symbol": "AAPL"}], "watchlist": []}
        self.actions.du.refresh_market_data = lambda data, **kwargs: (calls.append(kwargs) or {**data, "prices_last_updated": "2026-05-11T10:00:00"})
        self.actions.du.save_data = lambda data: None

        result = self.actions.refresh_all_market_data(force_source_refresh=True)

        self.assertEqual(result["prices_last_updated"], "2026-05-11T10:00:00")
        self.assertEqual(calls, [{"force_source_refresh": True}])

    def test_reconcile_portfolio_from_robinhood_imports_updates_holdings_and_cash(self):
        self.data_utils.save_data(
            {
                "account": {
                    "cash_available": 0.0,
                    "min_cash_buffer_pct": 0.1,
                    "max_single_position_pct": 0.2,
                    "max_total_exposure_pct": 0.9,
                },
                "holdings": [],
                "watchlist": [{"symbol": "TSLA", "notes": "keep", "last_price": 300.0}],
            }
        )
        self.transactions.save_transactions(
            [
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
                    "event_type": "SELL",
                    "side": "SELL",
                    "date": "2026-05-10 15:45:00",
                    "symbol": "AAPL",
                    "shares": 0.5,
                    "price": 120.0,
                    "proceeds": 60.0,
                    "source": "ROBINHOOD_ACCOUNT_ACTIVITY_CSV",
                },
            ]
        )

        result = self.actions.reconcile_portfolio_from_robinhood_imports()
        data = self.data_utils.load_data()

        self.assertAlmostEqual(result["cash_available"], 860.0)
        self.assertEqual(result["cash_mode"], "imported_cash_events")
        self.assertEqual(len(data["holdings"]), 1)
        self.assertEqual(data["holdings"][0]["symbol"], "AAPL")
        self.assertAlmostEqual(data["holdings"][0]["shares"], 1.5)
        self.assertAlmostEqual(data["holdings"][0]["cost"], 100.0)
        self.assertAlmostEqual(data["account"]["cash_available"], 860.0)
        self.assertEqual(data["watchlist"][0]["symbol"], "TSLA")

    def test_reconcile_portfolio_from_robinhood_imports_requires_imported_records(self):
        self.data_utils.save_data(
            {
                "account": {"cash_available": 100.0},
                "holdings": [{"symbol": "AAPL", "shares": 1.0, "cost": 100.0, "current_price": 110.0, "sector": "Tech"}],
                "watchlist": [],
            }
        )
        self.transactions.save_transactions([])

        with self.assertRaises(ValueError):
            self.actions.reconcile_portfolio_from_robinhood_imports()

    def test_add_watch_symbol_appends_new_watch_without_cash_change(self):
        self.data_utils.save_data(
            {
                "account": {
                    "cash_available": 3500.0,
                },
                "holdings": [],
                "watchlist": [],
            }
        )

        result = self.actions.add_watch_symbol("QQQ", notes="index ETF")
        data = self.data_utils.load_data()

        self.assertEqual(result["symbol"], "QQQ")
        self.assertEqual(len(data["watchlist"]), 1)
        self.assertEqual(data["watchlist"][0]["symbol"], "QQQ")
        self.assertEqual(data["watchlist"][0]["notes"], "index ETF")
        self.assertEqual(data["account"]["cash_available"], 3500.0)

    def test_remove_watch_symbol_deletes_existing_watch(self):
        self.data_utils.save_data(
            {
                "account": {
                    "cash_available": 3500.0,
                },
                "holdings": [],
                "watchlist": [{"symbol": "TSLA", "notes": "volatile", "last_price": 180.0}],
            }
        )

        result = self.actions.remove_watch_symbol("TSLA")
        data = self.data_utils.load_data()

        self.assertEqual(result["symbol"], "TSLA")
        self.assertEqual(data["watchlist"], [])
        self.assertEqual(data["account"]["cash_available"], 3500.0)


if __name__ == "__main__":
    unittest.main()
