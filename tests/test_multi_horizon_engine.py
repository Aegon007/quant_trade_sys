import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


class MultiHorizonDatasetTests(unittest.TestCase):
    def test_forward_labels_are_benchmark_relative_and_tail_is_unknown(self):
        from quant_core.models.multi_horizon.dataset import build_forward_labels

        index = pd.date_range("2024-01-01", periods=12, freq="D")
        asset = pd.DataFrame({"Close": np.arange(100.0, 112.0)}, index=index)
        benchmark = pd.DataFrame({"Close": np.arange(100.0, 106.0, 0.5)}, index=index)

        labels = build_forward_labels(asset, benchmark, horizons=(2, 4))

        expected_asset_return = 102.0 / 100.0 - 1.0
        expected_benchmark_return = 101.0 / 100.0 - 1.0
        self.assertAlmostEqual(labels.loc[index[0], "excess_return_2d"], expected_asset_return - expected_benchmark_return)
        self.assertTrue(labels["excess_return_4d"].tail(4).isna().all())
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
        histories = {"AAA": asset, "SPY": benchmark}

        panel = build_panel_frame(
            histories,
            benchmark_map={"AAA": "SPY"},
            symbols=["AAA"],
            horizons=(63, 126),
            observation_frequency="W-FRI",
        )

        self.assertFalse(panel.empty)
        self.assertIn("excess_return_63d", panel.columns)
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
        self.assertEqual(tuple(outputs["outperformance_logits"].shape), (2, 6, 3))
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
        for offset, symbol in enumerate(("AAA", "BBB", "CCC", "SPY")):
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
        self.assertEqual(bundle.excess_returns.shape[-1], 2)

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
        for offset, symbol in enumerate(("AAA", "BBB", "SPY")):
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
            "outperformance_logits": torch.tensor([[[0.5, 1.0, 1.5], [0.1, -0.5, -1.0]]]),
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
            risk_regime="NORMAL",
            model_metadata={"model_id": "finance_multi_asset_transformer", "trained_at": "2026-06-18"},
        )

        self.assertEqual(snapshot["symbols"][0]["symbol"], "MSFT")
        self.assertEqual(snapshot["symbols"][0]["long_horizon"]["state"], "ATTRACTIVE")
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
            targets=np.array(
                [
                    [[0.12], [0.04], [-0.03]],
                    [[-0.02], [0.11], [0.03]],
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
        self.assertGreater(report["quantile_coverage"]["p90"], report["quantile_coverage"]["p10"])
        self.assertFalse(report["moe"]["collapsed"])

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


class MultiHorizonConfigTests(unittest.TestCase):
    def test_config_cannot_auto_promote_or_enable_traditional_ml_by_accident(self):
        from quant_core.models.multi_horizon.config import normalize_multi_horizon_config

        config = normalize_multi_horizon_config(
            {
                "horizons": [252, 63, 63],
                "promotion": {"automatic": True},
                "traditional_ml_policy": {"production_enabled": True},
            }
        )

        self.assertEqual(config["horizons"], [63, 252])
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

    def test_default_registry_contains_only_multi_horizon_production_model(self):
        from quant_core.models.registry import default_model_registry

        registry = default_model_registry()
        by_id = {row["model_id"]: row for row in registry["models"]}

        self.assertTrue(by_id["finance_multi_asset_transformer"]["is_default"])
        self.assertEqual(set(by_id), {"finance_multi_asset_transformer"})


if __name__ == "__main__":
    unittest.main()
