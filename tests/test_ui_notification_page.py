import sys
import types
import unittest
from types import SimpleNamespace


class _FakeContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeColumn:
    def __init__(self, state):
        self._state = state

    def form_submit_button(self, label):
        return False

    def text_input(self, label, value="", **kwargs):
        return value

    def number_input(self, label, value=0, **kwargs):
        return value

    def checkbox(self, label, value=False, **kwargs):
        return value


class _FakeStreamlit:
    def __init__(self):
        self.state = {
            "headers": [],
            "subheaders": [],
            "captions": [],
            "writes": [],
        }

    def header(self, text):
        self.state["headers"].append(text)

    def subheader(self, text):
        self.state["subheaders"].append(text)

    def caption(self, text):
        self.state["captions"].append(text)

    def write(self, text):
        self.state["writes"].append(text)

    def success(self, text):
        pass

    def error(self, text):
        pass

    def rerun(self):
        pass

    def expander(self, label, expanded=False):
        return _FakeContext()

    def form(self, key):
        return _FakeContext()

    def columns(self, specs):
        count = specs if isinstance(specs, int) else len(specs)
        return [_FakeColumn(self.state) for _ in range(count)]

    def checkbox(self, label, value=False, **kwargs):
        return value

    def text_input(self, label, value="", **kwargs):
        return value

    def number_input(self, label, value=0, **kwargs):
        return value

    def button(self, label, **kwargs):
        return False


class UINotificationPageTests(unittest.TestCase):
    def setUp(self):
        sys.modules["streamlit"] = types.ModuleType("streamlit")
        if "app.ui.notification_page" in sys.modules:
            del sys.modules["app.ui.notification_page"]
        from app.ui import notification_page

        self.notification_page = notification_page
        self.fake_st = _FakeStreamlit()

    def test_render_notification_config_page_renders_status_lines(self):
        ncfg_module = SimpleNamespace(
            NOTIFICATION_CONFIG_FILE="storage/state/notification_config.json",
            load_notification_config=lambda: {
                "slack": {"enabled": True, "webhook_url": "https://hooks.slack.com/services/mock"},
                "email": {
                    "enabled": False,
                    "smtp_host": "smtp-mail.outlook.com",
                    "smtp_port": 587,
                    "use_starttls": True,
                    "username": "mock@outlook.com",
                    "password": "",
                    "from_email": "mock@outlook.com",
                    "to_emails": ["user@gmail.com"],
                },
            },
            save_notification_config=lambda cfg: cfg,
            apply_outlook_smtp_preset=lambda cfg: cfg,
        )
        nch_module = SimpleNamespace(
            send_slack_message=lambda message, webhook_url: (True, "ok"),
            send_email_message=lambda subject, body, email_cfg: (True, "ok"),
            build_test_notification_message=lambda channel: f"test:{channel}",
        )

        self.notification_page.render_notification_config_page(
            ncfg_module=ncfg_module,
            nch_module=nch_module,
            st_module=self.fake_st,
        )

        self.assertIn("通知配置", self.fake_st.state["headers"])
        self.assertIn("当前状态", self.fake_st.state["subheaders"])
        self.assertTrue(any(line.startswith("Slack:") for line in self.fake_st.state["writes"]))
        self.assertTrue(any(line.startswith("Email:") for line in self.fake_st.state["writes"]))


if __name__ == "__main__":
    unittest.main()
