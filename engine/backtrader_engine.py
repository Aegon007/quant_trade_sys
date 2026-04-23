import backtrader as bt
import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any
from datetime import datetime

from .base import BaseBacktestEngine, BaseStrategy, BacktestResult

class PandasDataFeed(bt.feeds.PandasData):
    """
    自定义 Pandas 数据源适配器。
    将我们标准化的 DataFrame 映射到 Backtrader 所需的数据线。
    """
    params = (
        ('datetime', None),       # 使用 DataFrame 的 index 作为时间
        ('open', 'Open'),
        ('high', 'High'),
        ('low', 'Low'),
        ('close', 'Close'),
        ('volume', 'Volume'),
        ('openinterest', -1),     # 我们没有持仓量数据
    )

class BacktraderEngine(BaseBacktestEngine):
    """
    Backtrader 回测引擎适配器。
    负责将我们的通用接口翻译为 Backtrader 的 Cerebro 引擎调用。
    """
    
    def __init__(self, initial_cash: float = 100000, commission: float = 0.001):
        """
        初始化 Backtrader 引擎。

        Args:
            initial_cash: 初始资金
            commission: 佣金费率（默认 0.1%）
        """
        super().__init__(initial_cash)
        self.commission = commission
        self.cerebro = None
        self._strategy_class = None

    def set_data(self, data: pd.DataFrame) -> None:
        """
        将标准化的 DataFrame 设置为回测数据。

        Args:
            data: 包含 OHLCV 列的 DataFrame
        """
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        for col in required_cols:
            if col not in data.columns:
                raise ValueError(f"数据必须包含 {col} 列")

        # 确保索引是 DatetimeIndex
        if not isinstance(data.index, pd.DatetimeIndex):
            data = data.copy()
            data.index = pd.to_datetime(data.index)

        self.data = data.copy()

    def set_strategy(self, strategy: BaseStrategy) -> None:
        """
        将我们的 BaseStrategy 适配为 Backtrader 的 Strategy 类。

        Args:
            strategy: 实现了 BaseStrategy 接口的策略对象
        """
        self.strategy = strategy
        user_strategy = strategy  # 闭包引用

        class BtStrategyAdapter(bt.Strategy):
            """
            内部适配器类，继承自 bt.Strategy，将 Backtrader 的回调转接到我们的 BaseStrategy。
            """
            def __init__(self):
                # 将数据传递给用户策略
                # 注意：这里无法直接获取整个 DataFrame，需要从 self.datas 中提取
                self.user_strategy = user_strategy
                self.user_strategy.set_data(self._extract_dataframe())

                # 调用用户策略的初始化
                self.user_strategy.init()

                # 用于记录交易的列表
                self.trades = []
                self.equity = []

            def _extract_dataframe(self) -> pd.DataFrame:
                """从 Backtrader 的数据线中重构 DataFrame"""
                data = self.datas[0]
                df = pd.DataFrame({
                    'Open': data.open.array,
                    'High': data.high.array,
                    'Low': data.low.array,
                    'Close': data.close.array,
                    'Volume': data.volume.array,
                })
                # 重建时间索引
                df.index = pd.to_datetime([bt.num2date(x) for x in data.datetime.array])
                return df

            def next(self):
                """每个时间步调用一次"""
                # 获取当前索引
                current_idx = len(self) - 1

                # 调用用户策略，获取信号
                signal = self.user_strategy.next(current_idx)

                # 如果没有信号或没有持仓，不操作
                if signal is None:
                    return

                action = signal.get('action', 'HOLD')
                size = signal.get('size', 100)

                # 检查当前持仓
                current_position = self.getposition().size

                if action == 'BUY' and current_position == 0:
                    self.buy(size=size)
                elif action == 'SELL' and current_position > 0:
                    self.sell(size=current_position)

            def notify_order(self, order):
                """订单状态变化通知"""
                if order.status in [order.Completed]:
                    if order.isbuy():
                        action = 'BUY'
                    else:
                        action = 'SELL'

                    self.trades.append({
                        'date': bt.num2date(self.datas[0].datetime[0]),
                        'action': action,
                        'price': order.executed.price,
                        'size': order.executed.size,
                        'value': order.executed.value,
                        'commission': order.executed.comm
                    })

            def notify_trade(self, trade):
                """交易完成通知（用于计算盈亏）"""
                if trade.isclosed:
                    self.log(f'TRADE CLOSED, Gross {trade.pnl:.2f}, Net {trade.pnlcomm:.2f}')

            def log(self, txt, dt=None):
                """日志记录"""
                dt = dt or self.datas[0].datetime.date(0)
                print(f'{dt.isoformat()} {txt}')

            def stop(self):
                """回测结束时调用，记录权益曲线"""
                self.equity = [self.broker.getvalue() for _ in range(len(self))]

        self._strategy_class = BtStrategyAdapter

    def run(self, **kwargs) -> BacktestResult:
        """
        执行回测并返回标准化结果。

        Returns:
            BacktestResult: 包含各项绩效指标的标准化结果对象
        """
        if self.data is None:
            raise ValueError("请先调用 set_data 设置数据")
        if self._strategy_class is None:
            raise ValueError("请先调用 set_strategy 设置策略")

        # 1. 创建 Cerebro 引擎
        self.cerebro = bt.Cerebro()

        # 2. 添加数据源
        data_feed = PandasDataFeed(dataname=self.data)
        self.cerebro.adddata(data_feed)

        # 3. 设置策略
        self.cerebro.addstrategy(self._strategy_class)

        # 4. 设置初始资金
        self.cerebro.broker.setcash(self.initial_cash)

        # 5. 设置佣金
        self.cerebro.broker.setcommission(commission=self.commission)

        # 6. 添加分析器
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                                 riskfreerate=0.02, annualize=True, timeframe=bt.TimeFrame.Days)
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

        # 7. 执行回测
        print(f'初始资金: {self.cerebro.broker.getvalue():.2f}')
        results = self.cerebro.run()
        strategy_instance = results[0]  # 获取策略实例
        print(f'最终资金: {self.cerebro.broker.getvalue():.2f}')

        # 8. 提取分析结果
        analyzers = strategy_instance.analyzers

        # 总收益率
        returns_analyzer = analyzers.getbyname('returns')
        total_return = returns_analyzer.get_analysis().get('rtot', 0.0)

        # 夏普比率
        sharpe_analyzer = analyzers.getbyname('sharpe')
        sharpe_ratio = sharpe_analyzer.get_analysis().get('sharperatio', 0.0)
        if sharpe_ratio is None:
            sharpe_ratio = 0.0

        # 最大回撤
        drawdown_analyzer = analyzers.getbyname('drawdown')
        max_drawdown = drawdown_analyzer.get_analysis().get('max', {}).get('drawdown', 0.0) / 100.0

        # 胜率与交易次数
        trade_analyzer = analyzers.getbyname('trades')
        trade_analysis = trade_analyzer.get_analysis()
        total_trades = trade_analysis.get('total', {}).get('total', 0)

        won = trade_analysis.get('won', {}).get('total', 0)
        lost = trade_analysis.get('lost', {}).get('total', 0)
        win_rate = won / total_trades if total_trades > 0 else 0.0

        # 权益曲线（从策略实例获取）
        equity_curve = getattr(strategy_instance, 'equity', [])
        if not equity_curve:
            equity_curve = [self.initial_cash, self.cerebro.broker.getvalue()]

        # 交易日志
        trade_log = getattr(strategy_instance, 'trades', [])

        return BacktestResult(
            total_return=total_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            total_trades=total_trades,
            equity_curve=equity_curve,
            trade_log=trade_log,
            metadata={'engine': 'backtrader', 'final_value': self.cerebro.broker.getvalue()}
        )