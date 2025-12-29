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
    ema20_up = last["ema20_slope"] > 0

    if just_above_ma5 and ema5_turn_up and ema20_up:
        score += 0.2

    # -------------------
    # ② 动能（0.2）：RSI > 55，MACD DIF 金叉且 histogram > 0
    #if last["rsi"] > 40 and last["rsi"] < 65 and last["macd"] > last["macd_signal"] and last["macd_hist"] > 0:
    if last["rsi"] > 40 and last["rsi"] < 65:
        score += 0.2

    # -------------------
    # ③ 结构（0.3）：最近低点突破前高
    if last["close"] > prev["high"] * 0.98 or last["close"] > df["high_3"].iloc[-2] * 0.98:
        score += 0.3

    # -------------------
    # ④ 量能（0.2）：最近 3 天成交量均大于 5 日均量
    recent_volume = df["volume"].iloc[-3:]
    if all(recent_volume > last["volume_ma5"] * 1.2):
        score += 0.2

    return score
