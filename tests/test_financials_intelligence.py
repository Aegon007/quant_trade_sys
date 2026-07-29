import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd


class FinancialsIntelligenceTests(unittest.TestCase):
    def test_financial_stress_scores_capex_and_cash_flow_pressure(self):
        from quant_core.fundamentals.financials import score_financial_stress

        scored = score_financial_stress(
            {
                "symbol": "MSFT",
                "status": "READY",
                "metrics": {
                    "free_cash_flow_margin": -0.02,
                    "capex_to_operating_cash_flow": 0.82,
                    "debt_to_operating_cash_flow": 4.2,
                    "debt_growth": 0.21,
                },
            }
        )

        self.assertEqual(scored["stress_state"], "STRESS")
        self.assertGreaterEqual(scored["stress_score"], 55)
        self.assertTrue(scored["drivers"])

    def test_financial_intelligence_missing_etf_data_is_not_bearish(self):
        from quant_core.fundamentals import financials

        with patch("quant_core.fundamentals.financials._fetch_yfinance_record") as fetch:
            fetch.return_value = {
                "symbol": "VOO",
                "status": "NO_STATEMENT_DATA",
                "source": "yfinance",
                "retrieved_at": "2026-07-28T00:00:00",
                "warnings": ["No financial statement data returned; this is common for ETFs."],
                "metrics": {},
            }
            snapshot = financials.build_financials_intelligence(
                symbols=["VOO"],
                config={"enabled": True, "llm_enabled": False, "source_order": ["yfinance"]},
                now=datetime(2026, 7, 28),
            )

        self.assertEqual(snapshot["status"], "NO_DATA")
        self.assertEqual(snapshot["summary"]["stress_count"], 0)
        self.assertEqual(snapshot["stress"][0]["stress_state"], "NO_DATA")

    def test_yfinance_record_extracts_statement_metrics(self):
        from quant_core.fundamentals import financials

        class FakeTicker:
            quarterly_cashflow = pd.DataFrame(
                {
                    pd.Timestamp("2026-06-30"): {
                        "Capital Expenditure": -100,
                        "Operating Cash Flow": 200,
                        "Free Cash Flow": 100,
                    },
                    pd.Timestamp("2026-03-31"): {
                        "Capital Expenditure": -80,
                        "Operating Cash Flow": 180,
                        "Free Cash Flow": 90,
                    },
                }
            )
            cashflow = pd.DataFrame()
            quarterly_balance_sheet = pd.DataFrame(
                {
                    pd.Timestamp("2026-06-30"): {"Total Debt": 500},
                    pd.Timestamp("2026-03-31"): {"Total Debt": 450},
                }
            )
            balance_sheet = pd.DataFrame()
            quarterly_financials = pd.DataFrame(
                {
                    pd.Timestamp("2026-06-30"): {"Total Revenue": 1000, "Net Income": 250},
                    pd.Timestamp("2026-03-31"): {"Total Revenue": 900, "Net Income": 210},
                }
            )
            financials = pd.DataFrame()

        class FakeYfinance:
            @staticmethod
            def Ticker(symbol):
                return FakeTicker()

        with patch("importlib.util.find_spec", return_value=True), patch.dict("sys.modules", {"yfinance": FakeYfinance}):
            record = financials._fetch_yfinance_record("MSFT", now=datetime(2026, 7, 28))

        self.assertEqual(record["status"], "READY")
        self.assertEqual(record["metrics"]["capital_expenditure"], 100)
        self.assertAlmostEqual(record["metrics"]["free_cash_flow_margin"], 0.1)
        self.assertAlmostEqual(record["metrics"]["capex_to_operating_cash_flow"], 0.5)


if __name__ == "__main__":
    unittest.main()
