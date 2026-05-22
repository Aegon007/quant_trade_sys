import sys
import types
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.support import clear_modules, reload_module


class FakeApp:
    def __init__(self, token=None):
        self.token = token
        self.command_handlers = {}
        self.event_handlers = {}

    def command(self, name):
        def decorator(func):
            self.command_handlers[name] = func
            return func

        return decorator

    def event(self, name):
        def decorator(func):
            self.event_handlers[name] = func
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

    def test_build_slack_app_registers_csv_upload_handler(self):
        bot = reload_module("jobs.slack_bot")
        said = []

        app = bot.build_slack_app(
            bot_token="xoxb-token",
            execute_command=lambda text: SimpleNamespace(message="ok"),
            sync_uploaded_csv=lambda content, filename="": f"synced:{filename}:{content.decode('utf-8')}",
            file_downloader=lambda url, token: b"csv-body",
        )
        handler = app.event_handlers["message"]

        handler(
            event={
                "ts": "123.456",
                "files": [
                    {
                        "name": "activity.csv",
                        "url_private_download": "https://files.example/activity.csv",
                        "filetype": "csv",
                    }
                ],
            },
            say=lambda **kwargs: said.append(kwargs),
            logger=SimpleNamespace(exception=lambda *args, **kwargs: None),
        )

        self.assertEqual(len(said), 1)
        self.assertEqual(said[0]["thread_ts"], "123.456")
        self.assertIn("synced:activity.csv:csv-body", said[0]["text"])

    def test_file_upload_handler_ignores_non_csv_files(self):
        bot = reload_module("jobs.slack_bot")
        said = []

        app = bot.build_slack_app(
            bot_token="xoxb-token",
            execute_command=lambda text: SimpleNamespace(message="ok"),
            sync_uploaded_csv=lambda content, filename="": "should-not-run",
            file_downloader=lambda url, token: b"ignored",
        )
        handler = app.event_handlers["message"]

        handler(
            event={
                "ts": "123.456",
                "files": [
                    {
                        "name": "notes.txt",
                        "url_private_download": "https://files.example/notes.txt",
                        "filetype": "txt",
                    }
                ],
            },
            say=lambda **kwargs: said.append(kwargs),
            logger=SimpleNamespace(exception=lambda *args, **kwargs: None),
        )

        self.assertEqual(said, [])

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


class SlackBotEntryPointTests(unittest.TestCase):
    def test_jobs_slack_bot_help_routes_to_real_entrypoint(self):
        project_root = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [sys.executable, "-m", "jobs.slack_bot", "--help"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Run the Slack /quant bot in Socket Mode.", proc.stdout)


class SlackCsvSyncTests(unittest.TestCase):
    def setUp(self):
        install_fake_slack_bolt()
        clear_modules(
            "yfinance",
            "integrations.slack.bot",
            "quant_core.data.storage",
            "quant_core.ledger.transactions",
            "quant_core.portfolio.actions",
        )
        from tests.support import install_fake_yfinance

        install_fake_yfinance()
        self.bot = reload_module("integrations.slack.bot")
        self.data_utils = reload_module("quant_core.data.storage")
        self.transactions = reload_module("quant_core.ledger.transactions")
        self.actions = reload_module("quant_core.portfolio.actions")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.data_utils.DATA_FILE = str(root / "portfolio_data.json")
        self.data_utils.CACHE_FILE = str(root / "price_cache.json")
        self.data_utils.EDITABLE_DATA_FILE = str(root / "portfolio_input.json")
        self.transactions.TRANS_FILE = str(root / "transactions.json")
        self.actions.du.DATA_FILE = self.data_utils.DATA_FILE
        self.actions.du.CACHE_FILE = self.data_utils.CACHE_FILE
        self.actions.du.EDITABLE_DATA_FILE = self.data_utils.EDITABLE_DATA_FILE
        self.actions.tx.TRANS_FILE = self.transactions.TRANS_FILE

    def test_sync_robinhood_csv_upload_imports_and_reconciles(self):
        self.data_utils.save_data(
            {
                "account": {
                    "cash_available": 0.0,
                    "min_cash_buffer_pct": 0.1,
                    "max_single_position_pct": 0.2,
                    "max_total_exposure_pct": 0.9,
                },
                "holdings": [],
                "watchlist": [],
            }
        )
        csv_bytes = (
            "Date,Symbol,Type,Quantity,Price,Total,Description\n"
            "2026-05-20 09:30,AAPL,Buy,1.500,100.00,150.00,Buy executed\n"
            "2026-05-20 12:00,,Cash Transfer,0,,1000.00,Cash deposit\n"
        ).encode("utf-8")

        message = self.bot.sync_robinhood_csv_upload(csv_bytes, filename="activity.csv")
        data = self.data_utils.load_data()

        self.assertIn("Robinhood CSV 已同步", message)
        self.assertIn("新增: 2", message)
        self.assertIn("当前持仓: 1", message)
        self.assertEqual(data["holdings"][0]["symbol"], "AAPL")
        self.assertAlmostEqual(data["account"]["cash_available"], 850.0)
