import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any
import pybroker as pb
from pybroker import Strategy, StrategyConfig
from .base import BaseBacktestEngine, BaseStrategy, BacktestResult

class PyBrokerEngine(BaseBacktestEngine):
    """PyBroker 回测引擎适配器"""
    
    def __init__(self, initial_cash: float = 100000):
        super().__init__(initial_cash)
        self._pybroker_strategy: Optional[Strategy] = None
        self._symbol = "STOCK"

    def set_data(self, data: pd.DataFrame) -> None:
        """
        将 DataFrame 转换为 PyBroker 可接受的数据格式。
        注意：PyBroker 需要通过 register_data 注册数据源。
        这里采用简便方法：将数据临时写入内存并注册。
        """
        if data is None or data.empty:
            raise ValueError("数据不能为空")
        # 确保列名符合 PyBroker 要求
        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        for col in required_cols:
            if col not in data.columns:
                raise ValueError(f"数据必须包含 {col} 列")
        self.data = data.copy()
        # 生成一个唯一标识符
        self._symbol = "CUSTOM"

    def set_strategy(self, strategy: BaseStrategy) -> None:
        self.strategy = strategy

    def run(self, **kwargs) -> BacktestResult:
        if self.data is None:
            raise ValueError("请先调用 set_data 设置数据")
        if self.strategy is None:
            raise ValueError("请先调用 set_strategy 设置策略")

        # 1. 注册数据源
        # PyBroker 要求使用其内置数据源或通过 register_data 注册自定义 DataFrame
        # 简便起见，我们使用 pb.YFinance 直接下载，但这里为了通用性，采用自定义数据源注册方式
        from pybroker.data import DataSource
        
        class CustomDataSource(DataSource):
            def __init__(self, df: pd.DataFrame):
                super().__init__()
                self._df = df.copy()
                self._df.index = pd.to_datetime(self._df.index)
            
            def query(self, symbols, start_date, end_date, _timeframe=None):
                # 返回 {symbol: df} 格式
                mask = (self._df.index >= pd.to_datetime(start_date)) & (self._df.index <= pd.to_datetime(end_date))
                return {symbols[0]: self._df.loc[mask]}

        data_source = CustomDataSource(self.data)
        
        # 2. 初始化 PyBroker 配置
        config = StrategyConfig(initial_cash=self.initial_cash)
        start_date = self.data.index[0].strftime('%Y-%m-%d')
        end_date = self.data.index[-1].strftime('%Y-%m-%d')
        
        pyb_strategy = Strategy(data_source, start_date, end_date, config)
        
        # 3. 将我们的 BaseStrategy 适配为 PyBroker 执行函数
        # 首先确保策略已初始化
        self.strategy.set_data(self.data)
        self.strategy.init()
        
        # 记录持仓状态
        position = 0
        entry_price = 0.0
        trades = []
        
        def exec_fn(ctx):
            nonlocal position, entry_price
            i = ctx.bar_index
            if i >= len(self.data):
                return
            
            # 调用用户策略
            signal = self.strategy.next(i)
            if signal is None:
                return
            
            action = signal.get('action', 'HOLD')
            size = signal.get('size', 0)
            current_price = ctx.close
            
            if action == 'BUY' and position == 0:
                # 买入
                shares = int(size) if size > 0 else 100  # 默认买入100股
                ctx.buy_shares = shares
                position = shares
                entry_price = current_price
                trades.append({
                    'date': ctx.dt,
                    'action': 'BUY',
                    'price': current_price,
                    'shares': shares
                })
            elif action == 'SELL' and position > 0:
                # 卖出
                ctx.sell_shares = position
                trades.append({
                    'date': ctx.dt,
                    'action': 'SELL',
                    'price': current_price,
                    'shares': position
                })
                position = 0
                entry_price = 0.0

        pyb_strategy.add_execution(exec_fn, [self._symbol])
        
        # 4. 执行回测
        result = pyb_strategy.backtest()
        
        # 5. 提取指标
        metrics = result.metrics
        equity = result.equity_curve
        
        return BacktestResult(
            total_return=metrics.get('total_return', 0.0),
            sharpe_ratio=metrics.get('sharpe', 0.0),
            max_drawdown=metrics.get('max_drawdown', 0.0),
            win_rate=metrics.get('win_rate', 0.0),
            total_trades=metrics.get('total_trades', 0),
            equity_curve=equity.tolist() if equity is not None else [],
            trade_log=trades,
            metadata={'engine': 'pybroker'}
        )