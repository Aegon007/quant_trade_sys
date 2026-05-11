import streamlit as st
import json
import os
from module_loader import import_from_path
from quant_core import paths as qpaths

CONFIG_PATH = qpaths.STRATEGY_CONFIG_FILE

DEFAULT_SIGNAL_FUNCTIONS = {
    "ma_crossover": "quant_core.analytics.quant_analysis.get_signal_ma_crossover",
    "bollinger": "quant_core.analytics.quant_analysis.get_signal_bollinger",
    "macd": "quant_core.analytics.quant_analysis.get_signal_macd",
    "rsi": "quant_core.analytics.quant_analysis.get_signal_rsi",
    "ml_lightgbm": "ml_strategy.get_ml_signal",
    "ensemble_voting": "ml_strategy.get_ensemble_signal",
    "deep_tcn": "deep_learning_strategy.get_deep_tcn_signal",
}

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

def render_strategy_selector(strategies, default_strategy_id=None):
    if not strategies:
        return None
    strategy_names = [s["name"] for s in strategies]
    strategy_ids = [s["id"] for s in strategies]
    if default_strategy_id in strategy_ids:
        default_index = strategy_ids.index(default_strategy_id)
    else:
        default_index = 0
    selected_name = st.selectbox("选择策略", strategy_names, index=default_index)
    selected_strategy = next((s for s in strategies if s["name"] == selected_name), None)
    return selected_strategy

def display_strategy_description(strategy):
    if strategy and "description" in strategy:
        st.info(strategy["description"])

def get_signal(strategy, symbol):
    """统一的信号获取接口"""
    strategy_id = strategy.get("id")
    params = strategy.get("params", {})
    try:
        signal_function_path = strategy.get("signal_function") or DEFAULT_SIGNAL_FUNCTIONS.get(strategy_id)
        if not signal_function_path:
            return "HOLD", "未知策略"
        signal_function = import_from_path(signal_function_path)
        return signal_function(symbol, **params)
    except Exception as e:
        return "HOLD", f"信号计算异常: {str(e)}"
