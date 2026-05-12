import tempfile
import unittest
from pathlib import Path

from tests.support import clear_modules, reload_module


class RobinhoodImportTests(unittest.TestCase):
    def setUp(self):
        clear_modules(
            "quant_core.ledger.transactions",
            "quant_core.ledger.robinhood_csv",
        )
        self.transactions = reload_module("quant_core.ledger.transactions")
        self.importer = reload_module("quant_core.ledger.robinhood_csv")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.transactions.TRANS_FILE = str(root / "transactions.json")

    def test_parse_robinhood_activity_csv_extracts_trade_rows_and_skips_unsupported_rows(self):
        csv_bytes = (
            "Date,Symbol,Type,Quantity,Price,Total,Description\n"
            "2026-05-10 09:30,AAPL,Buy,1.500,100.00,150.00,Buy executed\n"
            "2026-05-10 15:45,AAPL,Sell,1.000,110.00,110.00,Sell executed\n"
            "2026-05-10 12:00,,Cash Transfer,0,,1000.00,Cash deposit\n"
        ).encode("utf-8")

        result = self.importer.parse_robinhood_activity_csv(csv_bytes, filename="activity.csv")

        self.assertEqual(result["parsed_count"], 3)
        self.assertEqual(result["skipped_count"], 0)
        self.assertEqual(result["records"][0]["event_type"], "BUY")
        self.assertEqual(result["records"][0]["side"], "BUY")
        self.assertEqual(result["records"][0]["symbol"], "AAPL")
        self.assertEqual(result["records"][0]["shares"], 1.5)
        self.assertEqual(result["records"][0]["price"], 100.0)
        self.assertEqual(result["records"][0]["source"], "ROBINHOOD_ACCOUNT_ACTIVITY_CSV")
        self.assertTrue(result["records"][0]["import_key"])
        self.assertEqual(result["records"][1]["event_type"], "SELL")
        self.assertEqual(result["records"][1]["proceeds"], 110.0)
        self.assertEqual(result["records"][2]["record_type"], "CASH_EVENT")
        self.assertEqual(result["records"][2]["event_type"], "CASH_DEPOSIT")
        self.assertEqual(result["records"][2]["proceeds"], 1000.0)

    def test_import_robinhood_activity_csv_deduplicates_repeated_imports(self):
        csv_bytes = (
            "Date,Symbol,Type,Quantity,Price,Total,Description\n"
            "2026-05-10 09:30,AAPL,Buy,1.500,100.00,150.00,Buy executed\n"
            "2026-05-10 15:45,AAPL,Sell,1.000,110.00,110.00,Sell executed\n"
        ).encode("utf-8")

        first = self.transactions.import_robinhood_activity_csv(csv_bytes, filename="activity.csv")
        second = self.transactions.import_robinhood_activity_csv(csv_bytes, filename="activity.csv")
        rows = self.transactions.load_transactions()

        self.assertEqual(first["imported_count"], 2)
        self.assertEqual(first["duplicate_count"], 0)
        self.assertEqual(second["imported_count"], 0)
        self.assertEqual(second["duplicate_count"], 2)
        self.assertEqual(len(rows), 2)

    def test_import_robinhood_activity_csv_handles_overlapping_csv_ranges(self):
        csv_a = (
            "Date,Symbol,Type,Quantity,Price,Total,Description\n"
            "2026-05-10 09:30,AAPL,Buy,1.500,100.00,150.00,Buy executed\n"
            "2026-05-10 15:45,AAPL,Sell,1.000,110.00,110.00,Sell executed\n"
        ).encode("utf-8")
        csv_b = (
            "Date,Symbol,Type,Quantity,Price,Total,Description\n"
            "2026-05-10 15:45,AAPL,Sell,1.000,110.00,110.00,Sell executed\n"
            "2026-05-11 09:35,MSFT,Buy,2.000,200.00,400.00,Buy executed\n"
        ).encode("utf-8")

        self.transactions.import_robinhood_activity_csv(csv_a, filename="activity_a.csv")
        second = self.transactions.import_robinhood_activity_csv(csv_b, filename="activity_b.csv")
        rows = self.transactions.load_transactions()

        self.assertEqual(second["imported_count"], 1)
        self.assertEqual(second["duplicate_count"], 1)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]["symbol"], "MSFT")


if __name__ == "__main__":
    unittest.main()
