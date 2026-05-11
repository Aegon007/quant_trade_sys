import unittest


class SlackCommandParserTests(unittest.TestCase):
    def test_parse_help_command_in_chinese(self):
        from integrations.slack.command_parser import parse_slack_command

        command = parse_slack_command("可用命令")

        self.assertEqual(command.name, "HELP")
        self.assertIsNone(command.symbol)
        self.assertIsNone(command.shares)

    def test_parse_buy_command_supports_fractional_shares(self):
        from integrations.slack.command_parser import parse_slack_command

        command = parse_slack_command("买入AAPL 0.5股")

        self.assertEqual(command.name, "BUY")
        self.assertEqual(command.symbol, "AAPL")
        self.assertEqual(command.shares, 0.5)

    def test_parse_sell_all_command(self):
        from integrations.slack.command_parser import parse_slack_command

        command = parse_slack_command("全部卖出 tsla")

        self.assertEqual(command.name, "SELL_ALL")
        self.assertEqual(command.symbol, "TSLA")

    def test_parse_move_to_holding_defaults_to_no_share_override(self):
        from integrations.slack.command_parser import parse_slack_command

        command = parse_slack_command("转到持仓 msft")

        self.assertEqual(command.name, "MOVE_TO_HOLDING")
        self.assertEqual(command.symbol, "MSFT")
        self.assertIsNone(command.shares)

    def test_parse_status_command_in_english(self):
        from integrations.slack.command_parser import parse_slack_command

        command = parse_slack_command("status nvda")

        self.assertEqual(command.name, "STATUS")
        self.assertEqual(command.symbol, "NVDA")

    def test_parse_unknown_command(self):
        from integrations.slack.command_parser import parse_slack_command

        command = parse_slack_command("tell me everything")

        self.assertEqual(command.name, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
