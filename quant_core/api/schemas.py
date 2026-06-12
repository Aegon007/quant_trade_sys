"""Stable response builders for the local V3 API."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping, Optional


API_SCHEMA_VERSION = 1


def now_iso(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).isoformat()


def build_api_response(
    *,
    name: str,
    source: str,
    freshness_status: str,
    is_stale: bool,
    summary: Optional[Mapping] = None,
    items=None,
    errors=None,
    warnings=None,
    data_quality: Optional[Mapping] = None,
    next_update_hint: Optional[str] = None,
    payload=None,
    generated_at: Optional[str] = None,
) -> dict:
    """Build a compact, frontend-safe API DTO.

    `payload` keeps the raw snapshot available for early migration, while the
    top-level fields give React stable data to render without knowing every
    internal file format.
    """
    return {
        "schema_version": API_SCHEMA_VERSION,
        "name": str(name),
        "generated_at": generated_at or now_iso(),
        "source": str(source),
        "freshness_status": str(freshness_status or "UNKNOWN").upper(),
        "is_stale": bool(is_stale),
        "summary": dict(summary or {}),
        "items": list(items or []),
        "errors": list(errors or []),
        "warnings": list(warnings or []),
        "data_quality": dict(data_quality or {}),
        "next_update_hint": next_update_hint,
        "payload": payload if payload is not None else {},
    }
