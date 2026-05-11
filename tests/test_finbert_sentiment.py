import unittest

from tests.support import clear_modules


class FinBertSentimentTests(unittest.TestCase):
    def test_keyword_fallback_classifies_positive_and_negative(self):
        from quant_core.events.finbert_sentiment import analyze_financial_sentiment

        positive = analyze_financial_sentiment("Company beats earnings and raises guidance.", use_finbert=False)
        negative = analyze_financial_sentiment("Company misses earnings and cuts outlook.", use_finbert=False)

        self.assertEqual(positive["label"], "positive")
        self.assertEqual(negative["label"], "negative")
        self.assertEqual(positive["method"], "keyword")
        self.assertEqual(negative["method"], "keyword")

    def test_transformers_pipeline_is_used_when_available(self):
        import sys
        import types

        clear_modules("quant_core.events.finbert_sentiment")
        fake_transformers = types.ModuleType("transformers")

        def fake_pipeline(_task, model=None, tokenizer=None):
            def run(text):
                return [{"label": "positive", "score": 0.88}]
            return run

        fake_transformers.pipeline = fake_pipeline
        sys.modules["transformers"] = fake_transformers

        from quant_core.events.finbert_sentiment import analyze_financial_sentiment

        result = analyze_financial_sentiment("Mock headline", use_finbert=True)
        self.assertEqual(result["label"], "positive")
        self.assertEqual(result["method"], "finbert")
        self.assertGreaterEqual(result["score"], 0.8)


if __name__ == "__main__":
    unittest.main()
