from __future__ import annotations

import hashlib
import html
import io
import json
import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

from quant_core import paths as qpaths
from quant_core.models.multi_horizon import governance as mh_governance


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


def _read_json(path: str) -> dict:
    target = Path(str(path))
    if not target.is_file():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _checkpoint_metadata(path: str) -> dict:
    target = Path(str(path))
    if not target.is_file():
        return {}
    try:
        import torch

        payload = torch.load(str(target), map_location="cpu", weights_only=False)
    except Exception as exc:
        return {"error": str(exc), "path": str(target)}
    metadata = dict(payload.get("metadata", {}) or {})
    if not metadata and isinstance(payload.get("state_dict"), Mapping):
        metadata = {"checkpoint_format": "state_dict_only"}
    metadata["path"] = str(target)
    return metadata


def _fmt(value, *, pct: bool = False, digits: int = 3) -> str:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return "-"
    if not parsed == parsed or parsed in (float("inf"), float("-inf")):
        return "-"
    if pct:
        return f"{parsed * 100:.1f}%" if abs(parsed) <= 1 else f"{parsed:.1f}%"
    return f"{parsed:.{digits}f}"


def _text(value, fallback: str = "-") -> str:
    if value in (None, "", [], {}):
        return fallback
    return str(value)


def _horizon_metric_rows(validation: Mapping, metric: str) -> list[dict]:
    rows = []
    for horizon in list(validation.get("horizons", []) or []):
        key = str(horizon)
        rows.append(
            {
                "horizon": key,
                "candidate": dict(dict(validation.get("candidate", {}) or {}).get("horizons", {}) or {}).get(key, {}).get(metric),
                "scratch": dict(dict(validation.get("scratch", {}) or {}).get("horizons", {}) or {}).get(key, {}).get(metric),
                "baseline": dict(dict(validation.get("relative_strength_baseline", {}) or {}).get("horizons", {}) or {}).get(key, {}).get(metric),
            }
        )
    return rows


def _table(headers: Iterable[str], rows: Iterable[Iterable[str]]) -> str:
    header_html = "".join(f"<th>{html.escape(str(header))}</th>" for header in headers)
    row_html = []
    for row in rows:
        row_html.append("<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>")
    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(row_html)}</tbody></table>"


def _markdown_table(headers: Iterable[str], rows: Iterable[Iterable[str]]) -> str:
    headers = [str(header) for header in headers]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |")
    return "\n".join(lines)


def _svg_line_chart(series_by_name: Mapping[str, list[tuple[float, float]]], *, title: str, width: int = 760, height: int = 260) -> str:
    series = {}
    for name, values in dict(series_by_name or {}).items():
        points = []
        for x, y in list(values or []):
            try:
                parsed_x = float(x)
                parsed_y = float(y)
            except (TypeError, ValueError):
                continue
            if parsed_y == parsed_y:
                points.append((parsed_x, parsed_y))
        if points:
            series[str(name)] = points
    series = {name: values for name, values in series.items() if values}
    if not series:
        return f"<div class='empty-chart'>No chart data for {html.escape(title)}.</div>"
    xs = [x for values in series.values() for x, _ in values]
    ys = [y for values in series.values() for _, y in values]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    if min_x == max_x:
        max_x = min_x + 1
    if min_y == max_y:
        max_y = min_y + 1
    pad = 42
    colors = ["#0f766e", "#c2410c", "#2563eb", "#7c3aed", "#64748b"]

    def point(x, y):
        px = pad + (x - min_x) / (max_x - min_x) * (width - pad * 2)
        py = height - pad - (y - min_y) / (max_y - min_y) * (height - pad * 2)
        return px, py

    parts = [
        f"<svg viewBox='0 0 {width} {height}' class='chart' role='img' aria-label='{html.escape(title)}'>",
        f"<text x='18' y='24' class='chart-title'>{html.escape(title)}</text>",
        f"<line x1='{pad}' y1='{height-pad}' x2='{width-pad}' y2='{height-pad}' class='axis'/>",
        f"<line x1='{pad}' y1='{pad}' x2='{pad}' y2='{height-pad}' class='axis'/>",
        f"<text x='{pad}' y='{height-14}' class='tick'>epoch {int(min_x)}</text>",
        f"<text x='{width-pad-70}' y='{height-14}' class='tick'>epoch {int(max_x)}</text>",
        f"<text x='8' y='{pad+4}' class='tick'>{_fmt(max_y)}</text>",
        f"<text x='8' y='{height-pad}' class='tick'>{_fmt(min_y)}</text>",
    ]
    for index, (name, values) in enumerate(series.items()):
        color = colors[index % len(colors)]
        points = " ".join(f"{point(x, y)[0]:.1f},{point(x, y)[1]:.1f}" for x, y in values)
        parts.append(f"<polyline fill='none' stroke='{color}' stroke-width='3' points='{points}'/>")
        legend_x = width - pad - 150
        legend_y = pad + 18 + index * 20
        parts.append(f"<circle cx='{legend_x}' cy='{legend_y-4}' r='5' fill='{color}'/>")
        parts.append(f"<text x='{legend_x+12}' y='{legend_y}' class='legend'>{html.escape(name)}</text>")
    parts.append("</svg>")
    return "".join(parts)


