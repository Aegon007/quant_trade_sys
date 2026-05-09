import unittest

import numpy as np
import pandas as pd
from datetime import datetime

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
        import tempfile

        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.deep_learning_strategy.MODEL_DIR = self.temp_dir.name
        self.deep_learning_strategy._SIGNAL_CACHE.clear()

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

    def test_select_device_name_handles_non_string_preference(self):
        select_device = self.deep_learning_strategy.select_device_name

        self.assertEqual(select_device(1, cuda_available=False, mps_available=False), "cpu")

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

    def test_nightly_retrain_window_and_cycle_key(self):
        module = self.deep_learning_strategy
        late_night = datetime(2026, 5, 8, 23, 30)
        after_midnight = datetime(2026, 5, 9, 0, 30)
        daytime = datetime(2026, 5, 9, 14, 0)

        self.assertTrue(module.is_nightly_retrain_window(late_night))
        self.assertTrue(module.is_nightly_retrain_window(after_midnight))
        self.assertFalse(module.is_nightly_retrain_window(daytime))
        self.assertEqual(module.training_cycle_key_for_timestamp(late_night), "2026-05-08")
        self.assertEqual(module.training_cycle_key_for_timestamp(after_midnight), "2026-05-08")

    def test_should_run_nightly_retraining_respects_saved_cycle(self):
        module = self.deep_learning_strategy
        now = datetime(2026, 5, 8, 23, 15)

        self.assertTrue(module.should_run_nightly_retraining(now=now))
        module.mark_nightly_retraining_done(now=now)
        self.assertFalse(module.should_run_nightly_retraining(now=now))

    def test_force_retraining_bypasses_night_window(self):
        module = self.deep_learning_strategy
        original_torch_available = module.TORCH_AVAILABLE
        original_train_func = module.train_and_save_deep_tcn_model
        self.addCleanup(setattr, module, "TORCH_AVAILABLE", original_torch_available)
        self.addCleanup(setattr, module, "train_and_save_deep_tcn_model", original_train_func)
        module.TORCH_AVAILABLE = True
        module.train_and_save_deep_tcn_model = lambda symbol, **params: (True, f"{symbol} ok")

        ok, message = module.run_nightly_retraining_for_symbols(
            ["AAPL", "MSFT"],
            params={"period": "2y"},
            now=datetime(2026, 5, 8, 14, 0),
            force=True,
        )

        self.assertTrue(ok)
        self.assertIn("成功 2", message)

    def test_get_signal_profile_uses_prediction_output(self):
        module = self.deep_learning_strategy
        original_torch_available = module.TORCH_AVAILABLE
        original_predict = module.predict_with_saved_deep_tcn_model
        self.addCleanup(setattr, module, "TORCH_AVAILABLE", original_torch_available)
        self.addCleanup(setattr, module, "predict_with_saved_deep_tcn_model", original_predict)
        module.TORCH_AVAILABLE = True
        module._PROFILE_CACHE.clear()
        module.predict_with_saved_deep_tcn_model = lambda *args, **kwargs: {
            "probability": 0.66,
            "expected_return": 0.08,
            "device": "cpu",
            "trained_at": "2026-05-08T23:10:00",
            "latest_price": 100.0,
        }

        profile = module.get_deep_tcn_signal_profile("AAPL")

        self.assertEqual(profile.signal, "BUY")
        self.assertAlmostEqual(profile.probability, 0.66)
        self.assertAlmostEqual(profile.expected_return_pct, 0.08)
        self.assertAlmostEqual(profile.take_profit_price, 108.0)
        self.assertLess(profile.stop_loss_price, 100.0)
        self.assertEqual(profile.device, "cpu")


if __name__ == "__main__":
    unittest.main()
