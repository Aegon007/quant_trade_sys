import streamlit as st
import json
import os
import quant_analysis as qa

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

def run_backtest(strategy, symbol):
    func_name = strategy.get("function")
    params = strategy.get("params", {})
    backtest_func = getattr(qa, func_name, None)
    if backtest_func is None:
        st.error(f"回测函数 {func_name} 不存在")
        return None
    return backtest_func(symbol, **params)