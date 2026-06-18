import json
import tempfile
import unittest
from pathlib import Path

from tests.support import clear_modules, reload_module


class StrategyUITests(unittest.TestCase):
    def setUp(self):
        clear_modules("strategies.ui")
        self.strategy_ui = reload_module("strategies.ui")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.config_path = Path(self.temp_dir.name) / "strategies.json"
        self.strategy_ui.CONFIG_PATH = str(self.config_path)

    def _write_config(self, strategies):
        self.config_path.write_text(json.dumps({"strategies": strategies}), encoding="utf-8")

    def test_load_strategies_hides_disabled_models_by_default(self):
        self._write_config(
            [
                {"id": "ma_crossover", "name": "MA", "enabled": True},
                {"id": "rsi", "name": "RSI", "enabled": False},
            ]
        )

        strategies = self.strategy_ui.load_strategies()

        self.assertEqual([s["id"] for s in strategies], ["ma_crossover"])

    def test_load_strategies_can_include_disabled_models(self):
        self._write_config(
            [
                {"id": "ma_crossover", "name": "MA", "enabled": True, "is_default": True},
                {"id": "rsi", "name": "RSI", "enabled": False},
            ]
        )

        strategies = self.strategy_ui.load_strategies(include_disabled=True)

        self.assertEqual([s["id"] for s in strategies], ["ma_crossover", "rsi"])

    def test_get_default_strategy_id_prefers_marked_default(self):
        strategies = [
            {"id": "ma_crossover", "name": "MA"},
            {"id": "rsi", "name": "RSI", "is_default": True},
        ]

        default_id = self.strategy_ui.get_default_strategy_id(strategies)

        self.assertEqual(default_id, "rsi")

    def test_get_default_strategy_id_falls_back_to_first_available(self):
        strategies = [
            {"id": "ma_crossover", "name": "MA"},
            {"id": "rsi", "name": "RSI"},
        ]

        default_id = self.strategy_ui.get_default_strategy_id(strategies)

        self.assertEqual(default_id, "ma_crossover")


if __name__ == "__main__":
    unittest.main()
