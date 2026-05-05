import unittest

import pandas as pd

from tests.support import (
    clear_modules,
    install_fake_backtrader,
    install_fake_pybroker,
    reload_module,
)


class BuySellStrategy:
    def set_data(self, data):
        self.data = data

    def init(self):
        return None

    def next(self, index):
        if index == 0:
            return {"action": "BUY", "size": 1}
        if index == 2:
            return {"action": "SELL", "size": 1}
        return None


class BacktraderEquityCurveTests(unittest.TestCase):
    def setUp(self):
        install_fake_pybroker()
        install_fake_backtrader([100000.0, 101500.0, 99500.0])
        clear_modules("engine", "engine.base", "engine.pybroker_engine", "engine.backtrader_engine")
        self.engine_module = reload_module("engine.backtrader_engine")

    def test_run_returns_recorded_equity_curve_instead_of_repeating_final_value(self):
        dataframe = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0],
                "High": [101.0, 102.0, 103.0],
                "Low": [99.0, 100.0, 101.0],
                "Close": [100.0, 101.5, 99.5],
                "Volume": [1000, 1000, 1000],
            },
            index=pd.date_range("2024-01-01", periods=3, freq="D"),
        )

        engine = self.engine_module.BacktraderEngine(initial_cash=100000.0)
        engine.set_data(dataframe)
        engine.set_strategy(BuySellStrategy())
        result = engine.run()

        self.assertEqual(result.equity_curve, [100000.0, 101500.0, 99500.0])


if __name__ == "__main__":
    unittest.main()

