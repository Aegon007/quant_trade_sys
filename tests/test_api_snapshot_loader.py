import json
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from tests.support import clear_modules, reload_module


class ApiSnapshotLoaderTests(unittest.TestCase):
    def setUp(self):
        clear_modules("quant_core.api.snapshot_loader", "quant_core.jobs.job_registry")
        self.loader = reload_module("quant_core.api.snapshot_loader")
        self.registry = reload_module("quant_core.jobs.job_registry")

    def test_load_snapshot_response_marks_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "missing.json"

            response = self.loader.load_snapshot_response("core-etfs", str(missing_path))

        self.assertEqual(response["freshness_status"], "MISSING")
        self.assertTrue(response["is_stale"])
        self.assertTrue(response["errors"])
        self.assertEqual(response["payload"], {})

    def test_load_snapshot_response_extracts_summary_and_items(self):
        now = datetime.fromisoformat("2026-06-11T12:00:00")
        generated_at = (now - timedelta(minutes=10)).isoformat()
        payload = {
            "generated_at": generated_at,
            "summary": {"risk_regime": "NORMAL"},
            "symbols": [{"symbol": "VOO", "action": "HOLD"}],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "snapshot.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            response = self.loader.load_snapshot_response("core-etfs", str(path), now=now)

        self.assertEqual(response["freshness_status"], "OK")
        self.assertFalse(response["is_stale"])
        self.assertEqual(response["summary"], {"risk_regime": "NORMAL"})
        self.assertEqual(response["items"], [{"symbol": "VOO", "action": "HOLD"}])

    def test_load_runtime_schedule_merges_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "runtime_schedule.json"
            path.write_text(
                json.dumps({"trading_hours": {"market_monitor_interval_seconds": 900}}),
                encoding="utf-8",
            )

            schedule = self.loader.load_runtime_schedule(path=str(path))

        self.assertEqual(schedule["trading_hours"]["market_monitor_interval_seconds"], 900)
        self.assertEqual(schedule["trading_hours"]["tactical_watchlist_interval_seconds"], 600)
        self.assertIn("nightly", schedule)

    def test_normalize_runtime_schedule_clamps_invalid_intervals(self):
        schedule = self.loader.normalize_runtime_schedule(
            {
                "trading_hours": {
                    "market_monitor_interval_seconds": 0,
                    "data_health_interval_seconds": -1,
                },
                "nightly": {"poll_seconds": "bad"},
            }
        )

        self.assertEqual(schedule["trading_hours"]["market_monitor_interval_seconds"], 60)
        self.assertEqual(schedule["trading_hours"]["data_health_interval_seconds"], 300)
        self.assertEqual(schedule["nightly"]["poll_seconds"], 300)

    def test_job_registry_updates_status_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "job_status.json"

            payload = self.registry.update_job_status(
                "api-server",
                state="started",
                detail="python -m jobs.api_server",
                pid=1234,
                path=str(path),
                now=datetime.fromisoformat("2026-06-11T12:00:00"),
            )
            loaded = self.registry.load_job_status(path=str(path))

        self.assertEqual(payload["jobs"]["api-server"]["state"], "started")
        self.assertEqual(loaded["jobs"]["api-server"]["pid"], 1234)


if __name__ == "__main__":
    unittest.main()
