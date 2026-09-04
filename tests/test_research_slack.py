import unittest
from unittest.mock import patch

from integrations.slack.command_parser import parse_slack_command
from integrations.slack.command_service import execute_command, supported_commands_text


class ResearchSlackTests(unittest.TestCase):
    def test_parser_only_exposes_research_commands(self):
        self.assertEqual(parse_slack_command("机会").name, "SHOW_OPPORTUNITIES")
        self.assertEqual(parse_slack_command("分析 msft").name, "ANALYZE")
        self.assertEqual(parse_slack_command("关注 nvda").name, "ADD_WATCH")
        self.assertEqual(parse_slack_command("运行完整研究").name, "RUN_RESEARCH")
        self.assertEqual(parse_slack_command("买入 MSFT 1").name, "UNKNOWN")
        self.assertNotIn("买入", supported_commands_text())
        self.assertNotIn("持仓", supported_commands_text())

    @patch("integrations.slack.command_service.snapshot_loader.load_opportunities_response")
    def test_opportunity_message_is_readable_chinese_prose(self, load_snapshot):
        load_snapshot.return_value = {
            "payload": {
                "opportunities": [
                    {
                        "symbol": "MSFT",
                        "recommendation": "DEEP_RESEARCH",
                        "opportunity_score": 82,
                        "current_price": 400,
                        "fair_value": {"p10": 410, "p50": 460, "p90": 515},
                        "margin_of_safety": 0.15,
                        "reason_codes": ["VALUATION_SUPPORT", "TRANSIENT_EVENT"],
                    }
                ]
            }
        }
        result = execute_command("机会")
        self.assertTrue(result.ok)
        self.assertIn("MSFT", result.message)
        self.assertIn("合理价值", result.message)
        self.assertNotIn("|", result.message)

    @patch("integrations.slack.command_service.snapshot_loader.load_snapshot_response")
    def test_data_health_command_reads_current_health_schema(self, load_snapshot):
        load_snapshot.return_value = {
            "freshness_status": "OK",
            "payload": {
                "status": "OK",
                "summary": {
                    "reason": "价格、财报、估值与风险快照正常",
                    "warnings": "2条标的级错误未达到全局降级阈值",
                    "price_cache": {"status": "OK", "symbol_count": 600},
                    "analyzed_count": 30,
                    "error_count": 2,
                },
            },
        }

        result = execute_command("数据状态")

        self.assertIn("最新价格缓存正常，覆盖 600 个标的", result.message)
        self.assertIn("完成深度估值 30 个", result.message)
        self.assertNotIn("暂无", result.message)


if __name__ == "__main__":
    unittest.main()
