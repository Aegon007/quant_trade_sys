import unittest
from datetime import datetime, timedelta


class NewsSummaryTests(unittest.TestCase):
    def test_summarize_news_events_handles_empty_input(self):
        from news_summary import summarize_news_events

        summary = summarize_news_events([], lang="zh")

        self.assertEqual(summary.event_count, 0)
        self.assertEqual(summary.top_headlines, [])
        self.assertIn("暂无", summary.overview)

    def test_summarize_news_events_detects_negative_tone(self):
        from event_news import MarketEvent
        from news_summary import summarize_news_events

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
        from event_news import MarketEvent
        from news_summary import summarize_news_events

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


if __name__ == "__main__":
    unittest.main()
