_EXPORTS = {
    "create_strategy_from_function": ("strategies.base_strategy_adapter", "create_strategy_from_function"),
    "MACrossoverStrategy": ("strategies.classic_strategies", "MACrossoverStrategy"),
    "BollingerStrategy": ("strategies.classic_strategies", "BollingerStrategy"),
    "MACDStrategy": ("strategies.classic_strategies", "MACDStrategy"),
    "RSIStrategy": ("strategies.classic_strategies", "RSIStrategy"),
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _EXPORTS[name]
    from importlib import import_module

    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
