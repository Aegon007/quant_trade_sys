import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tests.support import clear_modules, reload_module


class StrategyValidationTests(unittest.TestCase):
    def setUp(self):
        clear_modules("quant_core.research.strategy_validation")
        self.module = reload_module("quant_core.research.strategy_validation")

    def test_build_strategy_validation_snapshot_classifies_default_strategy(self):
        snapshot = self.module.build_strategy_validation_snapshot(
            now=datetime.fromisoformat("2026-06-08T11:00:00"),
            history_period="5y",
            default_strategy={"id": "deep_tcn", "name": "TCN"},
            strategy_research_rows=[
                {
                    "symbol": "MU",
                    "focus_role": "satellite",
                    "comparison_rows": [
                        {"strategy_id": "deep_tcn", "strategy_name": "TCN", "composite_score": 4.2, "completed_trades": 8},
                        {"strategy_id": "macd", "strategy_name": "MACD", "composite_score": 3.7, "completed_trades": 6},
                    ],
                },
                {
                    "symbol": "QQQ",
                    "focus_role": "core",
                    "comparison_rows": [
                        {"strategy_id": "macd", "strategy_name": "MACD", "composite_score": 2.4, "completed_trades": 5},
                        {"strategy_id": "deep_tcn", "strategy_name": "TCN", "composite_score": 1.8, "completed_trades": 7},
                    ],
                },
            ],
            source="weekend_research",
        )

        self.assertEqual(snapshot["summary"]["status"], "REVIEW")
        self.assertEqual(snapshot["summary"]["symbol_count"], 2)
        self.assertEqual(snapshot["summary"]["validated_count"], 1)
        self.assertEqual(snapshot["summary"]["review_count"], 1)
        self.assertIn("QQQ", snapshot["summary"]["warning_symbols"])
        rows = {row["symbol"]: row for row in snapshot["symbols"]}
        self.assertEqual(rows["MU"]["status"], "VALIDATED")
        self.assertEqual(rows["QQQ"]["status"], "REVIEW")

    def test_append_and_load_strategy_experiment_journal(self):
        snapshot = self.module.build_strategy_validation_snapshot(
            now=datetime.fromisoformat("2026-06-08T11:00:00"),
            history_period="5y",
            default_strategy={"id": "deep_tcn", "name": "TCN"},
            strategy_research_rows=[],
            source="weekend_research",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = str(Path(temp_dir) / "strategy_experiment_journal.jsonl")
            self.module.append_strategy_experiment_journal(snapshot, journal_path=journal_path)
            rows = self.module.load_strategy_experiment_journal(journal_path=journal_path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "NO_DATA")
        self.assertEqual(rows[0]["default_strategy_id"], "deep_tcn")


if __name__ == "__main__":
    unittest.main()
