def score_strategy(df):
    """
    综合评分：趋势 0.2 + 动能 0.2 + 结构 0.3 + 量能 0.2
    """
    last = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0

    # -------------------
    # ① 趋势（0.2）：收盘刚站上5日均线 + 5均线拐头向上 + 20均线向上
    just_above_ma5 = last["close"] > last["ema5"] and prev["close"] <= prev["ema5"]
    ema5_turn_up = (last["ema5_slope"] > 0) and (prev["ema5_slope"] <= 0)
    #ema5_turn_up = (last["ema5_slope"] > 0) and (prev["ema5_slope"] <= 0)
    
    ema20_up = last["ema20_slope"] > 0
    ema10_up = last["ema10_slope"] > 0
    ema5_up = last["ema5_slope"] > 0
    close_above_ma5 = last["close"] > last["ema5"]

    if close_above_ma5 and ema5_up and ema10_up and ema20_up:
    #if just_above_ma5 and ema5_turn_up and ema10_up and ema20_up:
        score += 0.2

    # -------------------
    # ② 动能（0.2）：RSI > 55，MACD DIF 金叉且 histogram > 0
    #if last["rsi"] > 40 and last["rsi"] < 65 and last["macd"] > last["macd_signal"] and last["macd_hist"] > 0:
    #if last["rsi"] > 40 and last["rsi"] < 70:
    #    score += 0.2
    
    if last["rsi"] > 50 and last["rsi"] < 70 and last["macd"] > last["macd_signal"] and last["macd_hist"] > 0:
        score += 0.2
        
    # -------------------
    # ③ 结构（0.3）：最近低点突破前高
    high_3_prev = df["high_3"].iloc[-2]
    if last["close"] > prev["high"] * 1.01 or last["close"] > high_3_prev * 1.01:
        score += 0.3

    # -------------------
    # ④ 量能（0.2）：最近 3 天成交量均大于 5 日均量        
    recent_volume = df["volume"].iloc[-3:]
    if sum(recent_volume > last["volume_ma5"] * 1.2) >= 2:
        score += 0.2


    return score

def buy_signal(df):
    """
    根据用户提供的 TradingView 三重共振策略：
    RSI + KDJ + 背离 + Momentum + DMI
    返回 True/False
    """

    if len(df) < 30:
        return False

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # ========== 动态条件 ==========
    adxStrong = last["adx"] > 25
    adxWeak = not adxStrong

    upStrong = last["plusDI"] > last["minusDI"] and adxStrong
    upNormal = last["plusDI"] > last["minusDI"] and adxWeak
    downStrong = last["minusDI"] > last["plusDI"] and adxStrong
    downNormal = last["minusDI"] > last["plusDI"] and adxWeak

    # ========== RSI 多头 ==========
    rsiLong_strong = last["rsi"] <= 32 and downStrong
    rsiLong_normal = last["rsi"] <= 35 and downNormal
    rsiLongCond = rsiLong_strong or rsiLong_normal

    # ========== 背离检测 ==========
    buffer_factor = 0.0006

    price_LL = last["low"] < prev["low"] * (1 + buffer_factor)
    rsi_LL = last["rsi"] < prev["rsi"] * 1.0
    kdj_LL = last["j"] < prev["j"] * 1.0

    bull_div = price_LL and (not rsi_LL or not kdj_LL)

    # Momentum 背离
    momentum_LL = last["momentum"] < df["momentum"].iloc[-2]
    bull_mom_div = price_LL and not momentum_LL

    # ATR 滤波
    atrFilter = last["atr"] < df["atr"].rolling(14).mean().iloc[-1] * 1.2

    # ========== 最终多头信号 ==========
    longSignal = rsiLongCond and atrFilter and (bull_div or bull_mom_div)

    return bool(longSignal)

