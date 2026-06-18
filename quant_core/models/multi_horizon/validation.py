from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


def purged_walk_forward_splits(
    dates: Iterable,
    *,
    train_periods: int,
    test_periods: int,
    embargo_periods: int,
    step_periods: int | None = None,
):
    unique_dates = pd.Index(pd.to_datetime(list(dates))).drop_duplicates().sort_values()
    train_periods = max(int(train_periods), 1)
    test_periods = max(int(test_periods), 1)
    embargo_periods = max(int(embargo_periods), 0)
    step_periods = max(int(step_periods or test_periods), 1)
    splits = []
    test_start = train_periods + embargo_periods
    while test_start + test_periods <= len(unique_dates):
        train_end = test_start - embargo_periods
        train_start = max(0, train_end - train_periods)
        train_indices = np.arange(train_start, train_end, dtype=int)
        test_indices = np.arange(test_start, test_start + test_periods, dtype=int)
        splits.append((train_indices, test_indices))
        test_start += step_periods
    return splits


def rank_information_coefficient(predictions, targets) -> float | None:
    frame = pd.DataFrame({"prediction": predictions, "target": targets}).dropna()
    if len(frame) < 3:
        return None
    value = frame["prediction"].rank().corr(frame["target"].rank())
    return None if pd.isna(value) else float(value)


def top_k_excess_return(predictions, targets, *, k: int = 3) -> float | None:
    frame = pd.DataFrame({"prediction": predictions, "target": targets}).dropna()
    if frame.empty:
        return None
    selected = frame.nlargest(max(int(k), 1), "prediction")
    return float(selected["target"].mean())


def evaluate_prediction_arrays(
    *,
    rank_scores,
    targets,
    quantiles,
    expert_weights,
    asset_mask,
    horizons,
    top_k: int = 3,
) -> dict:
    rank_scores = np.asarray(rank_scores, dtype=float)
    targets = np.asarray(targets, dtype=float)
    quantiles = np.asarray(quantiles, dtype=float)
    expert_weights = np.asarray(expert_weights, dtype=float)
    asset_mask = np.asarray(asset_mask, dtype=bool)
    horizon_values = tuple(int(value) for value in horizons)
    horizon_reports = {}
    for horizon_index, horizon in enumerate(horizon_values):
        daily_ics = []
        daily_top_k = []
        for sample_index in range(rank_scores.shape[0]):
            valid = asset_mask[sample_index] & np.isfinite(targets[sample_index, :, horizon_index])
            if int(valid.sum()) < 2:
                continue
            score = rank_scores[sample_index, valid, horizon_index]
            target = targets[sample_index, valid, horizon_index]
            ic = rank_information_coefficient(score, target)
            top_return = top_k_excess_return(score, target, k=top_k)
            if ic is not None:
                daily_ics.append(ic)
            if top_return is not None:
                daily_top_k.append(top_return)
        horizon_reports[str(horizon)] = {
            "rank_ic": float(np.mean(daily_ics)) if daily_ics else None,
            "top_k_excess_return": float(np.mean(daily_top_k)) if daily_top_k else None,
            "sample_count": len(daily_top_k),
        }

    expanded_mask = asset_mask[..., None] & np.isfinite(targets)
    observed = targets[expanded_mask]
    p10 = quantiles[..., 0][expanded_mask]
    p50 = quantiles[..., 1][expanded_mask]
    p90 = quantiles[..., 2][expanded_mask]
    valid_experts = expert_weights[asset_mask]
    expert_usage = valid_experts.mean(axis=0) if len(valid_experts) else np.asarray([])
    collapsed = bool(
        len(expert_usage)
        and (
            float(expert_usage.max()) >= 0.90
            or int((expert_usage >= 0.05).sum()) <= 1
        )
    )
    return {
        "horizons": horizon_reports,
        "quantile_coverage": {
            "p10": float(np.mean(observed <= p10)) if len(observed) else None,
            "p50": float(np.mean(observed <= p50)) if len(observed) else None,
            "p90": float(np.mean(observed <= p90)) if len(observed) else None,
        },
        "quantile_interval_coverage": float(np.mean((observed >= p10) & (observed <= p90))) if len(observed) else None,
        "moe": {
            "expert_usage": [float(value) for value in expert_usage],
            "collapsed": collapsed,
        },
    }


def _subset_bundle(bundle, indices):
    from .training import MultiAssetTensorBundle

    positions = np.asarray(indices, dtype=int)
    return MultiAssetTensorBundle(
        sequences=bundle.sequences[positions],
        market_context=bundle.market_context[positions],
        asset_mask=bundle.asset_mask[positions],
        excess_returns=bundle.excess_returns[positions],
        favorable_excursion=bundle.favorable_excursion[positions],
        adverse_excursion=bundle.adverse_excursion[positions],
        timing_targets=bundle.timing_targets[positions],
        observation_dates=tuple(bundle.observation_dates[index] for index in positions),
        symbols=bundle.symbols,
        horizons=bundle.horizons,
        feature_columns=bundle.feature_columns,
    )


