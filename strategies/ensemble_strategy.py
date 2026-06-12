from engine.base import BaseStrategy
import pandas as pd
from strategies import ml_utils

class EnsembleVotingStrategy(BaseStrategy):
    """集成投票策略"""
    def __init__(self, params: dict = None):
        default_params = {
            'lookback': 252,
            'train_window': 60,
            'retrain_freq': 20,
            'target_horizon': 5,
            'buy_threshold': 0.55,
            'sell_threshold': 0.45,
            'max_holding_days': 20,
            'period': '2y'
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self._signals = None

    def init(self) -> None:
        if self.data is None or len(self.data) < self.params['lookback']:
            self._signals = pd.Series(0, index=self.data.index) if self.data is not None else None
            return

        result_df = ml_utils.backtest_ensemble_voting(
            symbol=None,
            data=self.data,
            **self.params
        )
        if result_df is not None:
            self._signals = result_df.get('Trade', pd.Series(0, index=self.data.index))

    def next(self, i: int) -> dict:
        if self._signals is None or i >= len(self._signals):
            return None
        signal = self._signals.iloc[i]
        if signal == 1:
            return {'action': 'BUY', 'size': 100}
        elif signal == -1:
            return {'action': 'SELL', 'size': 100}
        return None
