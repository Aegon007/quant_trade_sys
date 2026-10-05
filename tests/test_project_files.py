import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectFilesTests(unittest.TestCase):
    def test_requirements_match_research_architecture(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        for required in ("fastapi", "uvicorn", "pandas", "numpy", "pyarrow", "yfinance", "slack-bolt", "lxml"):
            self.assertIn(required, requirements)
        for removed in ("torch", "transformers", "chronos", "backtrader", "lightgbm"):
            self.assertNotIn(removed, requirements)

    def test_frontend_and_runtime_configs_exist(self):
        for path in (
            ROOT / "frontend/package.json", ROOT / "frontend/package-lock.json", ROOT / "frontend/.npmrc",
            ROOT / "storage/config/research_universe.example.json", ROOT / "storage/config/valuation_policy.example.json",
            ROOT / "storage/config/runtime_schedule.example.json", ROOT / "storage/config/watchlist.example.json",
        ):
            self.assertTrue(path.exists(), str(path))

    def test_mutable_machine_settings_are_git_ignored(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for name in ("notification_config.json", "runtime_schedule.json", "research_universe.json", "valuation_policy.json", "watchlist.json"):
            self.assertIn(f"storage/config/{name}", ignore)

    def test_removed_product_surfaces_are_absent(self):
        for path in (ROOT / "quant_core/models", ROOT / "quant_core/portfolio", ROOT / "quant_core/ledger", ROOT / "engine", ROOT / "strategies"):
            self.assertFalse(any(path.rglob("*.py")), str(path))
        source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "frontend/src").rglob("*.tsx"))
        for retired in ("Robinhood", "持仓账户", "模型训练", "Chronos"):
            self.assertNotIn(retired, source)


if __name__ == "__main__":
    unittest.main()
