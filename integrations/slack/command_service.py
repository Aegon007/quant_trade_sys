import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from quant_core import paths as qpaths
from quant_core.portfolio import actions as pactions
from quant_core.data import storage as du
from quant_core.snapshots import system_snapshot as ss
from share_utils import format_share_quantity, validate_share_quantity
from integrations.slack.command_parser import ParsedSlackCommand, parse_slack_command

qpaths.bootstrap_storage_paths()

COMMAND_AUDIT_FILE = qpaths.COMMAND_AUDIT_FILE


@dataclass(frozen=True)
class CommandExecutionResult:
    ok: bool
    command_name: str
    message: str
    snapshot: Optional[dict] = None
    action_payload: Optional[dict] = None


def supported_commands_text() -> str:
    return "\n".join(
        [
            "可用命令:",
            "- 可用命令 / help",
            "- 当前持仓",
            "- 当前关注",
            "- 状态 <代码>",
            "- 买入 <代码> <股数>",
            "- 卖出 <代码> <股数>",
            "- 全部卖出 <代码>",
            "- 转到关注 <代码>",
            "- 转到持仓 <代码> [股数]",
            "- 刷新 全部",
        ]
    )


def _format_currency(value) -> str:
    if value is None:
        return "—"
    return f"${float(value):,.2f}"


def _find_record(records, symbol: str):
    normalized = str(symbol or "").strip().upper()
    for record in records or []:
        if str(record.get("symbol", "")).strip().upper() == normalized:
            return record
    return None


def _load_snapshot(data=None):
    current_data = data if data is not None else du.load_data()
    return ss.build_system_snapshot(data=current_data)


def _account_summary_line(snapshot: dict) -> str:
    account = snapshot.get("account", {})
    cash_available = account.get("cash_available")
    deployable_cash = account.get("deployable_cash")
    if cash_available is None:
        return ""
    return (
        f"可用现金: {_format_currency(cash_available)} | "
        f"可部署现金: {_format_currency(deployable_cash)}"
    )


def _format_holdings_message(data, snapshot) -> str:
    holdings = data.get("holdings", [])
    if not holdings:
        return "当前没有持仓。"
    lines = [f"当前持仓 ({len(holdings)})"]
    for holding in holdings:
        market_value = None
        if holding.get("current_price") is not None:
            market_value = float(holding["shares"]) * float(holding["current_price"])
        lines.append(
            "- "
            f"{holding['symbol']} | {format_share_quantity(holding['shares'])} 股 | "
            f"成本 {_format_currency(holding.get('cost'))} | "
            f"现价 {_format_currency(holding.get('current_price'))} | "
            f"市值 {_format_currency(market_value)}"
        )
    account_line = _account_summary_line(snapshot)
    if account_line:
        lines.append(account_line)
    return "\n".join(lines)


def _format_watchlist_message(data, snapshot) -> str:
    watchlist = data.get("watchlist", [])
    if not watchlist:
        return "当前没有关注标的。"
    lines = [f"当前关注 ({len(watchlist)})"]
    for watch in watchlist:
        notes = str(watch.get("notes") or "").strip() or "—"
        lines.append(
            "- "
            f"{watch['symbol']} | 最新 {_format_currency(watch.get('last_price'))} | "
            f"备注 {notes}"
        )
    account_line = _account_summary_line(snapshot)
    if account_line:
        lines.append(account_line)
    return "\n".join(lines)


def _format_status_message(data, symbol: str) -> str:
    symbol = str(symbol or "").strip().upper()
    holding = _find_record(data.get("holdings", []), symbol)
    if holding is not None:
        market_value = None
        if holding.get("current_price") is not None:
            market_value = float(holding["shares"]) * float(holding["current_price"])
        return "\n".join(
            [
                f"{symbol} 当前在持仓中",
                f"- 股数: {format_share_quantity(holding['shares'])}",
                f"- 成本价: {_format_currency(holding.get('cost'))}",
                f"- 现价: {_format_currency(holding.get('current_price'))}",
                f"- 市值: {_format_currency(market_value)}",
                f"- 行业: {holding.get('sector') or '—'}",
            ]
        )

    watch = _find_record(data.get("watchlist", []), symbol)
    if watch is not None:
        return "\n".join(
            [
                f"{symbol} 当前在关注列表中",
                f"- 最新价: {_format_currency(watch.get('last_price'))}",
                f"- 备注: {watch.get('notes') or '—'}",
            ]
        )

    return f"未找到 {symbol}，对应标的不在持仓或关注列表中。"


