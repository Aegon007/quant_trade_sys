import unittest

from quant_core.execution import strategy_identity as si


class StrategyIdentityTests(unittest.TestCase):
    def test_classifies_known_strategy_sources(self):
        self.assertEqual(si.classify_signal({"strategy_source": "core_etf"}), "CORE_ETF_ALLOCATION")
        self.assertEqual(si.classify_signal({"list_type": "candidate_pool"}), "SATELLITE_TREND_RADAR")
        self.assertEqual(si.classify_signal({"category": "PORTFOLIO_RISK"}), "RISK_DISCIPLINE_GATE")
        self.assertEqual(si.classify_signal({"kind": "correlation_research"}), "WEEKEND_CORRELATION_RESEARCH")
        self.assertEqual(si.classify_signal({"source": "news_intelligence"}), "LLM_NEWS_EXPLANATION")

    def test_signal_badges_are_non_execution_for_research_and_llm(self):
        research = si.build_signal_identity({"kind": "correlation_research"})
        llm = si.build_signal_identity({"source": "news_intelligence"})
        self.assertFalse(research["can_create_trade_plan"])
        self.assertFalse(llm["can_create_trade_plan"])
        self.assertIn("周末", research["display_name"])


if __name__ == "__main__":
    unittest.main()