def _training_histories(snapshot: Mapping, checkpoint_metadata: Mapping, pretrain_metadata: Mapping) -> dict:
    training = dict(snapshot.get("training", {}) or {})
    final_history = list(training.get("epoch_history") or checkpoint_metadata.get("epoch_history") or [])
    pretraining = dict(training.get("pretraining", {}) or {})
    pretrain_history = list(pretraining.get("epoch_history") or pretrain_metadata.get("epoch_history") or [])
    return {
        "final": [dict(row or {}) for row in final_history],
        "pretrain": [dict(row or {}) for row in pretrain_history],
    }


def _report_context(*, files: Mapping[str, str] | None = None) -> dict:
    selected_files = dict(files or default_training_bundle_files())
    snapshot = _read_json(selected_files.get("reports/multi_horizon_snapshot.json", qpaths.MULTI_HORIZON_SNAPSHOT_FILE))
    validation = _read_json(selected_files.get("reports/multi_horizon_validation.json", qpaths.MULTI_HORIZON_VALIDATION_FILE))
    governance = _read_json(selected_files.get("reports/multi_horizon_governance.json", qpaths.MULTI_HORIZON_GOVERNANCE_FILE))
    config = _read_json(selected_files.get("config/multi_horizon_model.json", qpaths.MULTI_HORIZON_MODEL_CONFIG_FILE))
    candidate_metadata = _checkpoint_metadata(selected_files.get("models/candidate.pt", qpaths.MULTI_HORIZON_CHECKPOINT_FILE))
    pretrain_metadata = _checkpoint_metadata(selected_files.get("models/pretraining.pt", qpaths.MULTI_HORIZON_PRETRAIN_CHECKPOINT_FILE))
    blockers = list(governance.get("promotion_blockers", []) or mh_governance.promotion_blockers(validation))
    return {
        "created_at": datetime.now().isoformat(),
        "snapshot": snapshot,
        "validation": validation,
        "governance": governance,
        "config": config,
        "candidate_metadata": candidate_metadata,
        "pretrain_metadata": pretrain_metadata,
        "promotion_blockers": blockers,
        "histories": _training_histories(snapshot, candidate_metadata, pretrain_metadata),
    }


