import tempfile
import unittest
from datetime import datetime
from pathlib import Path


class IntradayJournalTests(unittest.TestCase):
    def setUp(self):
        from quant_core.monitoring import intraday_journal

        self.module = intraday_journal

    def test_append_and_load_intraday_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = str(Path(temp_dir) / "intraday_event_journal.jsonl")
            entry = self.module.build_intraday_event_entry(
                event_type="DISCIPLINE_MONTH_DETERIORATION",
                priority="high",
                now=datetime.fromisoformat("2026-05-14T10:30:00"),
                trigger_reason="月度纪律状态变化",
                was_alert_sent=True,
                send_context="intraday_alert",
                payload={"monthly_status": "CAUTION", "ignore_days": 4},
            )
            self.module.append_intraday_event(entry, journal_path=journal_path)
            rows = self.module.load_intraday_events(journal_path=journal_path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_type"], "DISCIPLINE_MONTH_DETERIORATION")
        self.assertTrue(rows[0]["was_alert_sent"])
        self.assertEqual(rows[0]["payload"]["monthly_status"], "CAUTION")

    def test_annotate_event_outcomes_marks_favorable_and_trade_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = str(Path(temp_dir) / "intraday_event_journal.jsonl")
            entry = self.module.build_intraday_event_entry(
                event_type="PLAN_BUY_ZONE_TRIGGER",
                priority="high",
                now=datetime.fromisoformat("2026-05-14T10:30:00"),
                symbol="AAPL",
                trigger_reason="buy_zone",
                was_alert_sent=True,
                send_context="intraday_alert",
                payload={"reference_price": 100.0, "action_side": "BUY"},
            )
            self.module.append_intraday_event(entry, journal_path=journal_path)
            summary = self.module.annotate_intraday_event_outcomes(
                journal_path=journal_path,
                review_day="2026-05-14",
                end_of_day_prices={"AAPL": 103.0},
                transactions=[
                    {
                        "record_type": "TRADE",
                        "date": "2026-05-14 10:35",
                        "symbol": "AAPL",
                        "side": "BUY",
                        "shares": 1.0,
                        "price": 100.5,
                    }
                ],
            )
            rows = self.module.load_intraday_events(journal_path=journal_path)

        self.assertEqual(summary["reviewed_count"], 1)
        self.assertEqual(summary["favorable_count"], 1)
        self.assertEqual(rows[0]["outcome_label"], "FAVORABLE")
        self.assertAlmostEqual(rows[0]["same_day_close_return_pct"], 0.03, places=6)
        self.assertEqual(rows[0]["matched_trade_count"], 1)
