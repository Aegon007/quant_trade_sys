"""
ML 策略核心模块：基于 LightGBM + Walk-Forward 的机器学习策略
"""

import numpy as np
import pandas as pd
import yfinance as yf
from typing import Optional, Tuple, Dict, List
import warnings
import os

warnings.filterwarnings('ignore', category=UserWarning)

# ---------- 检测 LightGBM 可用性 ----------
LGB_AVAILABLE = False
LGB_ERROR_MSG = ""

try:
    import lightgbm as lgb
    LGB_AVAILABLE = True
except ImportError as e:
    LGB_ERROR_MSG = f"lightgbm 未安装：{str(e)}"
except Exception as e:
    LGB_ERROR_MSG = f"lightgbm 加载异常：{str(e)}"

OPTUNA_AVAILABLE = False
try:
    import optuna
    OPTUNA_AVAILABLE = True
except ImportError:
    pass

try:
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import TimeSeriesSplit
    import joblib
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

MODEL_DIR = "trained_models"


CATBOOST_AVAILABLE = False
try:
    import catboost as cb
    CATBOOST_AVAILABLE = True
except ImportError:
    pass

XGBOOST_AVAILABLE = False
try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    pass


def get_model_path(symbol: str) -> str:
    os.makedirs(MODEL_DIR, exist_ok=True)
    return os.path.join(MODEL_DIR, f"{symbol}_lgbm_model.pkl")


def load_model_if_exists(symbol: str):
    if not SKLEARN_AVAILABLE:
        return None, None

    model_path = get_model_path(symbol)
    if os.path.exists(model_path):
        try:
            bundle = joblib.load(model_path)
            return bundle.get('model'), bundle.get('scaler')
        except Exception as e:
            print(f"加载模型失败: {e}")
    return None, None


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    close = data['Close']
    high = data['High']
    low = data['Low']
    volume = data['Volume']

    data['ret_1'] = close.pct_change(1)
    data['ret_5'] = close.pct_change(5)
    data['ret_10'] = close.pct_change(10)
    data['ret_20'] = close.pct_change(20)

    data['vol_5'] = data['ret_1'].rolling(5).std()
    data['vol_20'] = data['ret_1'].rolling(20).std()

    data['volume_ma_5'] = volume.rolling(5).mean()
    data['volume_ratio'] = volume / data['volume_ma_5'].replace(0, np.nan)
    data['volume_change_5'] = volume.pct_change(5)

    data['ma_5'] = close.rolling(5).mean()
    data['ma_20'] = close.rolling(20).mean()
    data['ma_50'] = close.rolling(50).mean()
    data['price_to_ma_5'] = close / data['ma_5'].replace(0, np.nan) - 1
    data['price_to_ma_20'] = close / data['ma_20'].replace(0, np.nan) - 1
    data['price_to_ma_50'] = close / data['ma_50'].replace(0, np.nan) - 1
    data['ma_5_20_cross'] = (data['ma_5'] - data['ma_20']) / data['ma_20'].replace(0, np.nan)

    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    data['rsi'] = 100 - (100 / (1 + rs))

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    data['bb_position'] = (close - bb_mid) / (2 * bb_std).replace(0, np.nan)

    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    data['macd'] = ema_12 - ema_26
    data['macd_signal'] = data['macd'].ewm(span=9, adjust=False).mean()
    data['macd_diff'] = data['macd'] - data['macd_signal']

    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    data['atr_14'] = tr.rolling(14).mean()
    data['atr_ratio'] = data['atr_14'] / close

    data['high_low_ratio'] = (close - low.rolling(20).min()) / (high.rolling(20).max() - low.rolling(20).min()).replace(0, np.nan)

    return data


def create_target(df: pd.DataFrame, horizon: int = 5) -> pd.Series:
    close = df['Close']
    future_ret = close.shift(-horizon) / close - 1
    target = pd.Series(np.nan, index=df.index, dtype=float)
    valid_mask = future_ret.notna()
    target.loc[valid_mask] = (future_ret.loc[valid_mask] > 0).astype(float)
    return target


