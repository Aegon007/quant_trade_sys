import tempfile
import unittest
from pathlib import Path
import os
import json

from tests.support import clear_modules, install_fake_yfinance, reload_module


class DataUtilsFractionalShareTests(unittest.TestCase):
    def setUp(self):
        install_fake_yfinance()
        clear_modules("share_utils", "data_utils")
        self.data_utils = reload_module("data_utils")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.data_utils.DATA_FILE = str(root / "portfolio_data.json")
        self.data_utils.CACHE_FILE = str(root / "price_cache.json")
        self.data_utils.EDITABLE_DATA_FILE = str(root / "portfolio_input.json")

    def test_add_holding_persists_fractional_shares(self):
        self.data_utils.add_holding("AAPL", 0.125, 100.0)

        data = self.data_utils.load_data()

        self.assertEqual(data["holdings"][0]["shares"], 0.125)

    def test_add_holding_rejects_smaller_than_minimum_trade_unit(self):
        with self.assertRaises(ValueError):
            self.data_utils.add_holding("AAPL", 0.0009, 100.0)

    def test_sell_partial_holding_supports_fractional_shares(self):
        self.data_utils.add_holding("AAPL", 1.125, 100.0)

        symbol, cost_basis = self.data_utils.sell_partial_holding(0, 0.375, 110.0)
        data = self.data_utils.load_data()

        self.assertEqual(symbol, "AAPL")
        self.assertEqual(cost_basis, 100.0)
        self.assertEqual(data["holdings"][0]["shares"], 0.75)

    def test_load_data_imports_newer_editable_portfolio_file(self):
        editable_path = Path(self.data_utils.EDITABLE_DATA_FILE)
        editable_path.write_text(json.dumps({
            "holdings": [
                {"symbol": "aapl", "shares": 0.125, "cost": 180.5, "sector": "Technology"}
            ],
            "watchlist": [
                {"symbol": "msft", "notes": "wait for pullback", "target_buy": 390}
            ]
        }), encoding="utf-8")

        data = self.data_utils.load_data()

        self.assertEqual(data["holdings"][0]["symbol"], "AAPL")
        self.assertEqual(data["holdings"][0]["shares"], 0.125)
        self.assertEqual(data["holdings"][0]["cost"], 180.5)
        self.assertEqual(data["holdings"][0]["sector"], "Technology")
        self.assertIsNone(data["holdings"][0]["current_price"])
        self.assertEqual(data["watchlist"][0]["symbol"], "MSFT")
        self.assertEqual(data["watchlist"][0]["notes"], "wait for pullback")
        self.assertEqual(data["watchlist"][0]["target_buy"], 390.0)
        self.assertIsNone(data["watchlist"][0]["last_price"])

    def test_editable_portfolio_import_preserves_runtime_prices(self):
        self.data_utils.save_data({
            "holdings": [
                {"symbol": "AAPL", "shares": 1, "cost": 150, "current_price": 222.22}
            ],
            "watchlist": [
                {"symbol": "MSFT", "notes": "old", "target_buy": 350, "last_price": 410.5}
            ]
        })
        editable_path = Path(self.data_utils.EDITABLE_DATA_FILE)
        editable_path.write_text(json.dumps({
            "holdings": [
                {"symbol": "AAPL", "shares": 0.5, "cost": 180, "sector": "Technology"}
            ],
            "watchlist": [
                {"symbol": "MSFT", "notes": "new", "target_buy": 390}
            ]
        }), encoding="utf-8")
        os.utime(editable_path, (Path(self.data_utils.DATA_FILE).stat().st_mtime + 10,) * 2)

        data = self.data_utils.load_data()

        self.assertEqual(data["holdings"][0]["shares"], 0.5)
        self.assertEqual(data["holdings"][0]["current_price"], 222.22)
        self.assertEqual(data["watchlist"][0]["notes"], "new")
        self.assertEqual(data["watchlist"][0]["last_price"], 410.5)

    def test_older_editable_portfolio_file_does_not_override_runtime_data(self):
        editable_path = Path(self.data_utils.EDITABLE_DATA_FILE)
        editable_path.write_text(json.dumps({
            "holdings": [
                {"symbol": "AAPL", "shares": 0.5, "cost": 180}
            ],
            "watchlist": []
        }), encoding="utf-8")
        self.data_utils.save_data({
            "holdings": [
                {"symbol": "NVDA", "shares": 1.25, "cost": 190, "current_price": 205}
            ],
            "watchlist": []
        })
        os.utime(editable_path, (Path(self.data_utils.DATA_FILE).stat().st_mtime - 10,) * 2)

        data = self.data_utils.load_data()

        self.assertEqual(data["holdings"][0]["symbol"], "NVDA")

    def test_force_editable_portfolio_sync_reloads_even_when_file_is_older(self):
        editable_path = Path(self.data_utils.EDITABLE_DATA_FILE)
        editable_path.write_text(json.dumps({
            "holdings": [
                {"symbol": "AAPL", "shares": 0.5, "cost": 180}
            ],
            "watchlist": []
        }), encoding="utf-8")
        self.data_utils.save_data({
            "holdings": [
                {"symbol": "NVDA", "shares": 1.25, "cost": 190, "current_price": 205}
            ],
            "watchlist": []
        })
        os.utime(editable_path, (Path(self.data_utils.DATA_FILE).stat().st_mtime - 10,) * 2)

        data = self.data_utils.load_data(force_editable_sync=True)

        self.assertEqual(data["holdings"][0]["symbol"], "AAPL")

    def test_missing_editable_sections_preserve_runtime_sections(self):
        self.data_utils.save_data({
            "holdings": [
                {"symbol": "NVDA", "shares": 1.25, "cost": 190, "current_price": 205}
            ],
            "watchlist": [
                {"symbol": "MSFT", "notes": "old", "target_buy": 350, "last_price": 410.5}
            ]
        })
        editable_path = Path(self.data_utils.EDITABLE_DATA_FILE)
        editable_path.write_text(json.dumps({
            "watchlist": [
                {"symbol": "AAPL", "notes": "new", "target_buy": 180}
            ]
        }), encoding="utf-8")
        os.utime(editable_path, (Path(self.data_utils.DATA_FILE).stat().st_mtime + 10,) * 2)

        data = self.data_utils.load_data()

        self.assertEqual(data["holdings"][0]["symbol"], "NVDA")
        self.assertEqual(data["watchlist"][0]["symbol"], "AAPL")


if __name__ == "__main__":
    unittest.main()
