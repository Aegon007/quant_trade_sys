import json
import os
from importlib import import_module

from quant_core import paths as qpaths

CONFIG_PATH = qpaths.STRATEGY_CONFIG_FILE

DEFAULT_SIGNAL_FUNCTIONS = {
    "ma_crossover": "quant_core.analytics.quant_analysis.get_signal_ma_crossover",
    "bollinger": "quant_core.analytics.quant_analysis.get_signal_bollinger",
    "macd": "quant_core.analytics.quant_analysis.get_signal_macd",
    "rsi": "quant_core.analytics.quant_analysis.get_signal_rsi",
    "deep_tcn": "strategies.deep_learning_utils.get_deep_tcn_signal",
}


def _import_from_path(dotted_path):
    module_name, _, attr_name = str(dotted_path or "").rpartition(".")
    if not module_name or not attr_name:
        raise ValueError(f"Invalid import path: {dotted_path}")
    module = import_module(module_name)
    return getattr(module, attr_name)

def load_strategies(include_disabled=False):
    if not os.path.exists(CONFIG_PATH):
        return []
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    strategies = data.get("strategies", [])
    if include_disabled:
        return strategies
    return [strategy for strategy in strategies if strategy.get("enabled", True)]

def get_default_strategy_id(strategies):
    for strategy in strategies:
        if strategy.get("is_default"):
            return strategy["id"]
    if not strategies:
        return None
    return strategies[0]["id"]

def get_signal(strategy, symbol):
    """统一的信号获取接口"""
    strategy_id = strategy.get("id")
    params = strategy.get("params", {})
    try:
        signal_function_path = strategy.get("signal_function") or DEFAULT_SIGNAL_FUNCTIONS.get(strategy_id)
        if not signal_function_path:
            return "HOLD", "未知策略"
        signal_function = _import_from_path(signal_function_path)
        return signal_function(symbol, **params)
    except Exception as e:
        return "HOLD", f"信号计算异常: {str(e)}"