def backtest_ml_lightgbm(
    symbol: str = None,
    data: pd.DataFrame = None,
    lookback: int = 252,
    train_window: int = 60,
    retrain_freq: int = 20,
    target_horizon: int = 5,
    buy_threshold: float = 0.55,
    sell_threshold: float = 0.45,
    max_holding_days: int = 20,
    n_trials: int = 30,
    period: str = "2y",
    use_saved_model: bool = True,
    **kwargs
) -> Optional[pd.DataFrame]:
    if not LGB_AVAILABLE:
        raise RuntimeError(f"LightGBM 不可用：{LGB_ERROR_MSG}")

    if data is not None:
        df = data.copy()
    elif symbol is not None:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)
        if df.empty:
            return None
    else:
        raise ValueError("必须提供 symbol 或 data 参数")

    if len(df) < lookback:
        return None

    df = compute_features(df)
    y = create_target(df, horizon=target_horizon)

    feature_cols = [
        'ret_1', 'ret_5', 'ret_10', 'ret_20',
        'vol_5', 'vol_20',
        'volume_ratio', 'volume_change_5',
        'price_to_ma_5', 'price_to_ma_20', 'price_to_ma_50', 'ma_5_20_cross',
        'rsi', 'bb_position',
        'macd', 'macd_diff',
        'atr_ratio', 'high_low_ratio'
    ]
    X = df[feature_cols].copy()
    X = X.replace([np.inf, -np.inf], np.nan).ffill().fillna(0)

    common_idx = X.dropna().index.intersection(y.dropna().index)
    X = X.loc[common_idx]
    y = y.loc[common_idx]
    meta = df.loc[common_idx].copy()

    n_samples = len(X)
    if n_samples < lookback:
        return None

    meta['pred_prob'] = np.nan
    meta['Position'] = 0
    meta['Trade'] = 0

    model = None
    scaler = None
    if use_saved_model and symbol is not None:
        model, scaler = load_model_if_exists(symbol)

    if model is not None and scaler is not None:
        X_scaled = scaler.transform(X)
        meta['pred_prob'] = model.predict_proba(X_scaled)[:, 1]
    else:
        for test_start in range(lookback, n_samples, retrain_freq):
            test_end = min(test_start + retrain_freq, n_samples)
            train_start = max(0, test_start - train_window)

            X_train = X.iloc[train_start:test_start]
            y_train = y.iloc[train_start:test_start]
            X_test = X.iloc[test_start:test_end]

            if len(X_train) < 30 or len(X_test) == 0:
                continue

            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)

            params = {
                'objective': 'binary',
                'metric': 'auc',
                'boosting_type': 'gbdt',
                'num_leaves': 31,
                'learning_rate': 0.1,
                'feature_fraction': 0.8,
                'bagging_fraction': 0.8,
                'bagging_freq': 5,
                'verbosity': -1,
                'seed': 42
            }
            if OPTUNA_AVAILABLE and n_trials > 0:
                def objective(trial):
                    p = {
                        'num_leaves': trial.suggest_int('num_leaves', 16, 128),
                        'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
                        'feature_fraction': trial.suggest_float('feature_fraction', 0.5, 1.0),
                        'bagging_fraction': trial.suggest_float('bagging_fraction', 0.5, 1.0),
                        'bagging_freq': trial.suggest_int('bagging_freq', 1, 10),
                        'min_child_samples': trial.suggest_int('min_child_samples', 10, 50),
                        'lambda_l1': trial.suggest_float('lambda_l1', 1e-8, 10.0, log=True),
                        'lambda_l2': trial.suggest_float('lambda_l2', 1e-8, 10.0, log=True),
                        'verbosity': -1,
                        'seed': 42,
                        'objective': 'binary',
                        'metric': 'auc',
                        'boosting_type': 'gbdt'
                    }
                    tscv = TimeSeriesSplit(n_splits=3)
                    scores = []
                    for tr_idx, val_idx in tscv.split(X_train_scaled):
                        X_tr = X_train_scaled[tr_idx]
                        y_tr = y_train.iloc[tr_idx]
                        X_val = X_train_scaled[val_idx]
                        y_val = y_train.iloc[val_idx]
                        model_tmp = lgb.LGBMClassifier(**p)
                        model_tmp.fit(X_tr, y_tr, eval_set=[(X_val, y_val)],
                                      callbacks=[lgb.early_stopping(10), lgb.log_evaluation(0)])
                        pred = model_tmp.predict_proba(X_val)[:, 1]
                        from sklearn.metrics import roc_auc_score
                        try:
                            scores.append(roc_auc_score(y_val, pred))
                        except:
                            pass
                    return np.mean(scores) if scores else 0.5

                study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
                study.optimize(objective, n_trials=min(n_trials, 20), show_progress_bar=False)
                params.update(study.best_params)

            model_tmp = lgb.LGBMClassifier(**params)
            model_tmp.fit(X_train_scaled, y_train)

            pred_proba = model_tmp.predict_proba(X_test_scaled)[:, 1]
            meta.loc[X_test.index, 'pred_prob'] = pred_proba

    position = 0
    holding_days = 0
    for i in range(1, len(meta)):
        prob = meta['pred_prob'].iloc[i]
        if pd.isna(prob):
            meta.loc[meta.index[i], 'Position'] = position
            holding_days = holding_days + 1 if position > 0 else 0
            continue

        if position == 0:
            if prob > buy_threshold:
                meta.loc[meta.index[i], 'Trade'] = 1
                position = 1
                holding_days = 1
            else:
                position = 0
                holding_days = 0
        else:
            holding_days += 1
            if prob < sell_threshold or holding_days >= max_holding_days:
                meta.loc[meta.index[i], 'Trade'] = -1
                position = 0
                holding_days = 0
        meta.loc[meta.index[i], 'Position'] = position

    meta['Returns'] = meta['Close'].pct_change()
    meta['Strategy'] = meta['Returns'] * meta['Position'].shift(1)
    return meta


