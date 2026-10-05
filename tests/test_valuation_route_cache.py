import tempfile
import unittest

from quant_core.valuation.router import route_valuation_model


FINANCIALS = {
    "symbol": "ACME",
    "status": "READY",
    "asset_type": "equity",
    "sector": "Technology",
    "revenue": 100_000_000_000,
    "net_income": 20_000_000_000,
    "free_cash_flow": 18_000_000_000,
    "cash": 25_000_000_000,
    "total_debt": 8_000_000_000,
    "shares_outstanding": 1_000_000_000,
    "revenue_growth": 0.12,
    "fiscal_period": "2026-Q2",
    "latest_filing_date": "2026-07-25",
}


class ValuationRouteCacheTests(unittest.TestCase):
    def test_rule_fallback_confidence_reflects_available_evidence(self):
        route = route_valuation_model(
            symbol="ACME",
            asset_type="equity",
            financials=FINANCIALS,
            llm_config={"enabled": False},
        )

        self.assertEqual(route["route_source"], "rules")
        self.assertGreaterEqual(route["confidence"], 0.55)
        self.assertIn("confidence_components", route)

    def test_successful_llm_route_is_reused_from_local_cache(self):
        calls = []

        def runner(_messages, _config):
            calls.append(1)
            return True, '{"asset_type":"equity","archetype":"mature_growth","primary_model":"fcff_multistage","confidence":0.78,"evidence":["2026-Q2 filing"]}'

        with tempfile.TemporaryDirectory() as cache_dir:
            first = route_valuation_model(
                symbol="ACME", asset_type="equity", financials=FINANCIALS,
                llm_config={"enabled": True, "model": "test-model"}, llm_runner=runner, cache_dir=cache_dir,
            )
            second = route_valuation_model(
                symbol="ACME", asset_type="equity", financials=FINANCIALS,
                llm_config={"enabled": True, "model": "test-model"}, llm_runner=runner, cache_dir=cache_dir,
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(first["route_source"], "llm")
        self.assertEqual(second["route_source"], "llm_cache")


if __name__ == "__main__":
    unittest.main()
