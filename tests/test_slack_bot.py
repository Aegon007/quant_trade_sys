import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests.support import clear_modules, reload_module


class FakeApp:
    def __init__(self, token=None):
        self.token = token
        self.command_handlers = {}

    def command(self, name):
        def decorator(func):
            self.command_handlers[name] = func
            return func

        return decorator


class FakeSocketModeHandler:
    instances = []

    def __init__(self, app, app_token):
        self.app = app
        self.app_token = app_token
        self.started = False
        FakeSocketModeHandler.instances.append(self)

    def start(self):
        self.started = True


def install_fake_slack_bolt():
    slack_bolt_module = types.ModuleType("slack_bolt")
    slack_bolt_module.__path__ = []
    slack_bolt_module.App = FakeApp

    adapter_module = types.ModuleType("slack_bolt.adapter")
    adapter_module.__path__ = []

    socket_mode_module = types.ModuleType("slack_bolt.adapter.socket_mode")
    socket_mode_module.SocketModeHandler = FakeSocketModeHandler

    sys.modules["slack_bolt"] = slack_bolt_module
    sys.modules["slack_bolt.adapter"] = adapter_module
    sys.modules["slack_bolt.adapter.socket_mode"] = socket_mode_module


class SlackBotTests(unittest.TestCase):
    def setUp(self):
        FakeSocketModeHandler.instances.clear()
        clear_modules("jobs.slack_bot", "slack_bolt", "slack_bolt.adapter", "slack_bolt.adapter.socket_mode")
        install_fake_slack_bolt()

    def test_build_slack_app_registers_quant_command(self):
        bot = reload_module("jobs.slack_bot")

        def execute_command(text):
            return SimpleNamespace(message=f"handled:{text}")

        app = bot.build_slack_app(bot_token="xoxb-token", execute_command=execute_command)
        handler = app.command_handlers["/quant"]
        ack_calls = []
        respond_calls = []

        result = handler(
            ack=lambda *args, **kwargs: ack_calls.append((args, kwargs)),
            respond=lambda **kwargs: respond_calls.append(kwargs),
            command={"text": "当前持仓"},
            logger=SimpleNamespace(info=lambda *args, **kwargs: None),
        )

        self.assertEqual(app.token, "xoxb-token")
        self.assertEqual(len(ack_calls), 1)
        self.assertEqual(respond_calls[0]["text"], "handled:当前持仓")
        self.assertEqual(respond_calls[0]["response_type"], "ephemeral")
        self.assertEqual(result.message, "handled:当前持仓")

    def test_run_slack_bot_uses_env_tokens_and_starts_handler(self):
        bot = reload_module("jobs.slack_bot")

        with patch.dict(
            "os.environ",
            {"SLACK_BOT_TOKEN": "xoxb-env", "SLACK_APP_TOKEN": "xapp-env"},
            clear=False,
        ):
            handler = bot.run_slack_bot(
                execute_command=lambda text: SimpleNamespace(message="ok"),
                command_name="/quant",
            )

        self.assertTrue(handler.started)
        self.assertEqual(handler.app.token, "xoxb-env")
        self.assertEqual(handler.app_token, "xapp-env")


if __name__ == "__main__":
    unittest.main()
