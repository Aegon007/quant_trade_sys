from engine.base import BaseStrategy
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any
from strategies import ml_utils

class LightGBMStrategy(BaseStrategy):
    """LightGBM 机器学习策略，实现 BaseStrategy 接口"""
    def __init__(self, params: dict = None):
        default_params = {
            'lookback': 252,
            'train_window': 60,
            'retrain_freq': 20,
            'target_horizon': 5,
            'buy_threshold': 0.55,
            'sell_threshold': 0.45,
            'max_holding_days': 20,
            'n_trials': 30,
            'use_saved_model': True
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self.model = None
        self.scaler = None
        self._signals = None
        self._pred_proba = None

    def init(self) -> None:
        """初始化：尝试加载已保存模型，若无则进行回测训练"""
        if self.data is None or len(self.data) < self.params['lookback']:
            self._signals = pd.Series(0, index=self.data.index) if self.data is not None else None
            return

        symbol = self.params.get('symbol', None)
        if symbol and self.params.get('use_saved_model', True):
            self.model, self.scaler = ml_utils.load_model_if_exists(symbol)

        # 如果没有预训练模型，则调用回测函数（它会进行 Walk-Forward 训练）
        result_df = ml_utils.backtest_ml_lightgbm(
            symbol=symbol,
            data=self.data,
            **self.params
        )

        if result_df is not None:
            self._signals = result_df.get('Trade', pd.Series(0, index=self.data.index))
            self._pred_proba = result_df.get('pred_prob')

    def next(self, i: int) -> Optional[Dict[str, Any]]:
        if self._signals is None or i >= len(self._signals):
            return None
        signal = self._signals.iloc[i]
        if signal == 1:
            return {'action': 'BUY', 'size': 100}
        elif signal == -1:
            return {'action': 'SELL', 'size': 100}
        return None
