import unittest

import numpy as np
import pandas as pd

from tests.support import clear_modules, install_fake_yfinance, reload_module


def make_ohlcv(rows=90):
    index = pd.date_range("2024-01-01", periods=rows, freq="D")
    close = pd.Series(np.linspace(100, 130, rows) + np.sin(np.arange(rows) / 3), index=index)
    return pd.DataFrame(
        {
            "Open": close * 0.99,
            "High": close * 1.02,
            "Low": close * 0.98,
            "Close": close,
            "Volume": np.linspace(1_000_000, 1_500_000, rows),
        },
        index=index,
    )


class DeepLearningStrategyTests(unittest.TestCase):
    def setUp(self):
        install_fake_yfinance({"AAPL": make_ohlcv(100)})
        clear_modules(
            "ml_strategy",
            "deep_learning_strategy",
            "strategies.deep_learning_strategy",
        )
        self.deep_learning_strategy = reload_module("deep_learning_strategy")

    def test_prepare_dataset_creates_fixed_length_sequences_without_future_tail(self):
        dataset = self.deep_learning_strategy.prepare_deep_learning_dataset(
            make_ohlcv(80),
            sequence_length=12,
            target_horizon=5,
        )

        self.assertEqual(dataset.features.shape[1], 12)
        self.assertEqual(dataset.features.shape[0], len(dataset.targets))
        self.assertEqual(dataset.features.shape[0], len(dataset.future_returns))
        self.assertLessEqual(dataset.index[-1], make_ohlcv(80).index[-6])

    def test_prepare_dataset_returns_empty_arrays_when_history_is_too_short(self):
        dataset = self.deep_learning_strategy.prepare_deep_learning_dataset(
            make_ohlcv(10),
            sequence_length=12,
            target_horizon=5,
        )

        self.assertEqual(dataset.features.shape[0], 0)
        self.assertEqual(dataset.features.shape[1], 12)

    def test_get_signal_degrades_cleanly_without_torch(self):
        if self.deep_learning_strategy.TORCH_AVAILABLE:
            self.skipTest("PyTorch is installed in this environment")

        signal, reason = self.deep_learning_strategy.get_deep_tcn_signal("AAPL")

        self.assertEqual(signal, "HOLD")
        self.assertIn("PyTorch", reason)

    def test_auto_device_prefers_cuda_then_mps_then_cpu(self):
        select_device = self.deep_learning_strategy.select_device_name

        self.assertEqual(select_device("auto", cuda_available=True, mps_available=True), "cuda")
        self.assertEqual(select_device("auto", cuda_available=False, mps_available=True), "mps")
        self.assertEqual(select_device("auto", cuda_available=False, mps_available=False), "cpu")

    def test_unavailable_explicit_device_falls_back_without_code_changes(self):
        select_device = self.deep_learning_strategy.select_device_name

        self.assertEqual(select_device("cuda", cuda_available=False, mps_available=True), "mps")
        self.assertEqual(select_device("mps", cuda_available=True, mps_available=False), "cuda")
        self.assertEqual(select_device("cpu", cuda_available=True, mps_available=True), "cpu")

    def test_strategy_adapter_uses_deep_tcn_trade_series(self):
        strategy_module = reload_module("strategies.deep_learning_strategy")

        def fake_backtest_deep_tcn(data=None, **params):
            result = data.copy()
            result["Trade"] = [0, 1, 0, -1]
            result["pred_prob"] = [np.nan, 0.7, 0.6, 0.3]
            return result

        strategy_module.dl_utils.backtest_deep_tcn = fake_backtest_deep_tcn
        strategy = strategy_module.DeepTCNStrategy({"sequence_length": 2, "lookback": 2})
        data = make_ohlcv(4)
        strategy.set_data(data)
        strategy.init()

        self.assertEqual(strategy.next(1), {"action": "BUY", "size": 100})
        self.assertEqual(strategy.next(3), {"action": "SELL", "size": 100})


if __name__ == "__main__":
    unittest.main()
