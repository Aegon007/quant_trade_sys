"""Compatibility wrapper for legacy jobs.slack_bot imports and `python -m` usage."""

from integrations.slack.bot import (  # noqa: F401
    DEFAULT_COMMAND_NAME,
    build_slack_app,
    create_socket_mode_handler,
    run_slack_bot,
)
from integrations.slack.bot import main as _main


def main(argv=None):
    return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
