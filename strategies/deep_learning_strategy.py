from typing import Any, Dict, Optional

import pandas as pd

from engine.base import BaseStrategy
from strategies import deep_learning_utils as dl_utils


class DeepTCNStrategy(BaseStrategy):
    """Temporal CNN deep learning strategy adapter for the backtest engines."""

    def __init__(self, params: dict = None):
        default_params = {
            "sequence_length": 60,
            "lookback": 120,
            "train_window": 180,
            "retrain_freq": 20,
            "target_horizon": 5,
            "buy_threshold": 0.57,
            "sell_threshold": 0.43,
            "min_expected_return": 0.005,
            "max_holding_days": 20,
            "epochs": 20,
            "batch_size": 32,
            "learning_rate": 0.001,
            "hidden_channels": 32,
            "num_layers": 3,
            "kernel_size": 3,
            "dropout": 0.15,
            "min_train_samples": 30,
            "device": "auto",
            "period": "3y",
        }
        if params:
            default_params.update(params)
        super().__init__(default_params)
        self._signals = None
        self._pred_proba = None
        self._expected_return = None
        self.error = None

    def init(self) -> None:
        if self.data is None:
            self._signals = None
            return

        try:
            result_df = dl_utils.backtest_deep_tcn(data=self.data, **self.params)
        except RuntimeError as e:
            self.error = str(e)
            self._signals = pd.Series(0, index=self.data.index)
            return

        if result_df is None:
            self._signals = pd.Series(0, index=self.data.index)
            return

        self._signals = result_df.get("Trade", pd.Series(0, index=result_df.index)).reindex(self.data.index).fillna(0)
        self._pred_proba = result_df.get("pred_prob")
        self._expected_return = result_df.get("expected_return")

    def next(self, i: int) -> Optional[Dict[str, Any]]:
        if self._signals is None or i >= len(self._signals):
            return None
        signal = self._signals.iloc[i]
        if signal == 1:
            return {"action": "BUY", "size": 100}
        if signal == -1:
            return {"action": "SELL", "size": 100}
        return None
