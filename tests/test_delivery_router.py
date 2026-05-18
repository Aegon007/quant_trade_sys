import unittest

from tests.support import clear_modules, reload_module


class DeliveryRouterTests(unittest.TestCase):
    def setUp(self):
        clear_modules("quant_core.notifications.delivery_router")
        self.module = reload_module("quant_core.notifications.delivery_router")

    def test_deliver_message_sends_slack_and_email(self):
        sent = []
        results = self.module.deliver_message(
            "nightly_report",
            subject="Nightly",
            body="hello",
            config={
                "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/services/test"},
                "email": {
                    "enabled": True,
                    "smtp_host": "smtp.example.com",
                    "smtp_port": 587,
                    "use_starttls": True,
                    "username": "sender@example.com",
                    "password": "secret",
                    "from_email": "sender@example.com",
                    "to_emails": ["target@example.com"],
                },
            },
            slack_sender=lambda text, url: (sent.append(("slack", text, url)) or True, "slack ok"),
            email_sender=lambda subject, body, cfg: (sent.append(("email", subject, body, cfg["to_emails"])) or True, "email ok"),
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(sent[0][0], "slack")
        self.assertEqual(sent[1][0], "email")

    def test_deliver_message_reports_skipped_channels(self):
        results = self.module.deliver_message(
            "premarket_brief",
            subject="Brief",
            body="nothing",
            config={
                "slack": {"enabled": False, "webhook_url": ""},
                "email": {"enabled": False, "to_emails": []},
            },
        )

        self.assertEqual(len(results), 2)
        self.assertFalse(results[0]["ok"])
        self.assertFalse(results[1]["ok"])
        self.assertEqual({row["channel"] for row in results}, {"slack", "email"})


if __name__ == "__main__":
    unittest.main()