def _predict_bundle(model, bundle, metadata, *, device):
    import torch

    mean = np.asarray(metadata["feature_mean"], dtype=np.float32).reshape(1, 1, 1, -1)
    std = np.asarray(metadata["feature_std"], dtype=np.float32).reshape(1, 1, 1, -1)
    scaled = (bundle.sequences - mean) / np.where(std < 1e-6, 1.0, std)
    resolved = next(model.parameters()).device
    with torch.no_grad():
        outputs = model(
            torch.tensor(scaled, dtype=torch.float32, device=resolved),
            market_context=torch.tensor(bundle.market_context, dtype=torch.float32, device=resolved),
            asset_mask=torch.tensor(bundle.asset_mask, dtype=torch.bool, device=resolved),
        )
    return {
        key: value.detach().cpu().numpy()
        for key, value in outputs.items()
        if key != "representation"
    }


def _aggregate_fold_reports(fold_reports, *, horizons):
    result = {"horizons": {}}
    for horizon in horizons:
        rows = [
            dict(dict(report.get("horizons", {}) or {}).get(str(horizon), {}) or {})
            for report in fold_reports
        ]
        result["horizons"][str(horizon)] = {
            "rank_ic": _finite_mean([row.get("rank_ic") for row in rows]),
            "top_k_excess_return": _finite_mean([row.get("top_k_excess_return") for row in rows]),
            "fold_count": len([row for row in rows if row.get("rank_ic") is not None]),
        }
    result["quantile_coverage"] = {
        label: _finite_mean([
            dict(report.get("quantile_coverage", {}) or {}).get(label)
            for report in fold_reports
        ])
        for label in ("p10", "p50", "p90")
    }
    result["quantile_interval_coverage"] = _finite_mean(
        [report.get("quantile_interval_coverage") for report in fold_reports]
    )
    usages = [
        np.asarray(dict(report.get("moe", {}) or {}).get("expert_usage", []), dtype=float)
        for report in fold_reports
        if dict(report.get("moe", {}) or {}).get("expert_usage")
    ]
    mean_usage = np.mean(np.stack(usages), axis=0) if usages else np.asarray([])
    result["moe"] = {
        "expert_usage": [float(value) for value in mean_usage],
        "collapsed": any(bool(dict(report.get("moe", {}) or {}).get("collapsed")) for report in fold_reports),
    }
    return result


def _finite_mean(values):
    finite = []
    for value in values:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(parsed):
            finite.append(parsed)
    return float(np.mean(finite)) if finite else None


def _baseline_report(bundle, test_indices, *, top_k):
    feature_index = (
        bundle.feature_columns.index("relative_strength_252d")
        if "relative_strength_252d" in bundle.feature_columns
        else bundle.feature_columns.index("relative_strength_126d")
    )
    score = bundle.sequences[np.asarray(test_indices), :, -1, feature_index]
    score = np.repeat(score[..., None], len(bundle.horizons), axis=-1)
    targets = bundle.excess_returns[np.asarray(test_indices)]
    mask = bundle.asset_mask[np.asarray(test_indices)]
    reports = {}
    for horizon_index, horizon in enumerate(bundle.horizons):
        values = []
        top_values = []
        for sample_index in range(len(score)):
            valid = mask[sample_index] & np.isfinite(targets[sample_index, :, horizon_index])
            if int(valid.sum()) < 2:
                continue
            ic = rank_information_coefficient(
                score[sample_index, valid, horizon_index],
                targets[sample_index, valid, horizon_index],
            )
            top_return = top_k_excess_return(
                score[sample_index, valid, horizon_index],
                targets[sample_index, valid, horizon_index],
                k=top_k,
            )
            if ic is not None:
                values.append(ic)
            if top_return is not None:
                top_values.append(top_return)
        reports[str(horizon)] = {
            "rank_ic": _finite_mean(values),
            "top_k_excess_return": _finite_mean(top_values),
            "sample_count": len(top_values),
        }
    return {"horizons": reports}


