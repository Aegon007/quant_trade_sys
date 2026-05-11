import json
import tempfile
import unittest
from pathlib import Path

from tests.support import clear_modules, install_fake_yfinance, reload_module


class SlackCommandServiceTests(unittest.TestCase):
    def setUp(self):
        install_fake_yfinance()
        clear_modules(
            "share_utils",
            "quant_core.data.storage",
            "quant_core.ledger.transactions",
            "quant_core.portfolio.actions",
            "integrations.slack.command_parser",
            "integrations.slack.command_service",
        )
        self.data_utils = reload_module("quant_core.data.storage")
        self.transactions = reload_module("quant_core.ledger.transactions")
        self.actions = reload_module("quant_core.portfolio.actions")
        self.service = reload_module("integrations.slack.command_service")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)

        self.data_utils.DATA_FILE = str(root / "portfolio_data.json")
        self.data_utils.CACHE_FILE = str(root / "price_cache.json")
        self.data_utils.EDITABLE_DATA_FILE = str(root / "portfolio_input.json")
        self.transactions.TRANS_FILE = str(root / "transactions.json")
        self.actions.du.DATA_FILE = self.data_utils.DATA_FILE
        self.actions.du.CACHE_FILE = self.data_utils.CACHE_FILE
        self.actions.du.EDITABLE_DATA_FILE = self.data_utils.EDITABLE_DATA_FILE
        self.actions.tx.TRANS_FILE = self.transactions.TRANS_FILE
        self.service.du.DATA_FILE = self.data_utils.DATA_FILE
        self.service.du.CACHE_FILE = self.data_utils.CACHE_FILE
        self.service.du.EDITABLE_DATA_FILE = self.data_utils.EDITABLE_DATA_FILE
        self.service.pactions.du.DATA_FILE = self.data_utils.DATA_FILE
        self.service.pactions.du.CACHE_FILE = self.data_utils.CACHE_FILE
        self.service.pactions.du.EDITABLE_DATA_FILE = self.data_utils.EDITABLE_DATA_FILE
        self.service.pactions.tx.TRANS_FILE = self.transactions.TRANS_FILE
        self.audit_path = root / "command_audit.jsonl"
        self.service.COMMAND_AUDIT_FILE = str(self.audit_path)

    def test_help_command_lists_supported_commands(self):
        result = self.service.execute_slack_command("可用命令")

        self.assertTrue(result.ok)
        self.assertIn("买入 <代码> <股数>", result.message)
        self.assertIn("全部卖出 <代码>", result.message)
        self.assertIn("关注 <代码>", result.message)
        self.assertIn("取消关注 <代码>", result.message)

    def test_current_holdings_command_formats_positions_and_cash(self):
        self.data_utils.save_data(
            {
                "account": {
                    "total_capital": 10000.0,
                    "cash_available": 2500.0,
                    "min_cash_buffer_pct": 0.10,
                    "max_single_position_pct": 0.20,
                    "max_total_exposure_pct": 0.90,
                },
                "holdings": [
                    {"symbol": "AAPL", "shares": 1.5, "cost": 100.0, "current_price": 120.0, "sector": "Tech"}
                ],
                "watchlist": [],
            }
        )

        result = self.service.execute_slack_command("当前持仓")

        self.assertTrue(result.ok)
        self.assertIn("当前持仓 (1)", result.message)
        self.assertIn("AAPL", result.message)
        self.assertIn("1.500 股", result.message)
        self.assertIn("可用现金", result.message)

    def test_buy_command_moves_watchlist_to_holdings_and_writes_audit_log(self):
        self.data_utils.save_data(
            {
                "account": {
                    "total_capital": 10000.0,
                    "cash_available": 3000.0,
                    "min_cash_buffer_pct": 0.10,
                    "max_single_position_pct": 0.20,
                    "max_total_exposure_pct": 1.0,
                },
                "holdings": [],
                "watchlist": [
                    {"symbol": "MSFT", "notes": "watch", "last_price": 310.0}
                ],
            }
        )

        result = self.service.execute_slack_command("买入 MSFT 1.5")
        data = self.data_utils.load_data()

        self.assertTrue(result.ok)
        self.assertIn("已买入 MSFT 1.500 股", result.message)
        self.assertEqual(data["watchlist"], [])
        self.assertEqual(data["holdings"][0]["symbol"], "MSFT")
        self.assertEqual(data["account"]["cash_available"], 2535.0)
        audit_rows = [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(audit_rows[-1]["command_name"], "BUY")
        self.assertTrue(audit_rows[-1]["ok"])

    def test_sell_all_command_moves_position_back_to_watchlist(self):
        self.data_utils.save_data(
            {
                "account": {
                    "total_capital": 10000.0,
                    "cash_available": 1000.0,
                    "min_cash_buffer_pct": 0.10,
                    "max_single_position_pct": 0.20,
                    "max_total_exposure_pct": 1.0,
                },
                "holdings": [
                    {"symbol": "AAPL", "shares": 2.0, "cost": 150.0, "current_price": 200.0, "sector": "Tech"}
                ],
                "watchlist": [],
            }
        )

        result = self.service.execute_slack_command("全部卖出 AAPL")
        data = self.data_utils.load_data()

        self.assertTrue(result.ok)
        self.assertIn("并转入关注列表", result.message)
        self.assertEqual(data["holdings"], [])
        self.assertEqual(data["watchlist"][0]["symbol"], "AAPL")

    def test_status_command_reports_watchlist_details(self):
        self.data_utils.save_data(
            {
                "account": {},
                "holdings": [],
                "watchlist": [
                    {"symbol": "NVDA", "notes": "pullback", "last_price": 820.0}
                ],
            }
        )

        result = self.service.execute_slack_command("状态 NVDA")

        self.assertTrue(result.ok)
        self.assertIn("NVDA 当前在关注列表中", result.message)
        self.assertIn("pullback", result.message)
        self.assertIn("$820.00", result.message)

    def test_add_watch_command_appends_symbol_to_watchlist(self):
        self.data_utils.save_data(
            {
                "account": {
                    "cash_available": 2000.0,
                },
                "holdings": [],
                "watchlist": [],
            }
        )

        result = self.service.execute_slack_command("关注 QQQ")
        data = self.data_utils.load_data()

        self.assertTrue(result.ok)
        self.assertIn("已关注 QQQ", result.message)
        self.assertEqual(len(data["watchlist"]), 1)
        self.assertEqual(data["watchlist"][0]["symbol"], "QQQ")
        audit_rows = [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(audit_rows[-1]["command_name"], "ADD_WATCH")

    def test_remove_watch_command_deletes_symbol_from_watchlist(self):
        self.data_utils.save_data(
            {
                "account": {
                    "cash_available": 2000.0,
                },
                "holdings": [],
                "watchlist": [
                    {"symbol": "TSLA", "notes": "watch", "last_price": 180.0}
                ],
            }
        )

        result = self.service.execute_slack_command("取消关注 TSLA")
        data = self.data_utils.load_data()

        self.assertTrue(result.ok)
        self.assertIn("已取消关注 TSLA", result.message)
        self.assertEqual(data["watchlist"], [])
        audit_rows = [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(audit_rows[-1]["command_name"], "REMOVE_WATCH")

    def test_invalid_fractional_share_returns_error(self):
        result = self.service.execute_slack_command("买入 AAPL 0.0005")

        self.assertFalse(result.ok)
        self.assertIn("至少为", result.message)


if __name__ == "__main__":
    unittest.main()
