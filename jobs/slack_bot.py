"""Slack bot entrypoint for /quant slash commands."""

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
        raise RuntimeError(
            "Slack bot dependencies are missing. Install requirements.txt before starting the bot."
        ) from exc
    return App, SocketModeHandler


def _require_env(name: str, value: Optional[str] = None) -> str:
    resolved = value if value is not None else os.getenv(name)
    if not resolved:
        raise RuntimeError(f"Missing required Slack environment variable: {name}")
    return resolved


def _register_slash_command(app, *, command_name: str, execute_command: Callable[[str], object]):
    @app.command(command_name)
    def _handle_quant_command(ack, respond, command, logger):
        ack()
        text = str(command.get("text", "")).strip()
        logger.info("Received Slack command %s text=%s", command_name, text)
        result = execute_command(text)
        respond(text=getattr(result, "message", ""), response_type="ephemeral")
        return result

    return app


def build_slack_app(
    *,
    bot_token: Optional[str] = None,
    command_name: str = DEFAULT_COMMAND_NAME,
    execute_command: Optional[Callable[[str], object]] = None,
):
    if execute_command is None:
        from slack_command_service import execute_slack_command

        execute_command = execute_slack_command

    App, _ = _load_slack_runtime()
    app = App(token=_require_env("SLACK_BOT_TOKEN", bot_token))
    return _register_slash_command(app, command_name=command_name, execute_command=execute_command)


def create_socket_mode_handler(app, *, app_token: Optional[str] = None):
    _, SocketModeHandler = _load_slack_runtime()
    return SocketModeHandler(app, _require_env("SLACK_APP_TOKEN", app_token))


def run_slack_bot(
    *,
    bot_token: Optional[str] = None,
    app_token: Optional[str] = None,
    command_name: str = DEFAULT_COMMAND_NAME,
    execute_command: Optional[Callable[[str], object]] = None,
):
    app = build_slack_app(
        bot_token=bot_token,
        command_name=command_name,
        execute_command=execute_command,
    )
    handler = create_socket_mode_handler(app, app_token=app_token)
    logging.getLogger(__name__).info("Starting Slack bot for command %s", command_name)
    handler.start()
    return handler


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the Slack /quant bot in Socket Mode.")
    parser.add_argument(
        "--command-name",
        default=os.getenv("SLACK_COMMAND_NAME", DEFAULT_COMMAND_NAME),
        help="Slack slash command name to register, defaults to /quant.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    run_slack_bot(command_name=args.command_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
