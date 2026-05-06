import unittest

import pandas as pd

from tests.support import (
    clear_modules,
    install_fake_backtrader,
    install_fake_pybroker,
    reload_module,
)


class FractionalBuyStrategy:
    def set_data(self, data):
        self.data = data

    def init(self):
        return None

    def next(self, index):
        if index == 0:
            return {"action": "BUY", "size": 0.125}
        if index == 1:
            return {"action": "SELL", "size": 0.125}
        return None


class PyBrokerFractionalShareTests(unittest.TestCase):
    def setUp(self):
        install_fake_backtrader([100000.0, 100000.0])
        self.pybroker_context = install_fake_pybroker()
        clear_modules("engine", "engine.base", "engine.backtrader_engine", "engine.pybroker_engine")
        self.engine_module = reload_module("engine.pybroker_engine")

    def test_run_preserves_fractional_order_size(self):
        dataframe = pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [101.0, 102.0],
                "Low": [99.0, 100.0],
                "Close": [100.0, 101.0],
                "Volume": [1000, 1000],
            },
            index=pd.date_range("2024-01-01", periods=2, freq="D"),
        )

        engine = self.engine_module.PyBrokerEngine(initial_cash=100000.0)
        engine.set_data(dataframe)
        engine.set_strategy(FractionalBuyStrategy())
        result = engine.run()

        self.assertEqual(self.pybroker_context.buy_sizes, [0.125])
        self.assertEqual(self.pybroker_context.sell_sizes, [0.125])
        self.assertEqual(result.trade_log[0]["shares"], 0.125)
        self.assertEqual(result.trade_log[1]["shares"], 0.125)


if __name__ == "__main__":
    unittest.main()
