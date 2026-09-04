"""Read-only API projection over background-generated research snapshots."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths
from quant_core.data.watchlist import load_watchlist
from quant_core.jobs import job_registry
from quant_core.notifications import notification_config
from quant_core.research.service import load_valuation_policy
from quant_core.research.universe import load_universe_config


DEFAULT_MAX_AGE_SECONDS = 36 * 3600


def now_iso() -> str:
    return datetime.now().isoformat()


def _load(path: str) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _age(generated_at, now=None):
    try:
        value = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None
    return max(((now or datetime.now()).replace(tzinfo=None) - value).total_seconds(), 0.0)


def _items(payload: Mapping) -> list:
    for key in ("recommendations", "opportunities", "valuations", "symbols", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _envelope(name: str, payload: Mapping, *, path: str, now=None, max_age_seconds=DEFAULT_MAX_AGE_SECONDS) -> dict:
    payload = dict(payload or {})
    generated_at = payload.get("generated_at")
    age = _age(generated_at, now=now)
    missing = not payload
    stale = missing or generated_at is None or (age is not None and age > max_age_seconds)
    return {
        "name": name,
        "generated_at": generated_at,
        "source": path,
        "freshness_status": "MISSING" if missing else "STALE" if stale else "OK",
        "is_stale": stale,
        "summary": dict(payload.get("summary", {}) or {}),
        "items": _items(payload),
        "errors": [f"snapshot missing: {path}"] if missing else list(payload.get("errors", []) or []),
        "warnings": [],
        "data_quality": {"age_seconds": age},
        "next_update_hint": "运行完整估值流程" if stale else None,
        "payload": payload,
    }


def load_snapshot_response(name: str, path: str, *, now: Optional[datetime] = None, max_age_seconds=DEFAULT_MAX_AGE_SECONDS) -> dict:
    return _envelope(name, _load(path), path=path, now=now, max_age_seconds=max_age_seconds)


def load_dashboard_response(*, now: Optional[datetime] = None) -> dict:
    recommendations = _load(qpaths.RECOMMENDATION_SNAPSHOT_FILE)
    brief = _load(qpaths.DECISION_BRIEF_FILE)
    market_risk = _load(qpaths.MARKET_RISK_SNAPSHOT_FILE)
    data_health = _load(qpaths.DATA_HEALTH_SNAPSHOT_FILE)
    change_feed = _load(qpaths.CHANGE_FEED_FILE)
    payload = {"recommendations": recommendations, "brief": brief, "market_risk": market_risk, "data_health": data_health, "change_feed": change_feed}
    generated = recommendations.get("generated_at") or brief.get("generated_at")
    return _envelope("dashboard", {"generated_at": generated, "summary": recommendations.get("summary", {}), **payload}, path="composed:valuation-research", now=now)


def load_opportunities_response(*, now: Optional[datetime] = None) -> dict:
    return load_snapshot_response("opportunities", qpaths.OPPORTUNITY_SNAPSHOT_FILE, now=now)


def load_valuations_response(symbol: str = "", *, now: Optional[datetime] = None) -> dict:
    payload = _load(qpaths.VALUATION_SNAPSHOT_FILE)
    normalized = str(symbol or "").strip().upper()
    if normalized:
        payload = {**payload, "valuations": [row for row in list(payload.get("valuations", []) or []) if str(row.get("symbol") or "").upper() == normalized]}
    return _envelope("valuations", payload, path=qpaths.VALUATION_SNAPSHOT_FILE, now=now)


def load_market_risk_response(*, now: Optional[datetime] = None) -> dict:
    return load_snapshot_response("market-risk", qpaths.MARKET_RISK_SNAPSHOT_FILE, now=now)


def load_watchlist_response(*, now: Optional[datetime] = None) -> dict:
    symbols = load_watchlist()
    recommendations = _load(qpaths.RECOMMENDATION_SNAPSHOT_FILE)
    indexed = {str(row.get("symbol") or "").upper(): row for row in list(recommendations.get("recommendations", []) or [])}
    payload = {"generated_at": recommendations.get("generated_at") or now_iso(), "symbols": [{"symbol": symbol, **dict(indexed.get(symbol, {}) or {})} for symbol in symbols]}
    return _envelope("watchlist", payload, path=qpaths.WATCHLIST_FILE, now=now)


def _sanitize(config: Mapping) -> dict:
    payload = json.loads(json.dumps(dict(config or {})))
    for section, key in notification_config.SECRET_FIELDS:
        current = str(dict(payload.get(section, {}) or {}).get(key) or "")
        payload.setdefault(section, {})[key] = ""
        payload[section][f"{key}_configured"] = bool(current)
    return payload


def default_runtime_schedule() -> dict:
    return {
        "schema_version": 2,
        "timezone": "America/New_York",
        "market_monitor": {"enabled": True, "interval_seconds": 1800, "market_hours_only": True},
        "nightly": {"enabled": True, "poll_seconds": 300, "run_window_local": {"start": "23:00", "end": "01:00"}},
        "weekend_research": {"enabled": True, "run_window_local": {"day": "Saturday", "start": "10:00", "end": "18:00"}},
    }


def load_runtime_schedule(path: str = qpaths.RUNTIME_SCHEDULE_CONFIG_FILE) -> dict:
    example = _load(qpaths.RUNTIME_SCHEDULE_EXAMPLE_FILE) if Path(path) == Path(qpaths.RUNTIME_SCHEDULE_CONFIG_FILE) else {}
    return {**default_runtime_schedule(), **example, **_load(path)}


def save_runtime_schedule(schedule: Mapping, path: str = qpaths.RUNTIME_SCHEDULE_CONFIG_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({**default_runtime_schedule(), **dict(schedule or {})}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(target)


def load_settings_response(*, now: Optional[datetime] = None) -> dict:
    payload = {
        "generated_at": now_iso(),
        "notification_config": _sanitize(notification_config.load_notification_config()),
        "runtime_schedule": load_runtime_schedule(),
        "research_universe": load_universe_config(),
        "valuation_policy": load_valuation_policy(),
    }
    return _envelope("settings", payload, path="composed:settings", now=now, max_age_seconds=365 * 86400)


def load_job_status_response(*, now: Optional[datetime] = None) -> dict:
    payload = job_registry.mark_stale_jobs(job_registry.load_job_status(), now=now)
    payload.setdefault("generated_at", now_iso())
    return _envelope("job-status", payload, path=qpaths.JOB_STATUS_FILE, now=now, max_age_seconds=365 * 86400)
