from dataclasses import dataclass, field, replace
from datetime import datetime
import json
import os
from typing import Iterable, List, Optional

from quant_core import paths as qpaths


qpaths.bootstrap_storage_paths()

MARKET_EVENTS_FILE = qpaths.MARKET_EVENTS_FILE
MARKET_EVENTS_EXAMPLE_FILE = qpaths.MARKET_EVENTS_EXAMPLE_FILE

_SEVERITY_POINTS = {"low": 0, "medium": 1, "high": 2}
_EVENT_TYPE_BONUS = {"fomc": 2, "macro": 1, "policy": 1, "geopolitical": 2}
_SOURCE_CONFIDENCE_HINTS = {
    "federal reserve": 0.35,
    "sec": 0.30,
    "company ir": 0.28,
    "reuters": 0.22,
    "bloomberg": 0.22,
    "wall street journal": 0.20,
    "financial times": 0.20,
    "yfinance": 0.10,
    "yahoo": 0.10,
    "social": -0.08,
    "rumor": -0.12,
}


@dataclass(frozen=True)
class MarketEvent:
    event_id: str
    title: str
    source_id: str = "manual"
    event_type: str = "macro"
    severity: str = "medium"
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    symbols: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    source: str = ""
    verified: bool = False
    sentiment: str = "neutral"
    sentiment_score: Optional[float] = None
    sentiment_model: str = ""
    confidence_score: Optional[float] = None
    confidence_level: str = "medium"
    notes: str = ""


@dataclass(frozen=True)
class EventRiskDecision:
    regime: str
    risk_score: int
    block_new_buys: bool
    max_position_weight: float
    reasons: List[str] = field(default_factory=list)
    active_event_count: int = 0


