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
        self.assertTrue(config["alert_settings"]["send_hourly_market_summary"])
        self.assertTrue(config["alert_settings"]["send_hourly_market_summary_market_hours_only"])
        self.assertTrue(config["alert_settings"]["send_premarket_brief"])
        self.assertTrue(config["alert_settings"]["send_intraday_alerts"])
        self.assertTrue(config["alert_settings"]["enable_weekend_research"])
        self.assertEqual(config["alert_settings"]["weekend_research_day_local"], "saturday")
        self.assertEqual(config["alert_settings"]["weekend_research_hour_local"], 10)
        self.assertEqual(config["alert_settings"]["weekend_research_history_period"], "5y")
        self.assertEqual(config["llm"]["provider"], "openai")
        self.assertEqual(config["llm"]["base_url"], "https://api.openai.com/v1")
        self.assertEqual(config["local_slm"]["model"], "Qwen/Qwen3-0.6B")

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
        public_config = self.module._read_json_file(self.config_path)
        secrets = self.module._read_json_file(
            str(Path(self.temp_dir.name) / "notification_secrets.local.json")
        )
        self.assertEqual(public_config["slack"]["webhook_url"], "")
        self.assertEqual(public_config["email"]["password"], "")
        self.assertEqual(secrets["slack"]["webhook_url"], "https://hooks.slack.com/services/test")
        self.assertEqual(secrets["email"]["password"], "secret")

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

    def test_apply_llm_preset_updates_endpoint_and_model(self):
        config = self.module.apply_llm_preset({}, "openrouter")

        self.assertEqual(config["llm"]["provider"], "openrouter")
        self.assertEqual(config["llm"]["base_url"], "https://openrouter.ai/api/v1")
        self.assertEqual(config["llm"]["model"], "openrouter/free")

    def test_apply_local_slm_preset_sets_qwen_defaults(self):
        config = self.module.apply_local_slm_preset({})

        self.assertTrue(config["local_slm"]["enabled"])
        self.assertEqual(config["local_slm"]["provider"], "openai")
        self.assertEqual(config["local_slm"]["base_url"], "http://127.0.0.1:8000/v1")
        self.assertEqual(config["local_slm"]["model"], "Qwen/Qwen3-0.6B")
        self.assertEqual(config["local_slm"]["api_key"], "EMPTY")

    def test_preserve_unsubmitted_secrets_keeps_existing_credentials(self):
        merged = self.module.preserve_unsubmitted_secrets(
            {
                "slack": {"enabled": True, "webhook_url": ""},
                "email": {"password": ""},
                "llm": {"api_key": "", "model": "new-model"},
                "local_slm": {"api_key": ""},
            },
            {
                "slack": {"webhook_url": "https://hooks.slack.com/secret"},
                "email": {"password": "smtp-secret"},
                "llm": {"api_key": "remote-secret"},
                "local_slm": {"api_key": "EMPTY"},
            },
        )

        self.assertEqual(merged["slack"]["webhook_url"], "https://hooks.slack.com/secret")
        self.assertEqual(merged["email"]["password"], "smtp-secret")
        self.assertEqual(merged["llm"]["api_key"], "remote-secret")
        self.assertEqual(merged["local_slm"]["api_key"], "EMPTY")
        self.assertEqual(merged["llm"]["model"], "new-model")

    def test_load_migrates_inline_secrets_to_local_file(self):
        Path(self.config_path).write_text(
            """{
  "llm": {
    "enabled": true,
    "api_key": "legacy-secret",
    "model": "test-model"
  }
}""",
            encoding="utf-8",
        )

        loaded = self.module.load_notification_config(self.config_path)

        public_config = self.module._read_json_file(self.config_path)
        secrets = self.module._read_json_file(
            str(Path(self.temp_dir.name) / "notification_secrets.local.json")
        )
        self.assertEqual(loaded["llm"]["api_key"], "legacy-secret")
        self.assertEqual(public_config["llm"]["api_key"], "")
        self.assertEqual(secrets["llm"]["api_key"], "legacy-secret")

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
                "LLM_API_BASE_URL": "https://api.openai.com/v1",
                "LLM_API_KEY": "llm-secret",
                "LLM_MODEL": "gpt-5-mini",
                "LLM_PROVIDER": "openai",
            },
        )

        self.assertTrue(config["slack"]["enabled"])
        self.assertEqual(config["slack"]["webhook_url"], "https://hooks.slack.com/services/env")
        self.assertTrue(config["email"]["enabled"])
        self.assertEqual(config["email"]["smtp_host"], "smtp.example.com")
        self.assertEqual(config["email"]["smtp_port"], 2525)
        self.assertFalse(config["email"]["use_starttls"])
        self.assertEqual(config["email"]["to_emails"], ["target@gmail.com"])
        self.assertTrue(config["llm"]["enabled"])
        self.assertEqual(config["llm"]["api_key"], "llm-secret")
        self.assertEqual(config["llm"]["model"], "gpt-5-mini")
        self.assertEqual(config["llm"]["provider"], "openai")
        self.assertFalse(config["local_slm"]["enabled"])

    def test_apply_environment_overrides_supports_local_slm(self):
        config = self.module.apply_environment_overrides(
            {},
            environ={
                "LOCAL_SLM_ENABLED": "true",
                "LOCAL_SLM_PROVIDER": "openai",
                "LOCAL_SLM_API_BASE_URL": "http://127.0.0.1:8000/v1",
                "LOCAL_SLM_API_KEY": "EMPTY",
                "LOCAL_SLM_MODEL": "Qwen/Qwen3-0.6B",
                "LOCAL_SLM_TEMPERATURE": "0.2",
                "LOCAL_SLM_MAX_TOKENS": "180",
                "LOCAL_SLM_TIMEOUT_SECONDS": "15",
            },
        )

        self.assertTrue(config["local_slm"]["enabled"])
        self.assertEqual(config["local_slm"]["base_url"], "http://127.0.0.1:8000/v1")
        self.assertEqual(config["local_slm"]["model"], "Qwen/Qwen3-0.6B")
        self.assertEqual(config["local_slm"]["max_tokens"], 180)

    def test_save_and_load_normalizes_research_schedule(self):
        self.module.save_notification_config(
            {
                "alert_settings": {
                    "send_premarket_brief": False,
                    "send_intraday_alerts": False,
                    "enable_weekend_research": True,
                    "weekend_research_day_local": "saturday",
                    "weekend_research_hour_local": "9",
                    "weekend_research_minute_local": "30",
                    "weekend_research_history_period": "10y",
                }
            },
            self.config_path,
        )

        config = self.module.load_notification_config(self.config_path)

        self.assertFalse(config["alert_settings"]["send_premarket_brief"])
        self.assertFalse(config["alert_settings"]["send_intraday_alerts"])
        self.assertTrue(config["alert_settings"]["enable_weekend_research"])
        self.assertEqual(config["alert_settings"]["weekend_research_day_local"], "saturday")
        self.assertEqual(config["alert_settings"]["weekend_research_hour_local"], 9)
        self.assertEqual(config["alert_settings"]["weekend_research_minute_local"], 30)
        self.assertEqual(config["alert_settings"]["weekend_research_history_period"], "10y")

    def test_save_and_load_normalizes_llm_settings(self):
        self.module.save_notification_config(
            {
                "llm": {
                    "enabled": True,
                    "provider": "openrouter",
                    "base_url": " https://openrouter.ai/api/v1 ",
                    "api_key": "secret",
                    "model": "openai/gpt-4.1-mini",
                    "temperature": "0.4",
                    "max_tokens": "512",
                    "timeout_seconds": "45",
                    "site_url": "https://example.com",
                    "app_name": "quant-test",
                }
            },
            self.config_path,
        )

        config = self.module.load_notification_config(self.config_path)

        self.assertTrue(config["llm"]["enabled"])
        self.assertEqual(config["llm"]["provider"], "openrouter")
        self.assertEqual(config["llm"]["base_url"], "https://openrouter.ai/api/v1")
        self.assertEqual(config["llm"]["model"], "openai/gpt-4.1-mini")
        self.assertEqual(config["llm"]["temperature"], 0.4)
        self.assertEqual(config["llm"]["max_tokens"], 512)
        self.assertEqual(config["llm"]["timeout_seconds"], 45)
        self.assertEqual(config["llm"]["site_url"], "https://example.com")
        self.assertEqual(config["llm"]["app_name"], "quant-test")


if __name__ == "__main__":
    unittest.main()
