import unittest
from unittest.mock import patch

from quant_core.api.actions import test_notification_channel


class NotificationActionTests(unittest.TestCase):
    @patch("quant_core.api.actions.notification_channels.send_slack_message", return_value=(True, "sent"))
    @patch("quant_core.api.actions.notification_config.load_notification_config")
    def test_slack_connection_can_be_tested_from_settings(self, load_config, send):
        load_config.return_value = {
            "slack": {"enabled": True, "webhook_url": "https://hooks.example/test"},
            "email": {},
        }

        result = test_notification_channel("slack")

        self.assertEqual(result["status"], "READY")
        send.assert_called_once()

    def test_unknown_notification_channel_is_rejected(self):
        with self.assertRaises(ValueError):
            test_notification_channel("carrier-pigeon")


if __name__ == "__main__":
    unittest.main()
