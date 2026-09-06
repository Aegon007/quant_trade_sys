import unittest

from quant_core.valuation.engine import value_security
from quant_core.valuation.router import normalize_valuation_route, route_valuation_model


class ValuationEngineTests(unittest.TestCase):
    def test_route_preserves_filing_intelligence_for_user_review(self):
        route = normalize_valuation_route(
            {
                "asset_type": "equity",
                "archetype": "mature_growth",
                "primary_model": "fcff_multistage",
                "filing_summary": "资本开支上升，但经营现金流仍能覆盖投资。",
                "fundamental_signals": ["云业务增长", "自由现金流承压"],
                "risks": ["资本开支回报不确定"],
            }
        )

        self.assertIn("资本开支", route["filing_summary"])
        self.assertEqual(route["fundamental_signals"], ["云业务增长", "自由现金流承压"])

    def test_llm_router_receives_extracted_filing_text_without_local_cache_path(self):
        captured = {}

        def runner(messages, _config):
            captured["prompt"] = messages[-1]["content"]
            return True, '{"asset_type":"equity","archetype":"mature_growth","primary_model":"fcff_multistage","filing_summary":"现金流仍然稳健","fundamental_signals":["现金流稳健"],"risks":[],"evidence":["10-Q MD&A"]}'

        route = route_valuation_model(
            symbol="ACME",
            asset_type="equity",
            financials={
                "free_cash_flow": 100,
                "filing_context": {
                    "filings": [{
                        "form": "10-Q",
                        "filing_date": "2026-05-01",
                        "cache_path": "/private/cache/filing.htm",
                        "sections": [{"item": "2", "title": "MD&A", "text": "Capital expenditure increased."}],
                    }]
                },
            },
            llm_config={"enabled": True},
            llm_runner=runner,
        )

        self.assertIn("Capital expenditure increased", captured["prompt"])
        self.assertNotIn("/private/cache", captured["prompt"])
        self.assertEqual(route["filing_summary"], "现金流仍然稳健")

    def test_mature_company_valuation_is_probabilistic_and_reproducible(self):
        financials = {
            "symbol": "ACME",
            "free_cash_flow": 10_000_000_000,
            "revenue": 100_000_000_000,
            "operating_margin": 0.24,
            "cash": 20_000_000_000,
            "total_debt": 10_000_000_000,
            "shares_outstanding": 1_000_000_000,
        }
        route = normalize_valuation_route(
            {
                "asset_type": "equity",
                "archetype": "mature_growth",
                "primary_model": "fcff_multistage",
                "secondary_models": ["reverse_dcf"],
                "assumptions": {
                    "growth_rate": {"bear": 0.03, "base": 0.07, "bull": 0.11},
                    "discount_rate": {"bear": 0.11, "base": 0.09, "bull": 0.08},
                    "terminal_growth": {"bear": 0.02, "base": 0.025, "bull": 0.03},
                },
                "confidence": 0.8,
                "evidence": ["2026 Q2 filing"],
            }
        )

        first = value_security(financials, route, current_price=120.0, simulations=500, seed=7)
        second = value_security(financials, route, current_price=120.0, simulations=500, seed=7)

        self.assertEqual(first, second)
        self.assertLess(first["fair_value"]["p10"], first["fair_value"]["p50"])
        self.assertLess(first["fair_value"]["p50"], first["fair_value"]["p90"])
        self.assertAlmostEqual(
            first["margin_of_safety"],
            first["fair_value"]["p50"] / 120.0 - 1.0,
            places=4,
        )
        self.assertEqual(first["primary_model"], "fcff_multistage")

    def test_financial_company_rejects_corporate_fcff_route(self):
        route = normalize_valuation_route(
            {
                "asset_type": "equity",
                "archetype": "financial_service",
                "primary_model": "fcff_multistage",
                "assumptions": {},
            }
        )

        self.assertEqual(route["primary_model"], "residual_income")
        self.assertIn("route_corrected", route["validation_warnings"])

    def test_etf_uses_etf_valuation_instead_of_company_dcf(self):
        result = value_security(
            {
                "symbol": "INDEX",
                "earnings_yield": 0.045,
                "historical_earnings_yield": 0.04,
                "drawdown_52w": -0.12,
            },
            normalize_valuation_route(
                {"asset_type": "etf", "archetype": "broad_market_etf", "primary_model": "etf_risk_premium"}
            ),
            current_price=100.0,
            simulations=200,
            seed=3,
        )

        self.assertEqual(result["primary_model"], "etf_risk_premium")
        self.assertGreater(result["fair_value"]["p50"], 0)

    def test_etf_without_current_yield_does_not_invent_undervaluation(self):
        result = value_security(
            {"symbol": "INDEX", "historical_earnings_yield": 0.04},
            normalize_valuation_route(
                {"asset_type": "etf", "archetype": "broad_market_etf", "primary_model": "etf_risk_premium"}
            ),
            current_price=100.0,
            simulations=400,
            seed=9,
        )

        self.assertLess(abs(result["margin_of_safety"]), 0.03)
        self.assertLess(result["confidence"], 0.5)
        self.assertIn("missing_valuation_inputs", result["validation_warnings"])

    def test_llm_assumptions_are_bounded_and_ordered_before_valuation(self):
        route = normalize_valuation_route(
            {
                "asset_type": "equity",
                "archetype": "high_growth_profitable",
                "primary_model": "revenue_growth_dcf",
                "assumptions": {
                    "growth_rate": {"bear": 2.0, "base": -4.0, "bull": 0.2},
                    "discount_rate": {"bear": 0.01, "base": 0.5, "bull": 0.02},
                    "terminal_growth": {"bear": 0.2, "base": 0.1, "bull": 0.3},
                    "target_margin": {"bear": 0.9, "base": -0.5, "bull": 0.25},
                    "normalized_multiple": {"bear": 200, "base": -2, "bull": 20},
                },
            }
        )

        assumptions = route["assumptions"]
        self.assertLessEqual(assumptions["growth_rate"]["bear"], assumptions["growth_rate"]["base"])
        self.assertLessEqual(assumptions["growth_rate"]["base"], assumptions["growth_rate"]["bull"])
        self.assertGreaterEqual(assumptions["discount_rate"]["bear"], assumptions["discount_rate"]["base"])
        self.assertGreaterEqual(assumptions["discount_rate"]["base"], assumptions["discount_rate"]["bull"])
        self.assertLessEqual(assumptions["terminal_growth"]["bull"], assumptions["discount_rate"]["bull"] - 0.01)
        self.assertIn("assumptions_sanitized", route["validation_warnings"])

    def test_compatible_llm_model_choice_is_preserved(self):
        route = normalize_valuation_route(
            {
                "asset_type": "equity",
                "archetype": "mature_growth",
                "primary_model": "revenue_growth_dcf",
            }
        )

        self.assertEqual(route["primary_model"], "revenue_growth_dcf")
        self.assertNotIn("route_corrected", route["validation_warnings"])

    def test_missing_model_specific_inputs_reduce_confidence(self):
        route = normalize_valuation_route(
            {"asset_type": "equity", "archetype": "mature_growth", "confidence": 0.9, "evidence": ["filing"]}
        )

        result = value_security(
            {"symbol": "ACME", "shares_outstanding": 100, "cash": 20, "total_debt": 5},
            route,
            current_price=10,
        )

        self.assertLess(result["confidence"], 0.5)
        self.assertIn("missing_valuation_inputs", result["validation_warnings"])

    def test_compatible_secondary_model_is_used_as_a_real_cross_check(self):
        route = normalize_valuation_route(
            {
                "asset_type": "equity",
                "archetype": "mature_growth",
                "primary_model": "fcff_multistage",
                "secondary_models": ["revenue_growth_dcf", "reverse_dcf"],
                "confidence": 0.8,
            }
        )
        result = value_security(
            {
                "symbol": "ACME",
                "free_cash_flow": 8_000_000_000,
                "revenue": 90_000_000_000,
                "cash": 12_000_000_000,
                "total_debt": 4_000_000_000,
                "shares_outstanding": 1_000_000_000,
            },
            route,
            current_price=100,
            simulations=300,
        )

        self.assertEqual(route["secondary_models"], ["revenue_growth_dcf"])
        self.assertEqual(set(result["model_values"]), {"fcff_multistage", "revenue_growth_dcf"})
        self.assertEqual(result["model_count"], 2)
        self.assertGreaterEqual(result["model_dispersion"], 0)


if __name__ == "__main__":
    unittest.main()
