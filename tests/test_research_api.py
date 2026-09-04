import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_core.api import snapshot_loader


class ResearchApiContractTests(unittest.TestCase):
    def test_dashboard_is_position_independent(self):
        fixtures = {
            "recommendation": {"generated_at": "2026-07-30T20:00:00", "status": "READY", "recommendations": [{"symbol": "MSFT", "recommendation": "WATCH"}]},
            "brief": {"generated_at": "2026-07-30T20:00:00", "headline": "当前无强信号", "summary_text": "等待。"},
            "risk": {"generated_at": "2026-07-30T20:00:00", "regime": "NORMAL", "risk_score": 25},
            "health": {"generated_at": "2026-07-30T20:00:00", "status": "OK"},
        }
        path_keys = {
            snapshot_loader.qpaths.RECOMMENDATION_SNAPSHOT_FILE: "recommendation",
            snapshot_loader.qpaths.DECISION_BRIEF_FILE: "brief",
            snapshot_loader.qpaths.MARKET_RISK_SNAPSHOT_FILE: "risk",
            snapshot_loader.qpaths.DATA_HEALTH_SNAPSHOT_FILE: "health",
        }
        with patch.object(snapshot_loader, "_load", side_effect=lambda path: fixtures.get(path_keys.get(path), {})):
            response = snapshot_loader.load_dashboard_response()

        payload = response["payload"]
        self.assertIn("recommendations", payload)
        self.assertIn("market_risk", payload)
        for forbidden in ("account", "holdings", "cash_available", "transactions"):
            self.assertNotIn(forbidden, payload)

    def test_snapshot_envelope_reports_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            response = snapshot_loader.load_snapshot_response("opportunities", str(Path(temp_dir) / "missing.json"))
        self.assertEqual(response["freshness_status"], "MISSING")
        self.assertTrue(response["is_stale"])

    def test_manifest_has_a_read_only_snapshot_endpoint(self):
        from jobs.api_server import create_app

        paths = {route.path for route in create_app().routes}

        self.assertIn("/api/research-manifest", paths)
        self.assertIn("/api/actions/test-notification", paths)


if __name__ == "__main__":
    unittest.main()
