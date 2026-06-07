import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tests.support import clear_modules, reload_module


class WeekendResearchTests(unittest.TestCase):
    def setUp(self):
        clear_modules("quant_core.research.weekend_research")
        self.module = reload_module("quant_core.research.weekend_research")

    def test_should_run_weekend_research_once_per_cycle(self):
        now = datetime.fromisoformat("2026-06-07T11:15:00")
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = str(Path(temp_dir) / "weekend_research_state.json")
            alert_settings = {
                "enable_weekend_research": True,
                "weekend_research_day_local": "sunday",
                "weekend_research_hour_local": 11,
                "weekend_research_minute_local": 0,
            }
            self.assertTrue(
                self.module.should_run_weekend_research(
                    now=now,
                    alert_settings=alert_settings,
                    state_path=state_path,
                )
            )
            self.module.mark_weekend_research_done(
                now=now,
                alert_settings=alert_settings,
                snapshot={"summary": {"next_week_bias": "BALANCED"}},
                state_path=state_path,
            )
            self.assertFalse(
                self.module.should_run_weekend_research(
                    now=now,
                    alert_settings=alert_settings,
                    state_path=state_path,
                )
            )

    def test_build_weekend_research_snapshot_infers_bias(self):
        now = datetime.fromisoformat("2026-06-07T11:15:00")
        snapshot = self.module.build_weekend_research_snapshot(
            now=now,
            history_period="5y",
            risk_gate={"regime": "RISK_OFF"},
            allocation_regime={"regime": "STOP"},
            core_rotation_snapshot={"summary": {"focus_symbols": ["VOO"]}},
            core_snapshot={"summary": {"focus_symbols": ["VOO"], "accumulate_count": 0}},
            satellite_snapshot={"summary": {"confirmed_count": 0}, "top_recommendations": []},
            strategy_research_rows=[],
            strategy_validation_snapshot={"summary": {"status": "NO_DATA"}},
        )
        self.assertEqual(snapshot["summary"]["next_week_bias"], "DEFENSIVE")
        self.assertIn("防守", snapshot["summary"]["message"])
        self.assertEqual(snapshot["strategy_validation_snapshot"]["summary"]["status"], "NO_DATA")


if __name__ == "__main__":
    unittest.main()