def get_ml_signal(symbol: str, **kwargs) -> Tuple[str, str]:
    if not LGB_AVAILABLE:
        return "HOLD", f"LightGBM 不可用：{LGB_ERROR_MSG}"

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1y")
        if df.empty or len(df) < 60:
            return "HOLD", "历史数据不足"

        df = compute_features(df)
        feature_cols = [
            'ret_1', 'ret_5', 'ret_10', 'ret_20',
            'vol_5', 'vol_20',
            'volume_ratio', 'volume_change_5',
            'price_to_ma_5', 'price_to_ma_20', 'price_to_ma_50', 'ma_5_20_cross',
            'rsi', 'bb_position',
            'macd', 'macd_diff',
            'atr_ratio', 'high_low_ratio'
        ]
        X = df[feature_cols].copy()
        X = X.replace([np.inf, -np.inf], np.nan).ffill().fillna(0)

        model, scaler = load_model_if_exists(symbol)

        if model is None or scaler is None:
            y = create_target(df, horizon=kwargs.get('target_horizon', 5))
            common_idx = X.dropna().index.intersection(y.dropna().index)
            X = X.loc[common_idx]
            y = y.loc[common_idx]

            train_window = kwargs.get('train_window', 60)
            if len(X) < train_window:
                return "HOLD", f"数据不足，需要至少 {train_window} 个有效样本"

            X_train = X.iloc[-train_window:]
            y_train = y.iloc[-train_window:]

            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)

            model = lgb.LGBMClassifier(
                objective='binary', metric='auc', num_leaves=31,
                learning_rate=0.1, verbosity=-1, seed=42
            )
            model.fit(X_train_scaled, y_train)

        latest_X = X.iloc[[-1]]
        latest_X_scaled = scaler.transform(latest_X)
        prob = model.predict_proba(latest_X_scaled)[0, 1]

        buy_threshold = kwargs.get('buy_threshold', 0.55)
        sell_threshold = kwargs.get('sell_threshold', 0.45)

        if prob > buy_threshold:
            return "BUY", f"ML 模型预测上涨概率 {prob:.1%} > {buy_threshold:.0%}，建议买入"
        elif prob < sell_threshold:
            return "SELL", f"ML 模型预测上涨概率 {prob:.1%} < {sell_threshold:.0%}，建议卖出"
        else:
            return "HOLD", f"ML 模型预测上涨概率 {prob:.1%}，处于中性区间，建议持有"
    except Exception as e:
        return "HOLD", f"信号计算异常：{str(e)}"


