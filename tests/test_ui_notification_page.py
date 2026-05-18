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

    def button(self, label, **kwargs):
        self._state.setdefault("buttons", []).append(label)
        return False

    def metric(self, label, value):
        self._state.setdefault("metrics", []).append((label, value))

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
            "markdowns": [],
            "metrics": [],
            "buttons": [],
            "successes": [],
            "errors": [],
            "infos": [],
        }

    def header(self, text):
        self.state["headers"].append(text)

    def subheader(self, text):
        self.state["subheaders"].append(text)

    def caption(self, text):
        self.state["captions"].append(text)

    def write(self, text):
        self.state["writes"].append(text)

    def markdown(self, text, **kwargs):
        self.state["markdowns"].append(text)

    def divider(self):
        pass

    def success(self, text):
        self.state["successes"].append(text)

    def error(self, text):
        self.state["errors"].append(text)

    def info(self, text):
        self.state["infos"].append(text)

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
        self.state["buttons"].append(label)
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
                "llm": {
                    "enabled": True,
                    "provider": "openrouter",
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key": "secret",
                    "model": "openai/gpt-4.1-mini",
                    "temperature": 0.2,
                    "max_tokens": 300,
                    "timeout_seconds": 30,
                    "site_url": "",
                    "app_name": "quant-trade-system",
                },
                "local_slm": {
                    "enabled": True,
                    "provider": "openai",
                    "base_url": "http://127.0.0.1:8000/v1",
                    "api_key": "EMPTY",
                    "model": "Qwen/Qwen3-0.6B",
                    "temperature": 0.1,
                    "max_tokens": 220,
                    "timeout_seconds": 20,
                },
                "alert_settings": {
                    "enable_auto_quant_analysis": True,
                    "auto_quant_analysis_min_interval_seconds": 7200,
                    "auto_quant_analysis_price_jump_pct": 0.03,
                    "cooldown_hours": 6,
                    "send_daily_summary": True,
                    "send_premarket_brief": True,
                    "send_intraday_alerts": True,
                    "send_hourly_market_summary": True,
                    "send_hourly_market_summary_market_hours_only": True,
                    "send_quant_analysis_change_summary": True,
                },
            },
            save_notification_config=lambda cfg: cfg,
            apply_outlook_smtp_preset=lambda cfg: cfg,
            apply_llm_preset=lambda cfg, preset: cfg,
            apply_local_slm_preset=lambda cfg: cfg,
        )
        nch_module = SimpleNamespace(
            send_slack_message=lambda message, webhook_url: (True, "ok"),
            send_email_message=lambda subject, body, email_cfg: (True, "ok"),
            build_test_notification_message=lambda channel: f"test:{channel}",
        )
        llm_module = SimpleNamespace(
            test_llm_connection=lambda cfg: (True, "OK"),
            inspect_openai_compatible_endpoint=lambda cfg: {
                "status": "running",
                "label": "RUNNING",
                "ok": True,
                "message": "本地 SLM 服务在线，且模型匹配",
                "models": ["Qwen/Qwen3-0.6B"],
            },
        )

        self.notification_page.render_notification_config_page(
            ncfg_module=ncfg_module,
            nch_module=nch_module,
            llm_module=llm_module,
            st_module=self.fake_st,
        )

        self.assertIn("Settings", self.fake_st.state["headers"])
        self.assertIn("连接状态", self.fake_st.state["subheaders"])
        self.assertTrue(any(line.startswith("自动全量分析:") for line in self.fake_st.state["captions"]))
        self.assertTrue(any(line.startswith("通知节奏:") for line in self.fake_st.state["captions"]))
        self.assertTrue(any("LM Studio" in text for text in self.fake_st.state["captions"]))
        self.assertIn(("Slack", "ENABLED"), self.fake_st.state["metrics"])
        self.assertIn(("Email", "DISABLED"), self.fake_st.state["metrics"])
        self.assertIn(("Remote LLM", "ENABLED"), self.fake_st.state["metrics"])
        self.assertIn(("Local SLM Status", "RUNNING"), self.fake_st.state["metrics"])
        self.assertIn(("Local SLM", "RUNNING"), self.fake_st.state["metrics"])
        self.assertIn("Refresh Status", self.fake_st.state["buttons"])
        self.assertIn("Test Narration", self.fake_st.state["buttons"])


if __name__ == "__main__":
    unittest.main()
