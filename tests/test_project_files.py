import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProjectFilesTests(unittest.TestCase):
    def test_runtime_dependencies_are_declared(self):
        config = json.loads((ROOT / "config" / "strategies.json").read_text(encoding="utf-8"))
        strategy_ids = {strategy["id"] for strategy in config["strategies"]}
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()

        for package_name in ["pandas", "numpy", "yfinance"]:
            self.assertIn(package_name, requirements)
        self.assertIn("slack-bolt", requirements)
        self.assertIn("fastapi", requirements)
        self.assertIn("uvicorn", requirements)
        self.assertIn("backtrader", requirements)
        self.assertIn("pyarrow", requirements)
        for excluded in ["lightgbm", "catboost", "xgboost"]:
            self.assertNotIn(excluded, requirements)
        self.assertIn("torch", requirements)
        self.assertIn("transformers", requirements)

    def test_event_source_config_exists_and_has_sources(self):
        config_path = ROOT / "config" / "event_sources.json"
        self.assertTrue(config_path.exists())
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertIn("sources", config)
        self.assertIsInstance(config["sources"], list)
        self.assertGreaterEqual(len(config["sources"]), 1)

    def test_core_etf_and_engine_policy_configs_exist(self):
        core_etf_path = ROOT / "storage" / "config" / "core_etf_universe.json"
        satellite_path = ROOT / "storage" / "config" / "satellite_universe.json"
        engine_policy_path = ROOT / "storage" / "config" / "engine_policy.json"
        model_registry_path = ROOT / "storage" / "config" / "model_registry.json"
        self.assertTrue(core_etf_path.exists())
        self.assertTrue(satellite_path.exists())
        self.assertTrue(engine_policy_path.exists())
        self.assertTrue(model_registry_path.exists())

        core_etf = json.loads(core_etf_path.read_text(encoding="utf-8"))
        satellite_universe = json.loads(satellite_path.read_text(encoding="utf-8"))
        engine_policy = json.loads(engine_policy_path.read_text(encoding="utf-8"))
        model_registry = json.loads(model_registry_path.read_text(encoding="utf-8"))
        self.assertIn("etfs", core_etf)
        self.assertIsInstance(core_etf["etfs"], list)
        self.assertGreaterEqual(len(core_etf["etfs"]), 3)
        self.assertGreaterEqual(len(satellite_universe.get("manual_include", [])), 10)
        self.assertIn("GELYY", satellite_universe.get("manual_exclude", []))
        self.assertIn("core_etf_weight_ranges", engine_policy)
        self.assertIn("models", model_registry)
        self.assertTrue((ROOT / "storage" / "config" / "runtime_schedule.json").exists())

    def test_notification_example_config_exists_without_real_secrets(self):
        notification_example = ROOT / "storage" / "config" / "notification_config.example.json"
        market_events_example = ROOT / "storage" / "config" / "market_events.example.json"
        portfolio_input_example = ROOT / "storage" / "config" / "portfolio_input.example.json"
        self.assertTrue(notification_example.exists())
        self.assertTrue(market_events_example.exists())
        self.assertTrue(portfolio_input_example.exists())

        config = json.loads(notification_example.read_text(encoding="utf-8"))
        self.assertIn("slack", config)
        self.assertIn("email", config)
        self.assertIn("alert_settings", config)
        self.assertFalse(config["slack"]["webhook_url"].startswith("https://hooks.slack.com/services/"))
        self.assertEqual(config["email"]["password"], "")

    def test_gitignore_covers_generated_runtime_artifacts(self):
        gitignore_path = ROOT / ".gitignore"
        self.assertTrue(gitignore_path.exists())

        gitignore = gitignore_path.read_text(encoding="utf-8")
        for entry in [
            "__pycache__/",
            ".venv/",
            "frontend/node_modules/",
            "frontend/dist/",
            "trained_models/",
            "catboost_info/",
            "reports/",
            "storage/state/price_cache.json",
            "storage/state/analyst_consensus_cache.json",
            "storage/state/alert_state.json",
            "storage/state/notification_config.json",
            "storage/config/*.local.json",
            "storage/state/market_events.json",
            "storage/state/command_audit.jsonl",
        ]:
            self.assertIn(entry, gitignore)

    def test_frontend_install_flow_uses_ci_without_rewriting_lockfile(self):
        package_json = ROOT / "frontend" / "package.json"
        package_lock = ROOT / "frontend" / "package-lock.json"
        npmrc = ROOT / "frontend" / ".npmrc"
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertTrue(package_json.exists())
        self.assertTrue(package_lock.exists())
        self.assertTrue(npmrc.exists())
        self.assertIn("cd frontend && npm ci && cd ..", readme)
        self.assertNotIn("cd frontend && npm install && cd ..", readme)
        npmrc_text = npmrc.read_text(encoding="utf-8")
        self.assertIn("save=false", npmrc_text)
        self.assertIn("package-lock=true", npmrc_text)

    def test_retired_tcn_is_absent_from_runtime_code_and_configuration(self):
        retired_files = [
            ROOT / "strategies" / "deep_learning_strategy.py",
            ROOT / "strategies" / "deep_learning_utils.py",
            ROOT / "tests" / "test_deep_learning_strategy.py",
        ]
        for path in retired_files:
            self.assertFalse(path.exists(), f"retired TCN file still exists: {path}")

        model_registry = json.loads(
            (ROOT / "storage" / "config" / "model_registry.json").read_text(encoding="utf-8")
        )
        strategy_config = json.loads(
            (ROOT / "config" / "strategies.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("deep_tcn", {row.get("model_id") for row in model_registry.get("models", [])})
        self.assertNotIn("deep_tcn", {row.get("id") for row in strategy_config.get("strategies", [])})

        runtime_paths = [
            ROOT / "quant_core",
            ROOT / "jobs",
            ROOT / "strategies",
            ROOT / "frontend" / "src",
        ]
        offenders = []
        for root in runtime_paths:
            for path in root.rglob("*"):
                if path.suffix not in {".py", ".ts", ".tsx", ".json"}:
                    continue
                text = path.read_text(encoding="utf-8").lower()
                if "deep_tcn" in text or "temporal cnn" in text or "tcn_profile" in text:
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
