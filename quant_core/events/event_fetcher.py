from datetime import datetime, timedelta
from dataclasses import replace
import json
import os
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from quant_core import paths as qpaths
from quant_core.events.event_news import (
    MARKET_EVENTS_FILE,
    MarketEvent,
    attach_event_sentiment,
    load_market_events,
    save_market_events,
    with_event_confidence,
)
from quant_core.events.finbert_sentiment import (
    DEFAULT_FINBERT_MODEL,
    analyze_financial_sentiment,
)


qpaths.bootstrap_storage_paths()

EVENT_SOURCES_CONFIG_PATH = qpaths.EVENT_SOURCES_CONFIG_FILE

DEFAULT_EVENT_SOURCE_CONFIG = {
    "sources": [
        {
            "id": "local_mock",
            "type": "local_file",
            "enabled": True,
            "path": MARKET_EVENTS_FILE,
        },
        {
            "id": "yfinance_news",
            "type": "yfinance_news",
            "enabled": False,
            "verified": False,
            "severity": "medium",
            "lookback_hours": 24,
            "max_items_per_symbol": 10,
            "use_finbert": True,
        },
    ]
}


def _parse_iso_datetime(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _normalize_symbol_set(symbols: Iterable[str]) -> set:
    return {
        str(symbol).strip().upper()
        for symbol in (symbols or [])
        if symbol and str(symbol).strip()
    }


def should_refresh_events_cache(
    *,
    last_fetched_at: Optional[str],
    previous_symbols: Iterable[str],
    current_symbols: Iterable[str],
    interval_seconds: int = 600,
    now: Optional[datetime] = None,
    force: bool = False,
) -> bool:
    if force:
        return True

    current_set = _normalize_symbol_set(current_symbols)
    if not current_set:
        return False
    previous_set = _normalize_symbol_set(previous_symbols)
    if previous_set != current_set:
        return True

    fetched_at = _parse_iso_datetime(last_fetched_at)
    if fetched_at is None:
        return True
    now = now or datetime.now()
    age_seconds = (now - fetched_at).total_seconds()
    return age_seconds >= float(interval_seconds)


def load_event_source_config(path: str = EVENT_SOURCES_CONFIG_PATH) -> Dict:
    if not path or not os.path.exists(path):
        return DEFAULT_EVENT_SOURCE_CONFIG.copy()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
        if isinstance(config, dict) and isinstance(config.get("sources"), list):
            return config
    except Exception:
        pass
    return DEFAULT_EVENT_SOURCE_CONFIG.copy()


def save_event_source_config(config: Dict, path: str = EVENT_SOURCES_CONFIG_PATH) -> str:
    if not isinstance(config, dict) or not isinstance(config.get("sources"), list):
        raise ValueError("Event source config must contain a sources list.")
    target = os.path.abspath(path)
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temporary = f"{target}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, target)
    return target


def _extract_news_payload(item: Dict) -> Dict:
    content = item.get("content")
    if isinstance(content, dict):
        return content
    return item


def _extract_related_tickers(item: Dict, payload: Dict) -> List[str]:
    related = item.get("relatedTickers")
    if related is None:
        related = payload.get("relatedTickers")
    if related is None:
        return []
    symbols = []
    for value in related:
        symbol = str(value or "").strip().upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def _extract_publish_time(item: Dict, payload: Dict, now: datetime, lookback_hours: int) -> Tuple[datetime, datetime]:
    publish_time = payload.get("providerPublishTime")
    if publish_time is None:
        publish_time = item.get("providerPublishTime")
    published_dt = None
    if publish_time is not None:
        try:
            published_dt = datetime.fromtimestamp(int(publish_time))
        except Exception:
            published_dt = None
    if published_dt is None:
        published_dt = now
    return published_dt, published_dt + timedelta(hours=max(1, int(lookback_hours)))


def _source_severity(source_config: Dict) -> str:
    severity = str(source_config.get("severity") or "medium").strip().lower()
    if severity not in ("low", "medium", "high"):
        return "medium"
    return severity


def _news_search_terms(symbol: str, quotes: Iterable[Dict], source_config: Dict) -> set[str]:
    ignored = {"corporation", "corp", "company", "inc", "limited", "holdings", "group", "plc", "class"}
    terms = {symbol.lower()}
    configured = dict(source_config.get("symbol_aliases", {}) or {}).get(symbol, [])
    if isinstance(configured, str):
        configured = [configured]
    for value in configured or []:
        text = str(value or "").strip().lower()
        if text:
            terms.add(text)
    for quote in list(quotes or [])[:3]:
        if not isinstance(quote, dict):
            continue
        for key in ("shortname", "longname", "shortName", "longName"):
            name = str(quote.get(key) or "").strip().lower()
            if not name:
                continue
            terms.add(name)
            terms.update(
                token.strip(".,()")
                for token in name.split()
                if len(token.strip(".,()")) >= 4 and token.strip(".,()") not in ignored
            )
    return terms


def _is_relevant_search_item(item: Dict, payload: Dict, *, symbol: str, terms: set[str]) -> bool:
    related = set(_extract_related_tickers(item, payload))
    if symbol in related:
        return True
    text = " ".join(
        str(payload.get(key) or item.get(key) or "")
        for key in ("title", "summary", "description")
    ).lower()
    return any(term and term in text for term in terms)


def _fetch_from_local_file(source_config: Dict) -> List[MarketEvent]:
    path = str(source_config.get("path") or MARKET_EVENTS_FILE)
    example_path = str(source_config.get("example_path") or qpaths.MARKET_EVENTS_EXAMPLE_FILE)
    source_id = str(source_config.get("id") or "local_mock")
    events = []
    for event in load_market_events(
        path=path,
        example_path=example_path,
        auto_bootstrap=True,
    ):
        if event.source_id == "manual":
            event = replace(event, source_id=source_id)
        events.append(with_event_confidence(event))
    return events


def _fetch_from_yfinance_news(
    source_config: Dict,
    symbols: Iterable[str],
    now: datetime,
    sentiment_fn: Callable[[str], Dict],
) -> List[MarketEvent]:
    import yfinance as yf

    source_id = str(source_config.get("id") or "yfinance_news")
    lookback_hours = int(source_config.get("lookback_hours", 24))
    max_items = int(source_config.get("max_items_per_symbol", 10))
    severity = _source_severity(source_config)
    verified = bool(source_config.get("verified", False))
    event_type = str(source_config.get("event_type") or "news").strip().lower()
    events: List[MarketEvent] = []

    for raw_symbol in symbols:
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol:
            continue
        items = []
        search_terms = {symbol.lower()}
        strict_relevance = False
        if hasattr(yf, "Search"):
            try:
                search = yf.Search(symbol, news_count=max(max_items * 2, max_items))
                items = list(getattr(search, "news", []) or [])
                search_terms = _news_search_terms(
                    symbol,
                    getattr(search, "quotes", []) or [],
                    source_config,
                )
                strict_relevance = True
            except Exception:
                items = []
        if not items:
            ticker = yf.Ticker(symbol)
            if hasattr(ticker, "get_news"):
                try:
                    items = ticker.get_news(count=max_items) or []
                except Exception:
                    items = []
            if not items:
                try:
                    items = getattr(ticker, "news", []) or []
                except Exception:
                    items = []
        accepted = 0
        for index, item in enumerate(items):
            if accepted >= max_items:
                break
            if not isinstance(item, dict):
                continue
            payload = _extract_news_payload(item)
            if strict_relevance and not _is_relevant_search_item(
                item,
                payload,
                symbol=symbol,
                terms=search_terms,
            ):
                continue
            try:
                title = str(payload.get("title") or item.get("title") or "").strip()
            except Exception:
                title = ""
            if not title:
                continue
            publisher = str(
                payload.get("publisher")
                or payload.get("provider", {}).get("displayName")
                or item.get("publisher")
                or "Yahoo Finance"
            ).strip()
            link = str(
                payload.get("canonicalUrl", {}).get("url")
                or payload.get("link")
                or item.get("link")
                or ""
            ).strip()
            starts_at, ends_at = _extract_publish_time(item, payload, now=now, lookback_hours=lookback_hours)
            related = _extract_related_tickers(item, payload) or [symbol]
            event_id = str(item.get("uuid") or payload.get("id") or f"{source_id}-{symbol}-{int(starts_at.timestamp())}-{index}")
            summary = str(payload.get("summary") or payload.get("description") or "").strip()
            sentiment_text = f"{title}. {summary}".strip()
            sentiment = sentiment_fn(sentiment_text) if sentiment_text else None

            event = MarketEvent(
                event_id=event_id,
                title=title,
                source_id=source_id,
                event_type=event_type,
                severity=severity,
                starts_at=starts_at,
                ends_at=ends_at,
                symbols=related,
                tags=["news", "yfinance"],
                source=publisher,
                verified=verified,
                sentiment="neutral",
                notes=link,
            )
            event = with_event_confidence(event)
            event = attach_event_sentiment(event, sentiment)
            events.append(event)
            accepted += 1
    return events


def _dedupe_events(events: List[MarketEvent]) -> List[MarketEvent]:
    unique: Dict[str, MarketEvent] = {}
    for event in events:
        dedupe_key = event.event_id or f"{event.source_id}:{event.title}:{event.starts_at}"
        if dedupe_key not in unique:
            unique[dedupe_key] = event
    return list(unique.values())


def fetch_events_from_sources(
    symbols: Iterable[str],
    *,
    config_path: str = EVENT_SOURCES_CONFIG_PATH,
    config: Optional[Dict] = None,
    now: Optional[datetime] = None,
    sentiment_fn: Optional[Callable[[str], Dict]] = None,
) -> Tuple[List[MarketEvent], List[Dict]]:
    now = now or datetime.now()
    source_config = config if config is not None else load_event_source_config(path=config_path)
    sources = source_config.get("sources", []) if isinstance(source_config, dict) else []
    reports: List[Dict] = []
    events: List[MarketEvent] = []
    custom_sentiment_fn = sentiment_fn

    if sentiment_fn is None:
        def sentiment_fn(text: str):
            return analyze_financial_sentiment(text, use_finbert=True)

    for source in sources:
        if not isinstance(source, dict):
            continue
        if not bool(source.get("enabled", True)):
            continue
        source_id = str(source.get("id") or source.get("type") or "source")
        source_type = str(source.get("type") or "local_file")
        try:
            if source_type == "local_file":
                fetched = _fetch_from_local_file(source)
            elif source_type == "yfinance_news":
                if custom_sentiment_fn is not None:
                    source_sentiment_fn = custom_sentiment_fn
                else:
                    use_finbert = bool(source.get("use_finbert", True))
                    finbert_model = str(source.get("finbert_model") or DEFAULT_FINBERT_MODEL)

                    def source_sentiment_fn(text: str, use_finbert=use_finbert, finbert_model=finbert_model):
                        return analyze_financial_sentiment(text, use_finbert=use_finbert, model_name=finbert_model)

                fetched = _fetch_from_yfinance_news(
                    source,
                    symbols=symbols,
                    now=now,
                    sentiment_fn=source_sentiment_fn,
                )
            else:
                fetched = []
            events.extend(fetched)
            reports.append({"source_id": source_id, "type": source_type, "ok": True, "fetched": len(fetched), "error": ""})
        except Exception as exc:
            reports.append({"source_id": source_id, "type": source_type, "ok": False, "fetched": 0, "error": str(exc)})

    return _dedupe_events(events), reports


def refresh_event_cache(
    symbols: Iterable[str],
    *,
    events_path: str = MARKET_EVENTS_FILE,
    status_path: str = qpaths.EVENT_SOURCE_STATUS_FILE,
    config_path: str = EVENT_SOURCES_CONFIG_PATH,
    fetcher: Callable = fetch_events_from_sources,
    now: Optional[datetime] = None,
) -> Dict:
    now = now or datetime.now()
    normalized_symbols = sorted(_normalize_symbol_set(symbols))
    try:
        events, reports = fetcher(normalized_symbols, config_path=config_path, now=now)
    except Exception as exc:
        events = load_market_events(path=events_path, auto_bootstrap=True)
        reports = [{"source_id": "event_fetcher", "type": "runtime", "ok": False, "fetched": 0, "error": str(exc)}]

    save_market_events(events, path=events_path)
    successful_sources = [row for row in reports if bool(dict(row or {}).get("ok"))]
    failed_sources = [row for row in reports if not bool(dict(row or {}).get("ok"))]
    if successful_sources and not failed_sources:
        status = "OK"
    elif successful_sources:
        status = "PARTIAL"
    else:
        status = "FAILED"
    payload = {
        "generated_at": now.isoformat(),
        "status": status,
        "tracked_symbols": normalized_symbols,
        "event_count": len(events),
        "successful_source_count": len(successful_sources),
        "failed_source_count": len(failed_sources),
        "sources": reports,
    }
    target = os.path.abspath(status_path)
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temporary = f"{target}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, target)
    return payload