def retrain_and_save_model(symbol: str, data: pd.DataFrame, params: dict) -> str:
    if not LGB_AVAILABLE:
        return f"❌ LightGBM 不可用：{LGB_ERROR_MSG}"
    if not SKLEARN_AVAILABLE:
        return "❌ scikit-learn 或 joblib 未安装，无法保存模型。"

    model_path = get_model_path(symbol)

    try:
        df = compute_features(data.copy())
        y = create_target(df, horizon=params.get('target_horizon', 5))

        feature_cols = [
            'ret_1', 'ret_5', 'ret_10', 'ret_20',
            'vol_5', 'vol_20',
            'volume_ratio', 'volume_change_5',
            'price_to_ma_5', 'price_to_ma_20', 'price_to_ma_50', 'ma_5_20_cross',
            'rsi', 'bb_position',
            'macd', 'macd_diff',
            'atr_ratio', 'high_low_ratio'
        ]
        X = df[feature_cols].copy()
        X = X.replace([np.inf, -np.inf], np.nan).ffill().fillna(0)

        common_idx = X.dropna().index.intersection(y.dropna().index)
        X = X.loc[common_idx]
        y = y.loc[common_idx]

        if len(X) < params.get('train_window', 60):
            return "⚠️ 重训练失败：有效数据样本不足。"

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        lgb_params = {
            'objective': 'binary', 'metric': 'auc', 'boosting_type': 'gbdt',
            'num_leaves': 31, 'learning_rate': 0.1, 'feature_fraction': 0.8,
            'bagging_fraction': 0.8, 'bagging_freq': 5, 'verbosity': -1, 'seed': 42
        }
        model = lgb.LGBMClassifier(**lgb_params)
        model.fit(X_scaled, y)

        joblib.dump({'model': model, 'scaler': scaler}, model_path)
        return f"✅ 模型重训练成功！已保存至 {model_path}"
    except Exception as e:
        return f"❌ 重训练模型时发生错误：{e}"


def backtest_ensemble_voting(
    symbol: str = None,
    data: pd.DataFrame = None,
    lookback: int = 252,
    train_window: int = 60,
    retrain_freq: int = 20,
    target_horizon: int = 5,
    buy_threshold: float = 0.55,
    sell_threshold: float = 0.45,
    max_holding_days: int = 20,
    period: str = "2y",
    **kwargs
) -> Optional[pd.DataFrame]:
    """
    集成投票策略：组合 LightGBM、CatBoost、XGBoost 预测概率平均。
    """
    if not LGB_AVAILABLE:
        raise RuntimeError("LightGBM 不可用")
    if not CATBOOST_AVAILABLE:
        raise RuntimeError("CatBoost 未安装，请运行 pip install catboost")
    if not XGBOOST_AVAILABLE:
        raise RuntimeError("XGBoost 未安装，请运行 pip install xgboost")

    # 获取数据（与之前相同）
    if data is not None:
        df = data.copy()
    elif symbol is not None:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)
        if df.empty:
            return None
    else:
        raise ValueError("必须提供 symbol 或 data 参数")

    if len(df) < lookback:
        return None

    df = compute_features(df)
    y = create_target(df, horizon=target_horizon)

    feature_cols = [
        'ret_1', 'ret_5', 'ret_10', 'ret_20',
        'vol_5', 'vol_20',
        'volume_ratio', 'volume_change_5',
        'price_to_ma_5', 'price_to_ma_20', 'price_to_ma_50', 'ma_5_20_cross',
        'rsi', 'bb_position',
        'macd', 'macd_diff',
        'atr_ratio', 'high_low_ratio'
    ]
    X = df[feature_cols].copy()
    X = X.replace([np.inf, -np.inf], np.nan).ffill().fillna(0)

    common_idx = X.dropna().index.intersection(y.dropna().index)
    X = X.loc[common_idx]
    y = y.loc[common_idx]
    meta = df.loc[common_idx].copy()

    n_samples = len(X)
    if n_samples < lookback:
        return None

    meta['pred_prob'] = np.nan
    meta['Position'] = 0
    meta['Trade'] = 0

    for test_start in range(lookback, n_samples, retrain_freq):
        test_end = min(test_start + retrain_freq, n_samples)
        train_start = max(0, test_start - train_window)

        X_train = X.iloc[train_start:test_start]
        y_train = y.iloc[train_start:test_start]
        X_test = X.iloc[test_start:test_end]

        if len(X_train) < 30 or len(X_test) == 0:
            continue

        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        # 训练三个模型
        model_lgb = lgb.LGBMClassifier(objective='binary', metric='auc', verbosity=-1, seed=42)
        model_lgb.fit(X_train_scaled, y_train)
        prob_lgb = model_lgb.predict_proba(X_test_scaled)[:, 1]

        model_cb = cb.CatBoostClassifier(verbose=0, random_seed=42)
        model_cb.fit(X_train_scaled, y_train)
        prob_cb = model_cb.predict_proba(X_test_scaled)[:, 1]

        model_xgb = xgb.XGBClassifier(objective='binary:logistic', eval_metric='logloss', verbosity=0, seed=42)
        model_xgb.fit(X_train_scaled, y_train)
        prob_xgb = model_xgb.predict_proba(X_test_scaled)[:, 1]

        # 平均概率
        prob_ensemble = (prob_lgb + prob_cb + prob_xgb) / 3.0
        meta.loc[X_test.index, 'pred_prob'] = prob_ensemble

    # 生成信号（与之前相同）
    position = 0
    holding_days = 0
    for i in range(1, len(meta)):
        prob = meta['pred_prob'].iloc[i]
        if pd.isna(prob):
            meta.loc[meta.index[i], 'Position'] = position
            holding_days = holding_days + 1 if position > 0 else 0
            continue

        if position == 0:
            if prob > buy_threshold:
                meta.loc[meta.index[i], 'Trade'] = 1
                position = 1
                holding_days = 1
            else:
                position = 0
                holding_days = 0
        else:
            holding_days += 1
            if prob < sell_threshold or holding_days >= max_holding_days:
                meta.loc[meta.index[i], 'Trade'] = -1
                position = 0
                holding_days = 0
        meta.loc[meta.index[i], 'Position'] = position

    meta['Returns'] = meta['Close'].pct_change()
    meta['Strategy'] = meta['Returns'] * meta['Position'].shift(1)
    return meta

