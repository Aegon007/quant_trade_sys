"""Small file-backed registry for local background service status.

The registry is intentionally simple: this is a single-user local system, so
we only need durable, inspectable JSON that the API and frontend can read.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths


DEFAULT_JOB_STATUS_FILE = qpaths.JOB_STATUS_FILE


def _now_iso(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).isoformat()


def _read_json(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _atomic_write_json(path: str, payload: Mapping) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload or {}), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, target)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return str(target)


def empty_job_status(*, now: Optional[datetime] = None) -> dict:
    timestamp = _now_iso(now)
    return {
        "schema_version": 1,
        "generated_at": timestamp,
        "updated_at": timestamp,
        "jobs": {},
    }


def load_job_status(*, path: str = DEFAULT_JOB_STATUS_FILE) -> dict:
    payload = _read_json(path)
    if not isinstance(payload, dict) or not payload:
        return empty_job_status()
    payload.setdefault("schema_version", 1)
    payload.setdefault("generated_at", payload.get("updated_at") or _now_iso())
    payload.setdefault("updated_at", payload.get("generated_at") or _now_iso())
    jobs = payload.get("jobs")
    payload["jobs"] = jobs if isinstance(jobs, dict) else {}
    return payload


def save_job_status(payload: Mapping, *, path: str = DEFAULT_JOB_STATUS_FILE) -> str:
    return _atomic_write_json(path, dict(payload or empty_job_status()))


def build_job_entry(
    *,
    name: str,
    state: str,
    detail: str = "",
    pid: Optional[int] = None,
    command: Optional[object] = None,
    metadata: Optional[Mapping] = None,
    now: Optional[datetime] = None,
) -> dict:
    entry = {
        "name": str(name),
        "state": str(state or "unknown").lower(),
        "detail": str(detail or ""),
        "updated_at": _now_iso(now),
    }
    if pid is not None:
        entry["pid"] = int(pid)
    if command is not None:
        entry["command"] = command
    for key, value in dict(metadata or {}).items():
        if key not in {"name", "state", "detail", "updated_at", "pid", "command"}:
            entry[str(key)] = value
    return entry


def update_job_status(
    name: str,
    *,
    state: str,
    detail: str = "",
    pid: Optional[int] = None,
    command: Optional[object] = None,
    metadata: Optional[Mapping] = None,
    path: str = DEFAULT_JOB_STATUS_FILE,
    now: Optional[datetime] = None,
) -> dict:
    payload = load_job_status(path=path)
    timestamp = _now_iso(now)
    payload["updated_at"] = timestamp
    payload.setdefault("generated_at", timestamp)
    payload.setdefault("jobs", {})
    payload["jobs"][str(name)] = build_job_entry(
        name=str(name),
        state=state,
        detail=detail,
        pid=pid,
        command=command,
        metadata=metadata,
        now=now,
    )
    save_job_status(payload, path=path)
    return payload


def record_startup_statuses(statuses, *, path: str = DEFAULT_JOB_STATUS_FILE, now: Optional[datetime] = None) -> dict:
    payload = load_job_status(path=path)
    timestamp = _now_iso(now)
    payload["updated_at"] = timestamp
    payload.setdefault("generated_at", timestamp)
    jobs = payload.setdefault("jobs", {})
    for status in list(statuses or []):
        if isinstance(status, Mapping):
            name = str(status.get("name") or "").strip()
            state = str(status.get("state") or "unknown")
            detail = str(status.get("detail") or "")
            pid = status.get("pid")
        else:
            name = str(getattr(status, "name", "") or "").strip()
            state = str(getattr(status, "state", "unknown") or "unknown")
            detail = str(getattr(status, "detail", "") or "")
            pid = getattr(status, "pid", None)
        if not name:
            continue
        jobs[name] = build_job_entry(name=name, state=state, detail=detail, pid=pid, now=now)
    save_job_status(payload, path=path)
    return payload
