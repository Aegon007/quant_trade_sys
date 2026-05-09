import sys
import types
import unittest
from types import SimpleNamespace

from tests.support import clear_modules, reload_module


class UIComponentsTests(unittest.TestCase):
    def setUp(self):
        sys.modules["streamlit"] = types.ModuleType("streamlit")
        clear_modules("ui_components", "strategy_ui", "deep_learning_strategy", "capital_allocator")
        self.ui = reload_module("ui_components")

    def test_build_watchlist_records_includes_allocation_guidance_for_deep_tcn_buy(self):
        self.ui.su.get_signal = lambda strategy, symbol: ("BUY", f"{symbol} buy")
        self.ui.dl_utils.get_deep_tcn_signal_profile = lambda symbol, **kwargs: SimpleNamespace(
            signal="BUY",
            reason=f"{symbol} profile",
            probability=0.60,
            expected_return_pct=0.03,
        )

        records = self.ui.build_watchlist_records(
            watchlist=[{"symbol": "MSFT", "notes": "watch", "target_buy": 300.0, "last_price": 100.0}],
            strategy={"id": "deep_tcn", "params": {"period": "2y"}},
            account={
                "total_capital": 10000.0,
                "cash_available": 5000.0,
                "min_cash_buffer_pct": 0.10,
                "max_single_position_pct": 0.20,
                "max_total_exposure_pct": 1.0,
            },
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["建议动作"], "买入")
        self.assertEqual(records[0]["建议投入"], "$1,600.00")
        self.assertEqual(records[0]["建议股数"], "16.000")
        self.assertIn("上涨概率", records[0]["资金说明"])


if __name__ == "__main__":
    unittest.main()
