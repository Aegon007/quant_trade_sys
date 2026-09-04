import re
from dataclasses import dataclass
from typing import Optional


SYMBOL_PATTERN = r"([A-Za-z][A-Za-z0-9.\-_^]*)"


@dataclass(frozen=True)
class ParsedSlackCommand:
    name: str
    raw_text: str
    normalized_text: str
    symbol: Optional[str] = None


def _command(name: str, raw: str, normalized: str, symbol=None) -> ParsedSlackCommand:
    return ParsedSlackCommand(
        name=name,
        raw_text=raw,
        normalized_text=normalized,
        symbol=str(symbol).strip().upper() if symbol else None,
    )


def parse_slack_command(text) -> ParsedSlackCommand:
    raw = str(text or "")
    normalized = " ".join(raw.replace("\u3000", " ").strip().split())
    lowered = normalized.lower()
    aliases = {
        "HELP": {"", "帮助", "可用命令", "help", "commands"},
        "SHOW_OVERVIEW": {"概览", "系统概览", "overview"},
        "SHOW_OPPORTUNITIES": {"机会", "超跌机会", "推荐", "opportunities"},
        "SHOW_RISK": {"风险", "市场风险", "risk"},
        "SHOW_WATCHLIST": {"关注列表", "当前关注", "watchlist"},
        "SHOW_DATA_HEALTH": {"数据状态", "数据健康", "data", "data health"},
        "SHOW_CALIBRATION": {"策略校准", "历史表现", "calibration"},
        "RUN_RESEARCH": {"运行完整研究", "运行研究", "run research"},
        "REFRESH_MARKET": {"刷新行情", "refresh market"},
    }
    for name, values in aliases.items():
        if lowered in values:
            return _command(name, raw, normalized)
    patterns = (
        ("ANALYZE", rf"^(?:分析|估值|analyze|value)\s+{SYMBOL_PATTERN}$"),
        ("ADD_WATCH", rf"^(?:关注|watch)\s+{SYMBOL_PATTERN}$"),
        ("REMOVE_WATCH", rf"^(?:取消关注|unwatch)\s+{SYMBOL_PATTERN}$"),
    )
    for name, pattern in patterns:
        match = re.match(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return _command(name, raw, normalized, match.group(1))
    return _command("UNKNOWN", raw, normalized)
