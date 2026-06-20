from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from quant_core import paths as qpaths


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_bootstrap_manifest(path: str = qpaths.MULTI_HORIZON_BOOTSTRAP_MANIFEST_FILE) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def install_bootstrap_checkpoint(
    *,
    runtime_path: str = qpaths.MULTI_HORIZON_CHECKPOINT_FILE,
    bootstrap_path: str = qpaths.MULTI_HORIZON_BOOTSTRAP_CHECKPOINT_FILE,
    manifest_path: str = qpaths.MULTI_HORIZON_BOOTSTRAP_MANIFEST_FILE,
) -> dict:
    runtime = Path(runtime_path)
    if runtime.exists():
        return {"status": "EXISTS", "runtime_path": str(runtime)}

    source = Path(bootstrap_path)
    manifest = load_bootstrap_manifest(manifest_path)
    artifact = dict(manifest.get("artifact", {}) or {})
    if not source.exists() or not artifact:
        return {
            "status": "UNAVAILABLE",
            "runtime_path": str(runtime),
            "bootstrap_path": str(source),
        }

    expected_hash = str(artifact.get("sha256") or "").strip().lower()
    actual_hash = sha256_file(str(source))
    if not expected_hash or actual_hash != expected_hash:
        raise ValueError("Bootstrap checkpoint SHA-256 verification failed.")
    expected_size = artifact.get("size_bytes")
    if expected_size is not None and int(expected_size) != source.stat().st_size:
        raise ValueError("Bootstrap checkpoint size verification failed.")
    if int(artifact.get("target_schema_version", 0) or 0) < 2:
        raise ValueError("Bootstrap checkpoint uses a retired target schema.")

    runtime.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=f".{runtime.name}.", suffix=".tmp", dir=str(runtime.parent))
    os.close(fd)
    try:
        shutil.copyfile(source, temporary_path)
        os.replace(temporary_path, runtime)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return {
        "status": "INSTALLED",
        "runtime_path": str(runtime),
        "bootstrap_path": str(source),
        "sha256": actual_hash,
        "model_version": manifest.get("model_version"),
        "validation_status": manifest.get("validation_status"),
    }
