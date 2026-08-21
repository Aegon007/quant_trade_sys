from __future__ import annotations

import importlib.util
import math
import sys
import warnings
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BackendCapabilities:
    name: str
    model_family: str
    status: str
    supports_covariates: bool
    supports_quantiles: bool
    message: str = ""


class FoundationModelBackend(Protocol):
    name: str

    def capabilities(self) -> BackendCapabilities:
        ...

    def forecast(
        self,
        histories: Mapping[str, pd.DataFrame],
        *,
        symbols: Sequence[str],
        horizons: Sequence[int],
        benchmarks: Mapping[str, str],
    ) -> dict[str, dict]:
        ...


def _close(frame) -> pd.Series:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "Close" not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame["Close"], errors="coerce").dropna().sort_index()


def _horizon_returns(series: pd.Series, horizon: int) -> pd.Series:
    if len(series) <= horizon:
        return pd.Series(dtype=float)
    returns = series.pct_change(horizon).shift(-horizon).dropna()
    return returns.tail(756)


def _latest_return(series: pd.Series, horizon: int) -> float:
    if len(series) <= horizon:
        return 0.0
    start = float(series.iloc[-horizon - 1])
    end = float(series.iloc[-1])
    if start <= 0 or not math.isfinite(start) or not math.isfinite(end):
        return 0.0
    return end / start - 1.0


def _quantiles(values: pd.Series, *, trend_adjustment: float) -> tuple[float, float, float]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return trend_adjustment - 0.08, trend_adjustment, trend_adjustment + 0.08
    p10 = float(clean.quantile(0.10)) + trend_adjustment
    p50 = float(clean.quantile(0.50)) + trend_adjustment
    p90 = float(clean.quantile(0.90)) + trend_adjustment
    return max(p10, -0.95), max(p50, -0.95), max(p90, -0.95)


def _probability(values: pd.Series, threshold: float) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return 0.5
    return float((clean > threshold).mean())


class ProxyFoundationBackend:
    name = "proxy"

    def __init__(self, *, trend_adjustment_weight: float = 0.35):
        self.trend_adjustment_weight = float(trend_adjustment_weight)

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name=self.name,
            model_family="FOUNDATION_PROXY",
            status="READY",
            supports_covariates=True,
            supports_quantiles=True,
            message="Deterministic distribution proxy; use only until a real foundation backend is installed.",
        )

    def forecast(
        self,
        histories: Mapping[str, pd.DataFrame],
        *,
        symbols: Sequence[str],
        horizons: Sequence[int],
        benchmarks: Mapping[str, str],
    ) -> dict[str, dict]:
        risk_free_symbol = str(benchmarks.get("risk_free") or "BIL").upper()
        market_symbol = str(benchmarks.get("market") or "SPY").upper()
        growth_symbol = str(benchmarks.get("growth") or "QQQ").upper()
        risk_free = _close(histories.get(risk_free_symbol))
        market = _close(histories.get(market_symbol))
        growth = _close(histories.get(growth_symbol))
        forecasts: dict[str, dict] = {}
        for raw_symbol in symbols:
            symbol = str(raw_symbol or "").strip().upper()
            series = _close(histories.get(symbol))
            if series.empty:
                continue
            latest_price = float(series.iloc[-1])
            horizon_payload = {}
            for horizon in horizons:
                horizon = int(horizon)
                returns = _horizon_returns(series, horizon)
                recent_trend = _latest_return(series, min(horizon, 126))
                trend_adjustment = max(min(recent_trend * self.trend_adjustment_weight, 0.12), -0.12)
                p10, p50, p90 = _quantiles(returns, trend_adjustment=trend_adjustment)
                rf_returns = _horizon_returns(risk_free, horizon)
                market_returns = _horizon_returns(market, horizon)
                growth_returns = _horizon_returns(growth, horizon)
                rf_threshold = float(rf_returns.median()) if not rf_returns.empty else 0.01 * horizon / 252.0
                market_threshold = float(market_returns.median()) if not market_returns.empty else 0.0
                growth_threshold = float(growth_returns.median()) if not growth_returns.empty else market_threshold
                shifted = returns + trend_adjustment
                confidence = min(max(len(returns) / 180.0, 0.25), 0.82)
                horizon_payload[str(horizon)] = {
                    "return_range": {"p10": p10, "p50": p50, "p90": p90},
                    "price_range": {
                        "p10": latest_price * (1.0 + p10),
                        "p50": latest_price * (1.0 + p50),
                        "p90": latest_price * (1.0 + p90),
                    },
                    "positive_return_probability": _probability(shifted, 0.0),
                    "risk_free_outperformance_probability": _probability(shifted, rf_threshold),
                    "market_outperformance_probability": _probability(shifted, market_threshold),
                    "growth_outperformance_probability": _probability(shifted, growth_threshold),
                    "expected_return": p50,
                    "forecast_confidence": round(confidence, 3),
                    "sample_count": int(len(returns)),
                }
            forecasts[symbol] = {
                "symbol": symbol,
                "latest_price": latest_price,
                "horizons": horizon_payload,
            }
        return forecasts


