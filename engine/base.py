from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, field
import pandas as pd

@dataclass
class BacktestResult:
    """标准化的回测结果"""
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    equity_curve: List[float] = field(default_factory=list)
    trade_log: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None

class BaseStrategy(ABC):
    """
    用户策略的抽象基类。
    所有自定义策略都必须继承此类并实现 init 和 next 方法。
    """
    def __init__(self, params: Optional[Dict[str, Any]] = None):
        self.params = params or {}
        self.data: Optional[pd.DataFrame] = None

    def set_data(self, data: pd.DataFrame) -> None:
        """设置回测使用的历史数据（由引擎调用）"""
        self.data = data

    @abstractmethod
    def init(self) -> None:
        """
        策略初始化，在回测开始前调用一次。
        可用于预计算指标、加载模型等。
        """
        pass

    @abstractmethod
    def next(self, i: int) -> Optional[Dict[str, Any]]:
        """
        每个时间步调用一次。
        参数 i: 当前数据索引（从0开始）
        返回: 交易信号字典，格式为 {'action': 'BUY'/'SELL'/'HOLD', 'size': float}
        """
        pass

class BaseBacktestEngine(ABC):
    """回测引擎抽象基类"""
    def __init__(self, initial_cash: float = 100000):
        self.initial_cash = initial_cash
        self.strategy: Optional[BaseStrategy] = None
        self.data: Optional[pd.DataFrame] = None

    @abstractmethod
    def set_data(self, data: pd.DataFrame) -> None:
        """设置回测数据（通常为 OHLCV DataFrame）"""
        pass

    @abstractmethod
    def set_strategy(self, strategy: BaseStrategy) -> None:
        """设置交易策略"""
        pass

    @abstractmethod
    def run(self, **kwargs) -> BacktestResult:
        """执行回测，返回标准化结果"""
        pass