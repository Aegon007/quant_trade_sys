from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Mapping

from quant_core import paths as qpaths


DEFAULT_MULTI_HORIZON_SNAPSHOT_FILE = qpaths.MULTI_HORIZON_SNAPSHOT_FILE


def load_multi_horizon_snapshot(*, path: str = DEFAULT_MULTI_HORIZON_SNAPSHOT_FILE) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_multi_horizon_snapshot(
    snapshot: Mapping,
    *,
    path: str = DEFAULT_MULTI_HORIZON_SNAPSHOT_FILE,
) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(snapshot or {}), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_path, target)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return str(target)
