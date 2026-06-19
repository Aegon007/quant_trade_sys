from __future__ import annotations

from typing import Callable, Iterable, Mapping

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
    absolute_targets,
    risk_free_excess_targets,
    market_excess_targets,
    positive_probabilities,
    risk_free_outperformance_probabilities,
    market_outperformance_probabilities,
    quantiles,
    expert_weights,
    asset_mask,
    horizons,
    top_k: int = 3,
) -> dict:
    rank_scores = np.asarray(rank_scores, dtype=float)
    absolute_targets = np.asarray(absolute_targets, dtype=float)
    risk_free_excess_targets = np.asarray(risk_free_excess_targets, dtype=float)
    market_excess_targets = np.asarray(market_excess_targets, dtype=float)
    positive_probabilities = np.asarray(positive_probabilities, dtype=float)
    risk_free_outperformance_probabilities = np.asarray(
        risk_free_outperformance_probabilities,
        dtype=float,
    )
    market_outperformance_probabilities = np.asarray(
        market_outperformance_probabilities,
        dtype=float,
    )
    quantiles = np.asarray(quantiles, dtype=float)
    expert_weights = np.asarray(expert_weights, dtype=float)
    asset_mask = np.asarray(asset_mask, dtype=bool)
    horizon_values = tuple(int(value) for value in horizons)
    horizon_reports = {}
    for horizon_index, horizon in enumerate(horizon_values):
        daily_ics = []
        daily_top_k = []
        daily_top_k_risk_free = []
        absolute_observed = []
        median_predictions = []
        positive_observed = []
        positive_predictions = []
        risk_free_observed = []
        risk_free_predictions = []
        market_observed = []
        market_predictions = []
        for sample_index in range(rank_scores.shape[0]):
            rank_valid = asset_mask[sample_index] & np.isfinite(
                market_excess_targets[sample_index, :, horizon_index]
            )
            if int(rank_valid.sum()) >= 2:
                score = rank_scores[sample_index, rank_valid, horizon_index]
                excess = market_excess_targets[sample_index, rank_valid, horizon_index]
                ic = rank_information_coefficient(score, excess)
                top_return = top_k_excess_return(score, excess, k=top_k)
                if ic is not None:
                    daily_ics.append(ic)
                if top_return is not None:
                    daily_top_k.append(top_return)
            forecast_valid = asset_mask[sample_index] & np.isfinite(
                absolute_targets[sample_index, :, horizon_index]
            )
            if forecast_valid.any():
                observed = absolute_targets[sample_index, forecast_valid, horizon_index]
                probability = positive_probabilities[sample_index, forecast_valid, horizon_index]
                median = quantiles[sample_index, forecast_valid, horizon_index, 1]
                absolute_observed.extend(observed.tolist())
                median_predictions.extend(median.tolist())
                positive_observed.extend((observed > 0).astype(float).tolist())
                positive_predictions.extend(probability.tolist())
                risk_free_excess = risk_free_excess_targets[
                    sample_index,
                    forecast_valid,
                    horizon_index,
                ]
                market_excess = market_excess_targets[
                    sample_index,
                    forecast_valid,
                    horizon_index,
                ]
                risk_free_observed.extend((risk_free_excess > 0).astype(float).tolist())
                risk_free_predictions.extend(
                    risk_free_outperformance_probabilities[
                        sample_index,
                        forecast_valid,
                        horizon_index,
                    ].tolist()
                )
                market_observed.extend((market_excess > 0).astype(float).tolist())
                market_predictions.extend(
                    market_outperformance_probabilities[
                        sample_index,
                        forecast_valid,
                        horizon_index,
                    ].tolist()
                )
                risk_free_score = risk_free_outperformance_probabilities[
                    sample_index,
                    forecast_valid,
                    horizon_index,
                ]
                risk_free_top = top_k_excess_return(
                    risk_free_score,
                    risk_free_excess,
                    k=top_k,
                )
                if risk_free_top is not None:
                    daily_top_k_risk_free.append(risk_free_top)
        observed_array = np.asarray(absolute_observed, dtype=float)
        median_array = np.asarray(median_predictions, dtype=float)
        positive_array = np.asarray(positive_observed, dtype=float)
        probability_array = np.asarray(positive_predictions, dtype=float)
        risk_free_array = np.asarray(risk_free_observed, dtype=float)
        risk_free_probability_array = np.asarray(risk_free_predictions, dtype=float)
        market_array = np.asarray(market_observed, dtype=float)
        market_probability_array = np.asarray(market_predictions, dtype=float)
        horizon_reports[str(horizon)] = {
            "rank_ic": float(np.mean(daily_ics)) if daily_ics else None,
            "top_k_excess_return": float(np.mean(daily_top_k)) if daily_top_k else None,
            "top_k_risk_free_excess_return": (
                float(np.mean(daily_top_k_risk_free)) if daily_top_k_risk_free else None
            ),
            "sample_count": len(daily_top_k),
            "median_return_mae": (
                float(np.mean(np.abs(median_array - observed_array))) if len(observed_array) else None
            ),
            "directional_accuracy": (
                float(np.mean((probability_array >= 0.5) == (positive_array >= 0.5)))
                if len(positive_array)
                else None
            ),
            "brier_score": (
                float(np.mean((probability_array - positive_array) ** 2))
                if len(positive_array)
                else None
            ),
            "positive_rate": float(np.mean(positive_array)) if len(positive_array) else None,
            "risk_free_directional_accuracy": (
                float(np.mean((risk_free_probability_array >= 0.5) == (risk_free_array >= 0.5)))
                if len(risk_free_array)
                else None
            ),
            "risk_free_brier_score": (
                float(np.mean((risk_free_probability_array - risk_free_array) ** 2))
                if len(risk_free_array)
                else None
            ),
            "market_directional_accuracy": (
                float(np.mean((market_probability_array >= 0.5) == (market_array >= 0.5)))
                if len(market_array)
                else None
            ),
            "market_brier_score": (
                float(np.mean((market_probability_array - market_array) ** 2))
                if len(market_array)
                else None
            ),
        }

    expanded_mask = asset_mask[..., None] & np.isfinite(absolute_targets)
    observed = absolute_targets[expanded_mask]
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
        absolute_returns=bundle.absolute_returns[positions],
        risk_free_excess_returns=bundle.risk_free_excess_returns[positions],
        market_excess_returns=bundle.market_excess_returns[positions],
        favorable_excursion=bundle.favorable_excursion[positions],
        adverse_excursion=bundle.adverse_excursion[positions],
        timing_targets=bundle.timing_targets[positions],
        observation_dates=tuple(bundle.observation_dates[index] for index in positions),
        symbols=bundle.symbols,
        horizons=bundle.horizons,
        feature_columns=bundle.feature_columns,
        risk_free_symbol=bundle.risk_free_symbol,
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
            "top_k_risk_free_excess_return": _finite_mean(
                [row.get("top_k_risk_free_excess_return") for row in rows]
            ),
            "median_return_mae": _finite_mean([row.get("median_return_mae") for row in rows]),
            "directional_accuracy": _finite_mean([row.get("directional_accuracy") for row in rows]),
            "brier_score": _finite_mean([row.get("brier_score") for row in rows]),
            "positive_rate": _finite_mean([row.get("positive_rate") for row in rows]),
            "risk_free_directional_accuracy": _finite_mean(
                [row.get("risk_free_directional_accuracy") for row in rows]
            ),
            "risk_free_brier_score": _finite_mean(
                [row.get("risk_free_brier_score") for row in rows]
            ),
            "market_directional_accuracy": _finite_mean(
                [row.get("market_directional_accuracy") for row in rows]
            ),
            "market_brier_score": _finite_mean(
                [row.get("market_brier_score") for row in rows]
            ),
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