class ChronosFoundationBackend:
    name = "chronos"

    def __init__(
        self,
        *,
        model_name: str = "amazon/chronos-2",
        revision: str = "",
        device: str = "auto",
        torch_dtype: str = "auto",
        context_length: int = 2048,
        batch_size: int = 8,
        cross_learning: bool = False,
        quantile_levels: Sequence[float] | None = None,
    ):
        self.model_name = str(model_name or "amazon/chronos-2").strip()
        self.revision = str(revision or "").strip()
        self.device = str(device or "auto").strip().lower()
        self.torch_dtype = str(torch_dtype or "auto").strip().lower()
        self.context_length = max(int(context_length or 2048), 64)
        self.batch_size = max(int(batch_size or 8), 1)
        self.cross_learning = bool(cross_learning)
        self.quantile_levels = list(quantile_levels or [0.1, 0.5, 0.9])
        self._pipeline = None
        self._runtime_device = "unknown"

    @property
    def is_chronos2(self) -> bool:
        return "chronos-2" in self.model_name.lower()

    def capabilities(self) -> BackendCapabilities:
        chronos_module = sys.modules.get("chronos")
        chronos_available = chronos_module is not None
        if not chronos_available:
            try:
                chronos_available = importlib.util.find_spec("chronos") is not None
            except ValueError:
                chronos_available = False
        if not chronos_available:
            return BackendCapabilities(
                name=self.name,
                model_family="CHRONOS",
                status="UNAVAILABLE",
                supports_covariates=False,
                supports_quantiles=True,
                message="Python package 'chronos-forecasting' is not installed. Install it in ~/venv to enable the real foundation backend.",
            )
        torch_module = sys.modules.get("torch")
        torch_available = torch_module is not None
        if not torch_available:
            try:
                torch_available = importlib.util.find_spec("torch") is not None
            except ValueError:
                torch_available = False
        if not torch_available:
            return BackendCapabilities(
                name=self.name,
                model_family="CHRONOS",
                status="UNAVAILABLE",
                supports_covariates=False,
                supports_quantiles=True,
                message="Python package 'torch' is not installed. Chronos requires PyTorch.",
            )
        return BackendCapabilities(
            name=self.name,
            model_family="CHRONOS",
            status="READY",
            supports_covariates=False,
            supports_quantiles=True,
            message=f"Real Chronos backend ready: {self.model_name}{('@' + self.revision) if self.revision else ''}",
        )

    def _resolve_device(self, torch_module: Any) -> str:
        if self.device and self.device != "auto":
            return self.device
        try:
            if bool(torch_module.cuda.is_available()):
                return "cuda"
        except Exception:
            pass
        try:
            mps = getattr(getattr(torch_module, "backends", None), "mps", None)
            if mps is not None and bool(mps.is_available()):
                return "mps"
        except Exception:
            pass
        return "cpu"

    def _resolve_dtype(self, torch_module: Any, device: str):
        if self.torch_dtype in {"", "auto", "none"}:
            if device == "cuda" and hasattr(torch_module, "bfloat16"):
                return getattr(torch_module, "bfloat16")
            return None
        return getattr(torch_module, self.torch_dtype, None)

    def _load_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        import torch
        try:
            from transformers import logging as transformers_logging
            transformers_logging.set_verbosity_error()
        except Exception:
            pass
        try:
            from chronos import BaseChronosPipeline as Pipeline
        except Exception:
            try:
                from chronos import ChronosPipeline as Pipeline
            except Exception:
                from chronos import ChronosBoltPipeline as Pipeline

        device = self._resolve_device(torch)
        dtype = self._resolve_dtype(torch, device)
        kwargs = {}
        if device:
            kwargs["device_map"] = device
        if dtype is not None:
            kwargs["torch_dtype"] = dtype
        if self.revision:
            kwargs["revision"] = self.revision
        try:
            pipeline = Pipeline.from_pretrained(self.model_name, **kwargs)
        except TypeError:
            pipeline = Pipeline.from_pretrained(self.model_name)
            if hasattr(pipeline, "to"):
                pipeline = pipeline.to(device)
        self._pipeline = pipeline
        self._runtime_device = device
        return pipeline

    def _contexts(self, histories: Mapping[str, pd.DataFrame], symbols: Sequence[str]):
        import torch

        contexts = []
        context_symbols = []
        latest_prices = {}
        for raw_symbol in symbols:
            symbol = str(raw_symbol or "").strip().upper()
            series = _close(histories.get(symbol)).tail(self.context_length)
            if len(series) < 64:
                continue
            values = series.astype(float).to_numpy()
            if not np.isfinite(values).all() or values[-1] <= 0:
                continue
            contexts.append(torch.tensor(values, dtype=getattr(torch, "float32", None)))
            context_symbols.append(symbol)
            latest_prices[symbol] = float(values[-1])
        return context_symbols, contexts, latest_prices

    @staticmethod
    def _to_numpy(value):
        if hasattr(value, "detach"):
            value = value.detach()
        if hasattr(value, "cpu"):
            value = value.cpu()
        if hasattr(value, "numpy"):
            value = value.numpy()
        return np.asarray(value, dtype=float)

    def forecast(
        self,
        histories: Mapping[str, pd.DataFrame],
        *,
        symbols: Sequence[str],
        horizons: Sequence[int],
        benchmarks: Mapping[str, str],
    ) -> dict[str, dict]:
        capabilities = self.capabilities()
        if capabilities.status != "READY":
            raise RuntimeError(capabilities.message)
        pipeline = self._load_pipeline()
        horizons = sorted({int(horizon) for horizon in horizons if int(horizon) > 0})
        if not horizons:
            return {}
        max_horizon = max(horizons)
        risk_free_symbol = str(benchmarks.get("risk_free") or "BIL").upper()
        market_symbol = str(benchmarks.get("market") or "SPY").upper()
        growth_symbol = str(benchmarks.get("growth") or "QQQ").upper()
        risk_free = _close(histories.get(risk_free_symbol))
        market = _close(histories.get(market_symbol))
        growth = _close(histories.get(growth_symbol))
        context_symbols, contexts, latest_prices = self._contexts(histories, symbols)
        forecasts: dict[str, dict] = {}
        if not contexts:
            return forecasts
        if self.is_chronos2 and hasattr(pipeline, "predict_df"):
            return self._forecast_with_predict_df(
                pipeline,
                histories,
                symbols=context_symbols,
                latest_prices=latest_prices,
                horizons=horizons,
                benchmarks=benchmarks,
            )

        median_index = min(range(len(self.quantile_levels)), key=lambda idx: abs(float(self.quantile_levels[idx]) - 0.5))
        low_index = min(range(len(self.quantile_levels)), key=lambda idx: abs(float(self.quantile_levels[idx]) - 0.1))
        high_index = min(range(len(self.quantile_levels)), key=lambda idx: abs(float(self.quantile_levels[idx]) - 0.9))

        for start in range(0, len(contexts), self.batch_size):
            batch_symbols = context_symbols[start:start + self.batch_size]
            batch_contexts = contexts[start:start + self.batch_size]
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*past_key_values.*", category=FutureWarning)
                warnings.filterwarnings("ignore", message=".*past_key_values.*", category=UserWarning)
                try:
                    quantiles, mean = pipeline.predict_quantiles(
                        inputs=batch_contexts,
                        prediction_length=max_horizon,
                        quantile_levels=self.quantile_levels,
                    )
                except TypeError:
                    quantiles, mean = pipeline.predict_quantiles(
                        context=batch_contexts,
                        prediction_length=max_horizon,
                        quantile_levels=self.quantile_levels,
                    )
            quantile_array = self._to_numpy(quantiles)
            mean_array = self._to_numpy(mean)
            for batch_index, symbol in enumerate(batch_symbols):
                latest_price = float(latest_prices[symbol])
                horizon_payload = {}
                for horizon in horizons:
                    step = horizon - 1
                    p10_price = float(quantile_array[batch_index, step, low_index])
                    p50_price = float(quantile_array[batch_index, step, median_index])
                    p90_price = float(quantile_array[batch_index, step, high_index])
                    mean_price = float(mean_array[batch_index, step]) if mean_array.ndim >= 2 else p50_price
                    p10 = p10_price / latest_price - 1.0
                    p50 = p50_price / latest_price - 1.0
                    p90 = p90_price / latest_price - 1.0
                    rf_returns = _horizon_returns(risk_free, horizon)
                    market_returns = _horizon_returns(market, horizon)
                    growth_returns = _horizon_returns(growth, horizon)
                    rf_threshold = float(rf_returns.median()) if not rf_returns.empty else 0.01 * horizon / 252.0
                    market_threshold = float(market_returns.median()) if not market_returns.empty else 0.0
                    growth_threshold = float(growth_returns.median()) if not growth_returns.empty else market_threshold
                    samples = np.array([p10, p50, p90, mean_price / latest_price - 1.0], dtype=float)
                    forecast_confidence = min(max(len(_close(histories.get(symbol))) / max(self.context_length, 1), 0.35), 0.9)
                    horizon_payload[str(horizon)] = {
                        "return_range": {"p10": max(p10, -0.95), "p50": max(p50, -0.95), "p90": max(p90, -0.95)},
                        "price_range": {"p10": p10_price, "p50": p50_price, "p90": p90_price},
                        "positive_return_probability": float((samples > 0.0).mean()),
                        "risk_free_outperformance_probability": float((samples > rf_threshold).mean()),
                        "market_outperformance_probability": float((samples > market_threshold).mean()),
                        "growth_outperformance_probability": float((samples > growth_threshold).mean()),
                        "expected_return": p50,
                        "forecast_confidence": round(forecast_confidence, 3),
                        "sample_count": int(len(_horizon_returns(_close(histories.get(symbol)), horizon))),
                    }
                forecasts[symbol] = {
                    "symbol": symbol,
                    "latest_price": latest_price,
                    "source_backend": self.name,
                    "runtime_device": self._runtime_device,
                    "model_name": self.model_name,
                    "revision": self.revision or None,
                    "horizons": horizon_payload,
                }
        return forecasts

    def _forecast_with_predict_df(
        self,
        pipeline,
        histories: Mapping[str, pd.DataFrame],
        *,
        symbols: Sequence[str],
        latest_prices: Mapping[str, float],
        horizons: Sequence[int],
        benchmarks: Mapping[str, str],
    ) -> dict[str, dict]:
        max_horizon = max(horizons)
        rows = []
        for symbol in symbols:
            series = _close(histories.get(symbol)).tail(self.context_length)
            if len(series) < 64:
                continue
            for timestamp, value in series.items():
                rows.append(
                    {
                        "item_id": symbol,
                        "timestamp": pd.Timestamp(timestamp).normalize(),
                        "target": float(value),
                    }
                )
        if not rows:
            return {}
        context_df = pd.DataFrame(rows).sort_values(["item_id", "timestamp"])
        predictions = pipeline.predict_df(
            context_df,
            id_column="item_id",
            timestamp_column="timestamp",
            target="target",
            prediction_length=max_horizon,
            quantile_levels=self.quantile_levels,
            batch_size=self.batch_size,
            context_length=self.context_length,
            cross_learning=self.cross_learning,
            validate_inputs=False,
        )
        risk_free_symbol = str(benchmarks.get("risk_free") or "BIL").upper()
        market_symbol = str(benchmarks.get("market") or "SPY").upper()
        growth_symbol = str(benchmarks.get("growth") or "QQQ").upper()
        risk_free = _close(histories.get(risk_free_symbol))
        market = _close(histories.get(market_symbol))
        growth = _close(histories.get(growth_symbol))
        forecasts: dict[str, dict] = {}
        low_key = str(self.quantile_levels[min(range(len(self.quantile_levels)), key=lambda idx: abs(float(self.quantile_levels[idx]) - 0.1))])
        median_key = str(self.quantile_levels[min(range(len(self.quantile_levels)), key=lambda idx: abs(float(self.quantile_levels[idx]) - 0.5))])
        high_key = str(self.quantile_levels[min(range(len(self.quantile_levels)), key=lambda idx: abs(float(self.quantile_levels[idx]) - 0.9))])
        for symbol in symbols:
            target_names = (
                predictions["target_name"].astype(str)
                if "target_name" in predictions.columns
                else pd.Series(["target"] * len(predictions), index=predictions.index)
            )
            symbol_predictions = predictions[
                (predictions["item_id"].astype(str).str.upper() == symbol)
                & (target_names == "target")
            ].reset_index(drop=True)
            if len(symbol_predictions) < max_horizon:
                continue
            latest_price = float(latest_prices[symbol])
            horizon_payload = {}
            for horizon in horizons:
                row = symbol_predictions.iloc[int(horizon) - 1]
                p10_price = float(row.get(low_key))
                p50_price = float(row.get(median_key))
                p90_price = float(row.get(high_key))
                mean_price = float(row.get("predictions", p50_price))
                p10 = p10_price / latest_price - 1.0
                p50 = p50_price / latest_price - 1.0
                p90 = p90_price / latest_price - 1.0
                rf_returns = _horizon_returns(risk_free, int(horizon))
                market_returns = _horizon_returns(market, int(horizon))
                growth_returns = _horizon_returns(growth, int(horizon))
                rf_threshold = float(rf_returns.median()) if not rf_returns.empty else 0.01 * int(horizon) / 252.0
                market_threshold = float(market_returns.median()) if not market_returns.empty else 0.0
                growth_threshold = float(growth_returns.median()) if not growth_returns.empty else market_threshold
                samples = np.array([p10, p50, p90, mean_price / latest_price - 1.0], dtype=float)
                forecast_confidence = min(max(len(_close(histories.get(symbol))) / max(self.context_length, 1), 0.35), 0.9)
                horizon_payload[str(horizon)] = {
                    "return_range": {"p10": max(p10, -0.95), "p50": max(p50, -0.95), "p90": max(p90, -0.95)},
                    "price_range": {"p10": p10_price, "p50": p50_price, "p90": p90_price},
                    "positive_return_probability": float((samples > 0.0).mean()),
                    "risk_free_outperformance_probability": float((samples > rf_threshold).mean()),
                    "market_outperformance_probability": float((samples > market_threshold).mean()),
                    "growth_outperformance_probability": float((samples > growth_threshold).mean()),
                    "expected_return": p50,
                    "forecast_confidence": round(forecast_confidence, 3),
                    "sample_count": int(len(_horizon_returns(_close(histories.get(symbol)), int(horizon)))),
                }
            forecasts[symbol] = {
                "symbol": symbol,
                "latest_price": latest_price,
                "source_backend": self.name,
                "runtime_device": self._runtime_device,
                "model_name": self.model_name,
                "revision": self.revision or None,
                "forecast_api": "predict_df",
                "cross_learning": self.cross_learning,
                "horizons": horizon_payload,
            }
        return forecasts


