import tempfile
import unittest
import json
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd


class MultiHorizonDatasetTests(unittest.TestCase):
    def test_forward_labels_include_absolute_and_benchmark_relative_returns(self):
        from quant_core.models.multi_horizon.dataset import build_forward_labels

        index = pd.date_range("2024-01-01", periods=12, freq="D")
        asset = pd.DataFrame({"Close": np.arange(100.0, 112.0)}, index=index)
        benchmark = pd.DataFrame({"Close": np.arange(100.0, 106.0, 0.5)}, index=index)
        treasury = pd.DataFrame({"Close": np.linspace(100.0, 101.1, len(index))}, index=index)

        labels = build_forward_labels(asset, benchmark, treasury, horizons=(2, 4))

        expected_asset_return = 102.0 / 100.0 - 1.0
        expected_benchmark_return = 101.0 / 100.0 - 1.0
        expected_treasury_return = 100.2 / 100.0 - 1.0
        self.assertAlmostEqual(labels.loc[index[0], "forward_return_2d"], expected_asset_return)
        self.assertAlmostEqual(
            labels.loc[index[0], "market_excess_return_2d"],
            expected_asset_return - expected_benchmark_return,
        )
        self.assertAlmostEqual(
            labels.loc[index[0], "risk_free_excess_return_2d"],
            expected_asset_return - expected_treasury_return,
        )
        self.assertTrue(labels["forward_return_4d"].tail(4).isna().all())
        self.assertTrue(labels["market_excess_return_4d"].tail(4).isna().all())
        self.assertTrue(labels["risk_free_excess_return_4d"].tail(4).isna().all())
        self.assertTrue(labels["max_adverse_4d"].tail(4).isna().all())

    def test_panel_builder_uses_only_features_available_at_observation_date(self):
        from quant_core.models.multi_horizon.dataset import build_panel_frame

        index = pd.date_range("2020-01-01", periods=340, freq="B")
        benchmark = pd.DataFrame(
            {
                "Open": np.linspace(100, 130, len(index)),
                "High": np.linspace(101, 131, len(index)),
                "Low": np.linspace(99, 129, len(index)),
                "Close": np.linspace(100, 130, len(index)),
                "Volume": np.linspace(1_000_000, 1_200_000, len(index)),
            },
            index=index,
        )
        asset = benchmark.copy()
        asset["Close"] = np.linspace(50, 90, len(index))
        treasury = benchmark.copy()
        treasury["Close"] = np.linspace(100, 104, len(index))
        histories = {"AAA": asset, "SPY": benchmark, "BIL": treasury}

        panel = build_panel_frame(
            histories,
            benchmark_map={"AAA": "SPY"},
            symbols=["AAA"],
            horizons=(63, 126),
            observation_frequency="W-FRI",
        )

        self.assertFalse(panel.empty)
        self.assertIn("market_excess_return_63d", panel.columns)
        self.assertIn("risk_free_excess_return_63d", panel.columns)
        self.assertIn("relative_strength_126d", panel.columns)
        comparable = panel.dropna(subset=["return_63d", "relative_strength_63d"])
        first_date = pd.Timestamp(comparable.iloc[0]["observation_date"])
        truncated = {key: value.loc[:first_date].copy() for key, value in histories.items()}
        truncated_panel = build_panel_frame(
            truncated,
            benchmark_map={"AAA": "SPY"},
            symbols=["AAA"],
            horizons=(63,),
            observation_frequency="W-FRI",
            include_unlabeled=True,
        )
        original_row = panel.loc[panel["observation_date"] == first_date].iloc[0]
        truncated_row = truncated_panel.loc[truncated_panel["observation_date"] == first_date].iloc[0]
        self.assertAlmostEqual(original_row["return_63d"], truncated_row["return_63d"])
        self.assertAlmostEqual(original_row["relative_strength_63d"], truncated_row["relative_strength_63d"])


