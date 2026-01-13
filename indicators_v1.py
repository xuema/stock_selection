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

    return df
