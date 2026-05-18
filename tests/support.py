import importlib
import sys
import types
from types import SimpleNamespace

import pandas as pd


_COMPAT_ALIAS_MODULES = {
    "data_utils": "quant_core.data.storage",
    "portfolio_actions": "quant_core.portfolio.actions",
    "transactions": "quant_core.ledger.transactions",
    "slack_command_parser": "integrations.slack.command_parser",
    "slack_command_service": "integrations.slack.command_service",
    "quant_analysis": "quant_core.analytics.quant_analysis",
    "monte_carlo": "quant_core.analytics.monte_carlo",
    "portfolio_metrics": "quant_core.portfolio.metrics",
    "portfolio_advisor": "quant_core.portfolio.risk",
    "risk_gate": "quant_core.risk.risk_gate",
    "capital_allocator": "quant_core.portfolio.allocation",
    "position_advisor": "quant_core.portfolio.position",
    "event_news": "quant_core.events.event_news",
    "event_fetcher": "quant_core.events.event_fetcher",
    "news_summary": "quant_core.events.news_summary",
    "analyst_consensus": "quant_core.events.analyst_consensus",
    "finbert_sentiment": "quant_core.events.finbert_sentiment",
    "notification_config": "quant_core.notifications.notification_config",
    "notification_channels": "quant_core.notifications.notification_channels",
    "alert_engine": "quant_core.notifications.alert_engine",
    "system_snapshot": "quant_core.snapshots.system_snapshot",
}


def clear_modules(*module_names):
    names = set(module_names)
    for module_name in list(module_names):
        alias_name = _COMPAT_ALIAS_MODULES.get(module_name)
        if alias_name:
            names.add(alias_name)
    parent_attrs = []
    for module_name in names:
        if "." in module_name:
            parent_name, attr_name = module_name.rsplit(".", 1)
            parent_attrs.append((parent_name, attr_name))
    for module_name in names:
        sys.modules.pop(module_name, None)
    for parent_name, attr_name in parent_attrs:
        parent_module = sys.modules.get(parent_name)
        if parent_module is not None and hasattr(parent_module, attr_name):
            try:
                delattr(parent_module, attr_name)
            except Exception:
                pass


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
