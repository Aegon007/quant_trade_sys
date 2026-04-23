"""
将原有基于函数的策略包装为 BaseStrategy 类的适配器。
便于平滑迁移，保持原有策略函数可用。
"""
from typing import Callable, Dict, Any, Optional
import pandas as pd
from engine.base import BaseStrategy

class FunctionStrategyAdapter(BaseStrategy):
    """将回测函数包装为 BaseStrategy"""
    def __init__(self, backtest_func: Callable, signal_func: Optional[Callable] = None, params: Dict[str, Any] = None):
        super().__init__(params)
        self.backtest_func = backtest_func
        self.signal_func = signal_func
        self._signals = None  # 缓存生成的信号
        
    def init(self) -> None:
        """预先运行回测函数以生成信号序列"""
        if self.data is None:
            return
        # 调用原有回测函数，它会返回包含 'Position' 或 'Signal' 列的 DataFrame
        result_df = self.backtest_func(self.data, **self.params)
        if result_df is not None and 'Position' in result_df.columns:
            self._signals = result_df['Position'].diff().fillna(0)
        elif result_df is not None and 'Trade' in result_df.columns:
            self._signals = result_df['Trade']
        else:
            self._signals = pd.Series(0, index=self.data.index)
    
    def next(self, i: int) -> Optional[Dict[str, Any]]:
        if self._signals is None or i >= len(self._signals):
            return None
        signal_val = self._signals.iloc[i]
        if signal_val == 1:
            return {'action': 'BUY', 'size': 100}  # 默认买入100股
        elif signal_val == -1:
            return {'action': 'SELL', 'size': 100}
        else:
            return None

def create_strategy_from_function(backtest_func: Callable, params: Dict[str, Any] = None) -> BaseStrategy:
    """工厂函数：从原有回测函数创建策略对象"""
    return FunctionStrategyAdapter(backtest_func, params=params)