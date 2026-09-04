"""Slack Socket Mode bot for the research-only command surface."""

from __future__ import annotations

import argparse
import logging
import os
from typing import Callable, Optional


DEFAULT_COMMAND_NAME = "/quant"


def _load_slack_runtime():
    try:
        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler
    except ImportError as exc:
        raise RuntimeError("Slack依赖未安装，请在 ~/venv 中安装 requirements.txt") from exc
    return App, SocketModeHandler


def _required(name: str, supplied: Optional[str] = None) -> str:
    value = supplied or os.getenv(name)
    if not value:
        raise RuntimeError(f"缺少Slack环境变量：{name}")
    return value


def build_slack_app(*, bot_token=None, command_name=DEFAULT_COMMAND_NAME, execute_command: Optional[Callable] = None):
    if execute_command is None:
        from integrations.slack.command_service import execute_command
    App, _ = _load_slack_runtime()
    app = App(token=_required("SLACK_BOT_TOKEN", bot_token))

    @app.command(command_name)
    def handle_command(ack, respond, command, logger):
        ack()
        raw = str(command.get("text") or "").strip()
        logger.info("收到Slack命令：%s", raw or "帮助")
        try:
            result = execute_command(raw)
            respond(text=result.message, response_type="ephemeral")
        except Exception as exc:
            logger.exception("Slack命令执行失败")
            respond(text=f"命令执行失败：{exc}", response_type="ephemeral")

    return app


def create_socket_mode_handler(app, *, app_token=None):
    _, SocketModeHandler = _load_slack_runtime()
    return SocketModeHandler(app, _required("SLACK_APP_TOKEN", app_token))


def run_slack_bot(*, bot_token=None, app_token=None, command_name=DEFAULT_COMMAND_NAME, execute_command=None):
    app = build_slack_app(bot_token=bot_token, command_name=command_name, execute_command=execute_command)
    handler = create_socket_mode_handler(app, app_token=app_token)
    logging.getLogger(__name__).info("Slack研究助手已启动，命令为 %s", command_name)
    handler.start()
    return handler


def main(argv=None):
    parser = argparse.ArgumentParser(description="运行Slack研究助手")
    parser.add_argument("--command-name", default=os.getenv("SLACK_COMMAND_NAME", DEFAULT_COMMAND_NAME))
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    run_slack_bot(command_name=args.command_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