def walk_forward_validate_bundle(
    bundle,
    *,
    config,
    train_periods: int,
    test_periods: int,
    embargo_periods: int,
    epochs: int = 5,
    batch_size: int = 8,
    learning_rate: float = 3e-4,
    weight_decay: float = 1e-4,
    device: str = "auto",
    top_k: int = 3,
    max_folds: int = 3,
    compare_pretraining: bool = True,
) -> dict:
    import tempfile
    from pathlib import Path

    from .pretraining import pretrain_temporal_encoder
    from .training import load_model_checkpoint, train_multi_asset_model

    splits = purged_walk_forward_splits(
        bundle.observation_dates,
        train_periods=train_periods,
        test_periods=test_periods,
        embargo_periods=embargo_periods,
        step_periods=test_periods,
    )
    if max_folds > 0:
        splits = splits[-max(int(max_folds), 1):]
    candidate_reports = []
    scratch_reports = []
    baseline_reports = []
    folds = []
    with tempfile.TemporaryDirectory() as temp_dir:
        for fold_index, (train_indices, test_indices) in enumerate(splits, start=1):
            train_bundle = _subset_bundle(bundle, train_indices)
            test_bundle = _subset_bundle(bundle, test_indices)
            pretrained_path = None
            pretrain_result = {}
            if compare_pretraining:
                pretrained_path = str(Path(temp_dir) / f"fold-{fold_index}-pretrain.pt")
                pretrain_result = pretrain_temporal_encoder(
                    train_bundle,
                    config=config,
                    epochs=max(1, int(epochs)),
                    batch_size=batch_size,
                    learning_rate=learning_rate,
                    device=device,
                    checkpoint_path=pretrained_path,
                    seed=100 + fold_index,
                )
            candidate_path = str(Path(temp_dir) / f"fold-{fold_index}-candidate.pt")
            train_multi_asset_model(
                train_bundle,
                config=config,
                epochs=epochs,
                batch_size=batch_size,
                learning_rate=learning_rate,
                weight_decay=weight_decay,
                device=device,
                checkpoint_path=candidate_path,
                pretrained_checkpoint_path=pretrained_path,
            )
            candidate_model, candidate_metadata = load_model_checkpoint(candidate_path, device=device)
            candidate_outputs = _predict_bundle(candidate_model, test_bundle, candidate_metadata, device=device)
            candidate_report = evaluate_prediction_arrays(
                rank_scores=candidate_outputs["rank_scores"],
                targets=test_bundle.excess_returns,
                quantiles=candidate_outputs["return_quantiles"],
                expert_weights=candidate_outputs["expert_weights"],
                asset_mask=test_bundle.asset_mask,
                horizons=bundle.horizons,
                top_k=top_k,
            )
            candidate_reports.append(candidate_report)

            scratch_report = None
            if compare_pretraining:
                scratch_path = str(Path(temp_dir) / f"fold-{fold_index}-scratch.pt")
                train_multi_asset_model(
                    train_bundle,
                    config=config,
                    epochs=epochs,
                    batch_size=batch_size,
                    learning_rate=learning_rate,
                    weight_decay=weight_decay,
                    device=device,
                    checkpoint_path=scratch_path,
                )
                scratch_model, scratch_metadata = load_model_checkpoint(scratch_path, device=device)
                scratch_outputs = _predict_bundle(scratch_model, test_bundle, scratch_metadata, device=device)
                scratch_report = evaluate_prediction_arrays(
                    rank_scores=scratch_outputs["rank_scores"],
                    targets=test_bundle.excess_returns,
                    quantiles=scratch_outputs["return_quantiles"],
                    expert_weights=scratch_outputs["expert_weights"],
                    asset_mask=test_bundle.asset_mask,
                    horizons=bundle.horizons,
                    top_k=top_k,
                )
                scratch_reports.append(scratch_report)
            baseline_report = _baseline_report(bundle, test_indices, top_k=top_k)
            baseline_reports.append(baseline_report)
            folds.append(
                {
                    "fold": fold_index,
                    "train_start": bundle.observation_dates[int(train_indices[0])],
                    "train_end": bundle.observation_dates[int(train_indices[-1])],
                    "test_start": bundle.observation_dates[int(test_indices[0])],
                    "test_end": bundle.observation_dates[int(test_indices[-1])],
                    "candidate": candidate_report,
                    "scratch": scratch_report,
                    "baseline": baseline_report,
                    "pretraining": pretrain_result,
                }
            )

    candidate = _aggregate_fold_reports(candidate_reports, horizons=bundle.horizons)
    scratch = _aggregate_fold_reports(scratch_reports, horizons=bundle.horizons) if scratch_reports else {}
    baseline = _aggregate_fold_reports(baseline_reports, horizons=bundle.horizons)
    primary_horizon = str(bundle.horizons[-1])
    candidate_top = dict(candidate.get("horizons", {}).get(primary_horizon, {}) or {}).get("top_k_excess_return")
    baseline_top = dict(baseline.get("horizons", {}).get(primary_horizon, {}) or {}).get("top_k_excess_return")
    scratch_top = dict(scratch.get("horizons", {}).get(primary_horizon, {}) or {}).get("top_k_excess_return")
    beats_baseline = candidate_top is not None and baseline_top is not None and candidate_top > baseline_top
    pretraining_incremental = (
        candidate_top is not None
        and scratch_top is not None
        and candidate_top > scratch_top
    )
    return {
        "schema_version": 1,
        "status": "PASS" if beats_baseline and not candidate["moe"]["collapsed"] else "REVIEW",
        "fold_count": len(folds),
        "horizons": list(bundle.horizons),
        "candidate": candidate,
        "scratch": scratch,
        "relative_strength_baseline": baseline,
        "governance": {
            "beats_baseline_252d_top_k": beats_baseline,
            "pretraining_incremental_252d_top_k": pretraining_incremental,
            "moe_collapsed": bool(candidate["moe"]["collapsed"]),
            "automatic_promotion": False,
        },
        "folds": folds,
    }
