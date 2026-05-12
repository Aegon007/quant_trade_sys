import tempfile
import unittest
from pathlib import Path
import os
import json
from datetime import datetime, timedelta

from tests.support import clear_modules, install_fake_yfinance, reload_module


class DataUtilsFractionalShareTests(unittest.TestCase):
    def setUp(self):
        install_fake_yfinance()
        clear_modules("share_utils", "quant_core.data.storage")
        self.data_utils = reload_module("quant_core.data.storage")
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
            "account": {
                "total_capital": 25000,
                "cash_available": 8000,
                "min_cash_buffer_pct": 0.1,
                "max_single_position_pct": 0.18,
                "max_total_exposure_pct": 0.9
            },
            "holdings": [
                {"symbol": "aapl", "shares": 0.125, "cost": 180.5, "sector": "Technology"}
            ],
            "watchlist": [
                {"symbol": "msft", "notes": "wait for pullback", "target_buy": 390}
            ]
        }), encoding="utf-8")

        data = self.data_utils.load_data()

        self.assertEqual(data["account"]["total_capital"], 25000.0)
        self.assertEqual(data["account"]["cash_available"], 8000.0)
        self.assertEqual(data["account"]["min_cash_buffer_pct"], 0.1)
        self.assertEqual(data["account"]["max_single_position_pct"], 0.18)
        self.assertEqual(data["account"]["max_total_exposure_pct"], 0.9)
        self.assertEqual(data["holdings"][0]["symbol"], "AAPL")
        self.assertEqual(data["holdings"][0]["shares"], 0.125)
        self.assertEqual(data["holdings"][0]["cost"], 180.5)
        self.assertEqual(data["holdings"][0]["sector"], "Technology")
        self.assertIsNone(data["holdings"][0]["current_price"])
        self.assertEqual(data["watchlist"][0]["symbol"], "MSFT")
        self.assertEqual(data["watchlist"][0]["notes"], "wait for pullback")
        self.assertIsNone(data["watchlist"][0]["last_price"])
        self.assertNotIn("target_buy", data["watchlist"][0])

    def test_editable_portfolio_import_preserves_runtime_prices(self):
        self.data_utils.save_data({
            "holdings": [
                {"symbol": "AAPL", "shares": 1, "cost": 150, "current_price": 222.22}
            ],
            "watchlist": [
                {"symbol": "MSFT", "notes": "old", "last_price": 410.5}
            ]
        })
        editable_path = Path(self.data_utils.EDITABLE_DATA_FILE)
        editable_path.write_text(json.dumps({
            "holdings": [
                {"symbol": "AAPL", "shares": 0.5, "cost": 180, "sector": "Technology"}
            ],
            "watchlist": [
                {"symbol": "MSFT", "notes": "new"}
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
            "account": {
                "total_capital": 50000.0,
                "cash_available": 12000.0,
                "min_cash_buffer_pct": 0.08,
                "max_single_position_pct": 0.22,
                "max_total_exposure_pct": 0.95,
            },
            "holdings": [
                {"symbol": "NVDA", "shares": 1.25, "cost": 190, "current_price": 205}
            ],
            "watchlist": [
                {"symbol": "MSFT", "notes": "old", "last_price": 410.5}
            ]
        })
        editable_path = Path(self.data_utils.EDITABLE_DATA_FILE)
        editable_path.write_text(json.dumps({
            "watchlist": [
                {"symbol": "AAPL", "notes": "new"}
            ]
        }), encoding="utf-8")
        os.utime(editable_path, (Path(self.data_utils.DATA_FILE).stat().st_mtime + 10,) * 2)

        data = self.data_utils.load_data()

        self.assertEqual(data["account"]["total_capital"], 50000.0)
        self.assertEqual(data["account"]["cash_available"], 12000.0)
        self.assertEqual(data["holdings"][0]["symbol"], "NVDA")
        self.assertEqual(data["watchlist"][0]["symbol"], "AAPL")

    def test_auto_refresh_market_data_updates_missing_prices_and_timestamp(self):
        now = datetime(2026, 5, 8, 12, 0, 0)
        data = {
            "holdings": [{"symbol": "AAPL", "shares": 1, "cost": 100, "current_price": None}],
            "watchlist": [{"symbol": "MSFT", "notes": "", "last_price": None}],
            "last_updated": None,
        }
        self.data_utils.fetch_prices = lambda symbols, **kwargs: {"AAPL": 210.5, "MSFT": 405.25}

        refreshed_data, refreshed = self.data_utils.auto_refresh_market_data(
            data,
            refresh_interval_seconds=300,
            now=now,
        )

        self.assertTrue(refreshed)
        self.assertEqual(refreshed_data["holdings"][0]["current_price"], 210.5)
        self.assertEqual(refreshed_data["watchlist"][0]["last_price"], 405.25)
        self.assertEqual(refreshed_data["prices_last_updated"], now.isoformat())

    def test_auto_refresh_market_data_skips_when_prices_are_fresh(self):
        now = datetime(2026, 5, 8, 12, 0, 0)
        data = {
            "holdings": [{"symbol": "AAPL", "shares": 1, "cost": 100, "current_price": 210.5}],
            "watchlist": [],
            "last_updated": None,
            "prices_last_updated": (now - timedelta(seconds=60)).isoformat(),
        }

        def fail_fetch(_symbols):
            raise AssertionError("fetch_prices should not be called for fresh prices")

        self.data_utils.fetch_prices = fail_fetch

        refreshed_data, refreshed = self.data_utils.auto_refresh_market_data(
            data,
            refresh_interval_seconds=300,
            now=now,
        )

        self.assertFalse(refreshed)
        self.assertEqual(refreshed_data["holdings"][0]["current_price"], 210.5)

    def test_auto_refresh_market_data_refreshes_stale_prices(self):
        now = datetime(2026, 5, 8, 12, 0, 0)
        data = {
            "holdings": [{"symbol": "AAPL", "shares": 1, "cost": 100, "current_price": 200.0}],
            "watchlist": [],
            "last_updated": None,
            "prices_last_updated": (now - timedelta(minutes=20)).isoformat(),
        }
        self.data_utils.fetch_prices = lambda symbols, **kwargs: {"AAPL": 215.0}

        refreshed_data, refreshed = self.data_utils.auto_refresh_market_data(
            data,
            refresh_interval_seconds=300,
            now=now,
        )

        self.assertTrue(refreshed)
        self.assertEqual(refreshed_data["holdings"][0]["current_price"], 215.0)
        self.assertEqual(refreshed_data["prices_last_updated"], now.isoformat())

    def test_fetch_prices_falls_back_when_yfinance_has_no_price(self):
        self.data_utils.md.fetch_latest_prices_from_stooq = lambda symbols: {"AAPL": 321.5}

        prices = self.data_utils.fetch_prices(["AAPL"], use_cache=False)

        self.assertEqual(prices["AAPL"], 321.5)

    def test_fetch_prices_uses_cache_when_ttl_not_expired(self):
        prices_first = self.data_utils.fetch_prices(["AAPL"], use_cache=True, cache_ttl=3600)
        self.assertIn("AAPL", prices_first)

        original_fetcher = self.data_utils._fetch_prices_from_provider

        def fail_fetch(_provider, _symbols):
            raise AssertionError("provider should not be called when cache is still fresh")

        self.data_utils._fetch_prices_from_provider = fail_fetch
        try:
            prices_second = self.data_utils.fetch_prices(["AAPL"], use_cache=True, cache_ttl=3600)
        finally:
            self.data_utils._fetch_prices_from_provider = original_fetcher

        self.assertEqual(prices_first["AAPL"], prices_second["AAPL"])

    def test_fetch_prices_refetches_after_cache_ttl_expired(self):
        first = self.data_utils.fetch_prices(["AAPL"], use_cache=True, cache_ttl=3600)
        self.assertIn("AAPL", first)

        original_time = self.data_utils.time.time
        self.data_utils.time.time = lambda: original_time() + 7200

        calls = []
        original_fetcher = self.data_utils._fetch_prices_from_provider

        def wrapped_fetch(provider, symbols):
            calls.append((provider, tuple(symbols)))
            return original_fetcher(provider, symbols)

        self.data_utils._fetch_prices_from_provider = wrapped_fetch
        try:
            second = self.data_utils.fetch_prices(["AAPL"], use_cache=True, cache_ttl=3600)
        finally:
            self.data_utils._fetch_prices_from_provider = original_fetcher
            self.data_utils.time.time = original_time

        self.assertIn("AAPL", second)
        self.assertTrue(calls)

    def test_fetch_prices_force_live_refresh_bypasses_cache_and_updates_cache(self):
        self.data_utils.DEFAULT_PRICE_SOURCE_ORDER = ("primary_mock",)
        live_price = {"value": 100.0}
        self.data_utils.CUSTOM_PRICE_PROVIDERS = {
            "primary_mock": lambda symbols: {"AAPL": live_price["value"]},
        }

        first = self.data_utils.fetch_prices(["AAPL"], use_cache=True, cache_ttl=3600)
        self.assertEqual(first["AAPL"], 100.0)

        live_price["value"] = 105.0
        second = self.data_utils.fetch_prices(["AAPL"], use_cache=False)
        self.assertEqual(second["AAPL"], 105.0)

        original_fetcher = self.data_utils._fetch_prices_from_provider

        def fail_fetch(_provider, _symbols):
            raise AssertionError("provider should not be called when refreshed cache is still fresh")

        self.data_utils._fetch_prices_from_provider = fail_fetch
        try:
            third = self.data_utils.fetch_prices(["AAPL"], use_cache=True, cache_ttl=3600)
        finally:
            self.data_utils._fetch_prices_from_provider = original_fetcher

        self.assertEqual(third["AAPL"], 105.0)

    def test_fetch_prices_uses_source_order_and_falls_back_on_error(self):
        self.data_utils.DEFAULT_PRICE_SOURCE_ORDER = ("primary_mock", "secondary_mock")

        def provider_primary(symbols):
            raise RuntimeError("quota exceeded")

        def provider_secondary(symbols):
            return {"AAPL": 456.78}

        self.data_utils.CUSTOM_PRICE_PROVIDERS = {
            "primary_mock": provider_primary,
            "secondary_mock": provider_secondary,
        }

        prices = self.data_utils.fetch_prices(["AAPL"], use_cache=False)

        self.assertEqual(prices["AAPL"], 456.78)
        status = self.data_utils.md.get_market_data_status_snapshot()
        self.assertEqual(status["prices"]["last_source"], "secondary_mock")
        self.assertIn("quota exceeded", str(status["prices"]["last_error"]))

    def test_move_holding_to_watchlist_moves_position_and_uses_latest_price(self):
        self.data_utils.save_data({
            "holdings": [
                {"symbol": "AAPL", "shares": 1.5, "cost": 180.0, "current_price": 205.0, "sector": "Tech"}
            ],
            "watchlist": []
        })

        symbol = self.data_utils.move_holding_to_watchlist(0)
        data = self.data_utils.load_data()

        self.assertEqual(symbol, "AAPL")
        self.assertEqual(data["holdings"], [])
        self.assertEqual(len(data["watchlist"]), 1)
        self.assertEqual(data["watchlist"][0]["symbol"], "AAPL")
        self.assertEqual(data["watchlist"][0]["last_price"], 205.0)
        self.assertNotIn("target_buy", data["watchlist"][0])

    def test_move_holding_to_watchlist_does_not_duplicate_existing_watch_symbol(self):
        self.data_utils.save_data({
            "holdings": [
                {"symbol": "AAPL", "shares": 1.0, "cost": 180.0, "current_price": 210.0, "sector": ""}
            ],
            "watchlist": [
                {"symbol": "AAPL", "notes": "existing", "last_price": None}
            ]
        })

        self.data_utils.move_holding_to_watchlist(0)
        data = self.data_utils.load_data()

        self.assertEqual(data["holdings"], [])
        self.assertEqual(len(data["watchlist"]), 1)
        self.assertEqual(data["watchlist"][0]["last_price"], 210.0)
        self.assertNotIn("target_buy", data["watchlist"][0])

    def test_move_watch_to_holding_buys_default_one_share(self):
        self.data_utils.save_data({
            "holdings": [],
            "watchlist": [
                {"symbol": "MSFT", "notes": "watch", "last_price": 310.0}
            ]
        })

        symbol, shares, entry_price = self.data_utils.move_watch_to_holding(0)
        data = self.data_utils.load_data()

        self.assertEqual(symbol, "MSFT")
        self.assertEqual(shares, 1.0)
        self.assertEqual(entry_price, 310.0)
        self.assertEqual(data["watchlist"], [])
        self.assertEqual(len(data["holdings"]), 1)
        self.assertEqual(data["holdings"][0]["symbol"], "MSFT")
        self.assertEqual(data["holdings"][0]["shares"], 1.0)
        self.assertEqual(data["holdings"][0]["cost"], 310.0)
        self.assertEqual(data["holdings"][0]["current_price"], 310.0)

    def test_move_watch_to_holding_merges_existing_position_with_weighted_cost(self):
        self.data_utils.save_data({
            "holdings": [
                {"symbol": "NVDA", "shares": 2.0, "cost": 100.0, "current_price": 105.0, "sector": ""}
            ],
            "watchlist": [
                {"symbol": "NVDA", "notes": "re-enter", "last_price": 110.0}
            ]
        })

        self.data_utils.move_watch_to_holding(0)
        data = self.data_utils.load_data()

        self.assertEqual(data["watchlist"], [])
        self.assertEqual(len(data["holdings"]), 1)
        self.assertEqual(data["holdings"][0]["shares"], 3.0)
        self.assertAlmostEqual(data["holdings"][0]["cost"], (2 * 100.0 + 110.0) / 3.0)
        self.assertEqual(data["holdings"][0]["current_price"], 110.0)


if __name__ == "__main__":
    unittest.main()