def build_training_analysis_markdown(*, files: Mapping[str, str] | None = None) -> str:
    context = _report_context(files=files)
    snapshot = context["snapshot"]
    validation = context["validation"]
    governance = context["governance"]
    improvement = dict(governance.get("candidate_improvement", {}) or {})
    blockers = context["promotion_blockers"]
    histories = context["histories"]
    candidate_meta = context["candidate_metadata"]
    pretrain_meta = context["pretrain_metadata"]
    lines = [
        "# Multi-Horizon Training Analysis",
        "",
        f"Generated at: {context['created_at']}",
        "",
        "## Summary",
        "",
        _markdown_table(
            ["Field", "Value"],
            [
                ["Snapshot status", _text(snapshot.get("status"), "MISSING")],
                ["Validation status", _text(validation.get("status"), "PENDING")],
                ["Governance status", _text(governance.get("status"), "UNKNOWN")],
                ["Model version", _text(dict(snapshot.get("model", {}) or {}).get("version") or candidate_meta.get("version"))],
                ["Production authorized", _text(snapshot.get("production_authorized") or governance.get("production_authorized"))],
                ["Promotion basis", _text(governance.get("candidate_promotion_basis"))],
                ["Candidate quality", _fmt(governance.get("candidate_quality_score"))],
                ["Production quality", _fmt(governance.get("approved_model_quality_score") or improvement.get("approved_model_quality_score"))],
                ["Quality delta", _fmt(improvement.get("delta"))],
                ["Symbols", _text(dict(snapshot.get("summary", {}) or {}).get("symbol_count"))],
                ["Risk-free benchmark", _text(dict(snapshot.get("benchmarks", {}) or {}).get("risk_free"), "BIL")],
            ],
        ),
        "",
        "## Promotion Blockers",
        "",
    ]
    if blockers:
        for blocker in blockers:
            lines.append(f"- `{blocker.get('code')}`: {blocker.get('message')}")
    else:
        lines.append("- None. The candidate is eligible for manual promotion.")
    lines.extend(["", "## 252d Validation Metrics", ""])
    metrics = dict(dict(validation.get("governance", {}) or {}).get("promotion_metrics", {}) or {})
    lines.append(
        _markdown_table(
            ["Metric", "Value"],
            [
                ["Directional accuracy", _fmt(metrics.get("directional_accuracy"), pct=True)],
                ["Risk-free directional accuracy", _fmt(metrics.get("risk_free_directional_accuracy"), pct=True)],
                ["Brier score", _fmt(metrics.get("brier_score"))],
                ["Risk-free Brier score", _fmt(metrics.get("risk_free_brier_score"))],
                ["Median return MAE", _fmt(metrics.get("median_return_mae"), pct=True)],
                ["Rank IC", _fmt(metrics.get("candidate_rank_ic"))],
                ["Top 3 vs BIL", _fmt(metrics.get("candidate_top_k_risk_free_excess_return"), pct=True)],
                ["Top 3 vs SPY", _fmt(metrics.get("candidate_top_k_excess_return"), pct=True)],
                ["Baseline Top 3 vs SPY", _fmt(metrics.get("baseline_top_k_excess_return"), pct=True)],
            ],
        )
    )
    lines.extend(["", "## Training Curves Data", ""])
    lines.append(f"- Pretraining epochs recorded: {len(histories['pretrain'])}")
    lines.append(f"- Final supervised epochs recorded: {len(histories['final'])}")
    lines.append(f"- Pretraining best epoch: {_text(pretrain_meta.get('best_epoch'))}")
    lines.append("")
    lines.append("The HTML report in this bundle renders the loss curves and validation tables visually.")
    return "\n".join(lines) + "\n"


