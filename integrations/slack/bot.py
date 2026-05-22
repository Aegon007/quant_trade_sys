"""Slack bot entrypoint for /quant slash commands."""

from __future__ import annotations

import argparse
import logging
import os
import urllib.request
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


def _is_csv_file(file_payload) -> bool:
    payload = dict(file_payload or {})
    filename = str(payload.get("name") or payload.get("title") or "").strip().lower()
    filetype = str(payload.get("filetype") or "").strip().lower()
    mimetype = str(payload.get("mimetype") or "").strip().lower()
    return (
        filename.endswith(".csv")
        or filetype == "csv"
        or mimetype in {"text/csv", "application/csv", "text/plain"}
    )


def download_private_file(url: str, bot_token: str) -> bytes:
    request = urllib.request.Request(
        str(url).strip(),
        headers={"Authorization": f"Bearer {str(bot_token).strip()}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def sync_robinhood_csv_upload(content, *, filename: str = "", force_price_refresh: bool = False) -> str:
    from quant_core.data import storage as du
    from quant_core.ledger import transactions as tx
    from quant_core.portfolio import actions as pactions

    imported = tx.import_robinhood_activity_csv(content, filename=filename)
    parsed_count = int(imported.get("parsed_count", 0) or 0)
    if parsed_count <= 0:
        raise ValueError("未识别到可导入的 Robinhood Account activity CSV。请确认上传的是 Account activity CSV。")

    reconciled = pactions.reconcile_portfolio_from_robinhood_imports(force_price_refresh=force_price_refresh)
    data = du.load_data()
    holdings = list(data.get("holdings", []) or [])
    watchlist = list(data.get("watchlist", []) or [])
    lines = [
        "Robinhood CSV 已同步",
        f"- 文件: {filename or 'upload.csv'}",
        f"- 解析记录: {parsed_count}",
        f"- 新增: {int(imported.get('imported_count', 0) or 0)} | 重复跳过: {int(imported.get('duplicate_count', 0) or 0)} | 不支持跳过: {int(imported.get('skipped_count', 0) or 0)}",
        f"- 当前持仓: {len(holdings)} | 当前关注: {len(watchlist)}",
        f"- 可用现金: ${float(reconciled.get('cash_available', 0.0) or 0.0):,.2f} ({reconciled.get('cash_mode') or 'unknown'})",
    ]
    issues = list(reconciled.get("issues", []) or [])
    if issues:
        lines.append(f"- 警告: {'；'.join(str(item).strip() for item in issues[:2] if str(item).strip())}")
    return "\n".join(lines)


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


def _register_file_upload_handler(
    app,
    *,
    bot_token: str,
    sync_uploaded_csv: Callable[..., str],
    file_downloader: Callable[[str, str], bytes],
):
    @app.event("message")
    def _handle_file_upload_event(event, say, logger):
        files = list((event or {}).get("files", []) or [])
        if not files:
            return None

        csv_files = [row for row in files if _is_csv_file(row)]
        if not csv_files:
            return None

        thread_ts = (event or {}).get("ts")
        for file_payload in csv_files:
            payload = dict(file_payload or {})
            filename = str(payload.get("name") or payload.get("title") or "upload.csv").strip() or "upload.csv"
            url = str(payload.get("url_private_download") or payload.get("url_private") or "").strip()
            if not url:
                say(text=f"{filename} 缺少可下载地址，无法同步。", thread_ts=thread_ts)
                continue
            try:
                content = file_downloader(url, bot_token)
                message = sync_uploaded_csv(content, filename=filename)
            except Exception as exc:
                logger.exception("Failed to sync uploaded Robinhood CSV %s", filename)
                message = f"{filename} 同步失败: {exc}"
            say(text=message, thread_ts=thread_ts)
        return None

    return app


def build_slack_app(
    *,
    bot_token: Optional[str] = None,
    command_name: str = DEFAULT_COMMAND_NAME,
    execute_command: Optional[Callable[[str], object]] = None,
    sync_uploaded_csv: Optional[Callable[..., str]] = None,
    file_downloader: Optional[Callable[[str, str], bytes]] = None,
):
    if execute_command is None:
        from integrations.slack.command_service import execute_slack_command

        execute_command = execute_slack_command
    if sync_uploaded_csv is None:
        sync_uploaded_csv = sync_robinhood_csv_upload
    if file_downloader is None:
        file_downloader = download_private_file

    App, _ = _load_slack_runtime()
    resolved_bot_token = _require_env("SLACK_BOT_TOKEN", bot_token)
    app = App(token=resolved_bot_token)
    _register_slash_command(app, command_name=command_name, execute_command=execute_command)
    return _register_file_upload_handler(
        app,
        bot_token=resolved_bot_token,
        sync_uploaded_csv=sync_uploaded_csv,
        file_downloader=file_downloader,
    )


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
