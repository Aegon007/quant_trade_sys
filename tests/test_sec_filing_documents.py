import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from quant_core.fundamentals.provider import load_financial_profile
from quant_core.fundamentals.sec_edgar import (
    build_filing_document_url,
    extract_filing_sections,
    select_relevant_filings,
)


class SecFilingDocumentTests(unittest.TestCase):
    def test_relevant_filings_are_point_in_time_and_include_latest_earnings_update(self):
        submissions = {
            "cik": "789019",
            "filings": {
                "recent": {
                    "form": ["10-K", "10-Q", "8-K", "10-Q"],
                    "filingDate": ["2026-02-01", "2026-05-01", "2026-05-15", "2026-08-01"],
                    "reportDate": ["2025-12-31", "2026-03-31", "2026-03-31", "2026-06-30"],
                    "accessionNumber": [
                        "0000789019-26-000001",
                        "0000789019-26-000002",
                        "0000789019-26-000003",
                        "0000789019-26-000004",
                    ],
                    "primaryDocument": ["annual.htm", "quarter.htm", "earnings.htm", "future.htm"],
                    "items": ["", "", "2.02,9.01", ""],
                }
            },
        }

        rows = select_relevant_filings(submissions, as_of=datetime(2026, 6, 1))

        self.assertEqual([row["form"] for row in rows], ["10-Q", "8-K"])
        self.assertNotIn("future.htm", {row["primary_document"] for row in rows})

    def test_document_url_uses_unpadded_cik_and_accession_without_hyphens(self):
        url = build_filing_document_url(
            cik="0000789019",
            accession_number="0000789019-26-000002",
            primary_document="msft-20260331.htm",
        )

        self.assertEqual(
            url,
            "https://www.sec.gov/Archives/edgar/data/789019/000078901926000002/msft-20260331.htm",
        )

    def test_html_parser_extracts_decision_relevant_sections(self):
        html = """<?xml version="1.0" encoding="utf-8"?>
        <html><body>
          <h2>Item 1A. Risk Factors</h2>
          <p>Customer concentration and supply constraints could materially affect results.</p>
          <p>Item 1A</p>
          <p>Material weaknesses would require separate review.</p>
          <h2>Item 7. Management's Discussion and Analysis</h2>
          <p>Cloud revenue increased while capital expenditures expanded for data centers.</p>
          <h2>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</h2>
          <p>Foreign exchange exposure increased.</p>
          <h2>Item 8. Financial Statements</h2>
          <p>Audited statements follow.</p>
        </body></html>
        """

        sections = extract_filing_sections(html, form="10-K")

        titles = " ".join(row["title"] for row in sections)
        content = " ".join(row["text"] for row in sections)
        self.assertIn("Risk Factors", titles)
        self.assertIn("Management's Discussion", titles)
        self.assertIn("capital expenditures", content)
        self.assertIn("Material weaknesses", content)
        self.assertNotIn("Audited statements follow", content)

    @patch("quant_core.fundamentals.provider.fetch_filing_context")
    @patch("quant_core.fundamentals.provider.normalize_sec_company_facts")
    @patch("quant_core.fundamentals.provider.fetch_company_facts")
    def test_financial_profile_includes_cached_filing_context(self, facts, normalize, filing_context):
        facts.return_value = {"cik": "789019"}
        normalize.return_value = {
            "symbol": "MSFT",
            "asset_type": "equity",
            "status": "READY",
            "source": "sec_companyfacts",
            "evidence": [],
        }
        filing_context.return_value = {
            "status": "READY",
            "source": "sec_edgar_filing",
            "filings": [{"form": "10-Q", "filing_date": "2026-05-01", "sections": []}],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            profile = load_financial_profile(
                "MSFT",
                now=datetime(2026, 6, 1),
                filing_cache_dir=Path(temp_dir),
            )

        self.assertEqual(profile["filing_context"]["source"], "sec_edgar_filing")
        self.assertEqual(profile["latest_filing_form"], "10-Q")
        filing_context.assert_called_once()


if __name__ == "__main__":
    unittest.main()