def get_ensemble_signal(symbol: str, **kwargs) -> Tuple[str, str]:
    """实时集成信号"""
    if not LGB_AVAILABLE or not CATBOOST_AVAILABLE or not XGBOOST_AVAILABLE:
        return "HOLD", "需要安装 lightgbm, catboost, xgboost"

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1y")
        if df.empty or len(df) < 60:
            return "HOLD", "历史数据不足"

        df = compute_features(df)
        feature_cols = [
            'ret_1', 'ret_5', 'ret_10', 'ret_20',
            'vol_5', 'vol_20',
            'volume_ratio', 'volume_change_5',
            'price_to_ma_5', 'price_to_ma_20', 'price_to_ma_50', 'ma_5_20_cross',
            'rsi', 'bb_position',
            'macd', 'macd_diff',
            'atr_ratio', 'high_low_ratio'
        ]
        X = df[feature_cols].copy()
        X = X.replace([np.inf, -np.inf], np.nan).ffill().fillna(0)

        y = create_target(df, horizon=kwargs.get('target_horizon', 5))
        common_idx = X.dropna().index.intersection(y.dropna().index)
        X = X.loc[common_idx]
        y = y.loc[common_idx]

        train_window = kwargs.get('train_window', 60)
        if len(X) < train_window:
            return "HOLD", f"数据不足，需要至少 {train_window} 个有效样本"

        X_train = X.iloc[-train_window:]
        y_train = y.iloc[-train_window:]

        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)

        model_lgb = lgb.LGBMClassifier(objective='binary', metric='auc', verbosity=-1, seed=42)
        model_lgb.fit(X_train_scaled, y_train)
        prob_lgb = model_lgb.predict_proba(scaler.transform(X.iloc[[-1]]))[0, 1]

        model_cb = cb.CatBoostClassifier(verbose=0, random_seed=42)
        model_cb.fit(X_train_scaled, y_train)
        prob_cb = model_cb.predict_proba(scaler.transform(X.iloc[[-1]]))[0, 1]

        model_xgb = xgb.XGBClassifier(objective='binary:logistic', eval_metric='logloss', verbosity=0, seed=42)
        model_xgb.fit(X_train_scaled, y_train)
        prob_xgb = model_xgb.predict_proba(scaler.transform(X.iloc[[-1]]))[0, 1]

        prob = (prob_lgb + prob_cb + prob_xgb) / 3.0

        buy_threshold = kwargs.get('buy_threshold', 0.55)
        sell_threshold = kwargs.get('sell_threshold', 0.45)

        if prob > buy_threshold:
            return "BUY", f"集成模型预测上涨概率 {prob:.1%} > {buy_threshold:.0%}，建议买入"
        elif prob < sell_threshold:
            return "SELL", f"集成模型预测上涨概率 {prob:.1%} < {sell_threshold:.0%}，建议卖出"
        else:
            return "HOLD", f"集成模型预测上涨概率 {prob:.1%}，处于中性区间，建议持有"
    except Exception as e:
        return "HOLD", f"信号计算异常：{str(e)}"
