"""
基于 BaseStrategy 实现的经典规则策略。
使用原 quant_analysis 中的计算函数，但遵循新接口。
"""
import pandas as pd
import numpy as np
from engine.base import BaseStrategy
from quant_core.analytics import quant_analysis as qa

class MACrossoverStrategy(BaseStrategy):
    """双均线交叉策略"""
    def __init__(self, short_window: int = 20, long_window: int = 50):
        super().__init__({'short_window': short_window, 'long_window': long_window})
        self.short = short_window
        self.long = long_window
        self._ma_short = None
        self._ma_long = None
    
    def init(self) -> None:
        close = self.data['Close']
        self._ma_short = close.rolling(self.short).mean()
        self._ma_long = close.rolling(self.long).mean()
    
    def next(self, i: int) -> dict:
        if i < self.long:
            return None
        prev_short = self._ma_short.iloc[i-1]
        prev_long = self._ma_long.iloc[i-1]
        curr_short = self._ma_short.iloc[i]
        curr_long = self._ma_long.iloc[i]
        
        # 金叉买入
        if prev_short <= prev_long and curr_short > curr_long:
            return {'action': 'BUY', 'size': 100}
        # 死叉卖出
        elif prev_short >= prev_long and curr_short < curr_long:
            return {'action': 'SELL', 'size': 100}
        return None

class BollingerStrategy(BaseStrategy):
    """布林带反转策略"""
    def __init__(self, window: int = 20, num_std: float = 2.0):
        super().__init__({'window': window, 'num_std': num_std})
        self.window = window
        self.num_std = num_std
        self._mid = None
        self._lower = None
        self._upper = None
    
    def init(self) -> None:
        close = self.data['Close']
        self._mid = close.rolling(self.window).mean()
        std = close.rolling(self.window).std()
        self._lower = self._mid - self.num_std * std
        self._upper = self._mid + self.num_std * std
    
    def next(self, i: int) -> dict:
        if i < self.window:
            return None
        price = self.data['Close'].iloc[i]
        lower = self._lower.iloc[i]
        mid = self._mid.iloc[i]
        # 买入：价格触及下轨
        if price <= lower * 1.01:
            return {'action': 'BUY', 'size': 100}
        # 卖出：价格回到中轨
        if price >= mid:
            return {'action': 'SELL', 'size': 100}
        return None

class MACDStrategy(BaseStrategy):
    """MACD 金叉死叉策略"""
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        super().__init__({'fast': fast, 'slow': slow, 'signal': signal})
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self._macd = None
        self._signal_line = None
    
    def init(self) -> None:
        close = self.data['Close']
        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        self._macd = ema_fast - ema_slow
        self._signal_line = self._macd.ewm(span=self.signal, adjust=False).mean()
    
    def next(self, i: int) -> dict:
        if i < self.slow + self.signal:
            return None
        prev_macd = self._macd.iloc[i-1]
        prev_signal = self._signal_line.iloc[i-1]
        curr_macd = self._macd.iloc[i]
        curr_signal = self._signal_line.iloc[i]
        
        if prev_macd <= prev_signal and curr_macd > curr_signal:
            return {'action': 'BUY', 'size': 100}
        elif prev_macd >= prev_signal and curr_macd < curr_signal:
            return {'action': 'SELL', 'size': 100}
        return None

class RSIStrategy(BaseStrategy):
    """RSI 超买超卖策略"""
    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70):
        super().__init__({'period': period, 'oversold': oversold, 'overbought': overbought})
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self._rsi = None
    
    def init(self) -> None:
        self._rsi = qa.calculate_rsi(self.data, self.period)
    
    def next(self, i: int) -> dict:
        if i < self.period:
            return None
        rsi_val = self._rsi.iloc[i]
        prev_rsi = self._rsi.iloc[i-1] if i > 0 else rsi_val
        
        # 从超卖区回升买入
        if prev_rsi < self.oversold and rsi_val >= self.oversold:
            return {'action': 'BUY', 'size': 100}
        # 从超买区回落卖出
        elif prev_rsi > self.overbought and rsi_val <= self.overbought:
            return {'action': 'SELL', 'size': 100}
        return None