class UnavailableFoundationBackend:
    name = "unavailable"

    def __init__(self, *, attempts: Sequence[Mapping] | None = None, require_real_backend: bool = True):
        self.attempts = [dict(item or {}) for item in list(attempts or [])]
        self.require_real_backend = bool(require_real_backend)

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name=self.name,
            model_family="REAL_BACKEND_REQUIRED",
            status="UNAVAILABLE",
            supports_covariates=False,
            supports_quantiles=False,
            message="No real foundation-model backend is available. Install chronos-forecasting or enable a validated backend before using model recommendations.",
        )

    def forecast(self, histories, *, symbols, horizons, benchmarks):
        raise RuntimeError(self.capabilities().message)


class OptionalPackageBackend:
    def __init__(self, *, name: str, package_name: str, model_family: str, supports_covariates: bool):
        self.name = name
        self.package_name = package_name
        self.model_family = model_family
        self.supports_covariates = bool(supports_covariates)

    def capabilities(self) -> BackendCapabilities:
        if importlib.util.find_spec(self.package_name) is None:
            return BackendCapabilities(
                name=self.name,
                model_family=self.model_family,
                status="UNAVAILABLE",
                supports_covariates=self.supports_covariates,
                supports_quantiles=True,
                message=f"Python package '{self.package_name}' is not installed.",
            )
        return BackendCapabilities(
            name=self.name,
            model_family=self.model_family,
            status="AVAILABLE_NOT_WIRED",
            supports_covariates=self.supports_covariates,
            supports_quantiles=True,
            message="Package is installed, but production adapter wiring is pending validation.",
        )

    def forecast(self, histories, *, symbols, horizons, benchmarks):
        raise RuntimeError(self.capabilities().message)


