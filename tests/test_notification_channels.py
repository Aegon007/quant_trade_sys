import unittest

from tests.support import clear_modules, reload_module


class FakeHttpResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_args = None
        self.sent_message = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        self.sent_message = message


class NotificationChannelsTests(unittest.TestCase):
    def setUp(self):
        clear_modules("notification_channels")
        self.module = reload_module("notification_channels")
        FakeSMTP.instances = []

    def test_send_slack_message_posts_json_payload(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["body"] = request.data.decode("utf-8")
            captured["timeout"] = timeout
            return FakeHttpResponse()

        ok, message = self.module.send_slack_message(
            "hello",
            "https://hooks.slack.com/services/test",
            urlopen=fake_urlopen,
        )

        self.assertTrue(ok)
        self.assertIn("Slack", message)
        self.assertEqual(captured["method"], "POST")
        self.assertIn('"text": "hello"', captured["body"])

    def test_send_email_message_uses_starttls_and_login(self):
        ok, message = self.module.send_email_message(
            "Test Subject",
            "Body",
            {
                "smtp_host": "smtp-mail.outlook.com",
                "smtp_port": 587,
                "use_starttls": True,
                "username": "sender@outlook.com",
                "password": "secret",
                "from_email": "sender@outlook.com",
                "to_emails": ["target@gmail.com"],
            },
            smtp_factory=FakeSMTP,
        )

        smtp = FakeSMTP.instances[0]
        self.assertTrue(ok)
        self.assertIn("Email", message)
        self.assertEqual((smtp.host, smtp.port), ("smtp-mail.outlook.com", 587))
        self.assertTrue(smtp.started_tls)
        self.assertEqual(smtp.login_args, ("sender@outlook.com", "secret"))
        self.assertEqual(smtp.sent_message["To"], "target@gmail.com")

    def test_send_email_message_requires_recipient(self):
        ok, message = self.module.send_email_message(
            "Subject",
            "Body",
            {
                "smtp_host": "smtp-mail.outlook.com",
                "from_email": "sender@outlook.com",
                "to_emails": [],
            },
            smtp_factory=FakeSMTP,
        )

        self.assertFalse(ok)
        self.assertIn("收件人", message)
        self.assertEqual(FakeSMTP.instances, [])


if __name__ == "__main__":
    unittest.main()