def _append_command_audit_log(command: ParsedSlackCommand, ok: bool, message: str, action_payload=None, path=None):
    path = path or COMMAND_AUDIT_FILE
    row = {
        "timestamp": datetime.now().isoformat(),
        "command_name": command.name,
        "raw_text": command.raw_text,
        "normalized_text": command.normalized_text,
        "symbol": command.symbol,
        "shares": command.shares,
        "ok": bool(ok),
        "message": str(message),
        "action_payload": action_payload or {},
    }
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _friendly_error_message(exc: Exception) -> str:
    message = str(exc)
    if "must be at least" in message:
        parts = message.split("must be at least", 1)
        field_name = parts[0].strip() or "shares"
        threshold = parts[1].strip()
        return f"{field_name} 至少为 {threshold} 股"
    return message


def _result(ok: bool, command: ParsedSlackCommand, message: str, action_payload=None, data=None) -> CommandExecutionResult:
    snapshot = None
    try:
        snapshot = _load_snapshot(data=data)
    except Exception:
        snapshot = None
    _append_command_audit_log(command, ok, message, action_payload=action_payload)
    return CommandExecutionResult(
        ok=bool(ok),
        command_name=command.name,
        message=message,
        snapshot=snapshot,
        action_payload=action_payload,
    )


def execute_slack_command(text) -> CommandExecutionResult:
    command = parse_slack_command(text)

    try:
        if command.name == "HELP":
            return _result(True, command, supported_commands_text())

        if command.name == "SHOW_HOLDINGS":
            data = du.load_data()
            snapshot = _load_snapshot(data=data)
            return _result(True, command, _format_holdings_message(data, snapshot), data=data)

        if command.name == "SHOW_WATCHLIST":
            data = du.load_data()
            snapshot = _load_snapshot(data=data)
            return _result(True, command, _format_watchlist_message(data, snapshot), data=data)

        if command.name == "STATUS":
            data = du.load_data()
            return _result(True, command, _format_status_message(data, command.symbol), data=data)

        if command.name == "REFRESH_ALL":
            data = pactions.refresh_all_market_data()
            updated_at = data.get("prices_last_updated") or "—"
            return _result(True, command, f"已刷新行情数据。更新时间: {updated_at}", data=data)

        if command.name in {"BUY", "SELL"}:
            validate_share_quantity(command.shares, field_name="shares")

        if command.name == "BUY":
            action = pactions.buy_symbol(command.symbol, command.shares)
            updated_data = du.load_data()
            account_line = _account_summary_line(_load_snapshot(data=updated_data))
            message = (
                f"已买入 {action['symbol']} {format_share_quantity(action['shares'])} 股 @ {_format_currency(action['price'])}。"
            )
            if account_line:
                message = f"{message}\n{account_line}"
            return _result(True, command, message, action_payload=action, data=updated_data)

        if command.name == "SELL":
            action = pactions.sell_symbol(command.symbol, command.shares)
            updated_data = du.load_data()
            account_line = _account_summary_line(_load_snapshot(data=updated_data))
            message = (
                f"已卖出 {action['symbol']} {format_share_quantity(action['shares'])} 股 @ {_format_currency(action['price'])}。"
            )
            if account_line:
                message = f"{message}\n{account_line}"
            return _result(True, command, message, action_payload=action, data=updated_data)

        if command.name == "SELL_ALL":
            action = pactions.sell_all_symbol(command.symbol)
            updated_data = du.load_data()
            account_line = _account_summary_line(_load_snapshot(data=updated_data))
            message = (
                f"已清仓 {action['symbol']} {format_share_quantity(action['shares'])} 股 @ {_format_currency(action['price'])}，并转入关注列表。"
            )
            if account_line:
                message = f"{message}\n{account_line}"
            return _result(True, command, message, action_payload=action, data=updated_data)

        if command.name == "MOVE_TO_WATCH":
            action = pactions.move_holding_to_watch(command.symbol)
            updated_data = du.load_data()
            account_line = _account_summary_line(_load_snapshot(data=updated_data))
            message = (
                f"已转到关注 {action['symbol']} {format_share_quantity(action['shares'])} 股 @ {_format_currency(action['price'])}。"
            )
            if account_line:
                message = f"{message}\n{account_line}"
            return _result(True, command, message, action_payload=action, data=updated_data)

        if command.name == "MOVE_TO_HOLDING":
            shares = 1.0 if command.shares is None else validate_share_quantity(command.shares, field_name="shares")
            action = pactions.move_watch_to_holding(command.symbol, shares)
            updated_data = du.load_data()
            account_line = _account_summary_line(_load_snapshot(data=updated_data))
            message = (
                f"已转到持仓 {action['symbol']} {format_share_quantity(action['shares'])} 股 @ {_format_currency(action['price'])}。"
            )
            if account_line:
                message = f"{message}\n{account_line}"
            return _result(True, command, message, action_payload=action, data=updated_data)

        if command.name == "UNKNOWN":
            return _result(False, command, "未识别命令。发送“可用命令”查看支持的操作。")

        return _result(False, command, f"暂未实现命令: {command.name}")
    except ValueError as exc:
        return _result(False, command, _friendly_error_message(exc))
    except Exception as exc:
        return _result(False, command, f"命令执行失败: {exc}")