def _parse_datetime(value) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _normalize_symbols(raw_symbols) -> List[str]:
    if raw_symbols is None:
        return []
    symbols = []
    for raw_symbol in raw_symbols:
        symbol = str(raw_symbol or "").strip().upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def _normalize_tags(raw_tags) -> List[str]:
    if raw_tags is None:
        return []
    tags = []
    for raw_tag in raw_tags:
        tag = str(raw_tag or "").strip().lower()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _confidence_level(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def compute_event_confidence_score(event: MarketEvent) -> float:
    score = 0.35
    if event.verified:
        score += 0.20
    if event.starts_at is not None and event.ends_at is not None:
        score += 0.08
    source_text = f"{event.source} {event.source_id}".lower()
    for hint, delta in _SOURCE_CONFIDENCE_HINTS.items():
        if hint in source_text:
            score += delta
    if "unconfirmed" in event.title.lower():
        score -= 0.10
    return max(0.0, min(1.0, float(score)))


def with_event_confidence(event: MarketEvent) -> MarketEvent:
    score = compute_event_confidence_score(event) if event.confidence_score is None else float(event.confidence_score)
    return replace(
        event,
        confidence_score=score,
        confidence_level=_confidence_level(score),
    )


def attach_event_sentiment(event: MarketEvent, sentiment_result: Optional[dict]) -> MarketEvent:
    if not sentiment_result:
        return event
    label = str(sentiment_result.get("label") or event.sentiment or "neutral").lower()
    score = sentiment_result.get("score")
    score = float(score) if score is not None else None
    model = str(sentiment_result.get("model") or sentiment_result.get("method") or event.sentiment_model or "").strip()
    return replace(
        event,
        sentiment=label,
        sentiment_score=score,
        sentiment_model=model,
    )


def _normalize_event(record, index: int) -> MarketEvent:
    if not isinstance(record, dict):
        raise ValueError(f"events[{index}] must be an object")
    event_id = str(record.get("id") or f"event-{index}").strip()
    title = str(record.get("title") or event_id).strip()
    event_type = str(record.get("event_type") or "macro").strip().lower()
    severity = str(record.get("severity") or "medium").strip().lower()
    if severity not in _SEVERITY_POINTS:
        severity = "medium"
    sentiment = str(record.get("sentiment") or "neutral").strip().lower()
    verified = bool(record.get("verified", False))
    confidence_score = record.get("confidence_score")
    if confidence_score is not None:
        try:
            confidence_score = float(confidence_score)
        except (TypeError, ValueError):
            confidence_score = None
    sentiment_score = record.get("sentiment_score")
    if sentiment_score is not None:
        try:
            sentiment_score = float(sentiment_score)
        except (TypeError, ValueError):
            sentiment_score = None
    return MarketEvent(
        event_id=event_id,
        title=title,
        source_id=str(record.get("source_id") or "manual").strip() or "manual",
        event_type=event_type,
        severity=severity,
        starts_at=_parse_datetime(record.get("starts_at")),
        ends_at=_parse_datetime(record.get("ends_at")),
        symbols=_normalize_symbols(record.get("symbols", [])),
        tags=_normalize_tags(record.get("tags", [])),
        source=str(record.get("source") or "").strip(),
        verified=verified,
        sentiment=sentiment,
        sentiment_score=sentiment_score,
        sentiment_model=str(record.get("sentiment_model") or "").strip(),
        confidence_score=confidence_score,
        confidence_level=str(record.get("confidence_level") or "medium").strip().lower(),
        notes=str(record.get("notes") or "").strip(),
    )


def ensure_market_events_file(
    path: str = MARKET_EVENTS_FILE,
    example_path: str = MARKET_EVENTS_EXAMPLE_FILE,
) -> bool:
    if not path or os.path.exists(path):
        return False
    if not example_path or not os.path.exists(example_path):
        return False
    try:
        with open(example_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return False
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        return False
    parent_dir = os.path.dirname(path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except Exception:
        return False
    return True


def load_market_events(
    path: str = MARKET_EVENTS_FILE,
    *,
    example_path: str = MARKET_EVENTS_EXAMPLE_FILE,
    auto_bootstrap: bool = False,
) -> List[MarketEvent]:
    if auto_bootstrap:
        ensure_market_events_file(path=path, example_path=example_path)
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    events = payload.get("events", [])
    if not isinstance(events, list):
        return []
    normalized = []
    for index, record in enumerate(events):
        try:
            normalized.append(with_event_confidence(_normalize_event(record, index)))
        except ValueError:
            continue
    return normalized


def _is_active(event: MarketEvent, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    if event.starts_at is not None and now < event.starts_at:
        return False
    if event.ends_at is not None and now > event.ends_at:
        return False
    return True


def select_active_events(
    events: Iterable[MarketEvent],
    symbols: Optional[Iterable[str]] = None,
    now: Optional[datetime] = None,
    verified_only: bool = False,
) -> List[MarketEvent]:
    now = now or datetime.now()
    symbol_set = {str(symbol).strip().upper() for symbol in (symbols or []) if symbol}
    selected = []
    for event in events:
        if verified_only and not event.verified:
            continue
        if not _is_active(event, now=now):
            continue
        if symbol_set and event.symbols and not symbol_set.intersection(set(event.symbols)):
            continue
        selected.append(event)
    return selected


def _event_risk_points(event: MarketEvent) -> int:
    base_points = _SEVERITY_POINTS.get(event.severity, 1)
    base_points += _EVENT_TYPE_BONUS.get(event.event_type, 0)
    title_lower = event.title.lower()
    if "fomc" in title_lower or "fomc" in event.tags:
        base_points += 2
    if event.sentiment in ("negative", "risk_off", "bearish"):
        base_points += 1
    if event.sentiment == "positive":
        base_points -= 1
    confidence = event.confidence_score if event.confidence_score is not None else compute_event_confidence_score(event)
    points = int(round(base_points * (0.5 + float(confidence))))
    return max(points, 0)


def evaluate_event_risk_switch(
    events: Iterable[MarketEvent],
    vix: Optional[float] = None,
    *,
    verified_only: bool = True,
    vix_caution: float = 24.0,
    vix_brake: float = 32.0,
    now: Optional[datetime] = None,
) -> EventRiskDecision:
    active_events = select_active_events(events, verified_only=verified_only, now=now)
    risk_score = 0
    reasons: List[str] = []

    if vix is not None:
        if float(vix) >= vix_brake:
            risk_score += 4
            reasons.append(f"VIX {float(vix):.1f} 超过急刹车阈值 {vix_brake:.1f}。")
        elif float(vix) >= vix_caution:
            risk_score += 1
            reasons.append(f"VIX {float(vix):.1f} 进入警戒区。")

    for event in active_events:
        event = with_event_confidence(event)
        points = _event_risk_points(event)
        risk_score += points
        reasons.append(
            f"事件 {event.title} ({event.severity}/{event.event_type}, 置信度 {event.confidence_level}) 风险分 {points}。"
        )

    if risk_score >= 4:
        return EventRiskDecision(
            regime="RISK_OFF",
            risk_score=risk_score,
            block_new_buys=True,
            max_position_weight=0.08,
            reasons=reasons or ["事件风险偏高，建议临时收缩风险。"],
            active_event_count=len(active_events),
        )
    if risk_score >= 2:
        return EventRiskDecision(
            regime="CAUTION",
            risk_score=risk_score,
            block_new_buys=False,
            max_position_weight=0.12,
            reasons=reasons or ["事件风险升温，建议谨慎新增仓位。"],
            active_event_count=len(active_events),
        )
    return EventRiskDecision(
        regime="NORMAL",
        risk_score=risk_score,
        block_new_buys=False,
        max_position_weight=0.20,
        reasons=reasons or ["无显著事件风险。"],
        active_event_count=len(active_events),
    )
