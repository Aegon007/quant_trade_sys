import importlib
import sys
import types
from types import SimpleNamespace

import pandas as pd


def clear_modules(*module_names):
    for module_name in module_names:
        sys.modules.pop(module_name, None)


def reload_module(module_name):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def install_fake_yfinance(histories=None):
    histories = histories or {}

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period="6mo"):
            return histories.get(self.symbol, pd.DataFrame()).copy()

        @property
        def fast_info(self):
            history = histories.get(self.symbol, pd.DataFrame())
            if history.empty:
                last_price = None
            else:
                last_price = history["Close"].iloc[-1]
            return SimpleNamespace(last_price=last_price)

    class FakeTickers:
        def __init__(self, symbols):
            symbol_list = [symbol for symbol in symbols.split() if symbol]
            self.tickers = {symbol: FakeTicker(symbol) for symbol in symbol_list}

    module = types.ModuleType("yfinance")
    module.Ticker = FakeTicker
    module.Tickers = FakeTickers
    sys.modules["yfinance"] = module
    return module


def install_fake_pybroker():
    pybroker_module = types.ModuleType("pybroker")

    class Strategy:
        def __init__(self, *args, **kwargs):
            pass

    class StrategyConfig:
        def __init__(self, initial_cash):
            self.initial_cash = initial_cash

    pybroker_module.Strategy = Strategy
    pybroker_module.StrategyConfig = StrategyConfig

    pybroker_data_module = types.ModuleType("pybroker.data")

    class DataSource:
        def __init__(self):
            pass

    pybroker_data_module.DataSource = DataSource

    sys.modules["pybroker"] = pybroker_module
    sys.modules["pybroker.data"] = pybroker_data_module


def install_fake_backtrader(equity_values):
    context = SimpleNamespace(
        broker=None,
        data=None,
        dataframe=None,
        current_step=0,
        current_len=0,
        position_size=0,
    )

    class FakeBroker:
        def __init__(self):
            self._cash = 0.0
            self._commission = 0.0

        def setcash(self, cash):
            self._cash = cash

        def setcommission(self, commission):
            self._commission = commission

        def getvalue(self):
            index = min(context.current_step, len(equity_values) - 1)
            return equity_values[index]

    class FakePosition:
        @property
        def size(self):
            return context.position_size

    class StrategyBase:
        @property
        def datas(self):
            return [context.data]

        @property
        def broker(self):
            return context.broker

        def getposition(self):
            return FakePosition()

        def buy(self, size):
            context.position_size = size

        def sell(self, size):
            context.position_size = 0

        def __len__(self):
            return context.current_len

    class Line:
        def __init__(self, values):
            self.array = list(values)

    class DateTimeLine:
        def __init__(self, values):
            self.array = list(values)

        def __getitem__(self, index):
            current = self.array[min(context.current_step, len(self.array) - 1)]
            return current

        def date(self, index):
            return self[index].date()

    class DataFeedWrapper:
        def __init__(self, dataframe):
            dataframe = dataframe.copy()
            dataframe.index = pd.to_datetime(dataframe.index)
            self.open = Line(dataframe["Open"])
            self.high = Line(dataframe["High"])
            self.low = Line(dataframe["Low"])
            self.close = Line(dataframe["Close"])
            self.volume = Line(dataframe["Volume"])
            self.datetime = DateTimeLine(dataframe.index.to_pydatetime())

    class FakePandasData:
        def __init__(self, dataname):
            self.dataname = dataname

    class FakeAnalyzer:
        def __init__(self, payload):
            self._payload = payload

        def get_analysis(self):
            return self._payload

    class FakeAnalyzers:
        def __init__(self):
            self._payloads = {
                "returns": {"rtot": 0.05},
                "sharpe": {"sharperatio": 1.25},
                "drawdown": {"max": {"drawdown": 8.0}},
                "trades": {
                    "total": {"total": 2},
                    "won": {"total": 1},
                    "lost": {"total": 1},
                },
            }

        def getbyname(self, name):
            return FakeAnalyzer(self._payloads[name])

    class Cerebro:
        def __init__(self):
            self._strategy_class = None
            self._dataframe = None
            self.broker = FakeBroker()

        def adddata(self, data_feed):
            self._dataframe = data_feed.dataname.copy()
            context.data = DataFeedWrapper(self._dataframe)

        def addstrategy(self, strategy_class):
            self._strategy_class = strategy_class

        def addanalyzer(self, *args, **kwargs):
            return None

        def run(self):
            context.broker = self.broker
            context.current_step = 0
            context.current_len = 0
            context.position_size = 0

            strategy_instance = self._strategy_class()
            strategy_instance.analyzers = FakeAnalyzers()

            for step in range(len(self._dataframe)):
                context.current_step = step
                context.current_len = step + 1
                strategy_instance.next()

            strategy_instance.stop()
            return [strategy_instance]

    analyzers_module = types.ModuleType("backtrader.analyzers")
    analyzers_module.SharpeRatio = object
    analyzers_module.DrawDown = object
    analyzers_module.Returns = object
    analyzers_module.TradeAnalyzer = object

    feeds_module = types.ModuleType("backtrader.feeds")
    feeds_module.PandasData = FakePandasData

    bt_module = types.ModuleType("backtrader")
    bt_module.Strategy = StrategyBase
    bt_module.Cerebro = Cerebro
    bt_module.analyzers = analyzers_module
    bt_module.feeds = feeds_module
    bt_module.TimeFrame = SimpleNamespace(Days="Days")
    bt_module.num2date = lambda value: value

    sys.modules["backtrader"] = bt_module

