_EXPORTS = {
    "BaseBacktestEngine": ("engine.base", "BaseBacktestEngine"),
    "BaseStrategy": ("engine.base", "BaseStrategy"),
    "BacktestResult": ("engine.base", "BacktestResult"),
    "PyBrokerEngine": ("engine.pybroker_engine", "PyBrokerEngine"),
    "BacktraderEngine": ("engine.backtrader_engine", "BacktraderEngine"),
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
