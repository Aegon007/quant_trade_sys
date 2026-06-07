import unittest
from datetime import datetime, timedelta


class NewsSummaryTests(unittest.TestCase):
    def test_summarize_news_events_handles_empty_input(self):
        from quant_core.events.news_summary import summarize_news_events

        summary = summarize_news_events([], lang="zh")

        self.assertEqual(summary.event_count, 0)
        self.assertEqual(summary.top_headlines, [])
        self.assertIn("暂无", summary.overview)

    def test_summarize_news_events_detects_negative_tone(self):
        from quant_core.events.event_news import MarketEvent
        from quant_core.events.news_summary import summarize_news_events

        now = datetime(2026, 5, 9, 10, 0, 0)
        events = [
            MarketEvent(
                event_id="n1",
                title="Policy uncertainty rises",
                severity="high",
                sentiment="negative",
                confidence_score=0.8,
                confidence_level="high",
                starts_at=now - timedelta(hours=1),
                ends_at=now + timedelta(hours=2),
                source="Reuters",
                verified=True,
            ),
            MarketEvent(
                event_id="n2",
                title="Company beats estimates",
                severity="medium",
                sentiment="positive",
                confidence_score=0.6,
                confidence_level="medium",
                starts_at=now - timedelta(hours=1),
                ends_at=now + timedelta(hours=2),
                source="Bloomberg",
                verified=True,
            ),
        ]

        summary = summarize_news_events(events, lang="en")

        self.assertEqual(summary.event_count, 2)
        self.assertEqual(summary.dominant_sentiment, "negative")
        self.assertGreaterEqual(summary.negative_count, summary.positive_count)
        self.assertIn("negative", summary.overview.lower())

    def test_summarize_news_events_prioritizes_high_severity_and_confidence(self):
        from quant_core.events.event_news import MarketEvent
        from quant_core.events.news_summary import summarize_news_events

        now = datetime(2026, 5, 9, 10, 0, 0)
        events = [
            MarketEvent(
                event_id="low",
                title="Minor sector note",
                severity="low",
                sentiment="neutral",
                confidence_score=0.4,
                confidence_level="low",
                starts_at=now - timedelta(hours=1),
                ends_at=now + timedelta(hours=2),
                source="Blog",
                verified=False,
            ),
            MarketEvent(
                event_id="high",
                title="FOMC decision window opens",
                severity="high",
                event_type="fomc",
                sentiment="negative",
                confidence_score=0.9,
                confidence_level="high",
                starts_at=now - timedelta(hours=1),
                ends_at=now + timedelta(hours=2),
                source="Federal Reserve",
                verified=True,
            ),
        ]

        summary = summarize_news_events(events, lang="zh", max_headlines=1)

        self.assertEqual(len(summary.top_headlines), 1)
        self.assertIn("FOMC", summary.top_headlines[0])
        self.assertEqual(len(summary.top_headline_details), 1)
        detail = summary.top_headline_details[0]
        self.assertEqual(detail.event_id, "high")
        self.assertGreater(detail.total_score, 0)
        self.assertGreaterEqual(detail.severity_component, 1.0)
        self.assertGreaterEqual(detail.confidence_component, 0.9)
        self.assertIn("总分", detail.explanation_zh)
        self.assertIn("Total", detail.explanation_en)

    def test_summarize_news_events_builds_theme_focuses_and_signature(self):
        from quant_core.events.event_news import MarketEvent
        from quant_core.events.news_summary import (
            build_news_summary_payload,
            build_news_summary_signature,
            summarize_news_events,
        )

        now = datetime(2026, 5, 9, 10, 0, 0)
        events = [
            MarketEvent(
                event_id="macro-1",
                title="FOMC uncertainty lifts volatility",
                event_type="fomc",
                severity="high",
                sentiment="negative",
                confidence_score=0.9,
                confidence_level="high",
                starts_at=now - timedelta(hours=1),
                ends_at=now + timedelta(hours=2),
                source="Reuters",
                verified=True,
                symbols=["QQQ", "SPY"],
            ),
            MarketEvent(
                event_id="symbol-1",
                title="NVDA supplier demand remains firm",
                event_type="company",
                severity="medium",
                sentiment="positive",
                confidence_score=0.7,
                confidence_level="medium",
                starts_at=now - timedelta(hours=1),
                ends_at=now + timedelta(hours=2),
                source="Bloomberg",
                verified=True,
                symbols=["NVDA"],
            ),
        ]

        summary = summarize_news_events(events, lang="zh", max_headlines=2)
        payload = build_news_summary_payload(summary)
        signature = build_news_summary_signature(summary)

        self.assertGreaterEqual(len(summary.theme_focuses), 2)
        self.assertGreaterEqual(len(summary.focus_points), 1)
        self.assertTrue(signature)
        self.assertEqual(payload["event_count"], 2)
        self.assertIn("theme_focuses", payload)
        self.assertIn("focus_points", payload)
        self.assertIn("FOMC", payload["theme_focuses"][0]["summary_zh"])


if __name__ == "__main__":
    unittest.main()
