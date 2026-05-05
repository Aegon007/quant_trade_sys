import unittest

from tests.support import clear_modules, install_fake_yfinance, reload_module


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


if __name__ == "__main__":
    unittest.main()

