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

    def test_gitignore_covers_generated_runtime_artifacts(self):
        gitignore_path = ROOT / ".gitignore"
        self.assertTrue(gitignore_path.exists())

        gitignore = gitignore_path.read_text(encoding="utf-8")
        for entry in ["__pycache__/", ".venv/", "trained_models/", "catboost_info/", "price_cache.json"]:
            self.assertIn(entry, gitignore)


if __name__ == "__main__":
    unittest.main()
