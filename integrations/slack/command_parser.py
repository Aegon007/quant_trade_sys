import re
from dataclasses import dataclass
from typing import Optional


SYMBOL_PATTERN = r"([A-Za-z][A-Za-z0-9.\-_^]*)"
NUMBER_PATTERN = r"([0-9]*\.?[0-9]+)"


@dataclass(frozen=True)
class ParsedSlackCommand:
    name: str
    raw_text: str
    normalized_text: str
    symbol: Optional[str] = None
    shares: Optional[float] = None


def _normalize_text(text) -> str:
    return " ".join(str(text or "").replace("\u3000", " ").strip().split())


def _command(name: str, raw_text: str, normalized_text: str, symbol=None, shares=None):
    normalized_symbol = None if symbol is None else str(symbol).strip().upper()
    normalized_shares = None if shares is None else float(shares)
    return ParsedSlackCommand(
        name=name,
        raw_text=str(raw_text or ""),
        normalized_text=normalized_text,
        symbol=normalized_symbol,
        shares=normalized_shares,
    )


def parse_slack_command(text) -> ParsedSlackCommand:
    raw_text = str(text or "")
    normalized = _normalize_text(raw_text)
    lowered = normalized.lower()

    if lowered in {"可用命令", "帮助", "help", "commands"}:
        return _command("HELP", raw_text, normalized)
    if lowered in {"当前持仓", "holdings"}:
        return _command("SHOW_HOLDINGS", raw_text, normalized)
    if lowered in {"当前关注", "watchlist", "watch list"}:
        return _command("SHOW_WATCHLIST", raw_text, normalized)
    if lowered in {"刷新", "刷新 全部", "refresh", "refresh all"}:
        return _command("REFRESH_ALL", raw_text, normalized)

    patterns = [
        ("SELL_ALL", rf"^(?:全部卖出|sell\s+all)\s*{SYMBOL_PATTERN}$"),
        ("REMOVE_WATCH", rf"^(?:取消关注|unwatch|remove\s+watch(?:list)?)\s+{SYMBOL_PATTERN}$"),
        ("ADD_WATCH", rf"^(?:关注|watch|add\s+watch(?:list)?)\s+{SYMBOL_PATTERN}$"),
        ("MOVE_TO_WATCH", rf"^(?:转到关注|move\s+to\s+watch(?:list)?)\s*{SYMBOL_PATTERN}$"),
        ("MOVE_TO_HOLDING", rf"^(?:转到持仓|move\s+to\s+holding)\s*{SYMBOL_PATTERN}(?:\s+{NUMBER_PATTERN})?\s*(?:股|share|shares)?$"),
        ("STATUS", rf"^(?:状态|status)\s+{SYMBOL_PATTERN}$"),
        ("BUY", rf"^(?:买入|buy)\s*{SYMBOL_PATTERN}\s+{NUMBER_PATTERN}\s*(?:股|share|shares)?$"),
        ("SELL", rf"^(?:卖出|sell)\s*{SYMBOL_PATTERN}\s+{NUMBER_PATTERN}\s*(?:股|share|shares)?$"),
    ]

    for name, pattern in patterns:
        match = re.match(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groups()
        symbol = groups[0] if groups else None
        shares = groups[1] if len(groups) > 1 and groups[1] is not None else None
        return _command(name, raw_text, normalized, symbol=symbol, shares=shares)

    return _command("UNKNOWN", raw_text, normalized)