class MultiAssetTransformerTests(unittest.TestCase):
    def test_network_outputs_all_required_multi_horizon_heads(self):
        import torch

        from quant_core.models.multi_horizon.network import (
            MultiAssetTransformerConfig,
            FinanceMultiAssetTransformer,
        )

        config = MultiAssetTransformerConfig(
            feature_count=8,
            horizon_count=3,
            d_model=16,
            temporal_layers=1,
            cross_asset_layers=1,
            attention_heads=4,
            patch_size=5,
            patch_stride=5,
            expert_count=3,
            top_k_experts=2,
        )
        model = FinanceMultiAssetTransformer(config)
        outputs = model(
            torch.randn(2, 6, 40, 8),
            market_context=torch.randn(2, 5),
            asset_mask=torch.ones(2, 6, dtype=torch.bool),
        )

        self.assertEqual(tuple(outputs["rank_scores"].shape), (2, 6, 3))
        self.assertEqual(tuple(outputs["positive_return_logits"].shape), (2, 6, 3))
        self.assertEqual(tuple(outputs["risk_free_outperformance_logits"].shape), (2, 6, 3))
        self.assertEqual(tuple(outputs["market_outperformance_logits"].shape), (2, 6, 3))
        self.assertEqual(tuple(outputs["return_quantiles"].shape), (2, 6, 3, 3))
        self.assertEqual(tuple(outputs["adverse_excursion"].shape), (2, 6, 3))
        self.assertEqual(tuple(outputs["timing_logits"].shape), (2, 6, 5))
        self.assertEqual(tuple(outputs["expert_weights"].shape), (2, 6, 3))
        self.assertTrue(torch.allclose(outputs["expert_weights"].sum(dim=-1), torch.ones(2, 6), atol=1e-5))

    def test_tensor_bundle_and_training_checkpoint_are_runnable(self):
        import torch

        from quant_core.models.multi_horizon.network import MultiAssetTransformerConfig
        from quant_core.models.multi_horizon.training import (
            build_multi_asset_tensor_bundle,
            load_model_checkpoint,
            train_multi_asset_model,
        )

        index = pd.date_range("2022-01-03", periods=360, freq="B")
        histories = {}
        for offset, symbol in enumerate(("AAA", "BBB", "CCC", "SPY", "BIL")):
            close = np.linspace(80 + offset * 5, 125 + offset * 7, len(index))
            close += np.sin(np.arange(len(index)) / (11 + offset)) * (1 + offset * 0.2)
            histories[symbol] = pd.DataFrame(
                {
                    "Open": close * 0.998,
                    "High": close * 1.01,
                    "Low": close * 0.99,
                    "Close": close,
                    "Volume": np.linspace(900_000, 1_500_000, len(index)),
                },
                index=index,
            )
        bundle = build_multi_asset_tensor_bundle(
            histories,
            symbols=["AAA", "BBB", "CCC"],
            benchmark_map={"AAA": "SPY", "BBB": "SPY", "CCC": "SPY"},
            horizons=(21, 63),
            lookback=80,
            observation_frequency="W-FRI",
        )
        self.assertGreater(bundle.sequences.shape[0], 2)
        self.assertEqual(bundle.sequences.shape[1:], (3, 80, len(bundle.feature_columns)))
        self.assertEqual(bundle.market_excess_returns.shape[-1], 2)
        self.assertEqual(bundle.absolute_returns.shape, bundle.market_excess_returns.shape)
        self.assertEqual(bundle.risk_free_excess_returns.shape, bundle.absolute_returns.shape)

        config = MultiAssetTransformerConfig(
            feature_count=len(bundle.feature_columns),
            horizon_count=2,
            d_model=16,
            temporal_layers=1,
            cross_asset_layers=1,
            attention_heads=4,
            patch_size=10,
            patch_stride=10,
            expert_count=2,
            top_k_experts=1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint = str(Path(temp_dir) / "model.pt")
            metrics = train_multi_asset_model(
                bundle,
                config=config,
                epochs=1,
                batch_size=4,
                device="cpu",
                checkpoint_path=checkpoint,
            )
            model, metadata = load_model_checkpoint(checkpoint, device="cpu")

        self.assertTrue(Path(metrics["checkpoint_path"]).name, "model.pt")
        self.assertEqual(metadata["horizons"], [21, 63])
        with torch.no_grad():
            output = model(
                torch.tensor(bundle.sequences[:1], dtype=torch.float32),
                market_context=torch.tensor(bundle.market_context[:1], dtype=torch.float32),
                asset_mask=torch.tensor(bundle.asset_mask[:1], dtype=torch.bool),
            )
        self.assertEqual(tuple(output["rank_scores"].shape), (1, 3, 2))

    def test_masked_patch_pretraining_checkpoint_initializes_temporal_encoder(self):
        from quant_core.models.multi_horizon.network import MultiAssetTransformerConfig
        from quant_core.models.multi_horizon.pretraining import pretrain_temporal_encoder
        from quant_core.models.multi_horizon.training import (
            build_multi_asset_tensor_bundle,
            train_multi_asset_model,
        )

        index = pd.date_range("2022-01-03", periods=260, freq="B")
        histories = {}
        for offset, symbol in enumerate(("AAA", "BBB", "SPY", "BIL")):
            close = np.linspace(80 + offset, 115 + offset * 2, len(index))
            histories[symbol] = pd.DataFrame(
                {
                    "Open": close,
                    "High": close * 1.01,
                    "Low": close * 0.99,
                    "Close": close,
                    "Volume": np.linspace(800_000, 1_100_000, len(index)),
                },
                index=index,
            )
        bundle = build_multi_asset_tensor_bundle(
            histories,
            symbols=["AAA", "BBB"],
            benchmark_map={"AAA": "SPY", "BBB": "SPY"},
            horizons=(21,),
            lookback=60,
        )
        config = MultiAssetTransformerConfig(
            feature_count=len(bundle.feature_columns),
            horizon_count=1,
            d_model=12,
            temporal_layers=1,
            cross_asset_layers=1,
            attention_heads=3,
            patch_size=10,
            patch_stride=10,
            expert_count=2,
            top_k_experts=1,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            pretrain_path = str(Path(temp_dir) / "pretrain.pt")
            model_path = str(Path(temp_dir) / "model.pt")
            pretrain_result = pretrain_temporal_encoder(
                bundle,
                config=config,
                epochs=1,
                batch_size=4,
                device="cpu",
                checkpoint_path=pretrain_path,
                seed=7,
            )
            train_result = train_multi_asset_model(
                bundle,
                config=config,
                epochs=1,
                batch_size=4,
                device="cpu",
                checkpoint_path=model_path,
                pretrained_checkpoint_path=pretrain_path,
            )

        self.assertGreaterEqual(pretrain_result["masked_patch_count"], 1)
        self.assertTrue(train_result["pretraining_loaded"])

    def test_pretraining_uses_time_ordered_validation_and_early_stopping(self):
        import torch

        from quant_core.models.multi_horizon.network import MultiAssetTransformerConfig
        from quant_core.models.multi_horizon.pretraining import (
            _time_ordered_split_indices,
            pretrain_temporal_encoder,
        )
        from quant_core.models.multi_horizon.training import build_multi_asset_tensor_bundle

        train_indices, validation_indices = _time_ordered_split_indices(10, validation_fraction=0.2)
        self.assertEqual(train_indices.tolist(), list(range(8)))
        self.assertEqual(validation_indices.tolist(), [8, 9])

        index = pd.date_range("2022-01-03", periods=260, freq="B")
        histories = {}
        for offset, symbol in enumerate(("AAA", "BBB", "SPY", "BIL")):
            close = np.linspace(80 + offset, 115 + offset * 2, len(index))
            histories[symbol] = pd.DataFrame(
                {
                    "Open": close,
                    "High": close * 1.01,
                    "Low": close * 0.99,
                    "Close": close,
                    "Volume": np.linspace(800_000, 1_100_000, len(index)),
                },
                index=index,
            )
        bundle = build_multi_asset_tensor_bundle(
            histories,
            symbols=["AAA", "BBB"],
            benchmark_map={"AAA": "SPY", "BBB": "SPY"},
            horizons=(21,),
            lookback=60,
        )
        config = MultiAssetTransformerConfig(
            feature_count=len(bundle.feature_columns),
            horizon_count=1,
            d_model=12,
            temporal_layers=1,
            cross_asset_layers=1,
            attention_heads=3,
            patch_size=10,
            patch_stride=10,
            expert_count=2,
            top_k_experts=1,
        )
        events = []
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint = str(Path(temp_dir) / "pretrain.pt")
            result = pretrain_temporal_encoder(
                bundle,
                config=config,
                epochs=8,
                minimum_epochs=1,
                early_stopping_patience=1,
                early_stopping_min_delta=1e9,
                validation_fraction=0.2,
                batch_size=4,
                device="cpu",
                checkpoint_path=checkpoint,
                seed=7,
                progress_callback=events.append,
            )
            payload = torch.load(checkpoint, map_location="cpu")

        self.assertTrue(result["stopped_early"])
        self.assertEqual(result["epochs_completed"], 2)
        self.assertEqual(result["best_epoch"], 1)
        self.assertEqual(len(result["epoch_history"]), 2)
        self.assertIn("training_loss", result["epoch_history"][0])
        self.assertIn("validation_loss", result["epoch_history"][0])
        self.assertEqual(payload["metadata"]["best_epoch"], 1)
        self.assertGreater(payload["metadata"]["validation_sample_count"], 0)
        self.assertEqual(
            payload["metadata"]["training_sample_count"] + payload["metadata"]["validation_sample_count"],
            len(bundle.observation_dates),
        )
        self.assertIn("validation_loss", events[-1])


class MultiHorizonFusionTests(unittest.TestCase):
    def test_long_term_attractive_short_term_weak_does_not_sell(self):
        from quant_core.models.multi_horizon.fusion import fuse_multi_horizon_decision

        decision = fuse_multi_horizon_decision(
            symbol="MSFT",
            long_horizon_state="ATTRACTIVE",
            timing_state="DETERIORATING",
            current_weight_pct=5.0,
            risk_regime="NORMAL",
            max_weight_pct=10.0,
        )

        self.assertEqual(decision.action, "HOLD")
        self.assertIn("WAIT_TO_ADD", decision.reason_codes)
        self.assertGreater(decision.target_weight_high_pct, 0.0)

    def test_risk_off_blocks_accumulation(self):
        from quant_core.models.multi_horizon.fusion import fuse_multi_horizon_decision

        decision = fuse_multi_horizon_decision(
            symbol="NVDA",
            long_horizon_state="ATTRACTIVE",
            timing_state="BUY_NOW",
            current_weight_pct=2.0,
            risk_regime="RISK_OFF",
            max_weight_pct=8.0,
        )

        self.assertNotEqual(decision.action, "ACCUMULATE")
        self.assertIn("RISK_GATE_BLOCK", decision.reason_codes)

    def test_raw_neural_outputs_become_stable_symbol_snapshots(self):
        import torch

        from quant_core.models.multi_horizon.prediction import build_prediction_snapshot

        outputs = {
            "rank_scores": torch.tensor([[[0.2, 0.8, 1.2], [1.0, 0.1, -0.2]]]),
            "positive_return_logits": torch.tensor([[[1.0, 1.4, 1.8], [-0.2, -0.8, -1.2]]]),
            "risk_free_outperformance_logits": torch.tensor([[[0.8, 1.2, 1.6], [-0.1, -0.7, -1.1]]]),
            "market_outperformance_logits": torch.tensor([[[0.5, 1.0, 1.5], [0.1, -0.5, -1.0]]]),
            "return_quantiles": torch.tensor(
                [[
                    [[-0.05, 0.08, 0.20], [-0.08, 0.12, 0.30], [-0.12, 0.18, 0.42]],
                    [[-0.10, 0.02, 0.12], [-0.15, -0.01, 0.16], [-0.22, -0.04, 0.20]],
                ]]
            ),
            "adverse_excursion": torch.tensor([[[-0.08, -0.12, -0.18], [-0.12, -0.20, -0.30]]]),
            "favorable_excursion": torch.tensor([[[0.12, 0.22, 0.40], [0.08, 0.12, 0.18]]]),
            "timing_logits": torch.tensor([[[0.1, 2.0, 0.2, 0.1, 0.0], [0.0, 0.1, 0.2, 1.8, 0.0]]]),
            "expert_weights": torch.tensor([[[0.6, 0.4], [0.3, 0.7]]]),
        }
        snapshot = build_prediction_snapshot(
            outputs,
            symbols=["MSFT", "XYZ"],
            horizons=[63, 126, 252],
            current_weights_pct={"MSFT": 5.0, "XYZ": 2.0},
            current_prices={"MSFT": 400.0, "XYZ": 100.0},
            risk_regime="NORMAL",
            model_metadata={"model_id": "finance_multi_asset_transformer", "trained_at": "2026-06-18"},
        )

        self.assertEqual(snapshot["symbols"][0]["symbol"], "MSFT")
        self.assertEqual(snapshot["symbols"][0]["long_horizon"]["state"], "ATTRACTIVE")
        self.assertGreater(snapshot["symbols"][0]["long_horizon"]["horizons"]["252"]["positive_return_probability"], 0.8)
        self.assertGreater(snapshot["symbols"][0]["long_horizon"]["horizons"]["252"]["risk_free_outperformance_probability"], 0.8)
        self.assertAlmostEqual(
            snapshot["symbols"][0]["long_horizon"]["horizons"]["252"]["price_range"]["p50"],
            472.0,
        )
        self.assertIn(snapshot["symbols"][0]["decision"]["action"], {"ACCUMULATE", "HOLD"})
        self.assertEqual(snapshot["symbols"][1]["timing"]["state"], "DETERIORATING")
        self.assertEqual(snapshot["summary"]["symbol_count"], 2)


class MultiHorizonValidationTests(unittest.TestCase):
    def test_purged_walk_forward_has_embargo_between_train_and_test(self):
        from quant_core.models.multi_horizon.validation import purged_walk_forward_splits

        dates = pd.date_range("2018-01-01", periods=180, freq="W-FRI")
        splits = purged_walk_forward_splits(
            dates,
            train_periods=80,
            test_periods=20,
            embargo_periods=4,
            step_periods=20,
        )

        self.assertGreaterEqual(len(splits), 3)
        train_idx, test_idx = splits[0]
        self.assertLess(max(train_idx), min(test_idx) - 4)

    def test_snapshot_round_trip_preserves_prediction(self):
        from quant_core.models.multi_horizon.snapshot import (
            load_multi_horizon_snapshot,
            save_multi_horizon_snapshot,
        )

        payload = {
            "generated_at": "2026-06-18T00:00:00",
            "model": {"model_id": "finance_multi_asset_transformer"},
            "symbols": [{"symbol": "MSFT", "decision": {"action": "HOLD"}}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "multi_horizon.json")
            save_multi_horizon_snapshot(payload, path=path)
            loaded = load_multi_horizon_snapshot(path=path)

        self.assertEqual(loaded["symbols"][0]["symbol"], "MSFT")
        self.assertEqual(loaded["symbols"][0]["decision"]["action"], "HOLD")

    def test_walk_forward_report_tracks_rank_top_k_quantiles_and_moe_usage(self):
        from quant_core.models.multi_horizon.validation import evaluate_prediction_arrays

        report = evaluate_prediction_arrays(
            rank_scores=np.array(
                [
                    [[0.9], [0.5], [0.1]],
                    [[0.2], [0.8], [0.4]],
                ]
            ),
            market_excess_targets=np.array(
                [
                    [[0.12], [0.04], [-0.03]],
                    [[-0.02], [0.11], [0.03]],
                ]
            ),
            risk_free_excess_targets=np.array(
                [
                    [[0.14], [0.06], [-0.02]],
                    [[0.00], [0.13], [0.05]],
                ]
            ),
            absolute_targets=np.array(
                [
                    [[0.15], [0.07], [-0.01]],
                    [[0.01], [0.14], [0.06]],
                ]
            ),
            positive_probabilities=np.array(
                [
                    [[0.85], [0.70], [0.35]],
                    [[0.60], [0.90], [0.75]],
                ]
            ),
            risk_free_outperformance_probabilities=np.array(
                [
                    [[0.82], [0.68], [0.32]],
                    [[0.50], [0.88], [0.72]],
                ]
            ),
            market_outperformance_probabilities=np.array(
                [
                    [[0.80], [0.65], [0.30]],
                    [[0.45], [0.85], [0.70]],
                ]
            ),
            quantiles=np.array(
                [
                    [[[-0.05, 0.08, 0.20]], [[-0.08, 0.03, 0.14]], [[-0.15, -0.02, 0.08]]],
                    [[[-0.12, 0.00, 0.10]], [[-0.02, 0.09, 0.18]], [[-0.08, 0.02, 0.12]]],
                ]
            ),
            expert_weights=np.array(
                [
                    [[0.6, 0.4], [0.5, 0.5], [0.4, 0.6]],
                    [[0.5, 0.5], [0.7, 0.3], [0.3, 0.7]],
                ]
            ),
            asset_mask=np.ones((2, 3), dtype=bool),
            horizons=(63,),
            top_k=1,
        )

        self.assertGreater(report["horizons"]["63"]["rank_ic"], 0.9)
        self.assertGreater(report["horizons"]["63"]["top_k_excess_return"], 0.1)
        self.assertGreater(report["horizons"]["63"]["directional_accuracy"], 0.8)
        self.assertLess(report["horizons"]["63"]["brier_score"], 0.2)
        self.assertGreater(report["horizons"]["63"]["risk_free_directional_accuracy"], 0.8)
        self.assertLess(report["horizons"]["63"]["risk_free_brier_score"], 0.2)
        self.assertLess(report["horizons"]["63"]["median_return_mae"], 0.08)
        self.assertGreater(report["quantile_coverage"]["p90"], report["quantile_coverage"]["p10"])
        self.assertFalse(report["moe"]["collapsed"])

    def test_validation_report_breaks_out_asset_groups(self):
        from quant_core.models.multi_horizon.validation import evaluate_prediction_arrays

        shape = (1, 3, 1)
        report = evaluate_prediction_arrays(
            rank_scores=np.array([[[0.9], [0.5], [0.1]]]),
            absolute_targets=np.array([[[0.12], [0.04], [-0.03]]]),
            risk_free_excess_targets=np.array([[[0.10], [0.02], [-0.05]]]),
            market_excess_targets=np.array([[[0.08], [0.01], [-0.04]]]),
            positive_probabilities=np.full(shape, 0.6),
            risk_free_outperformance_probabilities=np.full(shape, 0.6),
            market_outperformance_probabilities=np.full(shape, 0.6),
            quantiles=np.array(
                [[
                    [[-0.05, 0.08, 0.20]],
                    [[-0.05, 0.03, 0.15]],
                    [[-0.12, -0.02, 0.08]],
                ]]
            ),
            expert_weights=np.array([[[0.6, 0.4], [0.5, 0.5], [0.4, 0.6]]]),
            asset_mask=np.ones((1, 3), dtype=bool),
            asset_groups=("core_etf", "satellite", "satellite"),
            horizons=(63,),
            top_k=1,
        )

        self.assertEqual(set(report["asset_groups"]), {"core_etf", "satellite"})
        self.assertEqual(report["asset_groups"]["core_etf"]["asset_count"], 1)
        self.assertEqual(report["asset_groups"]["satellite"]["asset_count"], 2)

    def test_prediction_journal_is_compact_and_shadow_outcomes_are_scored(self):
        from quant_core.models.multi_horizon.governance import (
            append_prediction_journal,
            score_shadow_outcomes,
        )

        snapshot = {
            "generated_at": "2025-01-02T20:00:00",
            "model": {"model_id": "finance_multi_asset_transformer", "version": "v1"},
            "symbols": [
                {
                    "symbol": "AAA",
                    "latest_price": 100.0,
                    "long_horizon": {"blended_rank": 0.9, "horizons": {"2": {"rank": 0.9}}},
                    "decision": {"action": "ACCUMULATE"},
                },
                {
                    "symbol": "BBB",
                    "latest_price": 100.0,
                    "long_horizon": {"blended_rank": 0.2, "horizons": {"2": {"rank": 0.2}}},
                    "decision": {"action": "WATCH"},
                },
                {
                    "symbol": "CCC",
                    "latest_price": 100.0,
                    "long_horizon": {"blended_rank": 0.5, "horizons": {"2": {"rank": 0.5}}},
                    "decision": {"action": "HOLD"},
                },
            ],
        }
        index = pd.date_range("2025-01-02", periods=4, freq="B")
        histories = {
            "AAA": pd.DataFrame({"Close": [100.0, 105.0, 112.0, 115.0]}, index=index),
            "BBB": pd.DataFrame({"Close": [100.0, 99.0, 98.0, 97.0]}, index=index),
            "CCC": pd.DataFrame({"Close": [100.0, 102.0, 104.0, 105.0]}, index=index),
            "SPY": pd.DataFrame({"Close": [100.0, 101.0, 102.0, 103.0]}, index=index),
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "predictions.jsonl")
            append_prediction_journal(snapshot, path=path)
            line = Path(path).read_text(encoding="utf-8").splitlines()[0]
            journal = [__import__("json").loads(line)]

        report = score_shadow_outcomes(journal, histories=histories, horizons=(2,), top_k=1)
        self.assertNotIn("return_quantiles", line)
        self.assertEqual(report["horizons"]["2"]["matured_observations"], 1)
        self.assertGreater(report["horizons"]["2"]["rank_ic"], 0.9)
        self.assertGreater(report["horizons"]["2"]["top_k_excess_return"], 0.09)

    def test_validation_gate_requires_economic_and_model_quality_checks(self):
        from quant_core.models.multi_horizon.validation import evaluate_promotion_gates

        passed = evaluate_promotion_gates(
            candidate={
                "horizons": {
                    "252": {
                        "rank_ic": 0.08,
                        "top_k_excess_return": 0.12,
                        "top_k_risk_free_excess_return": 0.14,
                        "directional_accuracy": 0.62,
                        "brier_score": 0.21,
                        "risk_free_directional_accuracy": 0.64,
                        "risk_free_brier_score": 0.20,
                        "median_return_mae": 0.12,
                    }
                },
                "moe": {"collapsed": False},
            },
            baseline={"horizons": {"252": {"top_k_excess_return": 0.04}}},
            scratch={
                "horizons": {
                    "252": {
                        "top_k_excess_return": 0.07,
                        "top_k_risk_free_excess_return": 0.08,
                    }
                }
            },
            primary_horizon=252,
            fold_count=3,
            selected_initialization="pretrained",
        )
        failed = evaluate_promotion_gates(
            candidate={
                "horizons": {
                    "252": {
                        "rank_ic": -0.01,
                        "top_k_excess_return": 0.03,
                        "top_k_risk_free_excess_return": -0.01,
                        "directional_accuracy": 0.48,
                        "brier_score": 0.27,
                        "risk_free_directional_accuracy": 0.47,
                        "risk_free_brier_score": 0.28,
                        "median_return_mae": 0.24,
                    }
                },
                "moe": {"collapsed": False},
            },
            baseline={"horizons": {"252": {"top_k_excess_return": 0.04}}},
            scratch={
                "horizons": {
                    "252": {
                        "top_k_excess_return": 0.02,
                        "top_k_risk_free_excess_return": 0.01,
                    }
                }
            },
            primary_horizon=252,
            fold_count=2,
            selected_initialization="pretrained",
        )

        self.assertEqual(passed["status"], "PASS")
        self.assertTrue(all(passed["gates"].values()))
        self.assertEqual(failed["status"], "REVIEW")
        self.assertFalse(failed["gates"]["minimum_walk_forward_folds"])
        self.assertFalse(failed["gates"]["risk_free_direction_better_than_chance"])
        self.assertFalse(failed["gates"]["positive_rank_ic"])
        self.assertFalse(failed["gates"]["beats_baseline_top_k"])

    def test_initialization_selection_uses_composite_quality_not_one_top_k_metric(self):
        from quant_core.models.multi_horizon.validation import select_initialization

        candidate = {
            "horizons": {
                "252": {
                    "rank_ic": 0.02,
                    "top_k_excess_return": 0.70,
                    "top_k_risk_free_excess_return": 0.96,
                    "directional_accuracy": 0.55,
                    "risk_free_directional_accuracy": 0.54,
                    "brier_score": 0.24,
                    "risk_free_brier_score": 0.24,
                    "median_return_mae": 0.18,
                }
            }
        }
        scratch = {
            "horizons": {
                "252": {
                    "rank_ic": -0.10,
                    "top_k_excess_return": 0.72,
                    "top_k_risk_free_excess_return": 0.98,
                    "directional_accuracy": 0.35,
                    "risk_free_directional_accuracy": 0.34,
                    "brier_score": 0.36,
                    "risk_free_brier_score": 0.38,
                    "median_return_mae": 0.64,
                }
            }
        }

        selection = select_initialization(candidate, scratch, primary_horizon=252)

        self.assertEqual(selection["initialization"], "pretrained")
        self.assertGreater(selection["candidate_score"], selection["scratch_score"])

    def test_unapproved_model_is_shadow_only_until_manual_promotion(self):
        from quant_core.models.multi_horizon.governance import (
            apply_production_gate,
            approve_model_for_production,
            build_model_governance_snapshot,
        )

        prediction = {
            "status": "READY",
            "model": {"model_id": "finance_multi_asset_transformer", "version": "v1"},
            "symbols": [
                {"symbol": "MSFT", "list_type": "holding", "decision": {"action": "ACCUMULATE"}},
                {"symbol": "NVDA", "list_type": "candidate_pool", "decision": {"action": "PROBE"}},
            ],
        }
        validation = {"status": "PASS", "governance": {"moe_collapsed": False}}
        governance = build_model_governance_snapshot(
            prediction_snapshot=prediction,
            validation_snapshot=validation,
        )
        shadow = apply_production_gate(prediction, governance)

        self.assertEqual(governance["status"], "ELIGIBLE_FOR_MANUAL_PROMOTION")
        self.assertFalse(shadow["production_authorized"])
        self.assertEqual(shadow["symbols"][0]["decision"]["action"], "HOLD")
        self.assertEqual(shadow["symbols"][1]["decision"]["action"], "WATCH")
        self.assertEqual(shadow["symbols"][0]["shadow_decision"]["action"], "ACCUMULATE")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "governance.json")
            promoted = approve_model_for_production(
                prediction,
                governance,
                path=path,
            )
        production = apply_production_gate(shadow, promoted)
        self.assertEqual(promoted["status"], "PRODUCTION")
        self.assertTrue(production["production_authorized"])
        self.assertEqual(production["symbols"][0]["decision"]["action"], "ACCUMULATE")

    def test_initial_manual_override_can_deploy_ready_model_and_is_recorded(self):
        from quant_core.models.multi_horizon.governance import (
            apply_production_gate,
            approve_model_for_production,
        )

        prediction = {
            "status": "READY",
            "model": {"model_id": "finance_multi_asset_transformer", "version": "candidate-v1"},
            "symbols": [
                {
                    "symbol": "MSFT",
                    "list_type": "holding",
                    "decision": {"action": "ACCUMULATE"},
                }
            ],
        }
        governance = {
            "status": "SHADOW",
            "validation_status": "REVIEW",
            "production_authorized": False,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            promoted = approve_model_for_production(
                prediction,
                governance,
                path=str(Path(temp_dir) / "governance.json"),
                allow_initial_override=True,
            )

        production = apply_production_gate(prediction, promoted)
        self.assertEqual(promoted["approval_mode"], "INITIAL_MANUAL_OVERRIDE")
        self.assertTrue(promoted["validation_override"])
        self.assertTrue(production["production_authorized"])

    def test_governance_preserves_existing_production_when_new_candidate_arrives(self):
        from quant_core.models.multi_horizon import governance as module

        previous = {
            "status": "PRODUCTION",
            "production_authorized": True,
            "approved_model_version": "production-v1",
            "approved_at": "2026-06-20T10:00:00",
            "approval_mode": "VALIDATED_MANUAL_PROMOTION",
        }
        original_load = module.load_model_governance_snapshot
        original_save = module.save_model_governance_snapshot
        self.addCleanup(setattr, module, "load_model_governance_snapshot", original_load)
        self.addCleanup(setattr, module, "save_model_governance_snapshot", original_save)
        module.load_model_governance_snapshot = lambda **kwargs: previous
        module.save_model_governance_snapshot = lambda snapshot, **kwargs: "ignored"

        with tempfile.TemporaryDirectory() as temp_dir:
            validation_path = Path(temp_dir) / "validation.json"
            validation_path.write_text(json.dumps({"status": "REVIEW"}), encoding="utf-8")
            refreshed = module.refresh_model_governance(
                {
                    "status": "READY",
                    "model": {"version": "candidate-v2"},
                },
                validation_path=str(validation_path),
            )

        self.assertTrue(refreshed["production_authorized"])
        self.assertEqual(refreshed["approved_model_version"], "production-v1")
        self.assertEqual(refreshed["candidate_model_version"], "candidate-v2")
        self.assertEqual(refreshed["candidate_status"], "SHADOW")


class MultiHorizonConfigTests(unittest.TestCase):
    def test_compute_device_info_is_explicit(self):
        from quant_core.models.multi_horizon.training import describe_compute_device

        info = describe_compute_device("cpu")

        self.assertEqual(info["device"], "cpu")
        self.assertEqual(info["accelerator"], "CPU")
        self.assertIn("label", info)
        self.assertIn("torch_version", info)
        self.assertIn("torch_cuda_version", info)
        self.assertIn("cuda_available", info)
        self.assertIn("fallback_reason", info)

    def test_config_cannot_auto_promote_or_enable_traditional_ml_by_accident(self):
        from quant_core.models.multi_horizon.config import normalize_multi_horizon_config

        config = normalize_multi_horizon_config(
            {
                "horizons": [252, 63, 63],
                "risk_free_benchmark": "sgov",
                "promotion": {"automatic": True},
                "traditional_ml_policy": {"production_enabled": True},
            }
        )

        self.assertEqual(config["horizons"], [63, 252])
        self.assertEqual(config["risk_free_benchmark"], "SGOV")
        self.assertFalse(config["promotion"]["automatic"])
        self.assertFalse(config["traditional_ml_policy"]["production_enabled"])

    def test_model_universe_prioritizes_owned_and_watched_symbols(self):
        from quant_core.models.multi_horizon.pipeline import build_model_universe

        symbols = build_model_universe(
            {
                "holdings": [{"symbol": "MSFT"}, {"symbol": "IAU"}],
                "watchlist": [{"symbol": "BABA"}],
            },
            core_universe={"etfs": [{"symbol": "VOO", "enabled": True}]},
            satellite_universe={"manual_include": ["NVDA", "AMD", "MU"]},
            maximum_symbols=4,
        )

        self.assertEqual(symbols[:3], ["MSFT", "IAU", "BABA"])
        self.assertEqual(len(symbols), 4)

    def test_long_horizon_universe_excludes_tactical_products(self):
        from quant_core.models.multi_horizon.pipeline import build_model_universe_report

        report = build_model_universe_report(
            {
                "holdings": [{"symbol": "MSFT"}, {"symbol": "SQQQ"}],
                "watchlist": [{"symbol": "UVIX"}, {"symbol": "NVDA"}],
            },
            core_universe={"etfs": [{"symbol": "VOO", "enabled": True}]},
            satellite_universe={"manual_include": ["TQQQ", "AMD"]},
            universe_policy={
                "tactical_product_symbols": ["SQQQ", "TQQQ", "UVIX"],
                "exclude_tactical_products_from_long_horizon": True,
            },
            maximum_symbols=10,
        )

        self.assertEqual(report["symbols"], ["MSFT", "NVDA", "VOO", "AMD"])
        self.assertEqual(
            {row["symbol"] for row in report["excluded"]},
            {"SQQQ", "TQQQ", "UVIX"},
        )
        self.assertEqual(report["asset_groups"]["VOO"], "core_etf")

    def test_bootstrap_checkpoint_installs_only_after_hash_verification(self):
        from quant_core.models.multi_horizon.bootstrap import install_bootstrap_checkpoint

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bootstrap = root / "bootstrap.pt"
            runtime = root / "runtime" / "model.pt"
            manifest = root / "manifest.json"
            bootstrap.write_bytes(b"portable-shadow-checkpoint")
            digest = hashlib.sha256(bootstrap.read_bytes()).hexdigest()
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "artifact": {
                            "filename": bootstrap.name,
                            "sha256": digest,
                            "size_bytes": bootstrap.stat().st_size,
                            "target_schema_version": 2,
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = install_bootstrap_checkpoint(
                runtime_path=str(runtime),
                bootstrap_path=str(bootstrap),
                manifest_path=str(manifest),
            )

            self.assertEqual(result["status"], "INSTALLED")
            self.assertEqual(runtime.read_bytes(), bootstrap.read_bytes())

            runtime.unlink()
            manifest.write_text(
                json.dumps({"artifact": {"sha256": "0" * 64}}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                install_bootstrap_checkpoint(
                    runtime_path=str(runtime),
                    bootstrap_path=str(bootstrap),
                    manifest_path=str(manifest),
                )

    def test_history_loader_includes_market_and_configured_treasury_benchmarks(self):
        from quant_core.models.multi_horizon.pipeline import load_histories

        calls = []
        index = pd.date_range("2025-01-01", periods=3, freq="B")
        frame = pd.DataFrame({"Close": [100.0, 101.0, 102.0]}, index=index)
        histories, failures = load_histories(
            ["MSFT"],
            history_period="2y",
            risk_free_symbol="SGOV",
            load_history_fn=lambda symbol, period: calls.append((symbol, period)) or frame,
        )

        self.assertEqual(set(histories), {"MSFT", "SPY", "SGOV"})
        self.assertFalse(failures)
        self.assertEqual({symbol for symbol, _ in calls}, {"MSFT", "SPY", "SGOV"})

    def test_missing_checkpoint_produces_explicit_not_ready_snapshot(self):
        from quant_core.models.multi_horizon.pipeline import run_multi_horizon_job

        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_multi_horizon_job(
                config={
                    "enabled": True,
                    "history_period": "10y",
                    "maximum_training_symbols": 10,
                    "artifacts": {
                        "checkpoint_path": str(Path(temp_dir) / "missing.pt"),
                        "bootstrap_checkpoint_path": str(Path(temp_dir) / "missing-bootstrap.pt"),
                        "bootstrap_manifest_path": str(Path(temp_dir) / "missing-manifest.json"),
                        "pretraining_checkpoint_path": str(Path(temp_dir) / "pretrain.pt"),
                        "snapshot_path": str(Path(temp_dir) / "snapshot.json"),
                        "validation_path": str(Path(temp_dir) / "validation.json"),
                        "panel_path": str(Path(temp_dir) / "panel.parquet"),
                    },
                },
                data={"holdings": [{"symbol": "MSFT"}], "watchlist": [{"symbol": "NVDA"}]},
                core_universe={"etfs": []},
                satellite_universe={"manual_include": []},
                train=False,
            )

            snapshot = pd.read_json(Path(temp_dir) / "snapshot.json", typ="series")

        self.assertEqual(result["status"], "MODEL_NOT_READY")
        self.assertEqual(snapshot["status"], "MODEL_NOT_READY")

    def test_pipeline_reports_progress_before_missing_checkpoint_exit(self):
        from quant_core.models.multi_horizon.pipeline import run_multi_horizon_job

        events = []
        with tempfile.TemporaryDirectory() as temp_dir:
            run_multi_horizon_job(
                config={
                    "enabled": True,
                    "history_period": "10y",
                    "maximum_training_symbols": 10,
                    "artifacts": {
                        "checkpoint_path": str(Path(temp_dir) / "missing.pt"),
                        "bootstrap_checkpoint_path": str(Path(temp_dir) / "missing-bootstrap.pt"),
                        "bootstrap_manifest_path": str(Path(temp_dir) / "missing-manifest.json"),
                        "pretraining_checkpoint_path": str(Path(temp_dir) / "pretrain.pt"),
                        "snapshot_path": str(Path(temp_dir) / "snapshot.json"),
                        "validation_path": str(Path(temp_dir) / "validation.json"),
                        "panel_path": str(Path(temp_dir) / "panel.parquet"),
                    },
                },
                data={"holdings": [{"symbol": "MSFT"}], "watchlist": [{"symbol": "NVDA"}]},
                core_universe={"etfs": []},
                satellite_universe={"manual_include": []},
                train=False,
                progress_callback=events.append,
            )

        self.assertEqual(events[0]["stage"], "preparing")
        runtime_event = next(event for event in events if event["stage"] == "runtime_ready")
        self.assertIn(runtime_event["accelerator"], {"CPU", "CUDA", "MPS"})
        self.assertTrue(runtime_event["device_label"])
        self.assertIn("torch_version", runtime_event)
        self.assertIn("cuda_available", runtime_event)
        self.assertEqual(events[-1]["stage"], "not_ready")
        self.assertEqual(events[-1]["progress_pct"], 100)

    def test_default_registry_contains_only_multi_horizon_production_model(self):
        from quant_core.models.registry import default_model_registry

        registry = default_model_registry()
        by_id = {row["model_id"]: row for row in registry["models"]}

        self.assertTrue(by_id["finance_multi_asset_transformer"]["is_default"])
        self.assertEqual(set(by_id), {"finance_multi_asset_transformer"})


if __name__ == "__main__":
    unittest.main()
