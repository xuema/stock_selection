#!/usr/bin/env python3
"""
筛选同时满足以下买入信号的股票：
1. EXPMA(5,29) 金叉 — EMA5 刚上穿 EMA29
2. VOL(8,89) 金叉 — VOL_MA8 刚上穿 VOL_MA89
3. CR(26,11,19,35,53) 白线在所有均线上方

输出:
  - 终端打印结果
  - JSON 文件保存到 output/screen_signals_<YYYY-MM-DD>.json
  - 同时保存到 output/screen_signals_latest.json（每日覆盖）
"""

import os
import sys
import json
import glob
import argparse
import pandas as pd
import numpy as np
from tqdm import tqdm
from datetime import date


def ema(series, span):
    """计算指数移动平均"""
    return series.ewm(span=span, adjust=False).mean()


def calc_cr(df, cr_period=26):
    """
    计算 CR 能量指标
    MID = (High + Low) / 2
    PM = max(0, High - shift(MID, 1))  多头
    MM = max(0, shift(MID, 1) - Low)   空头
    CR = sum(PM, cr_period) / sum(MM, cr_period) * 100
    """
    mid = (df["High"] + df["Low"]) / 2
    mid_shift = mid.shift(1)
    pm = np.maximum(0, df["High"] - mid_shift)
    mm = np.maximum(0, mid_shift - df["Low"])

    cr_sum_pm = pm.rolling(window=cr_period).sum()
    cr_sum_mm = mm.rolling(window=cr_period).sum()

    # 避免除以零
    cr = cr_sum_pm / cr_sum_mm.replace(0, np.nan) * 100
    return cr


def check_stock(filepath):
    """
    检查单只股票是否满足所有买入信号。
    返回 (ticker, True/False, details_dict)
    """
    ticker = os.path.basename(filepath).replace(".csv", "")
    try:
        df = pd.read_csv(filepath, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
        # 确保数值列干净
        for col in ["Close", "High", "Low", "Open", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df.dropna(subset=["Close", "Volume"], inplace=True)
    except Exception:
        return ticker, False, {}

    if len(df) < 90:  # 数据不足，跳过
        return ticker, False, {}

    # === 1. EXPMA(5,29) 金叉 ===
    ema5 = ema(df["Close"], 5)
    ema29 = ema(df["Close"], 29)

    # 金叉：前一日 EMA5 < EMA29，今日 EMA5 > EMA29
    expma_cross = (ema5.iloc[-2] < ema29.iloc[-2]) & (ema5.iloc[-1] > ema29.iloc[-1])

    if not expma_cross:
        return ticker, False, {}

    # === 2. VOL(8,89) 金叉 ===
    vol_ma8 = df["Volume"].rolling(window=8).mean()
    vol_ma89 = df["Volume"].rolling(window=89).mean()

    vol_cross = (vol_ma8.iloc[-2] < vol_ma89.iloc[-2]) & (vol_ma8.iloc[-1] > vol_ma89.iloc[-1])

    if not vol_cross:
        return ticker, False, {}

    # === 3. CR(26,11,19,35,53) 白线在所有均线上方 ===
    cr = calc_cr(df, 26)
    cr_ma1 = cr.rolling(window=11).mean()  # 白线的均线
    cr_ma2 = cr.rolling(window=19).mean()
    cr_ma3 = cr.rolling(window=35).mean()
    cr_ma4 = cr.rolling(window=53).mean()

    latest = -1
    cr_ok = (
        cr.iloc[latest] > cr_ma1.iloc[latest]
        and cr.iloc[latest] > cr_ma2.iloc[latest]
        and cr.iloc[latest] > cr_ma3.iloc[latest]
        and cr.iloc[latest] > cr_ma4.iloc[latest]
    )
    # 确保值有效
    if not np.isfinite(cr.iloc[latest]):
        cr_ok = False

    if not cr_ok:
        return ticker, False, {}

    # 全部满足
    details = {
        "date": df["Date"].iloc[-1].strftime("%Y-%m-%d"),
        "close": round(df["Close"].iloc[-1], 2),
        "ema5": round(ema5.iloc[-1], 2),
        "ema29": round(ema29.iloc[-1], 2),
        "vol_ma8": round(vol_ma8.iloc[-1]),
        "vol_ma89": round(vol_ma89.iloc[-1]),
        "cr": round(cr.iloc[-1], 2),
    }
    return ticker, True, details


def save_json(results, output_dir):
    """保存筛选结果为 JSON"""
    today_str = date.today().strftime("%Y-%m-%d")
    os.makedirs(output_dir, exist_ok=True)

    stocks = []
    for ticker, d in results:
        stocks.append({"ticker": ticker, **d})

    payload = {
        "strategy": "expma_vol_cr_signals",
        "strategy_name": "EXPMA+VOL+CR 多因子信号",
        "screen_date": today_str,
        "total_scanned": _total_scanned,
        "total_matched": len(results),
        "stocks": stocks,
    }

    # 每日 dated 文件
    dated_path = os.path.join(output_dir, f"screen_signals_{today_str}.json")
    with open(dated_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # latest 指针文件（每日覆盖）
    latest_path = os.path.join(output_dir, "screen_signals_latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n💾 JSON 已保存:")
    print(f"   {dated_path}")
    print(f"   {latest_path}")
    return dated_path, latest_path


_total_scanned = 0  # module-level counter for save_json


def main():
    parser = argparse.ArgumentParser(description="EXPMA+VOL+CR 多因子选股")
    parser.add_argument("--data-dir", default="/Users/skyler/workspace/stock_selection/data_cache_daily",
                        help="股票 CSV 数据目录")
    parser.add_argument("--output-dir", default="/Users/skyler/workspace/stock_selection/output/strategy",
                        help="JSON 输出目录")
    parser.add_argument("--no-json", action="store_true", help="不保存 JSON 文件")
    args = parser.parse_args()

    data_dir = args.data_dir
    output_dir = args.output_dir

    csv_files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    print(f"共找到 {len(csv_files)} 只股票，开始扫描…\n")

    global _total_scanned
    _total_scanned = len(csv_files)

    results = []
    for filepath in tqdm(csv_files, desc="扫描中"):
        ticker, passed, details = check_stock(filepath)
        if passed:
            results.append((ticker, details))

    # === 输出结果 ===
    if results:
        print(f"\n{'='*60}")
        print(f"✅ 共 {len(results)} 只股票满足全部买入信号\n")
        for ticker, d in results:
            print(f"  {ticker}  收盘价:{d['close']}  日期:{d['date']}")
            print(f"    EXPMA: EMA5={d['ema5']} > EMA29={d['ema29']} (金叉)")
            print(f"    VOL:   MA8={d['vol_ma8']} > MA89={d['vol_ma89']} (金叉)")
            print(f"    CR={d['cr']} (白线在均线上方)")
            print()
    else:
        print("\n未找到同时满足三项条件的股票。")

    # JSON 输出
    if not args.no_json:
        save_json(results, output_dir)

    return results


if __name__ == "__main__":
    main()
