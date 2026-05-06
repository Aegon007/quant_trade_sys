from module_loader import import_from_path


DEFAULT_STRATEGY_CLASSES = {
    "ma_crossover": "strategies.classic_strategies.MACrossoverStrategy",
    "bollinger": "strategies.classic_strategies.BollingerStrategy",
    "macd": "strategies.classic_strategies.MACDStrategy",
    "rsi": "strategies.classic_strategies.RSIStrategy",
    "ml_lightgbm": "strategies.ml_strategy.LightGBMStrategy",
    "ensemble_voting": "strategies.ensemble_strategy.EnsembleVotingStrategy",
    "deep_tcn": "strategies.deep_learning_strategy.DeepTCNStrategy",
}


def create_strategy(strategy_config):
    strategy_id = strategy_config["id"]
    params = strategy_config.get("params", {})
    class_path = strategy_config.get("strategy_class") or DEFAULT_STRATEGY_CLASSES.get(strategy_id)

    if not class_path:
        raise ValueError(f"未知策略: {strategy_id}")

    strategy_class = import_from_path(class_path)
    if strategy_config.get("params_mode") == "dict":
        return strategy_class(params)
    return strategy_class(**params)