def build_backend(name: str, config: Mapping | None = None) -> FoundationModelBackend:
    normalized = str(name or "proxy").strip().lower()
    config = dict(config or {})
    if normalized == "timesfm":
        return OptionalPackageBackend(
            name="timesfm",
            package_name="timesfm",
            model_family="TIMESFM",
            supports_covariates=bool(config.get("supports_covariates", True)),
        )
    if normalized == "chronos":
        return ChronosFoundationBackend(
            model_name=str(config.get("model_name") or "amazon/chronos-2"),
            revision=str(config.get("revision") or ""),
            device=str(config.get("device") or "auto"),
            torch_dtype=str(config.get("torch_dtype") or "auto"),
            context_length=int(config.get("context_length") or 2048),
            batch_size=int(config.get("batch_size") or 8),
            cross_learning=bool(config.get("cross_learning", False)),
            quantile_levels=list(config.get("quantile_levels") or [0.1, 0.5, 0.9]),
        )
    if normalized == "moment":
        return OptionalPackageBackend(
            name="moment",
            package_name="momentfm",
            model_family="MOMENT",
            supports_covariates=False,
        )
    return ProxyFoundationBackend(
        trend_adjustment_weight=float(config.get("trend_adjustment_weight", 0.35) or 0.35)
    )


def select_backend(config: Mapping) -> tuple[FoundationModelBackend, list[dict]]:
    backends = dict(config.get("backends", {}) or {})
    attempts = []
    for name in list(config.get("backend_priority", []) or ["proxy"]):
        backend_config = dict(backends.get(name, {}) or {})
        if not bool(backend_config.get("enabled", True)):
            attempts.append({"name": name, "status": "DISABLED", "message": "Backend disabled in config."})
            continue
        backend = build_backend(str(name), backend_config)
        capabilities = backend.capabilities()
        attempts.append(capabilities.__dict__)
        if capabilities.status == "READY":
            return backend, attempts
    allow_proxy = bool(config.get("allow_development_proxy", False))
    proxy_config = dict(backends.get("proxy", {}) or {})
    if allow_proxy and bool(proxy_config.get("enabled", False)):
        proxy = build_backend("proxy", proxy_config)
        attempts.append(proxy.capabilities().__dict__)
        return proxy, attempts
    unavailable = UnavailableFoundationBackend(attempts=attempts, require_real_backend=True)
    attempts.append(unavailable.capabilities().__dict__)
    return unavailable, attempts
