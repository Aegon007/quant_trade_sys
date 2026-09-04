import unittest
from datetime import datetime

from quant_core.fundamentals.metrics import normalize_sec_company_facts
from quant_core.fundamentals.sec_edgar import _headers


def fact(values):
    return {"units": {"USD": values}}


class SecFinancialMetricsTests(unittest.TestCase):
    def test_normalization_respects_filing_date_and_computes_cash_flow(self):
        payload = {
            "entityName": "Acme Corp",
            "facts": {
                "dei": {
                    "EntityCommonStockSharesOutstanding": {
                        "units": {"shares": [{"end": "2025-12-31", "filed": "2026-02-01", "val": 100}]}
                    }
                },
                "us-gaap": {
                    "Revenues": fact([
                        {"start": "2024-01-01", "end": "2024-12-31", "filed": "2025-02-01", "form": "10-K", "val": 900},
                        {"start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-01", "form": "10-K", "val": 1000},
                        {"start": "2026-01-01", "end": "2026-12-31", "filed": "2027-02-01", "form": "10-K", "val": 5000},
                    ]),
                    "NetIncomeLoss": fact([
                        {"start": "2024-01-01", "end": "2024-12-31", "filed": "2025-02-01", "form": "10-K", "val": 90},
                        {"start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-01", "form": "10-K", "val": 120},
                    ]),
                    "NetCashProvidedByUsedInOperatingActivities": fact([
                        {"start": "2024-01-01", "end": "2024-12-31", "filed": "2025-02-01", "form": "10-K", "val": 130},
                        {"start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-01", "form": "10-K", "val": 160},
                    ]),
                    "PaymentsToAcquirePropertyPlantAndEquipment": fact([
                        {"start": "2024-01-01", "end": "2024-12-31", "filed": "2025-02-01", "form": "10-K", "val": 30},
                        {"start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-01", "form": "10-K", "val": 40},
                    ]),
                    "CashAndCashEquivalentsAtCarryingValue": fact([
                        {"end": "2025-12-31", "filed": "2026-02-01", "form": "10-K", "val": 200}
                    ]),
                    "LongTermDebtAndFinanceLeaseObligationsCurrent": fact([
                        {"end": "2025-12-31", "filed": "2026-02-01", "form": "10-K", "val": 50}
                    ]),
                    "LongTermDebtAndFinanceLeaseObligationsNoncurrent": fact([
                        {"end": "2025-12-31", "filed": "2026-02-01", "form": "10-K", "val": 100}
                    ]),
                    "StockholdersEquity": fact([
                        {"end": "2025-12-31", "filed": "2026-02-01", "form": "10-K", "val": 500}
                    ]),
                },
            },
        }

        result = normalize_sec_company_facts(
            payload,
            symbol="ACME",
            as_of=datetime.fromisoformat("2026-06-01T00:00:00"),
        )

        self.assertEqual(result["revenue"], 1000)
        self.assertEqual(result["free_cash_flow"], 120)
        self.assertEqual(result["shares_outstanding"], 100)
        self.assertEqual(result["total_debt"], 150)
        self.assertAlmostEqual(result["revenue_growth"], 100 / 900)
        self.assertEqual(result["fiscal_period"], "2025-12-31")
        self.assertLess(result["damage_score"], 40)
        self.assertGreater(result["quality_score"], 50)

    def test_latest_four_standalone_quarters_override_older_annual_value(self):
        quarters = [
            {"start": "2025-01-01", "end": "2025-03-31", "filed": "2025-05-01", "form": "10-Q", "val": 300},
            {"start": "2025-04-01", "end": "2025-06-30", "filed": "2025-08-01", "form": "10-Q", "val": 310},
            {"start": "2025-07-01", "end": "2025-09-30", "filed": "2025-11-01", "form": "10-Q", "val": 320},
            {"start": "2025-10-01", "end": "2025-12-31", "filed": "2026-02-01", "form": "10-Q", "val": 330},
        ]
        payload = {
            "facts": {
                "us-gaap": {
                    "Revenues": fact([
                        {"start": "2024-01-01", "end": "2024-12-31", "filed": "2025-02-01", "form": "10-K", "val": 1000},
                        *quarters,
                    ])
                }
            }
        }

        result = normalize_sec_company_facts(payload, symbol="ACME", as_of=datetime(2026, 3, 1))

        self.assertEqual(result["revenue"], 1260)
        self.assertEqual(result["fiscal_period"], "2025-12-31")

    def test_rows_without_filing_date_are_not_treated_as_point_in_time_evidence(self):
        payload = {
            "facts": {
                "us-gaap": {
                    "Revenues": fact([
                        {"start": "2024-01-01", "end": "2024-12-31", "filed": "2025-02-01", "form": "10-K", "val": 900},
                        {"start": "2025-01-01", "end": "2025-12-31", "form": "10-K", "val": 9999},
                    ])
                }
            }
        }

        result = normalize_sec_company_facts(payload, symbol="ACME", as_of=datetime(2026, 3, 1))

        self.assertEqual(result["revenue"], 900)

    def test_sec_request_does_not_ask_for_compression_it_cannot_decode(self):
        self.assertNotIn("Accept-Encoding", _headers("research contact@example.com"))


if __name__ == "__main__":
    unittest.main()
