import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from quant_core.data import prices


class PriceHistoryCacheTests(unittest.TestCase):
    def test_history_cache_avoids_second_network_fetch(self):
        frame = pd.DataFrame({"Close": [10.0, 11.0]}, index=pd.date_range("2026-01-01", periods=2))
        with TemporaryDirectory() as temp, patch.object(prices, "HISTORY_CACHE_DIR", Path(temp)), patch(
            "quant_core.data.prices.market_data.fetch_stooq_history", return_value=frame
        ) as fetch:
            first = prices.get_history("MSFT", period="2y")
            second = prices.get_history("MSFT", period="2y")
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(float(first["Close"].iloc[-1]), float(second["Close"].iloc[-1]))

    def test_force_refresh_bypasses_history_cache(self):
        frame = pd.DataFrame({"Close": [10.0, 11.0]}, index=pd.date_range("2026-01-01", periods=2))
        with TemporaryDirectory() as temp, patch.object(prices, "HISTORY_CACHE_DIR", Path(temp)), patch(
            "quant_core.data.prices.market_data.fetch_stooq_history", return_value=frame
        ) as fetch:
            prices.get_history("MSFT", period="2y")
            prices.get_history("MSFT", period="2y", force=True)
        self.assertEqual(fetch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
