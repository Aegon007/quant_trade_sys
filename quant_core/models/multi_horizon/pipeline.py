from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping, Sequence

import pandas as pd

from quant_core.analytics import quant_analysis as qa
from quant_core.data import storage as data_storage

from .config import load_multi_horizon_config, normalize_multi_horizon_config
from .bootstrap import install_bootstrap_checkpoint
from .dataset import build_panel_frame
from .network import MultiAssetTransformerConfig
from .pretraining import pretrain_temporal_encoder
from .runtime import run_multi_horizon_inference
from .snapshot import save_multi_horizon_snapshot
from .training import build_multi_asset_tensor_bundle, describe_compute_device, train_multi_asset_model
from .validation import walk_forward_validate_bundle


def _unique_symbols(values) -> list[str]:
    result = []
    seen = set()
    for value in values:
        symbol = str(value or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        result.append(symbol)
    return result


def _artifact_path(value: str) -> str:
    path = Path(str(value))
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[3] / path
    return str(path)


def build_model_universe(
    data: Mapping,
    *,
    core_universe: Mapping,
    satellite_universe: Mapping,
    universe_policy: Mapping | None = None,
    maximum_symbols: int = 100,
) -> list[str]:
    return build_model_universe_report(
        data,
        core_universe=core_universe,
        satellite_universe=satellite_universe,
        universe_policy=universe_policy,
        maximum_symbols=maximum_symbols,
    )["symbols"]


def build_model_universe_report(
    data: Mapping,
    *,
    core_universe: Mapping,
    satellite_universe: Mapping,
    universe_policy: Mapping | None = None,
    maximum_symbols: int = 100,
) -> dict:
    priority_symbols = [
        row.get("symbol")
        for row in list(dict(data or {}).get("holdings", []) or [])
    ]
    priority_symbols.extend(
        row.get("symbol")
        for row in list(dict(data or {}).get("watchlist", []) or [])
    )
    priority_symbols.extend(
        row.get("symbol")
        for row in list(dict(core_universe or {}).get("etfs", []) or [])
        if bool(dict(row or {}).get("enabled", True))
    )
    priority_symbols.extend(list(dict(satellite_universe or {}).get("manual_include", []) or []))
    excluded = {
        str(symbol or "").strip().upper()
        for symbol in list(dict(satellite_universe or {}).get("manual_exclude", []) or [])
    }
    policy = dict(universe_policy or {})
    tactical_symbols = {
        str(symbol or "").strip().upper()
        for symbol in list(policy.get("tactical_product_symbols", []) or [])
        if str(symbol or "").strip()
    }
    exclude_tactical = bool(policy.get("exclude_tactical_products_from_long_horizon", True))
    core_symbols = {
        str(dict(row or {}).get("symbol") or "").strip().upper()
        for row in list(dict(core_universe or {}).get("etfs", []) or [])
        if bool(dict(row or {}).get("enabled", True))
    }
    selected = []
    excluded_rows = []
    asset_groups = {}
    for symbol in _unique_symbols(priority_symbols):
        if symbol in excluded:
            excluded_rows.append({"symbol": symbol, "reason": "manual_exclude"})
            continue
        if exclude_tactical and symbol in tactical_symbols:
            excluded_rows.append({"symbol": symbol, "reason": "tactical_product"})
            continue
        selected.append(symbol)
        asset_groups[symbol] = "core_etf" if symbol in core_symbols else "satellite"
    selected = selected[: max(int(maximum_symbols), 2)]
    return {
        "symbols": selected,
        "asset_groups": {symbol: asset_groups[symbol] for symbol in selected},
        "excluded": excluded_rows,
        "requested_symbol_count": len(_unique_symbols(priority_symbols)),
    }


def build_benchmark_map(symbols: Sequence[str]) -> dict[str, str]:
    # Sector benchmarks can replace SPY as point-in-time sector data becomes
    # reliable. The fallback is explicit rather than silently inferred.
    return {str(symbol).strip().upper(): "SPY" for symbol in symbols}


def load_histories(
    symbols: Sequence[str],
    *,
    history_period: str,
    risk_free_symbol: str = "BIL",
    load_history_fn: Callable = qa.get_historical_data,
) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    histories = {}
    failures = []
    for symbol in _unique_symbols([*symbols, "SPY", risk_free_symbol]):
        try:
            frame = load_history_fn(symbol, period=history_period)
        except Exception as exc:
            failures.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if isinstance(frame, pd.DataFrame) and not frame.empty and "Close" in frame.columns:
            histories[symbol] = frame.sort_index()
        else:
            failures.append({"symbol": symbol, "error": "history unavailable"})
    return histories, failures


def summarize_history_failures(failures: Sequence[Mapping]) -> dict:
    counts = {}
    symbols = []
    for row in list(failures or []):
        item = dict(row or {})
        error = str(item.get("error") or "unknown error").strip()
        counts[error] = counts.get(error, 0) + 1
        symbol = str(item.get("symbol") or "").strip().upper()
        if symbol:
            symbols.append(symbol)
    grouped = [
        {"error": error, "count": count}
        for error, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {
        "failed_symbol_count": len(symbols),
        "symbols": symbols,
        "groups": grouped,
    }


def _load_default_universes():
    from quant_core.analytics import candidate_pool as candidate_pool
    from quant_core.analytics import core_etf_rotation

    return core_etf_rotation.load_core_etf_universe(), candidate_pool.load_satellite_universe()


def model_training_due(*, config: Mapping | None = None, now: datetime | None = None) -> bool:
    normalized = normalize_multi_horizon_config(config) if config is not None else load_multi_horizon_config()
    artifacts = dict(normalized.get("artifacts", {}) or {})
    checkpoint = Path(_artifact_path(str(artifacts["checkpoint_path"])))
    if not checkpoint.exists():
        install_bootstrap_checkpoint(
            runtime_path=str(checkpoint),
            bootstrap_path=_artifact_path(str(artifacts["bootstrap_checkpoint_path"])),
            manifest_path=_artifact_path(str(artifacts["bootstrap_manifest_path"])),
        )
    if not checkpoint.exists():
        return True
    interval_days = int(dict(normalized.get("training", {}) or {}).get("retrain_interval_days", 30))
    modified_at = datetime.fromtimestamp(checkpoint.stat().st_mtime)
    return (now or datetime.now()) - modified_at >= timedelta(days=max(interval_days, 1))


def build_satellite_snapshot_from_model(model_snapshot: Mapping | None) -> dict:
    model_snapshot = dict(model_snapshot or {})
    top = [dict(row or {}) for row in list(model_snapshot.get("satellite_top3", []) or [])]
    pool = [dict(row or {}) for row in list(model_snapshot.get("satellite_ranked_pool", []) or [])]
    status_counts = {}
    for row in pool:
        action = str(dict(row.get("decision", {}) or {}).get("action") or "WATCH").upper()
        status_counts[action] = status_counts.get(action, 0) + 1
    return {
        "schema_version": 2,
        "generated_at": model_snapshot.get("generated_at"),
        "source": "finance_multi_asset_transformer",
        "model": dict(model_snapshot.get("model", {}) or {}),
        "summary": {
            "scanned_symbols": int(dict(model_snapshot.get("summary", {}) or {}).get("symbol_count", 0) or 0),
            "candidate_count": len(pool),
            "deep_analysis_count": len(pool),
            "top_symbols": [str(row.get("symbol") or "").strip().upper() for row in top],
            "confirmed_count": status_counts.get("ACCUMULATE", 0),
            "probe_count": status_counts.get("PROBE", 0),
            "watch_count": status_counts.get("WATCH", 0) + status_counts.get("HOLD", 0),
            "overheated_count": sum(
                1 for row in pool if str(dict(row.get("timing", {}) or {}).get("state") or "").upper() == "EXTENDED"
            ),
        },
        "top_recommendations": top,
        "candidate_pool": pool,
        "symbols": pool,
    }


def _current_weights_pct(data: Mapping) -> dict[str, float]:
    holdings = list(dict(data or {}).get("holdings", []) or [])
    values = {}
    for row in holdings:
        item = dict(row or {})
        symbol = str(item.get("symbol") or "").strip().upper()
        try:
            shares = float(item.get("shares") or 0.0)
            price = float(item.get("current_price") or item.get("cost") or 0.0)
        except (TypeError, ValueError):
            continue
        values[symbol] = max(shares * price, 0.0)
    cash = dict(dict(data or {}).get("account", {}) or {}).get("cash_available")
    try:
        total = sum(values.values()) + max(float(cash or 0.0), 0.0)
    except (TypeError, ValueError):
        total = sum(values.values())
    if total <= 0:
        return {symbol: 0.0 for symbol in values}
    return {symbol: value / total * 100.0 for symbol, value in values.items()}


def _not_ready_snapshot(*, symbols, checkpoint_path: str, generated_at: datetime, reason: str) -> dict:
    return {
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "status": "MODEL_NOT_READY",
        "model": {
            "model_id": "finance_multi_asset_transformer",
            "status": "RESEARCH",
            "checkpoint_path": checkpoint_path,
        },
        "summary": {
            "symbol_count": len(symbols),
            "action_counts": {},
            "message": reason,
        },
        "symbols": [],
        "errors": [reason],
    }


def _save_panel(panel: pd.DataFrame, path: str) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(target, index=False)
    return str(target)


def _save_json(payload: Mapping, path: str) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return str(target)


def _emit_progress(callback, *, stage: str, detail: str, progress_pct: float, **metadata) -> None:
    if callback is None:
        return
    callback(
        {
            "stage": stage,
            "detail": detail,
            "progress_pct": round(float(progress_pct), 1),
            **metadata,
        }
    )


def _scaled_progress(callback, *, start: float, end: float, stage: str):
    if callback is None:
        return None

    def _report(event: Mapping) -> None:
        payload = dict(event or {})
        local = float(payload.pop("progress_pct", 0.0) or 0.0)
        detail = str(payload.pop("detail", "") or stage)
        payload.pop("stage", None)
        _emit_progress(
            callback,
            stage=stage,
            detail=detail,
            progress_pct=start + (end - start) * min(max(local, 0.0), 100.0) / 100.0,
            **payload,
        )

    return _report


def _model_config(config: Mapping) -> MultiAssetTransformerConfig:
    architecture = dict(config.get("architecture", {}) or {})
    return MultiAssetTransformerConfig(
        feature_count=15,
        horizon_count=len(config["horizons"]),
        d_model=int(architecture.get("d_model", 64)),
        temporal_layers=int(architecture.get("temporal_layers", 2)),
        cross_asset_layers=int(architecture.get("cross_asset_layers", 2)),
        attention_heads=int(architecture.get("attention_heads", 4)),
        feedforward_multiplier=int(architecture.get("feedforward_multiplier", 4)),
        dropout=float(architecture.get("dropout", 0.1)),
        patch_size=int(architecture.get("patch_size", 10)),
        patch_stride=int(architecture.get("patch_stride", 5)),
        expert_count=int(architecture.get("expert_count", 4)),
        top_k_experts=int(architecture.get("top_k_experts", 2)),
    )


def run_multi_horizon_job(
    *,
    config: Mapping | None = None,
    data: Mapping | None = None,
    core_universe: Mapping | None = None,
    satellite_universe: Mapping | None = None,
    train: bool = False,
    load_history_fn: Callable = qa.get_historical_data,
    risk_regime: str = "NORMAL",
    now: datetime | None = None,
    progress_callback: Callable[[Mapping], None] | None = None,
) -> dict:
    now = now or datetime.now()
    _emit_progress(
        progress_callback,
        stage="preparing",
        detail="Reading model configuration and building the training universe",
        progress_pct=1,
    )
    normalized = normalize_multi_horizon_config(config) if config is not None else load_multi_horizon_config()
    device_info = describe_compute_device(
        str(dict(normalized.get("training", {}) or {}).get("device", "auto"))
    )
    _emit_progress(
        progress_callback,
        stage="runtime_ready",
        detail=f"Compute device: {device_info['label']}",
        progress_pct=2,
        device=device_info["device"],
        accelerator=device_info["accelerator"],
        device_label=device_info["label"],
        torch_version=device_info["torch_version"],
        torch_cuda_version=device_info["torch_cuda_version"],
        cuda_available=device_info["cuda_available"],
        fallback_reason=device_info["fallback_reason"],
    )
    risk_free_symbol = str(normalized.get("risk_free_benchmark") or "BIL").strip().upper()
    artifacts = dict(normalized.get("artifacts", {}) or {})
    candidate_checkpoint_path = _artifact_path(str(artifacts["checkpoint_path"]))
    production_checkpoint_path = _artifact_path(
        str(artifacts.get("production_checkpoint_path") or candidate_checkpoint_path)
    )
    checkpoint_path = (
        production_checkpoint_path
        if not train and Path(production_checkpoint_path).exists()
        else candidate_checkpoint_path
    )
    snapshot_path = _artifact_path(str(artifacts["snapshot_path"]))
    if not bool(normalized.get("enabled", True)):
        snapshot = _not_ready_snapshot(
            symbols=[],
            checkpoint_path=checkpoint_path,
            generated_at=now,
            reason="Multi-horizon model is disabled.",
        )
        save_multi_horizon_snapshot(snapshot, path=snapshot_path)
        _emit_progress(
            progress_callback,
            stage="disabled",
            detail="Multi-horizon model is disabled",
            progress_pct=100,
        )
        return snapshot

    data = dict(data or data_storage.load_data())
    if core_universe is None or satellite_universe is None:
        default_core, default_satellite = _load_default_universes()
        core_universe = default_core if core_universe is None else core_universe
        satellite_universe = default_satellite if satellite_universe is None else satellite_universe
    universe_report = build_model_universe_report(
        data,
        core_universe=dict(core_universe or {}),
        satellite_universe=dict(satellite_universe or {}),
        universe_policy=dict(normalized.get("universe_policy", {}) or {}),
        maximum_symbols=int(normalized["maximum_training_symbols"]),
    )
    symbols = list(universe_report["symbols"])
    _emit_progress(
        progress_callback,
        stage="universe_ready",
        detail=f"Training universe contains {len(symbols)} symbols",
        progress_pct=5,
        symbol_count=len(symbols),
    )
    bootstrap_result = {"status": "SKIPPED"}
    if not train and not Path(checkpoint_path).exists():
        try:
            bootstrap_result = install_bootstrap_checkpoint(
                runtime_path=checkpoint_path,
                bootstrap_path=_artifact_path(str(artifacts["bootstrap_checkpoint_path"])),
                manifest_path=_artifact_path(str(artifacts["bootstrap_manifest_path"])),
            )
        except ValueError as exc:
            snapshot = _not_ready_snapshot(
                symbols=symbols,
                checkpoint_path=checkpoint_path,
                generated_at=now,
                reason=str(exc),
            )
            snapshot["bootstrap"] = {"status": "INVALID", "error": str(exc)}
            save_multi_horizon_snapshot(snapshot, path=snapshot_path)
            return snapshot
    if not train and not Path(checkpoint_path).exists():
        snapshot = _not_ready_snapshot(
            symbols=symbols,
            checkpoint_path=checkpoint_path,
            generated_at=now,
            reason="No trained multi-horizon checkpoint. Run model training from Research & Models.",
        )
        snapshot["bootstrap"] = bootstrap_result
        save_multi_horizon_snapshot(snapshot, path=snapshot_path)
        _emit_progress(
            progress_callback,
            stage="not_ready",
            detail="No trained checkpoint is available",
            progress_pct=100,
        )
        return snapshot

    _emit_progress(
        progress_callback,
        stage="loading_history",
        detail=f"Loading {normalized['history_period']} of history for {len(symbols)} symbols",
        progress_pct=7,
        symbol_count=len(symbols),
    )
    histories, failures = load_histories(
        symbols,
        history_period=str(normalized["history_period"]),
        risk_free_symbol=risk_free_symbol,
        load_history_fn=load_history_fn,
    )
    usable_symbols = [symbol for symbol in symbols if symbol in histories]
    _emit_progress(
        progress_callback,
        stage="history_ready",
        detail=f"Loaded {len(usable_symbols)} symbols; {len(failures)} failed",
        progress_pct=15,
        usable_symbol_count=len(usable_symbols),
        failed_symbol_count=len(failures),
    )
    benchmark_map = build_benchmark_map(usable_symbols)
    if len(usable_symbols) < 2 or "SPY" not in histories or risk_free_symbol not in histories:
        snapshot = _not_ready_snapshot(
            symbols=symbols,
            checkpoint_path=checkpoint_path,
            generated_at=now,
            reason=(
                "At least two usable asset histories plus SPY and "
                f"{risk_free_symbol} are required."
            ),
        )
        snapshot["data_failures"] = failures
        save_multi_horizon_snapshot(snapshot, path=snapshot_path)
        _emit_progress(
            progress_callback,
            stage="not_ready",
            detail="Insufficient usable history for multi-asset training",
            progress_pct=100,
        )
        return snapshot

    training_result = None
    if train:
        _emit_progress(
            progress_callback,
            stage="building_panel",
            detail="Building leakage-safe weekly panel and forward labels",
            progress_pct=17,
        )
        panel = build_panel_frame(
            histories,
            benchmark_map=benchmark_map,
            symbols=usable_symbols,
            horizons=normalized["horizons"],
            observation_frequency=str(normalized["observation_frequency"]),
            risk_free_symbol=risk_free_symbol,
        )
        panel_path = _save_panel(panel, _artifact_path(str(artifacts["panel_path"])))
        _emit_progress(
            progress_callback,
            stage="building_tensors",
            detail=f"Panel ready with {len(panel)} rows; building model tensors",
            progress_pct=21,
            panel_rows=len(panel),
        )
        bundle = build_multi_asset_tensor_bundle(
            histories,
            symbols=usable_symbols,
            benchmark_map=benchmark_map,
            horizons=normalized["horizons"],
            lookback=int(normalized["lookback"]),
            observation_frequency=str(normalized["observation_frequency"]),
            risk_free_symbol=risk_free_symbol,
        )
        _emit_progress(
            progress_callback,
            stage="validating",
            detail=f"Tensor bundle ready with {len(bundle.observation_dates)} observations",
            progress_pct=25,
            sample_count=len(bundle.observation_dates),
            device=str(dict(normalized.get("training", {}) or {}).get("device", "auto")),
        )
        network_config = _model_config(normalized)
        training = dict(normalized.get("training", {}) or {})
        sample_count = len(bundle.observation_dates)
        test_periods = max(min(26, sample_count // 6), 4)
        embargo_periods = max(int(max(normalized["horizons"]) / 5), 1)
        train_periods = max(sample_count - embargo_periods - test_periods * 3, test_periods * 2)
        validation_result = walk_forward_validate_bundle(
            bundle,
            config=network_config,
            train_periods=train_periods,
            test_periods=test_periods,
            embargo_periods=embargo_periods,
            epochs=int(training["walk_forward_epochs"]),
            batch_size=int(training["batch_size"]),
            learning_rate=float(training["learning_rate"]),
            weight_decay=float(training["weight_decay"]),
            device=str(training["device"]),
            top_k=3,
            max_folds=3,
            compare_pretraining=True,
            initialization_policy=str(training.get("initialization_policy", "auto_long_horizon")),
            asset_groups={
                symbol: str(universe_report["asset_groups"].get(symbol) or "satellite")
                for symbol in usable_symbols
            },
            progress_callback=_scaled_progress(
                progress_callback,
                start=25,
                end=65,
                stage="walk_forward_validation",
            ),
        )
        validation_result["generated_at"] = now.isoformat()
        validation_result["model_id"] = normalized["model_id"]
        validation_result["universe"] = {
            "asset_groups": {
                symbol: universe_report["asset_groups"].get(symbol)
                for symbol in usable_symbols
            },
            "excluded": list(universe_report["excluded"]),
        }
        validation_path = _save_json(validation_result, _artifact_path(str(artifacts["validation_path"])))
        pretraining_path = _artifact_path(str(artifacts["pretraining_checkpoint_path"]))
        _emit_progress(
            progress_callback,
            stage="pretraining",
            detail="Starting full-universe masked-patch pretraining",
            progress_pct=67,
        )
        pretraining_result = pretrain_temporal_encoder(
            bundle,
            config=network_config,
            epochs=int(training["pretraining_epochs"]),
            batch_size=int(training["batch_size"]),
            learning_rate=float(training["learning_rate"]),
            validation_fraction=float(training["pretraining_validation_fraction"]),
            minimum_epochs=int(training["pretraining_minimum_epochs"]),
            early_stopping_patience=int(training["pretraining_early_stopping_patience"]),
            early_stopping_min_delta=float(training["pretraining_early_stopping_min_delta"]),
            device=str(training["device"]),
            checkpoint_path=pretraining_path,
            progress_callback=_scaled_progress(
                progress_callback,
                start=67,
                end=76,
                stage="pretraining",
            ),
        )
        _emit_progress(
            progress_callback,
            stage="supervised_training",
            detail="Starting final multi-horizon supervised training",
            progress_pct=78,
            device=pretraining_result.get("device"),
        )
        training_result = train_multi_asset_model(
            bundle,
            config=network_config,
            epochs=int(training["epochs"]),
            batch_size=int(training["batch_size"]),
            learning_rate=float(training["learning_rate"]),
            weight_decay=float(training["weight_decay"]),
            device=str(training["device"]),
            checkpoint_path=candidate_checkpoint_path,
            pretrained_checkpoint_path=(
                pretraining_path
                if str(dict(validation_result.get("selection", {}) or {}).get("initialization"))
                == "pretrained"
                else None
            ),
            progress_callback=_scaled_progress(
                progress_callback,
                start=78,
                end=96,
                stage="supervised_training",
            ),
        )
        checkpoint_path = candidate_checkpoint_path
        training_result["pretraining"] = pretraining_result
        training_result["final_initialization"] = (
            "pretrained"
            if training_result.get("pretraining_loaded")
            else "scratch_selected_by_walk_forward"
        )
        training_result["panel_path"] = panel_path
        training_result["validation_path"] = validation_path
        training_result["validation_status"] = validation_result["status"]

    _emit_progress(
        progress_callback,
        stage="inference",
        detail="Generating the latest portfolio and candidate predictions",
        progress_pct=97,
    )
    snapshot = run_multi_horizon_inference(
        histories,
        symbols=usable_symbols,
        benchmark_map=benchmark_map,
        current_weights_pct=_current_weights_pct(data),
        risk_regime=risk_regime,
        checkpoint_path=checkpoint_path,
        device=str(dict(normalized.get("training", {}) or {}).get("device", "auto")),
    )
    snapshot["benchmarks"] = {
        "risk_free": risk_free_symbol,
        "market": "SPY",
    }
    holding_symbols = {
        str(row.get("symbol") or "").strip().upper()
        for row in list(data.get("holdings", []) or [])
    }
    watchlist_symbols = {
        str(row.get("symbol") or "").strip().upper()
        for row in list(data.get("watchlist", []) or [])
    }
    core_symbols = {
        str(row.get("symbol") or "").strip().upper()
        for row in list(dict(core_universe or {}).get("etfs", []) or [])
        if bool(dict(row or {}).get("enabled", True))
    }
    weight_map = _current_weights_pct(data)
    for row in list(snapshot.get("symbols", []) or []):
        symbol = str(row.get("symbol") or "").strip().upper()
        history = histories.get(symbol)
        row["latest_price"] = (
            float(history["Close"].dropna().iloc[-1])
            if isinstance(history, pd.DataFrame) and not history.empty
            else None
        )
        row["current_weight_pct"] = float(weight_map.get(symbol, 0.0))
        row["list_type"] = (
            "holding"
            if symbol in holding_symbols
            else "watchlist"
            if symbol in watchlist_symbols
            else "candidate_pool"
        )
        row["model_id"] = dict(snapshot.get("model", {}) or {}).get("model_id")
    satellite_candidates = [
        row
        for row in list(snapshot.get("symbols", []) or [])
        if str(row.get("symbol") or "").strip().upper() not in core_symbols
        and str(row.get("symbol") or "").strip().upper() not in holding_symbols
    ]
    satellite_candidates.sort(
        key=lambda row: (
            float(
                dict(row.get("long_horizon", {}) or {}).get(
                    "risk_free_outperformance_probability"
                )
                or 0.0
            ),
            float(dict(row.get("long_horizon", {}) or {}).get("expected_return") or 0.0),
            float(dict(row.get("long_horizon", {}) or {}).get("blended_rank") or 0.0),
        ),
        reverse=True,
    )
    satellite_top3 = satellite_candidates[:3]
    top3_symbols = {str(row.get("symbol") or "").strip().upper() for row in satellite_top3}
    for row in satellite_candidates:
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol in top3_symbols:
            row["satellite_rank"] = 1 + next(
                index
                for index, candidate in enumerate(satellite_top3)
                if str(candidate.get("symbol") or "").strip().upper() == symbol
            )
            continue
        decision = dict(row.get("decision", {}) or {})
        if str(decision.get("action") or "").upper() in {"ACCUMULATE", "PROBE"}:
            decision["action"] = "WATCH"
            decision["target_weight_range_pct"] = [0.0, 0.0]
            decision["reason_codes"] = [
                *list(decision.get("reason_codes", []) or []),
                "OUTSIDE_SATELLITE_TOP3",
            ]
            row["decision"] = decision
    snapshot["core_etfs"] = [
        row
        for row in list(snapshot.get("symbols", []) or [])
        if str(row.get("symbol") or "").strip().upper() in core_symbols
    ]
    snapshot["satellite_top3"] = satellite_top3
    snapshot["satellite_ranked_pool"] = satellite_candidates
    snapshot["summary"]["top_satellite_symbols"] = [
        str(row.get("symbol") or "").strip().upper() for row in satellite_top3
    ]
    snapshot["summary"]["action_counts"] = {}
    for row in list(snapshot.get("symbols", []) or []):
        action = str(dict(row.get("decision", {}) or {}).get("action") or "UNKNOWN")
        snapshot["summary"]["action_counts"][action] = snapshot["summary"]["action_counts"].get(action, 0) + 1
    snapshot["status"] = "READY"
    snapshot["data_quality"] = {
        "requested_symbol_count": len(symbols),
        "usable_symbol_count": len(usable_symbols),
        "failed_symbol_count": len(failures),
        "failures": failures,
        "failure_summary": summarize_history_failures(failures),
        "excluded_from_long_horizon": list(universe_report["excluded"]),
    }
    snapshot["universe"] = {
        "asset_groups": {
            symbol: universe_report["asset_groups"].get(symbol)
            for symbol in usable_symbols
        },
        "excluded": list(universe_report["excluded"]),
    }
    if not train:
        snapshot["bootstrap"] = bootstrap_result
    if training_result:
        snapshot["training"] = training_result
    save_multi_horizon_snapshot(snapshot, path=snapshot_path)
    _emit_progress(
        progress_callback,
        stage="completed",
        detail=f"Training and inference complete for {len(usable_symbols)} symbols",
        progress_pct=100,
        symbol_count=len(usable_symbols),
        checkpoint_path=checkpoint_path,
    )
    return snapshot
