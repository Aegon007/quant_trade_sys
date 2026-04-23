import streamlit as st
import json
import os
import quant_analysis as qa
import ml_strategy as ml_utils
from strategies import (
    MACrossoverStrategy, BollingerStrategy, MACDStrategy, RSIStrategy,
    LightGBMStrategy
)

CONFIG_PATH = os.path.join("config", "strategies.json")

def load_strategies():
    if not os.path.exists(CONFIG_PATH):
        return []
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("strategies", [])

def render_strategy_selector(strategies):
    strategy_names = [s["name"] for s in strategies]
    selected_name = st.selectbox("选择策略", strategy_names)
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
        if strategy_id == "ml_lightgbm":
            return ml_utils.get_ml_signal(symbol, **params)
        elif strategy_id == "ensemble_voting":
            return ml_utils.get_ensemble_signal(symbol, **params)
        else:
            return qa.get_signal_for_strategy(symbol, strategy)
    except Exception as e:
        return "HOLD", f"信号计算异常: {str(e)}"
