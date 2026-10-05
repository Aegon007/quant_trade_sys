import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from quant_core.notifications import notification_config


class NotificationConfigTests(unittest.TestCase):
    def test_all_secrets_are_split_from_public_file(self):
        with TemporaryDirectory() as temp:
            path = str(Path(temp) / "notification.json")
            notification_config.save_notification_config({
                "slack": {"enabled": True, "webhook_url": "hook", "bot_token": "bot", "app_token": "app"},
                "email": {"password": "mail"}, "llm": {"api_key": "remote"}, "local_slm": {"api_key": "local"},
            }, path)
            public = notification_config._read(path)
            secret = notification_config._read(str(Path(temp) / "notification_secrets.local.json"))
            loaded = notification_config.load_notification_config(path)
        self.assertEqual(public["slack"]["bot_token"], "")
        self.assertEqual(secret["slack"]["bot_token"], "bot")
        self.assertEqual(loaded["llm"]["api_key"], "remote")

    def test_environment_overrides_are_supported(self):
        config = notification_config.apply_environment_overrides({}, {"SLACK_BOT_TOKEN": "bot", "SLACK_APP_TOKEN": "app", "LLM_API_KEY": "key", "LLM_MODEL": "model"})
        self.assertEqual(config["slack"]["bot_token"], "bot")
        self.assertTrue(config["llm"]["enabled"])

    def test_empty_submitted_secret_preserves_existing(self):
        result = notification_config.preserve_unsubmitted_secrets({"llm": {"api_key": ""}}, {"llm": {"api_key": "secret"}})
        self.assertEqual(result["llm"]["api_key"], "secret")


if __name__ == "__main__":
    unittest.main()
