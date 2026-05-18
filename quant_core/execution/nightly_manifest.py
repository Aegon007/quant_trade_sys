from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping, Optional

from quant_core import paths as qpaths


DEFAULT_NIGHTLY_MANIFEST_FILE = qpaths.NIGHTLY_RUN_MANIFEST_FILE


def _read_json(path: str):
    target = Path(path)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: str, payload: Mapping):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload or {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def _timestamp(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).isoformat()


def _run_id(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d-nightly")


def load_nightly_run_manifest(*, path: str = DEFAULT_NIGHTLY_MANIFEST_FILE):
    return _read_json(path)


def save_nightly_run_manifest(manifest: Mapping, *, path: str = DEFAULT_NIGHTLY_MANIFEST_FILE) -> str:
    return _write_json(path, manifest)


def initialize_nightly_run_manifest(*, now: Optional[datetime] = None, force: bool = False, path: str = DEFAULT_NIGHTLY_MANIFEST_FILE) -> dict:
    now = now or datetime.now()
    run_id = _run_id(now)
    existing = load_nightly_run_manifest(path=path) or {}
    if not force and str(existing.get("run_id") or "").strip() == run_id:
        manifest = dict(existing)
        manifest["status"] = "running"
        manifest.setdefault("steps", {})
        manifest.setdefault("started_at", _timestamp(now))
        manifest["resumed_at"] = _timestamp(now)
        manifest["finished_at"] = None
    else:
        manifest = {
            "run_id": run_id,
            "started_at": _timestamp(now),
            "resumed_at": None,
            "finished_at": None,
            "completed_at": None,
            "status": "running",
            "steps": {},
        }
    save_nightly_run_manifest(manifest, path=path)
    return manifest


def can_resume_step(
    manifest: Optional[Mapping],
    *,
    step_name: str,
    output_file: Optional[str] = None,
    now: Optional[datetime] = None,
) -> bool:
    manifest = dict(manifest or {})
    if str(manifest.get("run_id") or "").strip() != _run_id(now):
        return False
    step = dict((manifest.get("steps") or {}).get(step_name, {}) or {})
    if str(step.get("status") or "").strip().lower() != "completed":
        return False
    if output_file:
        return Path(output_file).exists()
    return True


def mark_step_started(
    manifest: Mapping,
    *,
    step_name: str,
    input_version: Optional[str] = None,
    path: str = DEFAULT_NIGHTLY_MANIFEST_FILE,
    now: Optional[datetime] = None,
) -> dict:
    updated = dict(manifest or {})
    steps = dict(updated.get("steps", {}) or {})
    existing = dict(steps.get(step_name, {}) or {})
    existing.update(
        {
            "step_name": step_name,
            "status": "running",
            "started_at": existing.get("started_at") or _timestamp(now),
            "finished_at": None,
            "input_version": input_version,
            "output_file": existing.get("output_file"),
            "is_fresh": False,
            "reused": False,
            "error_message": None,
        }
    )
    steps[step_name] = existing
    updated["steps"] = steps
    updated["status"] = "running"
    save_nightly_run_manifest(updated, path=path)
    return updated


def mark_step_completed(
    manifest: Mapping,
    *,
    step_name: str,
    output_file: Optional[str] = None,
    input_version: Optional[str] = None,
    reused: bool = False,
    metadata: Optional[Mapping] = None,
    path: str = DEFAULT_NIGHTLY_MANIFEST_FILE,
    now: Optional[datetime] = None,
) -> dict:
    updated = dict(manifest or {})
    steps = dict(updated.get("steps", {}) or {})
    existing = dict(steps.get(step_name, {}) or {})
    existing.update(
        {
            "step_name": step_name,
            "status": "completed",
            "started_at": existing.get("started_at") or _timestamp(now),
            "finished_at": _timestamp(now),
            "input_version": input_version if input_version is not None else existing.get("input_version"),
            "output_file": output_file or existing.get("output_file"),
            "is_fresh": True,
            "reused": bool(reused),
            "error_message": None,
        }
    )
    if metadata:
        existing["metadata"] = dict(metadata)
    steps[step_name] = existing
    updated["steps"] = steps
    save_nightly_run_manifest(updated, path=path)
    return updated


def mark_step_failed(
    manifest: Mapping,
    *,
    step_name: str,
    error_message: str,
    path: str = DEFAULT_NIGHTLY_MANIFEST_FILE,
    now: Optional[datetime] = None,
) -> dict:
    updated = dict(manifest or {})
    steps = dict(updated.get("steps", {}) or {})
    existing = dict(steps.get(step_name, {}) or {})
    existing.update(
        {
            "step_name": step_name,
            "status": "failed",
            "started_at": existing.get("started_at") or _timestamp(now),
            "finished_at": _timestamp(now),
            "is_fresh": False,
            "error_message": str(error_message or "").strip(),
        }
    )
    steps[step_name] = existing
    updated["steps"] = steps
    updated["status"] = "failed"
    updated["finished_at"] = _timestamp(now)
    save_nightly_run_manifest(updated, path=path)
    return updated


def finalize_nightly_run_manifest(
    manifest: Mapping,
    *,
    status: str = "completed",
    path: str = DEFAULT_NIGHTLY_MANIFEST_FILE,
    now: Optional[datetime] = None,
) -> dict:
    updated = dict(manifest or {})
    updated["status"] = str(status or "completed")
    updated["finished_at"] = _timestamp(now)
    updated["completed_at"] = updated["finished_at"]
    save_nightly_run_manifest(updated, path=path)
    return updated
