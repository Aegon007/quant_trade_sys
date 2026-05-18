from importlib import import_module


DEFAULT_STRATEGY_CLASSES = {
    "ma_crossover": "strategies.classic_strategies.MACrossoverStrategy",
    "bollinger": "strategies.classic_strategies.BollingerStrategy",
    "macd": "strategies.classic_strategies.MACDStrategy",
    "rsi": "strategies.classic_strategies.RSIStrategy",
    "deep_tcn": "strategies.deep_learning_strategy.DeepTCNStrategy",
}


def _import_from_path(dotted_path):
    module_name, _, attr_name = str(dotted_path or "").rpartition(".")
    if not module_name or not attr_name:
        raise ValueError(f"Invalid import path: {dotted_path}")
    module = import_module(module_name)
    return getattr(module, attr_name)


def create_strategy(strategy_config):
    strategy_id = strategy_config["id"]
    params = strategy_config.get("params", {})
    class_path = strategy_config.get("strategy_class") or DEFAULT_STRATEGY_CLASSES.get(strategy_id)

    if not class_path:
        raise ValueError(f"未知策略: {strategy_id}")

    strategy_class = _import_from_path(class_path)
    if strategy_config.get("params_mode") == "dict":
        return strategy_class(params)
    return strategy_class(**params)
