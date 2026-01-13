import pandas as pd
import ta

def indicators(df):
    df = df.copy()

    # EMA 均线
    df["ema5"] = ta.trend.EMAIndicator(df["close"], 5).ema_indicator()
    df["ema10"] = ta.trend.EMAIndicator(df["close"], 10).ema_indicator()
    df["ema20"] = ta.trend.EMAIndicator(df["close"], 20).ema_indicator()

    # 均线斜率（本日 - 前日）
    df["ema5_slope"] = df["ema5"].diff()
    df["ema10_slope"] = df["ema10"].diff()
    df["ema20_slope"] = df["ema20"].diff()

    # RSI
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], 14).rsi()

    # MACD
    macd = ta.trend.MACD(df["close"])
    df["macd"] = macd.macd()            # DIF
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()  # DIF - DEA

    # 成交量
    df["volume_ma5"] = df["volume"].rolling(5).mean()
    df["volume_ma3"] = df["volume"].rolling(3).mean()

    # 前 3 日低点 & 高点，用于结构判断
    df["low_3"] = df["low"].rolling(3).min()
    df["high_3"] = df["high"].rolling(3).max()

    # ========== RSI ==========
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()

    # ========== KDJ ==========
    stoch = ta.momentum.StochasticOscillator(
        high=df["high"], low=df["low"], close=df["close"], window=9, smooth_window=3
    )
    df["k"] = stoch.stoch()
    df["d"] = stoch.stoch_signal()
    df["j"] = 3 * df["k"] - 2 * df["d"]

    # ========== Momentum ==========
    df["momentum"] = df["close"].diff(14)

    # ========== DMI ==========
    dmi = ta.trend.ADXIndicator(
        high=df["high"], low=df["low"], close=df["close"], window=14
    )
    df["adx"] = dmi.adx()
    df["plusDI"] = dmi.adx_pos()
    df["minusDI"] = dmi.adx_neg()

    # ========== ATR ==========
    df["atr"] = ta.volatility.AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"], window=14
    ).average_true_range()

    # 历史窗口
    df["high_8"] = df["high"].rolling(8).max()
    df["low_8"] = df["low"].rolling(8).min()
    df["rsi_8_max"] = df["rsi"].rolling(8).max()
    df["rsi_8_min"] = df["rsi"].rolling(8).min()
    df["j_8_max"] = df["j"].rolling(8).max()
    df["j_8_min"] = df["j"].rolling(8).min()
    df["momentum_8_max"] = df["momentum"].rolling(8).max()
    df["momentum_8_min"] = df["momentum"].rolling(8).min()

    return df
