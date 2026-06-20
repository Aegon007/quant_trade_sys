from __future__ import annotations

import hashlib
import io
import json
import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Mapping

from quant_core import paths as qpaths


def default_training_bundle_files() -> dict[str, str]:
    return {
        "data/multi_horizon_panel.parquet": qpaths.MULTI_HORIZON_PANEL_FILE,
        "reports/multi_horizon_validation.json": qpaths.MULTI_HORIZON_VALIDATION_FILE,
        "reports/multi_horizon_snapshot.json": qpaths.MULTI_HORIZON_SNAPSHOT_FILE,
        "reports/multi_horizon_governance.json": qpaths.MULTI_HORIZON_GOVERNANCE_FILE,
        "reports/job_status.json": qpaths.JOB_STATUS_FILE,
        "config/multi_horizon_model.json": qpaths.MULTI_HORIZON_MODEL_CONFIG_FILE,
        "models/candidate.pt": qpaths.MULTI_HORIZON_CHECKPOINT_FILE,
        "models/pretraining.pt": qpaths.MULTI_HORIZON_PRETRAIN_CHECKPOINT_FILE,
        "models/production.pt": qpaths.MULTI_HORIZON_PRODUCTION_CHECKPOINT_FILE,
    }


def _runtime_environment() -> dict:
    payload = {
        "created_at": datetime.now().isoformat(),
        "python_version": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
    }
    try:
        import torch

        payload["torch"] = {
            "version": str(torch.__version__),
            "cuda_build": str(torch.version.cuda or ""),
            "cuda_available": bool(torch.cuda.is_available()),
            "gpu_name": (
                torch.cuda.get_device_name(0)
                if torch.cuda.is_available()
                else None
            ),
        }
    except Exception as exc:
        payload["torch"] = {"available": False, "error": str(exc)}
    return payload


def build_training_analysis_bundle(
    *,
    files: Mapping[str, str] | None = None,
) -> bytes:
    selected_files = dict(files or default_training_bundle_files())
    included = []
    missing = []
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        environment = _runtime_environment()
        archive.writestr(
            "runtime_environment.json",
            json.dumps(environment, ensure_ascii=False, indent=2),
        )
        for archive_name, raw_path in selected_files.items():
            path = Path(str(raw_path))
            if not path.is_file():
                missing.append({"archive_name": archive_name, "path": str(path)})
                continue
            content = path.read_bytes()
            archive.writestr(str(archive_name), content)
            included.append(
                {
                    "archive_name": str(archive_name),
                    "source_name": path.name,
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        manifest = {
            "schema_version": 1,
            "created_at": datetime.now().isoformat(),
            "purpose": "Offline model-quality analysis and reproducibility",
            "privacy": {
                "contains_portfolio": False,
                "contains_transactions": False,
                "contains_notification_secrets": False,
            },
            "included": included,
            "missing": missing,
        }
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
    return output.getvalue()
