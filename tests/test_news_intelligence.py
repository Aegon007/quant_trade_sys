import tempfile
import unittest
from datetime import datetime
from pathlib import Path


class NewsIntelligenceTests(unittest.TestCase):
    def setUp(self):
        from quant_core.events import news_intelligence
        from quant_core.events.event_news import MarketEvent

        self.module = news_intelligence
        self.MarketEvent = MarketEvent

    def test_build_analyst_context_labels_structured_consensus(self):
        context = self.module.build_analyst_context(
            {
                "last_updated": "2026-06-20T00:15:00",
                "recommendations": {
                    "MSFT": {
                        "signal": "STRONG_BUY",
                        "total_analysts": 40,
                        "bullish_ratio": 0.95,
                        "reason": "38 of 40 analysts are bullish",
                        "source": "yfinance",
                        "retrieved_at": "2026-06-20T00:15:00",
                    }
                },
            },
            ["MSFT", "VOO"],
        )

        self.assertEqual(context["input_type"], "structured_consensus")
        self.assertEqual(context["covered_count"], 1)
        self.assertEqual(context["records"][0]["symbol"], "MSFT")
        self.assertFalse(context["includes_report_text"])

    def test_build_news_intelligence_keeps_evidence_and_llm_summary(self):
        events = [
            self.MarketEvent(
                event_id="news-1",
                title="Microsoft raises cloud outlook",
                event_type="earnings",
                severity="high",
                symbols=["MSFT"],
                source="Company IR",
                verified=True,
                sentiment="positive",
                confidence_score=0.9,
            ),
            self.MarketEvent(
                event_id="macro-1",
                title="Rates remain elevated",
                event_type="macro",
                severity="high",
                symbols=[],
                source="Federal Reserve",
                verified=True,
                sentiment="negative",
                confidence_score=0.95,
            ),
        ]

        snapshot = self.module.build_news_intelligence(
            events=events,
            portfolio_symbols=["MSFT", "QQQM"],
            candidate_symbols=["NVDA"],
            analyst_cache={"recommendations": {}},
            notification_config={"llm": {"enabled": True, "base_url": "https://example.test/v1", "model": "test"}},
            llm_runner=lambda **kwargs: (
                True,
                "云业务利好 MSFT，但高利率仍压制整体风险偏好。",
                {"route_name": "llm", "model": "test-model", "cached": False, "fallback_attempts": []},
            ),
            now=datetime(2026, 6, 20, 1, 0, 0),
        )

        self.assertEqual(snapshot["status"], "READY")
        self.assertEqual(snapshot["executive_summary"], "云业务利好 MSFT，但高利率仍压制整体风险偏好。")
        self.assertEqual(snapshot["llm"]["route_name"], "llm")
        msft = next(row for row in snapshot["portfolio_impacts"] if row["symbol"] == "MSFT")
        self.assertIn("news-1", msft["event_ids"])
        self.assertTrue(msft["evidence"])
        self.assertEqual(msft["direction"], "MIXED")

    def test_build_news_intelligence_sanitizes_markdown_table_summary(self):
        event = self.MarketEvent(
            event_id="news-1",
            title="Microsoft raises cloud outlook",
            event_type="earnings",
            severity="high",
            symbols=["MSFT"],
            source="Company IR",
            verified=True,
            sentiment="positive",
            confidence_score=0.9,
        )

        snapshot = self.module.build_news_intelligence(
            events=[event],
            portfolio_symbols=["MSFT"],
            candidate_symbols=[],
            analyst_cache={},
            notification_config={"llm": {"enabled": True}},
            llm_runner=lambda **kwargs: (
                True,
                "| 标的 | 影响 |\n|---|---|\n| MSFT | 云业务偏正面 |",
                {"route_name": "llm", "model": "test-model"},
            ),
        )

        self.assertNotIn("|---", snapshot["executive_summary"])
        self.assertIn("标的: MSFT", snapshot["executive_summary"])
        self.assertIn("影响: 云业务偏正面", snapshot["executive_summary"])

    def test_build_news_intelligence_falls_back_without_llm(self):
        event = self.MarketEvent(
            event_id="risk-1",
            title="Verified regulatory action",
            event_type="policy",
            severity="high",
            symbols=["BABA"],
            source="SEC",
            verified=True,
            sentiment="negative",
            confidence_score=0.9,
        )

        snapshot = self.module.build_news_intelligence(
            events=[event],
            portfolio_symbols=["BABA"],
            candidate_symbols=[],
            analyst_cache={},
            notification_config={},
            llm_runner=lambda **kwargs: (False, "not configured", {"route_name": "", "model": ""}),
        )

        self.assertEqual(snapshot["status"], "STRUCTURED_ONLY")
        self.assertIn("BABA", snapshot["executive_summary"])
        self.assertEqual(snapshot["portfolio_impacts"][0]["risk_action"], "REVIEW")

    def test_save_and_load_news_intelligence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "news_intelligence.json")
            payload = {"status": "READY", "generated_at": "2026-06-20T01:00:00"}
            self.module.save_news_intelligence(payload, path=path)
            self.assertEqual(self.module.load_news_intelligence(path=path), payload)


if __name__ == "__main__":
    unittest.main()
