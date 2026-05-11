import yfinance as yf
import pandas as pd
import numpy as np

from quant_core.data import market_data as md


def get_historical_data(symbol, period="6mo"):
    """获取历史数据"""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
    except Exception as exc:
        hist = pd.DataFrame()
        primary_error = exc
    else:
        primary_error = None
    if md.history_is_usable(hist):
        md.record_history_source(symbol, "yfinance")
        return hist
    fallback = md.fetch_stooq_history(symbol, period=period)
    if md.history_is_usable(fallback):
        md.record_history_source(symbol, "stooq", error=primary_error)
        return fallback
    if primary_error is not None:
        md.record_history_source(symbol, "yfinance", error=primary_error)
        return hist
    md.record_history_source(symbol, "stooq", error="history unavailable from yfinance and stooq")
    return fallback

def calculate_ma(hist, windows=[20, 50, 200]):
    """计算移动平均线"""
    df = hist.copy()
    for w in windows:
        df[f"MA{w}"] = df["Close"].rolling(window=w).mean()
    return df

def calculate_rsi(hist, period=14):
    """计算RSI"""
    delta = hist["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_volatility(hist, annualize=True):
    """计算波动率"""
    returns = hist["Close"].pct_change().dropna()
    vol = returns.std()
    if annualize:
        vol = vol * np.sqrt(252)
    return vol

def calculate_max_drawdown(hist):
    """计算最大回撤"""
    cumulative = (1 + hist["Close"].pct_change()).cumprod()
    peak = cumulative.expanding().max()
    drawdown = (cumulative - peak) / peak
    return drawdown.min()

def backtest_ma_crossover(symbol, short_window=20, long_window=50, period="1y"):
    """双均线策略回测"""
    hist = get_historical_data(symbol, period)
    df = calculate_ma(hist, windows=[short_window, long_window])
    df["Signal"] = 0
    df.loc[df[f"MA{short_window}"] > df[f"MA{long_window}"], "Signal"] = 1
    df["Position"] = df["Signal"].diff()
    df["Returns"] = df["Close"].pct_change()
    df["Strategy"] = df["Returns"] * df["Signal"].shift(1)
    return df

def calculate_correlation_matrix(symbols, period="6mo"):
    """计算收益率相关性矩阵"""
    prices = pd.DataFrame()
    for sym in symbols:
        hist = get_historical_data(sym, period)
        if hist is None or hist.empty or "Close" not in hist.columns:
            continue
        prices[sym] = hist["Close"]
    returns = prices.pct_change().dropna()
    if returns.empty:
        return returns.corr()
    return returns.corr()

def calculate_portfolio_beta(holdings_data, benchmark="SPY", period="6mo"):
    """计算组合 Beta（市值加权）"""
    symbol_values = {}
    for h in holdings_data:
        price = h.get("current_price")
        if price is None:
            continue
        val = h["shares"] * price
        symbol_values[h["symbol"]] = symbol_values.get(h["symbol"], 0) + val

    if not symbol_values:
        raise ValueError("至少需要一个带有当前价格的持仓才能计算 Beta。")

    total_value = sum(symbol_values.values())
    weights = {symbol: value / total_value for symbol, value in symbol_values.items()}
    symbols = list(weights.keys())

    symbols.append(benchmark)
    prices = pd.DataFrame()
    for sym in symbols:
        hist = get_historical_data(sym, period)
        if hist is None or hist.empty or "Close" not in hist.columns:
            continue
        prices[sym] = hist["Close"]
    returns = prices.pct_change().dropna()
    if benchmark not in returns.columns:
        raise ValueError(f"缺少基准 {benchmark} 的历史数据，无法计算 Beta。")

    betas = {}
    for sym in weights.keys():
        cov = returns[sym].cov(returns[benchmark])
        var = returns[benchmark].var()
        betas[sym] = cov / var

    portfolio_beta = sum(weights[sym] * betas[sym] for sym in weights)
    return portfolio_beta, betas

# ---------- 短线技术指标 ----------
def calculate_macd(hist, fast=12, slow=26, signal=9):
    """计算 MACD 指标"""
    close = hist["Close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def calculate_bollinger_bands(hist, window=20, num_std=2):
    """计算布林带"""
    close = hist["Close"]
    ma = close.rolling(window=window).mean()
    std = close.rolling(window=window).std()
    upper = ma + num_std * std
    lower = ma - num_std * std
    return ma, upper, lower

def calculate_atr(hist, period=14):
    """计算平均真实波幅 (ATR)"""
    high = hist["High"]
    low = hist["Low"]
    close = hist["Close"]
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr

def calculate_stochastic(hist, k_period=14, d_period=3):
    """计算随机指标 (KDJ 的 K/D)"""
    high = hist["High"]
    low = hist["Low"]
    close = hist["Close"]
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    d = k.rolling(window=d_period).mean()
    return k, d

def calculate_momentum(hist, period=10):
    """计算动量指标"""
    close = hist["Close"]
    momentum = close - close.shift(period)
    return momentum

def calculate_williams_r(hist, period=14):
    """计算威廉指标"""
    high = hist["High"]
    low = hist["Low"]
    close = hist["Close"]
    highest_high = high.rolling(window=period).max()
    lowest_low = low.rolling(window=period).min()
    wr = -100 * (highest_high - close) / (highest_high - lowest_low)
    return wr

def calculate_volume_profile(hist, bins=20):
    """成交量分布 (简化版)"""
    price = hist["Close"]
    volume = hist["Volume"]
    hist_bins = np.linspace(price.min(), price.max(), bins)
    vol_profile = np.zeros(bins-1)
    for i in range(len(price)):
        idx = np.digitize(price.iloc[i], hist_bins) - 1
        if 0 <= idx < len(vol_profile):
            vol_profile[idx] += volume.iloc[i]
    return hist_bins, vol_profile

# ---------- 短线策略回测 ----------
def backtest_bollinger_reversal(symbol, window=20, num_std=2, period="3mo"):
    """
    布林带反转策略：
    当价格触及下轨时买入，触及上轨时卖出（空仓时）；持仓后价格回到中轨平仓。
    """
    hist = get_historical_data(symbol, period)
    df = hist.copy()
    ma, upper, lower = calculate_bollinger_bands(df, window, num_std)
    df["MA"] = ma
    df["Upper"] = upper
    df["Lower"] = lower
    df["Position"] = 0
    df["Signal"] = 0

    for i in range(1, len(df)):
        price = df["Close"].iloc[i]
        prev_price = df["Close"].iloc[i-1]
        ma_val = df["MA"].iloc[i]
        lower_val = df["Lower"].iloc[i]
        upper_val = df["Upper"].iloc[i]
        # 买入信号：价格从下轨下方回升 或 价格触及下轨
        if df["Position"].iloc[i-1] == 0:
            if price <= lower_val * 1.01 and price > lower_val * 0.99:
                df.loc[df.index[i], "Signal"] = 1
        # 卖出信号：持有中且价格回到中轨或触及上轨
        elif df["Position"].iloc[i-1] > 0:
            if price >= ma_val or price >= upper_val:
                df.loc[df.index[i], "Signal"] = -1

        df.loc[df.index[i], "Position"] = df["Position"].iloc[i-1] + df["Signal"].iloc[i]

    df["Returns"] = df["Close"].pct_change()
    df["Strategy"] = df["Returns"] * df["Position"].shift(1)
    return df

def backtest_macd_crossover(symbol, fast=12, slow=26, signal=9, period="3mo"):
    """
    MACD 金叉死叉策略：
    MACD线上穿信号线买入，下穿卖出。
    """
    hist = get_historical_data(symbol, period)
    df = hist.copy()
    macd, signal_line, _ = calculate_macd(df, fast, slow, signal)
    df["MACD"] = macd
    df["Signal_Line"] = signal_line
    df["Position"] = 0
    df["Trade"] = 0

    for i in range(1, len(df)):
        if df["MACD"].iloc[i] > df["Signal_Line"].iloc[i] and df["MACD"].iloc[i-1] <= df["Signal_Line"].iloc[i-1]:
            df.loc[df.index[i], "Trade"] = 1
        elif df["MACD"].iloc[i] < df["Signal_Line"].iloc[i] and df["MACD"].iloc[i-1] >= df["Signal_Line"].iloc[i-1]:
            df.loc[df.index[i], "Trade"] = -1

        df.loc[df.index[i], "Position"] = df["Position"].iloc[i-1] + df["Trade"].iloc[i]

    df["Returns"] = df["Close"].pct_change()
    df["Strategy"] = df["Returns"] * df["Position"].shift(1)
    return df

def backtest_rsi_oversold(symbol, rsi_period=14, oversold=30, overbought=70, period="3mo"):
    """
    RSI 超买超卖策略：
    RSI 低于超卖线买入，高于超买线卖出。
    """
    hist = get_historical_data(symbol, period)
    df = hist.copy()
    rsi = calculate_rsi(df, rsi_period)
    df["RSI"] = rsi
    df["Position"] = 0
    df["Trade"] = 0

    for i in range(1, len(df)):
        if df["RSI"].iloc[i] < oversold and df["Position"].iloc[i-1] == 0:
            df.loc[df.index[i], "Trade"] = 1
        elif df["RSI"].iloc[i] > overbought and df["Position"].iloc[i-1] > 0:
            df.loc[df.index[i], "Trade"] = -1

        df.loc[df.index[i], "Position"] = df["Position"].iloc[i-1] + df["Trade"].iloc[i]

    df["Returns"] = df["Close"].pct_change()
    df["Strategy"] = df["Returns"] * df["Position"].shift(1)
    return df

def calculate_sharpe_ratio(returns, risk_free_rate=0.02):
    """计算年化夏普比率"""
    if returns.std() == 0:
        return 0
    excess = returns - risk_free_rate / 252
    return np.sqrt(252) * excess.mean() / returns.std()

def calculate_win_rate(trades):
    """计算胜率"""
    if len(trades) == 0:
        return 0
    wins = sum(1 for t in trades if t > 0)
    return wins / len(trades)

def get_trade_returns(strategy_returns, position_col="Position"):
    """提取每次交易的收益列表"""
    trades = []
    in_trade = False
    entry_ret = 0
    for i, ret in enumerate(strategy_returns):
        if not in_trade and strategy_returns.index[i-1] if i>0 else 0:
            # 简化：直接使用策略收益每日累加，交易区间由持仓状态决定
            pass
    # 更精确的实现：根据 Position 变化识别交易区间，此处略，使用每日策略收益计算整体表现
    return strategy_returns[strategy_returns != 0]

# ---------- 策略信号统一接口 ----------
def get_signal_for_strategy(symbol, strategy):
    """根据策略配置返回当前信号和理由"""
    strategy_id = strategy["id"]
    params = strategy.get("params", {})
    if strategy_id == "ma_crossover":
        return get_signal_ma_crossover(symbol, **params)
    elif strategy_id == "bollinger":
        return get_signal_bollinger(symbol, **params)
    elif strategy_id == "macd":
        return get_signal_macd(symbol, **params)
    elif strategy_id == "rsi":
        return get_signal_rsi(symbol, **params)
    else:
        return "HOLD", "未知策略"

# ---------- 各策略信号计算函数 ----------
def get_signal_ma_crossover(symbol, short_window=20, long_window=50, period="3mo"):
    hist = get_historical_data(symbol, period=period)
    if hist.empty or len(hist) < long_window:
        return "HOLD", "数据不足"
    df = calculate_ma(hist, windows=[short_window, long_window])
    last = df.iloc[-1]
    prev = df.iloc[-2]
    if prev[f"MA{short_window}"] <= prev[f"MA{long_window}"] and last[f"MA{short_window}"] > last[f"MA{long_window}"]:
        return "BUY", "金叉形成，短期均线上穿长期均线"
    elif prev[f"MA{short_window}"] >= prev[f"MA{long_window}"] and last[f"MA{short_window}"] < last[f"MA{long_window}"]:
        return "SELL", "死叉形成，短期均线下穿长期均线"
    elif last[f"MA{short_window}"] > last[f"MA{long_window}"]:
        return "HOLD", "短期均线仍在长期均线上方，维持看多"
    else:
        return "HOLD", "短期均线在长期均线下方，维持观望"

def get_signal_bollinger(symbol, window=20, num_std=2, period="3mo"):
    hist = get_historical_data(symbol, period=period)
    if hist.empty or len(hist) < window:
        return "HOLD", "数据不足"
    ma, upper, lower = calculate_bollinger_bands(hist, window, num_std)
    last_close = hist["Close"].iloc[-1]
    last_ma = ma.iloc[-1]
    last_lower = lower.iloc[-1]
    if last_close <= last_lower * 1.02:
        return "BUY", "股价触及下轨，超卖反弹概率大"
    elif last_close >= last_ma:
        return "SELL", "股价回升至中轨，可考虑止盈"
    else:
        return "HOLD", "股价位于下轨与中轨之间，可继续持有"

def get_signal_macd(symbol, fast=12, slow=26, signal=9, period="3mo"):
    hist = get_historical_data(symbol, period=period)
    if hist.empty:
        return "HOLD", "数据不足"
    macd, signal_line, _ = calculate_macd(hist, fast, slow, signal)
    last_macd = macd.iloc[-1]
    last_signal = signal_line.iloc[-1]
    prev_macd = macd.iloc[-2]
    prev_signal = signal_line.iloc[-2]
    if prev_macd <= prev_signal and last_macd > last_signal:
        return "BUY", "MACD金叉，动能转强"
    elif prev_macd >= prev_signal and last_macd < last_signal:
        return "SELL", "MACD死叉，动能转弱"
    elif last_macd > last_signal:
        return "HOLD", "MACD在信号线上方，维持看多"
    else:
        return "HOLD", "MACD在信号线下方，维持观望"

def get_signal_rsi(symbol, rsi_period=14, oversold=30, overbought=70, period="3mo"):
    history_period = period
    if isinstance(period, (int, float)) and not isinstance(period, bool):
        # 兼容当前 RSI 配置：period 表示 RSI 窗口，而不是 yfinance 的历史周期字符串。
        rsi_period = int(period)
        history_period = "3mo"

    hist = get_historical_data(symbol, period=history_period)
    if hist.empty or len(hist) < max(int(rsi_period) + 1, 2):
        return "HOLD", "数据不足"
    rsi = calculate_rsi(hist, rsi_period)
    last_rsi = rsi.iloc[-1]
    prev_rsi = rsi.iloc[-2]
    if prev_rsi < oversold and last_rsi >= oversold:
        return "BUY", "RSI从超卖区回升，反弹信号"
    elif prev_rsi > overbought and last_rsi <= overbought:
        return "SELL", "RSI从超买区回落，回调风险"
    elif last_rsi < oversold:
        return "HOLD", "RSI处于超卖区，可关注但需等待反弹确认"
    elif last_rsi > overbought:
        return "HOLD", "RSI处于超买区，注意风险"
    else:
        return "HOLD", "RSI中性区间，趋势不明"
