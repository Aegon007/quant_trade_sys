import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


class EventNewsTests(unittest.TestCase):
    def test_load_market_events_normalizes_and_parses(self):
        from quant_core.events.event_news import load_market_events

        now = datetime(2026, 5, 8, 12, 0, 0)
        payload = {
            "events": [
                {
                    "id": "fomc-2026-05",
                    "title": "FOMC Rate Decision",
                    "event_type": "FOMC",
                    "severity": "HIGH",
                    "starts_at": (now - timedelta(hours=1)).isoformat(),
                    "ends_at": (now + timedelta(hours=3)).isoformat(),
                    "symbols": ["spy", "qqq"],
                    "verified": True,
                    "source": "Federal Reserve",
                    "tags": ["macro", "fomc"],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "market_events.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            events = load_market_events(path=str(path))

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, "fomc")
        self.assertEqual(event.severity, "high")
        self.assertEqual(event.symbols, ["SPY", "QQQ"])
        self.assertTrue(event.verified)
        self.assertIn("fomc", event.tags)
        self.assertIsNotNone(event.starts_at)
        self.assertIsNotNone(event.ends_at)

    def test_active_events_filters_by_time_and_symbol(self):
        from quant_core.events.event_news import MarketEvent, select_active_events

        now = datetime(2026, 5, 8, 12, 0, 0)
        events = [
            MarketEvent(
                event_id="1",
                title="FOMC",
                event_type="fomc",
                severity="high",
                starts_at=now - timedelta(hours=1),
                ends_at=now + timedelta(hours=1),
                symbols=["SPY"],
                tags=["fomc"],
                verified=True,
            ),
            MarketEvent(
                event_id="2",
                title="Old Event",
                event_type="macro",
                severity="high",
                starts_at=now - timedelta(days=2),
                ends_at=now - timedelta(days=1),
                symbols=["SPY"],
                verified=True,
            ),
        ]

        filtered = select_active_events(events, symbols=["AAPL"], now=now)
        self.assertEqual(len(filtered), 0)

        filtered = select_active_events(events, symbols=["SPY"], now=now)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].event_id, "1")

    def test_evaluate_event_risk_switch_triggers_brake(self):
        from quant_core.events.event_news import MarketEvent, evaluate_event_risk_switch

        now = datetime(2026, 5, 8, 12, 0, 0)
        events = [
            MarketEvent(
                event_id="fomc",
                title="FOMC Press Conference",
                event_type="fomc",
                severity="high",
                starts_at=now - timedelta(minutes=30),
                ends_at=now + timedelta(hours=2),
                verified=True,
                tags=["fomc"],
            )
        ]
        decision = evaluate_event_risk_switch(events=events, vix=19.0, now=now)
        self.assertEqual(decision.regime, "RISK_OFF")
        self.assertTrue(decision.block_new_buys)
        self.assertLessEqual(decision.max_position_weight, 0.08)

    def test_evaluate_event_risk_switch_ignores_unverified_when_requested(self):
        from quant_core.events.event_news import MarketEvent, evaluate_event_risk_switch

        now = datetime(2026, 5, 8, 12, 0, 0)
        events = [
            MarketEvent(
                event_id="rumor",
                title="Unverified policy rumor",
                event_type="policy",
                severity="high",
                starts_at=now - timedelta(minutes=30),
                ends_at=now + timedelta(hours=2),
                verified=False,
            )
        ]
        decision = evaluate_event_risk_switch(events=events, vix=18.0, verified_only=True, now=now)
        self.assertEqual(decision.regime, "NORMAL")
        self.assertFalse(decision.block_new_buys)

    def test_evaluate_event_risk_switch_uses_vix_brake(self):
        from quant_core.events.event_news import evaluate_event_risk_switch

        decision = evaluate_event_risk_switch(events=[], vix=36.0)
        self.assertEqual(decision.regime, "RISK_OFF")
        self.assertTrue(decision.block_new_buys)

    def test_event_confidence_prefers_verified_official_sources(self):
        from quant_core.events.event_news import MarketEvent, compute_event_confidence_score

        official = MarketEvent(
            event_id="fed-1",
            title="FOMC Rate Decision",
            event_type="fomc",
            severity="high",
            source="Federal Reserve",
            verified=True,
        )
        rumor = MarketEvent(
            event_id="rumor-1",
            title="Unconfirmed social media rumor",
            event_type="macro",
            severity="high",
            source="social media",
            verified=False,
        )

        official_score = compute_event_confidence_score(official)
        rumor_score = compute_event_confidence_score(rumor)
        self.assertGreater(official_score, rumor_score)
        self.assertGreaterEqual(official_score, 0.7)
        self.assertLessEqual(rumor_score, 0.45)

    def test_ensure_market_events_file_bootstraps_from_example(self):
        from quant_core.events.event_news import ensure_market_events_file

        payload = {"events": [{"id": "seed-1", "title": "Seed Event"}]}
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_path = root / "market_events.json"
            example_path = root / "market_events.example.json"
            example_path.write_text(json.dumps(payload), encoding="utf-8")

            created = ensure_market_events_file(
                path=str(target_path),
                example_path=str(example_path),
            )

            self.assertTrue(created)
            self.assertTrue(target_path.exists())
            self.assertEqual(json.loads(target_path.read_text(encoding="utf-8")), payload)

    def test_load_market_events_auto_bootstraps_missing_file_from_example(self):
        from quant_core.events.event_news import load_market_events

        now = datetime(2026, 5, 8, 12, 0, 0)
        payload = {
            "events": [
                {
                    "id": "seed-2",
                    "title": "Bootstrap Event",
                    "event_type": "macro",
                    "severity": "medium",
                    "starts_at": now.isoformat(),
                    "verified": True,
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_path = root / "market_events.json"
            example_path = root / "market_events.example.json"
            example_path.write_text(json.dumps(payload), encoding="utf-8")

            events = load_market_events(
                path=str(target_path),
                example_path=str(example_path),
                auto_bootstrap=True,
            )

            self.assertEqual(len(events), 1)
            self.assertTrue(target_path.exists())
            self.assertEqual(events[0].event_id, "seed-2")


if __name__ == "__main__":
    unittest.main()
