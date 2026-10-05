from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from quant_core import paths as qpaths


class ResearchManifest:
    def __init__(self, *, path: str = qpaths.RESEARCH_MANIFEST_FILE, run_id: str = ""):
        self.path = str(path)
        self.run_id = run_id or datetime.now().strftime("%Y%m%dT%H%M%S")

    def load(self) -> dict:
        try:
            payload = json.loads(Path(self.path).read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write(self, payload: dict) -> None:
        target = Path(self.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
                handle.write("\n")
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def start(self) -> None:
        now = datetime.now().isoformat()
        self._write({"schema_version": 1, "run_id": self.run_id, "state": "running", "generated_at": now, "started_at": now, "updated_at": now, "steps": {}, "error": ""})

    def step(self, name: str, progress_pct: int, detail: str, **metadata) -> None:
        payload = self.load() or {"run_id": self.run_id, "started_at": datetime.now().isoformat(), "steps": {}}
        now = datetime.now().isoformat()
        payload.update({"state": "running", "updated_at": now, "progress_pct": int(progress_pct), "detail": detail})
        payload.setdefault("steps", {})[name] = {"state": "completed", "completed_at": now, "detail": detail, **metadata}
        self._write(payload)

    def complete(self, *, summary=None) -> None:
        payload = self.load()
        payload.update({"state": "completed", "updated_at": datetime.now().isoformat(), "completed_at": datetime.now().isoformat(), "progress_pct": 100, "summary": dict(summary or {})})
        self._write(payload)

    def fail(self, error: Exception) -> None:
        payload = self.load()
        payload.update({"state": "failed", "updated_at": datetime.now().isoformat(), "error": f"{type(error).__name__}: {error}"})
        self._write(payload)
