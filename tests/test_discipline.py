import unittest
from datetime import datetime
import tempfile
from pathlib import Path

from tests.support import clear_modules, reload_module


class DisciplineTests(unittest.TestCase):
    def setUp(self):
        clear_modules(
            "quant_core.analytics.core_etf_rotation",
            "quant_core.portfolio.discipline",
        )
        reload_module("quant_core.analytics.core_etf_rotation")
        self.module = reload_module("quant_core.portfolio.discipline")

    def test_build_discipline_snapshot_blocks_satellite_when_analysis_is_expired(self):
        allocation_regime = type(
            "Alloc",
            (),
            {
                "regime": "HEAVY",
                "reasons": ["expectancy positive"],
                "target_exposure_min_pct": 55.0,
                "target_exposure_max_pct": 95.0,
            },
        )()
        snapshot = self.module.build_discipline_snapshot(
            account_snapshot={"deployable_cash": 2000.0, "exposure_pct": 55.0},
            allocation_regime=allocation_regime,
            analysis_freshness_alert={"expired_symbols": ["AAPL"], "missing_symbols": []},
            now=datetime(2026, 5, 13, 22, 0, 0),
        )

        self.assertEqual(snapshot["regime"], "LIGHT")
        self.assertFalse(snapshot["can_open_new_satellite_positions"])
        self.assertTrue(snapshot["warnings"])

    def test_build_discipline_snapshot_risk_off_results_in_stop(self):
        risk_gate = type("Risk", (), {"regime": "RISK_OFF", "reasons": ["VIX spike"]})()
        allocation_regime = type("Alloc", (), {"regime": "NORMAL", "reasons": []})()
        snapshot = self.module.build_discipline_snapshot(
            account_snapshot={"deployable_cash": 1000.0, "exposure_pct": 20.0},
            risk_gate=risk_gate,
            allocation_regime=allocation_regime,
        )

        self.assertEqual(snapshot["regime"], "STOP")
        self.assertFalse(snapshot["can_open_new_satellite_positions"])
        self.assertIn("RISK_OFF", snapshot["summary"])

    def test_build_monthly_discipline_review_groups_follow_and_ignore_days(self):
        journal_rows = [
            {
                "generated_at": "2026-05-10T23:00:00",
                "daily_recap": {"day": "2026-05-10", "trade_count": 0, "realized_pl": 0.0, "symbols": []},
                "trade_plan": {"has_actions": False},
                "execution_review": {"executed_count": 0, "missed_count": 0, "unplanned_trade_count": 0},
                "discipline_snapshot": {"regime": "LIGHT"},
            },
            {
                "generated_at": "2026-05-11T23:00:00",
                "daily_recap": {"day": "2026-05-11", "trade_count": 1, "realized_pl": 120.0, "symbols": ["QQQ"]},
                "trade_plan": {"has_actions": True},
                "execution_review": {"executed_count": 1, "missed_count": 0, "unplanned_trade_count": 0},
                "discipline_snapshot": {"regime": "NORMAL"},
            },
            {
                "generated_at": "2026-05-12T23:00:00",
                "daily_recap": {"day": "2026-05-12", "trade_count": 1, "realized_pl": -80.0, "symbols": ["TSLA"]},
                "trade_plan": {"has_actions": False},
                "execution_review": {"executed_count": 0, "missed_count": 0, "unplanned_trade_count": 1},
                "discipline_snapshot": {"regime": "STOP"},
            },
        ]

        scoreboard = type("Scoreboard", (), {"expectancy_return_pct": 0.01, "win_rate": 0.6})()
        review = self.module.build_monthly_discipline_review(
            discipline_snapshot={"regime": "LIGHT"},
            scoreboard=scoreboard,
            latest_post_close_review={"executed_count": 0, "missed_count": 0, "unplanned_trade_count": 1},
            snapshot_journal=journal_rows,
            now=datetime(2026, 5, 14, 9, 0, 0),
        )

        self.assertEqual(review["follow_days"], 2)
        self.assertEqual(review["ignore_days"], 1)
        self.assertEqual(review["follow_action_days"], 1)
        self.assertEqual(review["follow_idle_days"], 1)
        self.assertEqual(review["ignore_idle_days"], 1)
        self.assertEqual(review["defensive_override_days"], 1)
        self.assertEqual(review["follow_realized_pl"], 120.0)
        self.assertEqual(review["ignore_realized_pl"], -80.0)
        self.assertEqual(review["follow_directional_hit_rate"], 0.5)
        self.assertEqual(review["ignore_directional_hit_rate"], 0.0)
        self.assertEqual(review["defensive_override_penalty_rate"], 1.0)

    def test_build_monthly_discipline_review_can_load_jsonl_journal(self):
        scoreboard = type("Scoreboard", (), {"expectancy_return_pct": None, "win_rate": None})()
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "nightly_snapshot_journal.jsonl"
            journal_path.write_text(
                '{"generated_at":"2026-05-10T23:00:00","daily_recap":{"day":"2026-05-10","trade_count":0,"realized_pl":0.0,"symbols":[]},"trade_plan":{"has_actions":false},"execution_review":{"executed_count":0,"missed_count":0,"unplanned_trade_count":0},"discipline_snapshot":{"regime":"NORMAL"}}\n',
                encoding="utf-8",
            )

            review = self.module.build_monthly_discipline_review(
                discipline_snapshot={"regime": "NORMAL"},
                scoreboard=scoreboard,
                journal_path=str(journal_path),
                now=datetime(2026, 5, 14, 9, 0, 0),
            )

        self.assertEqual(review["follow_days"], 1)
        self.assertEqual(review["ignore_days"], 0)
        self.assertEqual(review["status"], "ALIGNED")


if __name__ == "__main__":
    unittest.main()
