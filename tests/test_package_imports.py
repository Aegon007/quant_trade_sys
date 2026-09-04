import importlib
import unittest


class PackageImportTests(unittest.TestCase):
    def test_runtime_modules_import(self):
        modules = [
            "quant_core.api.actions", "quant_core.api.snapshot_loader", "quant_core.data.prices",
            "quant_core.data.data_health", "quant_core.fundamentals.provider", "quant_core.llm.explainer",
            "quant_core.notifications.delivery_router", "quant_core.opportunities.dislocation",
            "quant_core.research.service", "quant_core.research.calibration", "quant_core.risk.market_regime",
            "quant_core.valuation.engine", "quant_core.valuation.router", "jobs.api_server", "jobs.run_all",
            "integrations.slack.command_service",
        ]
        for name in modules:
            with self.subTest(name=name):
                importlib.import_module(name)

if __name__ == "__main__":
    unittest.main()