def evaluate_promotion_gates(
    *,
    candidate,
    baseline,
    scratch,
    primary_horizon: int,
    fold_count: int,
    minimum_folds: int = 3,
) -> dict:
    horizon = str(int(primary_horizon))
    candidate_row = dict(dict(candidate or {}).get("horizons", {}).get(horizon, {}) or {})
    baseline_row = dict(dict(baseline or {}).get("horizons", {}).get(horizon, {}) or {})
    scratch_row = dict(dict(scratch or {}).get("horizons", {}).get(horizon, {}) or {})
    candidate_rank_ic = candidate_row.get("rank_ic")
    candidate_top = candidate_row.get("top_k_excess_return")
    candidate_risk_free_top = candidate_row.get("top_k_risk_free_excess_return")
    directional_accuracy = candidate_row.get("directional_accuracy")
    brier_score = candidate_row.get("brier_score")
    risk_free_directional_accuracy = candidate_row.get("risk_free_directional_accuracy")
    risk_free_brier_score = candidate_row.get("risk_free_brier_score")
    median_return_mae = candidate_row.get("median_return_mae")
    baseline_top = baseline_row.get("top_k_excess_return")
    scratch_top = scratch_row.get("top_k_excess_return")
    scratch_risk_free_top = scratch_row.get("top_k_risk_free_excess_return")

    def positive(value) -> bool:
        try:
            return bool(np.isfinite(float(value)) and float(value) > 0)
        except (TypeError, ValueError):
            return False

    def greater(left, right) -> bool:
        try:
            return bool(np.isfinite(float(left)) and np.isfinite(float(right)) and float(left) > float(right))
        except (TypeError, ValueError):
            return False

    def less(value, threshold) -> bool:
        try:
            return bool(np.isfinite(float(value)) and float(value) < float(threshold))
        except (TypeError, ValueError):
            return False

    gates = {
        "minimum_walk_forward_folds": int(fold_count) >= int(minimum_folds),
        "absolute_direction_better_than_chance": greater(directional_accuracy, 0.5),
        "absolute_probability_calibrated": less(brier_score, 0.25),
        "risk_free_direction_better_than_chance": greater(
            risk_free_directional_accuracy,
            0.5,
        ),
        "risk_free_probability_calibrated": less(risk_free_brier_score, 0.25),
        "median_return_error_bounded": less(median_return_mae, 0.20),
        "positive_top_k_risk_free_excess": positive(candidate_risk_free_top),
        "positive_rank_ic": positive(candidate_rank_ic),
        "positive_top_k_excess_return": positive(candidate_top),
        "beats_baseline_top_k": greater(candidate_top, baseline_top),
        "pretraining_incremental": greater(
            candidate_risk_free_top,
            scratch_risk_free_top,
        ),
        "moe_stable": not bool(dict(candidate or {}).get("moe", {}).get("collapsed")),
    }
    return {
        "status": "PASS" if all(gates.values()) else "REVIEW",
        "primary_horizon": int(primary_horizon),
        "gates": gates,
        "metrics": {
            "candidate_rank_ic": candidate_rank_ic,
            "candidate_top_k_excess_return": candidate_top,
            "candidate_top_k_risk_free_excess_return": candidate_risk_free_top,
            "directional_accuracy": directional_accuracy,
            "brier_score": brier_score,
            "risk_free_directional_accuracy": risk_free_directional_accuracy,
            "risk_free_brier_score": risk_free_brier_score,
            "median_return_mae": median_return_mae,
            "baseline_top_k_excess_return": baseline_top,
            "scratch_top_k_excess_return": scratch_top,
            "scratch_top_k_risk_free_excess_return": scratch_risk_free_top,
        },
    }


