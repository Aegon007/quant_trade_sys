import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProjectFilesTests(unittest.TestCase):
    def test_ensemble_strategy_dependencies_are_declared(self):
        config = json.loads((ROOT / "config" / "strategies.json").read_text(encoding="utf-8"))
        strategy_ids = {strategy["id"] for strategy in config["strategies"]}
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()

        if "ensemble_voting" in strategy_ids:
            self.assertIn("catboost", requirements)
            self.assertIn("xgboost", requirements)
        if "deep_tcn" in strategy_ids:
            self.assertIn("torch", requirements)

    def test_gitignore_covers_generated_runtime_artifacts(self):
        gitignore_path = ROOT / ".gitignore"
        self.assertTrue(gitignore_path.exists())

        gitignore = gitignore_path.read_text(encoding="utf-8")
        for entry in [
            "__pycache__/",
            ".venv/",
            "trained_models/",
            "catboost_info/",
            "price_cache.json",
            "analyst_consensus_cache.json",
            "alert_state.json",
            "notification_config.json",
            "market_events.json",
        ]:
            self.assertIn(entry, gitignore)

    def test_event_source_config_exists_and_has_sources(self):
        config_path = ROOT / "config" / "event_sources.json"
        self.assertTrue(config_path.exists())
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertIn("sources", config)
        self.assertIsInstance(config["sources"], list)
        self.assertGreaterEqual(len(config["sources"]), 1)

    def test_notification_example_config_exists_without_real_secrets(self):
        config_path = ROOT / "notification_config.example.json"
        self.assertTrue(config_path.exists())
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertIn("slack", config)
        self.assertIn("email", config)
        self.assertIn("alert_settings", config)
        self.assertFalse(config["slack"]["webhook_url"].startswith("https://hooks.slack.com/services/"))
        self.assertEqual(config["email"]["password"], "")


if __name__ == "__main__":
    unittest.main()
