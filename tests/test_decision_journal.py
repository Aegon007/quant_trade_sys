import json
import tempfile
import unittest
from pathlib import Path

from tests.support import clear_modules, reload_module


class DecisionJournalTests(unittest.TestCase):
    def setUp(self):
        clear_modules("quant_core.execution.decision_journal")
        self.module = reload_module("quant_core.execution.decision_journal")

    def test_build_nightly_decision_entry_extracts_core_fields(self):
        entry = self.module.build_nightly_decision_entry(
            {
                "generated_at": "2026-06-06T22:00:00",
                "decision_signature": "abcd1234",
                "trade_plan": {
                    "plan_date": "2026-06-09",
                    "decision": "ACTION",
                    "has_actions": True,
                    "action_count": 2,
                    "summary_reason": "有两条强信号。",
                    "items": [{"symbol": "QQQ", "plan_action": "ADD"}],
                },
                "risk": {"regime": "CAUTION"},
                "allocation_regime": {"regime": "LIGHT"},
                "discipline_snapshot": {"regime": "LIGHT"},
                "monthly_discipline_review": {"status": "CAUTION"},
                "strategy_validation_snapshot": {"summary": {"status": "REVIEW"}},
                "core_etf_snapshot": {
                    "summary": {"focus_symbols": ["QQQ"]},
                    "symbols": [{"symbol": "QQQ", "action": "HOLD", "rotation_score": 72.0, "signal_stability_score": 80.0}],
                },
                "satellite_candidate_snapshot": {
                    "summary": {"top_symbols": ["NVDA"]},
                    "top_recommendations": [{"symbol": "NVDA", "recommendation_status": "CONFIRMED", "top3_membership_state": "RETAINED"}],
                },
                "change_feed": {"high_items": [{"message": "纪律层转为 LIGHT。"}]},
                "execution_review": {"status": "OK", "executed_count": 1, "missed_count": 0, "unplanned_trade_count": 0},
            }
        )

        self.assertEqual(entry["decision_signature"], "abcd1234")
        self.assertEqual(entry["trade_plan_decision"], "ACTION")
        self.assertEqual(entry["risk_regime"], "CAUTION")
        self.assertEqual(entry["strategy_validation_status"], "REVIEW")
        self.assertEqual(entry["top3_symbols"], ["NVDA"])
        self.assertEqual(entry["high_priority_change_messages"], ["纪律层转为 LIGHT。"])

    def test_append_and_load_nightly_decision_journal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            journal_path = str(Path(tmpdir) / "decision.jsonl")
            self.module.append_nightly_decision_journal(
                {"generated_at": "2026-06-06T22:00:00", "trade_plan": {"decision_signature": "sig-1"}},
                journal_path=journal_path,
            )
            self.module.append_nightly_decision_journal(
                {"generated_at": "2026-06-07T22:00:00", "trade_plan": {"decision_signature": "sig-2"}},
                journal_path=journal_path,
            )

            rows = self.module.load_nightly_decision_journal(journal_path=journal_path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[-1]["decision_signature"], "sig-2")

            raw = Path(journal_path).read_text(encoding="utf-8").splitlines()
            self.assertEqual(json.loads(raw[0])["decision_signature"], "sig-1")


if __name__ == "__main__":
    unittest.main()
