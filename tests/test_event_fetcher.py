import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tests.support import clear_modules


class EventFetcherTests(unittest.TestCase):
    def test_fetch_events_from_local_source_config(self):
        from quant_core.events.event_fetcher import fetch_events_from_sources

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            events_path = root / "market_events.json"
            config_path = root / "event_sources.json"
            events_path.write_text(
                json.dumps(
                    {
                        "events": [
                            {
                                "id": "local-1",
                                "title": "Local Mock Event",
                                "event_type": "macro",
                                "severity": "medium",
                                "verified": True,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            config_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "id": "local_mock",
                                "type": "local_file",
                                "enabled": True,
                                "path": str(events_path),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            events, reports = fetch_events_from_sources(
                symbols=["AAPL"],
                config_path=str(config_path),
                now=datetime(2026, 5, 8, 12, 0, 0),
            )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_id, "local-1")
        self.assertEqual(events[0].source_id, "local_mock")
        self.assertEqual(len(reports), 1)
        self.assertTrue(reports[0]["ok"])
        self.assertEqual(reports[0]["fetched"], 1)

    def test_should_refresh_events_cache_on_first_fetch(self):
        from quant_core.events.event_fetcher import should_refresh_events_cache

        self.assertTrue(
            should_refresh_events_cache(
                last_fetched_at=None,
                previous_symbols=[],
                current_symbols=["AAPL"],
                interval_seconds=600,
                now=datetime(2026, 5, 8, 12, 0, 0),
            )
        )

    def test_should_refresh_events_cache_when_symbols_change(self):
        from quant_core.events.event_fetcher import should_refresh_events_cache

        now = datetime(2026, 5, 8, 12, 0, 0)
        self.assertTrue(
            should_refresh_events_cache(
                last_fetched_at=now.isoformat(),
                previous_symbols=["AAPL"],
                current_symbols=["AAPL", "MSFT"],
                interval_seconds=600,
                now=now,
            )
        )

    def test_should_refresh_events_cache_when_interval_elapsed(self):
        from quant_core.events.event_fetcher import should_refresh_events_cache

        now = datetime(2026, 5, 8, 12, 10, 1)
        self.assertTrue(
            should_refresh_events_cache(
                last_fetched_at=datetime(2026, 5, 8, 12, 0, 0).isoformat(),
                previous_symbols=["AAPL"],
                current_symbols=["AAPL"],
                interval_seconds=600,
                now=now,
            )
        )

    def test_should_not_refresh_events_cache_when_recent_and_same_symbols(self):
        from quant_core.events.event_fetcher import should_refresh_events_cache

        now = datetime(2026, 5, 8, 12, 5, 0)
        self.assertFalse(
            should_refresh_events_cache(
                last_fetched_at=datetime(2026, 5, 8, 12, 0, 30).isoformat(),
                previous_symbols=["AAPL", "MSFT"],
                current_symbols=["MSFT", "AAPL"],
                interval_seconds=600,
                now=now,
            )
        )

    def test_fetch_events_from_yfinance_source_with_sentiment_callback(self):
        import sys
        import types

        now = datetime(2026, 5, 8, 12, 0, 0)
        clear_modules("quant_core.events.event_fetcher")

        class FakeTicker:
            def __init__(self, symbol):
                self.symbol = symbol

            @property
            def news(self):
                return [
                    {
                        "uuid": "news-1",
                        "title": "Apple beats estimates and raises guidance",
                        "publisher": "Reuters",
                        "link": "https://example.com/news-1",
                        "providerPublishTime": int(now.timestamp()),
                        "relatedTickers": ["AAPL"],
                    }
                ]

        fake_yf = types.ModuleType("yfinance")
        fake_yf.Ticker = FakeTicker
        sys.modules["yfinance"] = fake_yf

        from quant_core.events.event_fetcher import fetch_events_from_sources

        def sentiment_fn(text):
            return {
                "label": "positive",
                "score": 0.91,
                "positive": 0.91,
                "neutral": 0.07,
                "negative": 0.02,
                "method": "mock",
                "model": "mock-finbert",
            }

        events, reports = fetch_events_from_sources(
            symbols=["AAPL"],
            config={
                "sources": [
                    {"id": "yf_news", "type": "yfinance_news", "enabled": True, "verified": False}
                ]
            },
            now=now,
            sentiment_fn=sentiment_fn,
        )

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_id, "news-1")
        self.assertEqual(event.sentiment, "positive")
        self.assertGreaterEqual(event.sentiment_score, 0.9)
        self.assertEqual(event.sentiment_model, "mock-finbert")
        self.assertEqual(event.source_id, "yf_news")
        self.assertEqual(len(reports), 1)
        self.assertTrue(reports[0]["ok"])


if __name__ == "__main__":
    unittest.main()
