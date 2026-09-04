import unittest
from unittest.mock import patch

from quant_core.fundamentals.provider import _etf_profile, load_financial_profile


class FundamentalFallbackTests(unittest.TestCase):
    def test_etf_profile_does_not_invent_current_yield_when_market_metadata_is_missing(self):
        result = _etf_profile("VOO", metadata={}, market_info={})

        self.assertEqual(result["status"], "PARTIAL")
        self.assertIsNone(result["earnings_yield"])

    def test_etf_profile_uses_live_trailing_pe_and_configured_historical_anchor(self):
        result = _etf_profile(
            "VOO",
            metadata={"historical_earnings_yield": 0.042},
            market_info={"trailingPE": 25, "yield": 0.012},
        )

        self.assertAlmostEqual(result["earnings_yield"], 0.04)
        self.assertAlmostEqual(result["historical_earnings_yield"], 0.042)
        self.assertEqual(result["status"], "READY")
    @patch("quant_core.fundamentals.provider._load_yfinance_profile")
    @patch("quant_core.fundamentals.provider.fetch_company_facts")
    def test_non_sec_security_uses_marked_fallback(self, sec, fallback):
        sec.side_effect = LookupError("missing")
        fallback.return_value = {"symbol": "BYDDY", "status": "PARTIAL", "source": "yfinance_fallback"}
        result = load_financial_profile("BYDDY")
        self.assertEqual(result["source"], "yfinance_fallback")
        self.assertIn("sec_error", result)


if __name__ == "__main__":
    unittest.main()
