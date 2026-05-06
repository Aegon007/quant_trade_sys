import unittest

from tests.support import clear_modules, install_fake_yfinance, reload_module


class ConfigOnlyStrategy:
    def __init__(self, strength=1):
        self.strength = strength


def config_only_signal(symbol, strength=1):
    return "BUY", f"{symbol} strength={strength}"


class StrategyRegistryTests(unittest.TestCase):
    def setUp(self):
        install_fake_yfinance()
        clear_modules(
            "quant_analysis",
            "ml_strategy",
            "strategies",
            "strategies.classic_strategies",
            "strategies.ml_strategy",
            "strategies.ensemble_strategy",
            "strategies.deep_learning_strategy",
            "deep_learning_strategy",
            "strategy_registry",
        )
        self.strategy_registry = reload_module("strategy_registry")

    def test_create_strategy_builds_expected_rule_strategy(self):
        strategy = self.strategy_registry.create_strategy(
            {"id": "ma_crossover", "params": {"short_window": 10, "long_window": 30}}
        )

        self.assertEqual(type(strategy).__name__, "MACrossoverStrategy")
        self.assertEqual(strategy.short, 10)
        self.assertEqual(strategy.long, 30)

    def test_create_strategy_raises_for_unknown_strategy(self):
        with self.assertRaises(ValueError):
            self.strategy_registry.create_strategy({"id": "does_not_exist"})

    def test_create_strategy_uses_configured_class_path_without_registry_edit(self):
        strategy = self.strategy_registry.create_strategy(
            {
                "id": "config_only",
                "strategy_class": "tests.test_strategy_registry.ConfigOnlyStrategy",
                "params": {"strength": 7},
            }
        )

        self.assertEqual(type(strategy).__name__, "ConfigOnlyStrategy")
        self.assertEqual(strategy.strength, 7)

    def test_create_strategy_builds_deep_tcn_strategy_without_torch_import_failure(self):
        strategy = self.strategy_registry.create_strategy(
            {
                "id": "deep_tcn",
                "strategy_class": "strategies.deep_learning_strategy.DeepTCNStrategy",
                "params_mode": "dict",
                "params": {"sequence_length": 30, "device": "auto"},
            }
        )

        self.assertEqual(type(strategy).__name__, "DeepTCNStrategy")
        self.assertEqual(strategy.params["sequence_length"], 30)
        self.assertEqual(strategy.params["device"], "auto")

    def test_get_signal_uses_configured_signal_function_without_code_edit(self):
        import sys
        import types

        sys.modules["streamlit"] = types.ModuleType("streamlit")
        clear_modules("strategy_ui")
        strategy_ui = reload_module("strategy_ui")

        signal, reason = strategy_ui.get_signal(
            {
                "id": "config_only",
                "signal_function": "tests.test_strategy_registry.config_only_signal",
                "params": {"strength": 3},
            },
            "AAPL",
        )

        self.assertEqual(signal, "BUY")
        self.assertEqual(reason, "AAPL strength=3")


if __name__ == "__main__":
    unittest.main()