def build_training_analysis_report_html(*, files: Mapping[str, str] | None = None) -> str:
    context = _report_context(files=files)
    snapshot = context["snapshot"]
    validation = context["validation"]
    governance = context["governance"]
    improvement = dict(governance.get("candidate_improvement", {}) or {})
    histories = context["histories"]
    blockers = context["promotion_blockers"]
    metrics = dict(dict(validation.get("governance", {}) or {}).get("promotion_metrics", {}) or {})
    gates = dict(dict(validation.get("governance", {}) or {}).get("promotion_gates", {}) or {})
    model = dict(snapshot.get("model", {}) or {})
    candidate_meta = context["candidate_metadata"]
    pretrain_meta = context["pretrain_metadata"]

    pretrain_chart = _svg_line_chart(
        {
            "train": [(row.get("epoch"), row.get("training_loss")) for row in histories["pretrain"]],
            "validation": [(row.get("epoch"), row.get("validation_loss")) for row in histories["pretrain"]],
            "best validation": [(row.get("epoch"), row.get("best_validation_loss")) for row in histories["pretrain"]],
        },
        title="Pretraining Reconstruction Loss",
    )
    final_chart = _svg_line_chart(
        {
            "total": [(row.get("epoch"), row.get("loss")) for row in histories["final"]],
            "quantile": [(row.get("epoch"), row.get("quantile_loss")) for row in histories["final"]],
            "positive": [(row.get("epoch"), row.get("positive_return_loss")) for row in histories["final"]],
            "BIL prob": [(row.get("epoch"), row.get("risk_free_outperformance_loss")) for row in histories["final"]],
        },
        title="Final Supervised Training Loss",
    )
    gate_rows = [
        [
            code,
            "PASS" if bool(value) else "REVIEW",
            mh_governance.PROMOTION_GATE_LABELS.get(code, ""),
        ]
        for code, value in gates.items()
    ]
    horizon_rows = []
    for row in _horizon_metric_rows(validation, "top_k_risk_free_excess_return"):
        horizon = row["horizon"]
        directional = _horizon_metric_rows(validation, "directional_accuracy")
        directional_row = next((item for item in directional if item["horizon"] == horizon), {})
        horizon_rows.append(
            [
                f"{horizon}d",
                _fmt(row.get("candidate"), pct=True),
                _fmt(row.get("scratch"), pct=True),
                _fmt(row.get("baseline"), pct=True),
                _fmt(directional_row.get("candidate"), pct=True),
                _fmt(
                    dict(dict(validation.get("candidate", {}) or {}).get("horizons", {}) or {})
                    .get(horizon, {})
                    .get("risk_free_directional_accuracy"),
                    pct=True,
                ),
            ]
        )
    blocker_items = "".join(
        f"<li><code>{html.escape(str(item.get('code')))}</code> {html.escape(str(item.get('message')))}</li>"
        for item in blockers
    ) or "<li>No blockers. Candidate is eligible for manual promotion.</li>"
    llm_note = (
        "This report is deterministic and offline-safe. For longer narrative review, "
        "send this HTML/JSON bundle to the configured remote LLM from the app."
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Quant Training Analysis</title>
  <style>
    :root {{ color-scheme: light; --ink:#0f172a; --muted:#64748b; --line:#dbe3ec; --ok:#0f766e; --warn:#b45309; --bad:#b91c1c; --paper:#fffaf0; }}
    body {{ margin:0; font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--ink); background:#f6f8fb; }}
    main {{ max-width:1120px; margin:0 auto; padding:32px; }}
    header {{ padding:28px; border-radius:24px; background:linear-gradient(135deg,#0f766e,#155e75); color:white; box-shadow:0 18px 40px rgba(15,23,42,.14); }}
    h1 {{ margin:0 0 8px; font-size:30px; }}
    h2 {{ margin:0 0 14px; font-size:18px; }}
    .sub {{ color:#d7fffb; margin:0; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin:18px 0; }}
    .card {{ background:white; border:1px solid var(--line); border-radius:18px; padding:16px; box-shadow:0 10px 24px rgba(15,23,42,.06); }}
    .card small {{ display:block; color:var(--muted); text-transform:uppercase; font-weight:800; letter-spacing:.08em; }}
    .card b {{ display:block; margin-top:6px; font-size:20px; }}
    section {{ margin-top:18px; background:white; border:1px solid var(--line); border-radius:22px; padding:20px; box-shadow:0 10px 24px rgba(15,23,42,.05); }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{ text-align:left; border-bottom:1px solid var(--line); padding:9px 8px; vertical-align:top; }}
    th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.07em; }}
    code {{ background:#eef6f4; color:#115e59; padding:2px 5px; border-radius:6px; }}
    .status-pass {{ color:var(--ok); font-weight:800; }}
    .status-review {{ color:var(--warn); font-weight:800; }}
    .chart {{ width:100%; height:auto; background:#fbfcfd; border:1px solid var(--line); border-radius:16px; margin-top:8px; }}
    .axis {{ stroke:#94a3b8; stroke-width:1; }}
    .tick,.legend {{ fill:#64748b; font-size:12px; }}
    .chart-title {{ fill:#0f172a; font-size:16px; font-weight:800; }}
    .empty-chart {{ padding:28px; background:#fbfcfd; border:1px dashed var(--line); border-radius:16px; color:var(--muted); }}
    .two {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
    @media (max-width:900px) {{ .grid,.two {{ grid-template-columns:1fr; }} main {{ padding:16px; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>Quant Training Analysis</h1>
    <p class="sub">Readable model-quality report generated at {html.escape(context["created_at"])}.</p>
  </header>
  <div class="grid">
    <div class="card"><small>Snapshot</small><b>{html.escape(_text(snapshot.get("status"), "MISSING"))}</b></div>
    <div class="card"><small>Validation</small><b>{html.escape(_text(validation.get("status"), "PENDING"))}</b></div>
    <div class="card"><small>Governance</small><b>{html.escape(_text(governance.get("status"), "UNKNOWN"))}</b></div>
    <div class="card"><small>Symbols</small><b>{html.escape(_text(dict(snapshot.get("summary", {}) or {}).get("symbol_count"), "0"))}</b></div>
  </div>
  <section>
    <h2>Promotion Readiness</h2>
    <p>Validated promotion is enabled only when every gate passes. Manual warning deployment is still available in the UI for a READY candidate.</p>
    <ul>{blocker_items}</ul>
    {_table(["Gate", "State", "Meaning"], gate_rows)}
  </section>
  <section>
    <h2>Key 252d Metrics</h2>
    {_table(["Metric", "Value"], [
        ["Directional accuracy", _fmt(metrics.get("directional_accuracy"), pct=True)],
        ["Risk-free directional accuracy", _fmt(metrics.get("risk_free_directional_accuracy"), pct=True)],
        ["Brier score", _fmt(metrics.get("brier_score"))],
        ["Risk-free Brier score", _fmt(metrics.get("risk_free_brier_score"))],
        ["Median return MAE", _fmt(metrics.get("median_return_mae"), pct=True)],
        ["Rank IC", _fmt(metrics.get("candidate_rank_ic"))],
        ["Top 3 vs BIL", _fmt(metrics.get("candidate_top_k_risk_free_excess_return"), pct=True)],
        ["Top 3 vs SPY", _fmt(metrics.get("candidate_top_k_excess_return"), pct=True)],
        ["Baseline Top 3 vs SPY", _fmt(metrics.get("baseline_top_k_excess_return"), pct=True)],
    ])}
  </section>
  <section>
    <h2>Horizon Comparison</h2>
    {_table(["Horizon", "Candidate Top 3 vs BIL", "Scratch Top 3 vs BIL", "Baseline Top 3 vs SPY", "Candidate Up Accuracy", "Candidate BIL Accuracy"], horizon_rows)}
  </section>
  <div class="two">
    <section><h2>Pretraining Curve</h2>{pretrain_chart}</section>
    <section><h2>Final Training Curve</h2>{final_chart}</section>
  </div>
  <section>
    <h2>Model Metadata</h2>
    {_table(["Field", "Value"], [
        ["Model ID", _text(model.get("model_id") or candidate_meta.get("model_id"))],
        ["Version", _text(model.get("version") or candidate_meta.get("version"))],
        ["Promotion basis", _text(governance.get("candidate_promotion_basis"))],
        ["Candidate quality", _fmt(governance.get("candidate_quality_score"))],
        ["Production quality", _fmt(governance.get("approved_model_quality_score") or improvement.get("approved_model_quality_score"))],
        ["Quality delta", _fmt(improvement.get("delta"))],
        ["Risk-free benchmark", _text(dict(snapshot.get("benchmarks", {}) or {}).get("risk_free") or dict(candidate_meta.get("target_definition", {}) or {}).get("risk_free_benchmark"), "BIL")],
        ["Pretraining loaded", _text(dict(candidate_meta.get("pretraining", {}) or {}).get("loaded"))],
        ["Pretraining best epoch", _text(pretrain_meta.get("best_epoch"))],
        ["Final epochs recorded", str(len(histories["final"]))],
        ["Pretraining epochs recorded", str(len(histories["pretrain"]))],
    ])}
  </section>
  <section>
    <h2>LLM Narrative</h2>
    <p>{html.escape(llm_note)}</p>
  </section>
</main>
</body>
</html>
"""


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
        archive.writestr("analysis/training_analysis.html", build_training_analysis_report_html(files=selected_files))
        archive.writestr("analysis/training_analysis.md", build_training_analysis_markdown(files=selected_files))
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
