from strategies import (
    BollingerStrategy,
    EnsembleVotingStrategy,
    LightGBMStrategy,
    MACDStrategy,
    MACrossoverStrategy,
    RSIStrategy,
)


def create_strategy(strategy_config):
    strategy_id = strategy_config["id"]
    params = strategy_config.get("params", {})

    if strategy_id == "ma_crossover":
        return MACrossoverStrategy(**params)
    if strategy_id == "bollinger":
        return BollingerStrategy(**params)
    if strategy_id == "macd":
        return MACDStrategy(**params)
    if strategy_id == "rsi":
        return RSIStrategy(**params)
    if strategy_id == "ml_lightgbm":
        return LightGBMStrategy(params)
    if strategy_id == "ensemble_voting":
        return EnsembleVotingStrategy(params)

    raise ValueError(f"未知策略: {strategy_id}")

