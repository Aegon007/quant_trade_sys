"""Atomic JSON status registry for local background work."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths


DEFAULT_JOB_STATUS_FILE = qpaths.JOB_STATUS_FILE
ACTIVE_STATES = {"queued", "started", "running"}
_THREAD_LOCK = threading.RLock()


@contextmanager
def _registry_lock(path):
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCK:
        with lock_path.open("a+", encoding="utf-8") as handle:
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            try:
                yield
            finally:
                try:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except (ImportError, OSError):
                    pass


def _now(now=None) -> str:
    return (now or datetime.now()).isoformat()


def load_job_status(*, path=DEFAULT_JOB_STATUS_FILE) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("schema_version", 1)
    payload.setdefault("generated_at", _now())
    payload.setdefault("updated_at", payload["generated_at"])
    payload["jobs"] = dict(payload.get("jobs", {}) or {})
    return payload


def save_job_status(payload: Mapping, *, path=DEFAULT_JOB_STATUS_FILE) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, ensure_ascii=False, indent=2, default=str)
            handle.write("\n")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return str(target)


def update_job_status(name: str, *, state: str, detail="", pid=None, command=None, metadata=None, path=DEFAULT_JOB_STATUS_FILE, now: Optional[datetime] = None) -> dict:
    with _registry_lock(path):
        payload = load_job_status(path=path)
        timestamp = _now(now)
        previous = dict(payload["jobs"].get(name, {}) or {})
        started_at = timestamp if state in {"queued", "started"} else previous.get("started_at", timestamp)
        entry = {"name": name, "state": str(state).lower(), "detail": str(detail), "updated_at": timestamp, "started_at": started_at, **dict(metadata or {})}
        if pid is not None:
            entry["pid"] = int(pid)
        if command is not None:
            entry["command"] = command
        try:
            entry["elapsed_seconds"] = round(max(((now or datetime.now()) - datetime.fromisoformat(started_at)).total_seconds(), 0), 2)
        except Exception:
            entry["elapsed_seconds"] = 0
        event = {key: value for key, value in entry.items() if key in {"state", "detail", "updated_at", "stage", "progress_pct", "result_summary"}}
        entry["events"] = (list(previous.get("events", []) or []) + [event])[-60:]
        payload["jobs"][name] = entry
        payload["updated_at"] = timestamp
        save_job_status(payload, path=path)
    return payload


def mark_stale_jobs(payload: Mapping, *, now: Optional[datetime] = None, stale_after_seconds=1800) -> dict:
    result = {**dict(payload or {}), "jobs": {name: dict(row or {}) for name, row in dict(dict(payload or {}).get("jobs", {}) or {}).items()}}
    current = now or datetime.now()
    for row in result["jobs"].values():
        if str(row.get("state")) not in ACTIVE_STATES:
            continue
        try:
            age = (current - datetime.fromisoformat(str(row.get("updated_at")))).total_seconds()
        except Exception:
            continue
        if age > stale_after_seconds:
            row.update({"state": "stale", "detail": f"{row.get('detail') or '任务'}：超过30分钟没有心跳", "stale_since_seconds": round(age, 1)})
    return result
