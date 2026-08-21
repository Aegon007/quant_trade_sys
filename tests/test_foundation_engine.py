import tempfile
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd


def _history(start=100.0, periods=420, drift=0.001):
    dates = pd.date_range("2024-01-01", periods=periods, freq="B")
    prices = [start]
    for _ in range(periods - 1):
        prices.append(prices[-1] * (1.0 + drift))
    return pd.DataFrame(
        {
            "Open": prices,
            "High": [price * 1.01 for price in prices],
            "Low": [price * 0.99 for price in prices],
            "Close": prices,
            "Volume": [1000000] * periods,
        },
        index=dates,
    )


class FoundationEngineTests(unittest.TestCase):
    def test_proxy_backend_produces_quantile_forecasts(self):
        from quant_core.models.foundation.backends import ProxyFoundationBackend

        backend = ProxyFoundationBackend()
        forecasts = backend.forecast(
            {"MSFT": _history(), "BIL": _history(drift=0.0001), "SPY": _history(), "QQQ": _history()},
            symbols=["MSFT"],
            horizons=[63, 252],
            benchmarks={"risk_free": "BIL", "market": "SPY", "growth": "QQQ"},
        )

        self.assertIn("MSFT", forecasts)
        self.assertIn("252", forecasts["MSFT"]["horizons"])
        horizon = forecasts["MSFT"]["horizons"]["252"]
        self.assertIn("return_range", horizon)
        self.assertGreaterEqual(horizon["positive_return_probability"], 0.0)
        self.assertLessEqual(horizon["positive_return_probability"], 1.0)

    def test_chronos_backend_calls_real_package_adapter_when_available(self):
        from quant_core.models.foundation.backends import ChronosFoundationBackend

        calls = []

        class FakeChronosPipeline:
            @classmethod
            def from_pretrained(cls, model_name, **kwargs):
                calls.append({"model_name": model_name, "kwargs": kwargs})
                return cls()

            def predict_quantiles(self, *args, **kwargs):
                contexts = kwargs.get("context") or kwargs.get("inputs") or args[0]
                prediction_length = int(kwargs["prediction_length"])
                batch = len(contexts)
                quantiles = np.zeros((batch, prediction_length, 3), dtype=float)
                means = np.zeros((batch, prediction_length), dtype=float)
                for batch_index, context in enumerate(contexts):
                    latest = float(context[-1].item())
                    for step in range(prediction_length):
                        growth = 1.0 + 0.001 * (step + 1)
                        quantiles[batch_index, step, 0] = latest * (growth - 0.02)
                        quantiles[batch_index, step, 1] = latest * growth
                        quantiles[batch_index, step, 2] = latest * (growth + 0.03)
                        means[batch_index, step] = latest * growth
                return quantiles, means

        fake_chronos = types.ModuleType("chronos")
        fake_chronos.BaseChronosPipeline = FakeChronosPipeline
        fake_chronos.ChronosPipeline = FakeChronosPipeline
        fake_torch = types.ModuleType("torch")
        fake_torch.float32 = "float32"

        class FakeCuda:
            @staticmethod
            def is_available():
                return False

        class FakeMps:
            @staticmethod
            def is_available():
                return False

        fake_torch.cuda = FakeCuda()
        fake_torch.backends = types.SimpleNamespace(mps=FakeMps())
        fake_torch.tensor = lambda values, dtype=None: np.array(values, dtype=float)

        with patch.dict(sys.modules, {"chronos": fake_chronos, "torch": fake_torch}):
            backend = ChronosFoundationBackend(model_name="amazon/chronos-t5-tiny", revision="abc123", device="cpu")
            forecasts = backend.forecast(
                {"MSFT": _history(), "BIL": _history(drift=0.0001), "SPY": _history(), "QQQ": _history()},
                symbols=["MSFT"],
                horizons=[10, 20],
                benchmarks={"risk_free": "BIL", "market": "SPY", "growth": "QQQ"},
            )

        self.assertEqual(calls[0]["model_name"], "amazon/chronos-t5-tiny")
        self.assertEqual(calls[0]["kwargs"]["revision"], "abc123")
        self.assertEqual(forecasts["MSFT"]["source_backend"], "chronos")
        self.assertEqual(forecasts["MSFT"]["model_name"], "amazon/chronos-t5-tiny")
        self.assertEqual(forecasts["MSFT"]["revision"], "abc123")
        self.assertIn("20", forecasts["MSFT"]["horizons"])
        self.assertGreater(forecasts["MSFT"]["horizons"]["20"]["return_range"]["p50"], 0)

    def test_foundation_config_exposes_chronos_presets(self):
        from quant_core.models.foundation.config import normalize_foundation_model_config

        config = normalize_foundation_model_config(
            {
                "backends": {
                    "chronos": {
                        "model_name": "amazon/chronos-2",
                        "revision": "main",
                    }
                }
            }
        )

        self.assertEqual(config["backends"]["chronos"]["model_name"], "amazon/chronos-2")
        self.assertEqual(config["backends"]["chronos"]["revision"], "main")
        self.assertIn("chronos_2", config["model_presets"])
        self.assertEqual(config["model_presets"]["chronos_2"]["parameter_count"], "120M")

    def test_foundation_config_migrates_bolt_to_chronos2(self):
        from quant_core.models.foundation.config import normalize_foundation_model_config

        config = normalize_foundation_model_config(
            {
                "backends": {
                    "chronos": {
                        "model_name": "amazon/chronos-bolt-small",
                        "supports_covariates": False,
                    }
                },
                "model_presets": {
                    "chronos_bolt_small": {"model_name": "amazon/chronos-bolt-small"},
                },
            }
        )

        self.assertEqual(config["backends"]["chronos"]["model_name"], "amazon/chronos-2")
        self.assertTrue(config["backends"]["chronos"]["supports_covariates"])
        self.assertNotIn("chronos_bolt_small", config["model_presets"])

    def test_chronos2_backend_uses_predict_df_adapter(self):
        from quant_core.models.foundation.backends import ChronosFoundationBackend

        calls = []

        class FakeChronos2Pipeline:
            @classmethod
            def from_pretrained(cls, model_name, **kwargs):
                return cls()

            def predict_df(self, df, **kwargs):
                calls.append({"rows": len(df), "kwargs": kwargs})
                prediction_length = int(kwargs["prediction_length"])
                rows = []
                for symbol in sorted(set(df["item_id"])):
                    latest = float(df[df["item_id"] == symbol]["target"].iloc[-1])
                    for step in range(prediction_length):
                        growth = 1.0 + 0.001 * (step + 1)
                        rows.append(
                            {
                                "item_id": symbol,
                                "timestamp": pd.Timestamp("2026-01-01") + pd.Timedelta(days=step),
                                "target_name": "target",
                                "predictions": latest * growth,
                                "0.1": latest * (growth - 0.02),
                                "0.5": latest * growth,
                                "0.9": latest * (growth + 0.03),
                            }
                        )
                return pd.DataFrame(rows)

        fake_chronos = types.ModuleType("chronos")
        fake_chronos.BaseChronosPipeline = FakeChronos2Pipeline
        fake_chronos.ChronosPipeline = FakeChronos2Pipeline
        fake_torch = types.ModuleType("torch")
        fake_torch.float32 = "float32"

        class FakeCuda:
            @staticmethod
            def is_available():
                return False

        class FakeMps:
            @staticmethod
            def is_available():
                return False

        fake_torch.cuda = FakeCuda()
        fake_torch.backends = types.SimpleNamespace(mps=FakeMps())
        fake_torch.tensor = lambda values, dtype=None: np.array(values, dtype=float)

        with patch.dict(sys.modules, {"chronos": fake_chronos, "torch": fake_torch}):
            backend = ChronosFoundationBackend(model_name="amazon/chronos-2", device="cpu", context_length=128, batch_size=4)
            forecasts = backend.forecast(
                {"MSFT": _history(), "BIL": _history(drift=0.0001), "SPY": _history(), "QQQ": _history()},
                symbols=["MSFT"],
                horizons=[10, 20],
                benchmarks={"risk_free": "BIL", "market": "SPY", "growth": "QQQ"},
            )

        self.assertEqual(calls[0]["kwargs"]["prediction_length"], 20)
        self.assertEqual(calls[0]["kwargs"]["context_length"], 128)
        self.assertEqual(forecasts["MSFT"]["model_name"], "amazon/chronos-2")
        self.assertEqual(forecasts["MSFT"]["forecast_api"], "predict_df")
        self.assertIn("20", forecasts["MSFT"]["horizons"])

    def test_foundation_training_observations_are_appended_and_retained(self):
        from quant_core.models.foundation.training_data import append_training_observations

        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "foundation_training.parquet")
            result = append_training_observations(
                {"MSFT": _history(periods=90), "SPY": _history(periods=90)},
                symbols=["MSFT", "SPY"],
                captured_at=datetime(2026, 7, 28, 23, 0, 0),
                model_name="amazon/chronos-2",
                retention_days=1200,
                path=path,
            )
            frame = pd.read_parquet(path)

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["symbol_count"], 2)
        self.assertIn("model_name", frame.columns)
        self.assertEqual(set(frame["model_name"]), {"amazon/chronos-2"})

    def test_semiconductor_sector_overlay_upgrades_neutral_watch_to_probe(self):
        from quant_core.models.foundation.pipeline import _apply_sector_overlay, _sector_momentum

        histories = {
            "MU": _history(drift=0.004),
            "SMH": _history(drift=0.003),
            "SOXX": _history(drift=0.0028),
            "SPY": _history(drift=0.0004),
        }
        sector = _sector_momentum("MU", histories, market_symbol="SPY")
        decision = _apply_sector_overlay(
            {
                "action": "WATCH",
                "target_weight_range_pct": [0.0, 0.0],
                "suggested_trade_size_pct": 0.0,
                "reason_codes": ["SATELLITE_NOT_STRONG_ENOUGH"],
                "risk_overrides": [],
            },
            sector,
            asset_type="satellite_stock",
            current_weight_pct=0.0,
        )

        self.assertEqual(sector["state"], "STRONG")
        self.assertEqual(decision["action"], "PROBE")
        self.assertEqual(decision["primary_reason"], "SECTOR_MOMENTUM_CONFIRMED")
        self.assertIn("SEMI_SECTOR_CONFIRMATION", decision["reason_codes"])

    def test_foundation_pipeline_writes_compatible_snapshot(self):
        from quant_core.models.foundation import pipeline

        histories = {
            "MSFT": _history(drift=0.0015),
            "QQQM": _history(drift=0.001),
            "BIL": _history(drift=0.0001),
            "SPY": _history(drift=0.0006),
            "QQQ": _history(drift=0.0008),
            "VOO": _history(drift=0.0006),
            "^VIX": _history(start=18, drift=0.0),
        }

        def load_history(symbol, period="10y"):
            frame = histories.get(str(symbol).upper())
            return frame.copy() if frame is not None else pd.DataFrame()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            with patch("quant_core.paths.FOUNDATION_MODEL_SNAPSHOT_FILE", str(temp / "foundation.json")), \
                patch("quant_core.paths.MULTI_HORIZON_SNAPSHOT_FILE", str(temp / "multi.json")), \
                patch("quant_core.paths.MARKET_SENTIMENT_SNAPSHOT_FILE", str(temp / "sentiment.json")), \
                patch("quant_core.paths.SYSTEMIC_RISK_SNAPSHOT_FILE", str(temp / "systemic.json")), \
                patch("quant_core.paths.NEWS_INTELLIGENCE_FILE", str(temp / "news.json")), \
                patch("quant_core.paths.FOUNDATION_TRAINING_OBSERVATIONS_FILE", str(temp / "foundation_training.parquet")):
                snapshot = pipeline.run_foundation_job(
                    config={
                        "history_period": "10y",
                        "maximum_symbols": 10,
                        "allow_development_proxy": True,
                        "backend_priority": ["proxy"],
                        "backends": {"proxy": {"enabled": True}},
                        "horizons": [63, 252],
                    },
                    data={
                        "account": {"cash_available": 1000},
                        "holdings": [{"symbol": "QQQM", "shares": 1, "current_price": 100}],
                        "watchlist": [{"symbol": "MSFT"}],
                    },
                    core_universe={"etfs": [{"symbol": "QQQM", "enabled": True}]},
                    satellite_universe={"manual_include": ["MSFT"], "manual_exclude": []},
                    load_history_fn=load_history,
                    now=datetime(2026, 7, 28, 23, 0, 0),
                )

        self.assertEqual(snapshot["status"], "READY")
        self.assertEqual(snapshot["model"]["model_family"], "FOUNDATION_MODEL")
        self.assertEqual(snapshot["model"]["backend"], "proxy")
        self.assertIn("market_sentiment", snapshot)
        self.assertIn("systemic_risk", snapshot)
        self.assertTrue(snapshot["symbols"])
        self.assertTrue(snapshot["core_etfs"])
        self.assertTrue(snapshot["satellite_ranked_pool"])

    def test_foundation_pipeline_blocks_when_real_backend_is_required_and_missing(self):
        from quant_core.models.foundation import pipeline

        histories = {
            "MSFT": _history(drift=0.0015),
            "BIL": _history(drift=0.0001),
            "SPY": _history(drift=0.0006),
            "QQQ": _history(drift=0.0008),
            "VOO": _history(drift=0.0006),
            "^VIX": _history(start=18, drift=0.0),
        }

        def load_history(symbol, period="10y"):
            frame = histories.get(str(symbol).upper())
            return frame.copy() if frame is not None else pd.DataFrame()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            with patch("quant_core.paths.FOUNDATION_MODEL_SNAPSHOT_FILE", str(temp / "foundation.json")), \
                patch("quant_core.paths.MULTI_HORIZON_SNAPSHOT_FILE", str(temp / "multi.json")), \
                patch("quant_core.paths.MARKET_SENTIMENT_SNAPSHOT_FILE", str(temp / "sentiment.json")), \
                patch("quant_core.paths.SYSTEMIC_RISK_SNAPSHOT_FILE", str(temp / "systemic.json")), \
                patch("quant_core.paths.NEWS_INTELLIGENCE_FILE", str(temp / "news.json")), \
                patch("quant_core.paths.FOUNDATION_TRAINING_OBSERVATIONS_FILE", str(temp / "foundation_training.parquet")), \
                patch("quant_core.models.foundation.backends.importlib.util.find_spec", return_value=None):
                snapshot = pipeline.run_foundation_job(
                    config={
                        "history_period": "10y",
                        "maximum_symbols": 10,
                        "backend_priority": ["chronos"],
                        "require_real_backend": True,
                        "allow_development_proxy": False,
                        "horizons": [63, 252],
                    },
                    data={
                        "account": {"cash_available": 1000},
                        "holdings": [],
                        "watchlist": [{"symbol": "MSFT"}],
                    },
                    core_universe={"etfs": []},
                    satellite_universe={"manual_include": ["MSFT"], "manual_exclude": []},
                    load_history_fn=load_history,
                    now=datetime(2026, 7, 28, 23, 0, 0),
                )

        self.assertEqual(snapshot["status"], "MODEL_UNAVAILABLE")
        self.assertEqual(snapshot["model"]["authority"], "BLOCKED")
        self.assertEqual(snapshot["symbols"], [])
        self.assertIn("chronos-forecasting", snapshot["summary"]["installation_hint"])


if __name__ == "__main__":
    unittest.main()
