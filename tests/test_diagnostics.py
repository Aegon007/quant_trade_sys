import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.support import clear_modules, reload_module


class DiagnosticsTests(unittest.TestCase):
    def test_diagnostics_bundle_includes_safe_summary_and_excludes_secrets(self):
        clear_modules("quant_core.diagnostics")
        diagnostics = reload_module("quant_core.diagnostics")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            portfolio_path = root / "portfolio_data.json"
            health_path = root / "data_health_snapshot.json"
            cache_path = root / "price_cache.json"
            secrets_path = root / "notification_secrets.local.json"
            portfolio_path.write_text(
                json.dumps(
                    {
                        "account": {"cash_available": 123.45},
                        "holdings": [{"symbol": "AAPL", "current_price": 100}],
                        "watchlist": [{"symbol": "MSFT", "last_price": 200}],
                        "prices_last_updated": "2026-06-11T12:00:00",
                    }
                ),
                encoding="utf-8",
            )
            health_path.write_text(
                json.dumps({"summary": {"status": "DEGRADED", "health_reason": "fallback_source_used"}}),
                encoding="utf-8",
            )
            cache_path.write_text(
                json.dumps({"AAPL": {"price": 100, "timestamp": 1, "source": "stooq"}}),
                encoding="utf-8",
            )
            secrets_path.write_text(json.dumps({"slack_webhook_url": "secret"}), encoding="utf-8")

            diagnostics.qpaths.PORTFOLIO_DATA_FILE = str(portfolio_path)
            diagnostics.qpaths.DATA_HEALTH_SNAPSHOT_FILE = str(health_path)
            diagnostics.qpaths.PRICE_CACHE_FILE = str(cache_path)
            diagnostics._SAFE_STATE_FILES = {"portfolio_data.json": str(portfolio_path), "data_health_snapshot.json": str(health_path)}
            diagnostics.summarize_recommendation_consistency = lambda now=None: {"status": "NO_ACTION"}

            bundle_path = root / "bundle.zip"
            bundle_path.write_bytes(diagnostics.build_diagnostics_bundle())
            with zipfile.ZipFile(bundle_path) as archive:
                names = set(archive.namelist())
                self.assertIn("diagnostics_summary.json", names)
                self.assertIn("state/portfolio_data.json", names)
                self.assertNotIn("state/notification_secrets.local.json", names)
                summary = json.loads(archive.read("diagnostics_summary.json").decode("utf-8"))
                self.assertEqual(summary["portfolio"]["holding_count"], 1)
                self.assertEqual(summary["data_health"]["health_reason"], "fallback_source_used")


if __name__ == "__main__":
    unittest.main()
