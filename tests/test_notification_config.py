import tempfile
import unittest
from pathlib import Path

from tests.support import clear_modules, reload_module


class NotificationConfigTests(unittest.TestCase):
    def setUp(self):
        clear_modules("quant_core.notifications.notification_config")
        self.module = reload_module("quant_core.notifications.notification_config")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.config_path = str(Path(self.temp_dir.name) / "notification_config.json")

    def test_load_missing_config_returns_outlook_defaults(self):
        config = self.module.load_notification_config(self.config_path)

        self.assertEqual(config["email"]["smtp_host"], "smtp-mail.outlook.com")
        self.assertEqual(config["email"]["smtp_port"], 587)
        self.assertTrue(config["email"]["use_starttls"])
        self.assertFalse(config["slack"]["enabled"])

    def test_save_and_load_normalizes_recipients(self):
        self.module.save_notification_config(
            {
                "email": {
                    "enabled": True,
                    "username": "sender@outlook.com",
                    "password": "secret",
                    "to_emails": "a@gmail.com, b@gmail.com; a@gmail.com",
                },
                "slack": {
                    "enabled": True,
                    "webhook_url": " https://hooks.slack.com/services/test ",
                },
            },
            self.config_path,
        )

        config = self.module.load_notification_config(self.config_path)

        self.assertTrue(config["email"]["enabled"])
        self.assertEqual(config["email"]["from_email"], "sender@outlook.com")
        self.assertEqual(config["email"]["to_emails"], ["a@gmail.com", "b@gmail.com"])
        self.assertEqual(config["slack"]["webhook_url"], "https://hooks.slack.com/services/test")

    def test_apply_outlook_smtp_preset_preserves_credentials(self):
        config = self.module.apply_outlook_smtp_preset({
            "email": {
                "smtp_host": "old",
                "smtp_port": 25,
                "use_starttls": False,
                "username": "sender@outlook.com",
                "password": "secret",
            }
        })

        self.assertEqual(config["email"]["smtp_host"], "smtp-mail.outlook.com")
        self.assertEqual(config["email"]["smtp_port"], 587)
        self.assertTrue(config["email"]["use_starttls"])
        self.assertEqual(config["email"]["username"], "sender@outlook.com")
        self.assertEqual(config["email"]["password"], "secret")

    def test_redact_secret_keeps_suffix_only(self):
        self.assertEqual(self.module.redact_secret("abcdef123456"), "********3456")

    def test_apply_environment_overrides_enables_env_based_channels(self):
        config = self.module.apply_environment_overrides(
            {},
            environ={
                "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/env",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": "2525",
                "SMTP_USER": "sender@example.com",
                "SMTP_PASSWORD": "secret",
                "ALERT_EMAIL_TO": "target@gmail.com",
                "SMTP_STARTTLS": "false",
            },
        )

        self.assertTrue(config["slack"]["enabled"])
        self.assertEqual(config["slack"]["webhook_url"], "https://hooks.slack.com/services/env")
        self.assertTrue(config["email"]["enabled"])
        self.assertEqual(config["email"]["smtp_host"], "smtp.example.com")
        self.assertEqual(config["email"]["smtp_port"], 2525)
        self.assertFalse(config["email"]["use_starttls"])
        self.assertEqual(config["email"]["to_emails"], ["target@gmail.com"])


if __name__ == "__main__":
    unittest.main()