def _baseline_report(bundle, test_indices, *, top_k):
    feature_index = (
        bundle.feature_columns.index("relative_strength_252d")
        if "relative_strength_252d" in bundle.feature_columns
        else bundle.feature_columns.index("relative_strength_126d")
    )
    score = bundle.sequences[np.asarray(test_indices), :, -1, feature_index]
    score = np.repeat(score[..., None], len(bundle.horizons), axis=-1)
    targets = bundle.market_excess_returns[np.asarray(test_indices)]
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
    progress_callback: Callable[[Mapping], None] | None = None,
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
    work_per_fold = 3 if compare_pretraining else 1
    total_work = max(len(splits) * work_per_fold, 1)
    completed_work = 0

    def report(detail: str, *, fold: int, phase: str):
        if progress_callback is None:
            return
        progress_callback(
            {
                "stage": "walk_forward_validation",
                "detail": detail,
                "progress_pct": round(completed_work / total_work * 100.0, 1),
                "fold": fold,
                "folds": len(splits),
                "phase": phase,
            }
        )

    def child_progress(*, fold: int, phase: str):
        if progress_callback is None:
            return None

        def _report(event: Mapping):
            payload = dict(event or {})
            local = min(max(float(payload.get("progress_pct", 0.0) or 0.0), 0.0), 100.0)
            progress_callback(
                {
                    "stage": "walk_forward_validation",
                    "detail": f"Fold {fold}/{len(splits)} {payload.get('detail') or phase}",
                    "progress_pct": round((completed_work + local / 100.0) / total_work * 100.0, 1),
                    "fold": fold,
                    "folds": len(splits),
                    "phase": phase,
                    "epoch": payload.get("epoch"),
                    "epochs": payload.get("epochs"),
                    "loss": payload.get("loss"),
                    "device": payload.get("device"),
                }
            )

        return _report

    with tempfile.TemporaryDirectory() as temp_dir:
        for fold_index, (train_indices, test_indices) in enumerate(splits, start=1):
            train_bundle = _subset_bundle(bundle, train_indices)
            test_bundle = _subset_bundle(bundle, test_indices)
            pretrained_path = None
            pretrain_result = {}
            if compare_pretraining:
                report(f"Fold {fold_index}/{len(splits)} pretraining", fold=fold_index, phase="pretraining")
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
                    progress_callback=child_progress(fold=fold_index, phase="pretraining"),
                )
                completed_work += 1
                report(f"Fold {fold_index}/{len(splits)} pretrained", fold=fold_index, phase="pretraining")
            candidate_path = str(Path(temp_dir) / f"fold-{fold_index}-candidate.pt")
            report(f"Fold {fold_index}/{len(splits)} candidate training", fold=fold_index, phase="candidate")
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
                progress_callback=child_progress(fold=fold_index, phase="candidate"),
            )
            completed_work += 1
            report(f"Fold {fold_index}/{len(splits)} candidate evaluated", fold=fold_index, phase="candidate")
            candidate_model, candidate_metadata = load_model_checkpoint(candidate_path, device=device)
            candidate_outputs = _predict_bundle(candidate_model, test_bundle, candidate_metadata, device=device)
            candidate_report = evaluate_prediction_arrays(
                rank_scores=candidate_outputs["rank_scores"],
                absolute_targets=test_bundle.absolute_returns,
                risk_free_excess_targets=test_bundle.risk_free_excess_returns,
                market_excess_targets=test_bundle.market_excess_returns,
                positive_probabilities=1.0 / (1.0 + np.exp(-candidate_outputs["positive_return_logits"])),
                risk_free_outperformance_probabilities=1.0
                / (1.0 + np.exp(-candidate_outputs["risk_free_outperformance_logits"])),
                market_outperformance_probabilities=1.0
                / (1.0 + np.exp(-candidate_outputs["market_outperformance_logits"])),
                quantiles=candidate_outputs["return_quantiles"],
                expert_weights=candidate_outputs["expert_weights"],
                asset_mask=test_bundle.asset_mask,
                horizons=bundle.horizons,
                top_k=top_k,
            )
            candidate_reports.append(candidate_report)

            scratch_report = None
            if compare_pretraining:
                report(f"Fold {fold_index}/{len(splits)} scratch control", fold=fold_index, phase="scratch")
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
                    progress_callback=child_progress(fold=fold_index, phase="scratch"),
                )
                scratch_model, scratch_metadata = load_model_checkpoint(scratch_path, device=device)
                scratch_outputs = _predict_bundle(scratch_model, test_bundle, scratch_metadata, device=device)
                scratch_report = evaluate_prediction_arrays(
                    rank_scores=scratch_outputs["rank_scores"],
                    absolute_targets=test_bundle.absolute_returns,
                    risk_free_excess_targets=test_bundle.risk_free_excess_returns,
                    market_excess_targets=test_bundle.market_excess_returns,
                    positive_probabilities=1.0 / (1.0 + np.exp(-scratch_outputs["positive_return_logits"])),
                    risk_free_outperformance_probabilities=1.0
                    / (1.0 + np.exp(-scratch_outputs["risk_free_outperformance_logits"])),
                    market_outperformance_probabilities=1.0
                    / (1.0 + np.exp(-scratch_outputs["market_outperformance_logits"])),
                    quantiles=scratch_outputs["return_quantiles"],
                    expert_weights=scratch_outputs["expert_weights"],
                    asset_mask=test_bundle.asset_mask,
                    horizons=bundle.horizons,
                    top_k=top_k,
                )
                scratch_reports.append(scratch_report)
                completed_work += 1
                report(f"Fold {fold_index}/{len(splits)} complete", fold=fold_index, phase="scratch")
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
    gate_report = evaluate_promotion_gates(
        candidate=candidate,
        baseline=baseline,
        scratch=scratch,
        primary_horizon=bundle.horizons[-1],
        fold_count=len(folds),
    )
    return {
        "schema_version": 1,
        "status": gate_report["status"],
        "fold_count": len(folds),
        "horizons": list(bundle.horizons),
        "candidate": candidate,
        "scratch": scratch,
        "relative_strength_baseline": baseline,
        "governance": {
            "beats_baseline_252d_top_k": gate_report["gates"]["beats_baseline_top_k"],
            "pretraining_incremental_252d_top_k": gate_report["gates"]["pretraining_incremental"],
            "moe_collapsed": bool(candidate["moe"]["collapsed"]),
            "automatic_promotion": False,
            "promotion_gates": gate_report["gates"],
            "promotion_metrics": gate_report["metrics"],
        },
        "folds": folds,
    }
