#!/usr/bin/env python3
"""
筛选满足「均线多头排列 + 回调放量反弹」的股票

规则:
  ① MA10 > MA20 > MA60               （多头排列）
  ② MA20 今日 > MA20 五日前           （趋势向上）
  ③ Close > MA20                      （价格在20日均线上方）
  ④ 回调幅度 5%~15%                   （从近期高点回落）
  ⑤ VOL5 < VOL10 < VOL20              （缩量回调）
  ⑥ VOL5 < VOL20 × 0.7                （5日均量显著低于20日均量）
  ⑦ 今日涨幅 > 2%
  ⑧ 今日成交量 > VOL5 × 1.2           （今日开始放量）
  ⑨ 今日成交额 > 3亿元

输出:
  - 终端打印结果
  - JSON 文件保存到 output/screen_ma_pullback_<YYYY-MM-DD>.json
  - 同时保存到 output/screen_ma_pullback_latest.json（每日覆盖）
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

# ─── 股票名称映射 ───
_NAMES_CACHE = {}

def _load_names():
    global _NAMES_CACHE
    if _NAMES_CACHE:
        return _NAMES_CACHE
    for p in [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stock_names.json"),
        "/Users/skyler/workspace/stock_selection/stock_names.json",
    ]:
        if os.path.exists(p):
            try:
                with open(p) as f:
                    _NAMES_CACHE = json.load(f)
                return _NAMES_CACHE
            except Exception:
                pass
    return _NAMES_CACHE

def _name(ticker):
    if not _NAMES_CACHE:
        _load_names()
    return _NAMES_CACHE.get(ticker, "")

def calc_ma(series, period):
    return series.rolling(window=period, min_periods=period).mean()

def screen_one(csv_path):
    """Returns dict if match, or None."""
    try:
        df = pd.read_csv(csv_path, parse_dates=['Date'])
    except Exception:
        return None

    if len(df) < 60:
        return None

    try:
        df = df.sort_values('Date').reset_index(drop=True)
        df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
        df['Adj Close'] = pd.to_numeric(df.get('Adj Close', df['Close']), errors='coerce')
        df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce')
        df['High'] = pd.to_numeric(df['High'], errors='coerce')
        df['Low'] = pd.to_numeric(df.get('Low', df['Close']), errors='coerce')
    except Exception:
        return None

    if df['Close'].isna().any() or df['Volume'].isna().any():
        return None

    close = df['Close']
    volume = df['Volume']
    high = df['High']

    # ─── 计算指标 ───
    ma10 = calc_ma(close, 10)
    ma20 = calc_ma(close, 20)
    ma60 = calc_ma(close, 60)

    vol5 = volume.rolling(5).mean()
    vol10 = volume.rolling(10).mean()
    vol20 = volume.rolling(20).mean()

    # ─── 取最新一行 (today) ───
    last = df.iloc[-1]
    today_ma10 = ma10.iloc[-1]
    today_ma20 = ma20.iloc[-1]
    today_ma60 = ma60.iloc[-1]

    ma20_today = today_ma20
    if len(df) >= 5:
        ma20_5d_ago = ma20.iloc[-5]
    else:
        return None

    today_close = last['Close']
    today_vol = last['Volume']
    today_high = last['High']

    # 成交额估算（Close × Volume，A股以人民币计，Yahoo数据Volume=股数，Close≈元）
    today_turnover = today_close * today_vol

    vol5_val = volume.rolling(5).mean().iloc[-1]
    vol10_val = volume.rolling(10).mean().iloc[-1]
    vol20_val = volume.rolling(20).mean().iloc[-1]

    if np.isnan(vol5_val) or np.isnan(vol10_val) or np.isnan(vol20_val):
        return None
    if np.isnan(today_ma10) or np.isnan(today_ma20) or np.isnan(today_ma60):
        return None

    # ─── 规则判定 ───

    # ① MA10 > MA20 > MA60
    if not (today_ma10 > today_ma20 > today_ma60):
        return None

    # ② MA20 今日 > MA20 五日前
    if not (ma20_today > ma20_5d_ago):
        return None

    # ③ Close > MA20
    if not (today_close > today_ma20):
        return None

    # ④ 回调幅度 5%~15%（近20日最高价到最近低点）
    recent_high = high.iloc[-20:].max()
    # 找到回调低点：近10日的最低价
    recent_low = df['Low'].iloc[-10:].min()
    if recent_high <= 0:
        return None
    pullback = (recent_high - recent_low) / recent_high
    if not (0.05 <= pullback <= 0.15):
        return None

    # ⑤ VOL5 < VOL10 < VOL20
    if not (vol5_val < vol10_val < vol20_val):
        return None

    # ⑥ VOL5 < VOL20 × 0.7
    if not (vol5_val < vol20_val * 0.7):
        return None

    # ⑦ 今日涨幅 > 2%
    if len(df) >= 2:
        prev_close = df.iloc[-2]['Close']
        if prev_close <= 0:
            return None
        pct_change = (today_close - prev_close) / prev_close
        if not (pct_change > 0.02):
            return None
    else:
        return None

    # ⑧ 今日成交量 > VOL5 × 1.2
    if not (today_vol > vol5_val * 1.2):
        return None

    # ⑨ 今日成交额 > 3亿元（3e8）
    if not (today_turnover > 3e8):
        return None

    # ─── 通过！ ───
    prev_close = df.iloc[-2]['Close'] if len(df) >= 2 else today_close
    pct = (today_close - prev_close) / prev_close * 100 if prev_close > 0 else 0

    return {
        "ticker": os.path.basename(csv_path).replace(".csv", ""),
        "name": _name(os.path.basename(csv_path).replace(".csv", "")),
        "close": round(today_close, 2),
        "pct_change": round(pct, 2),
        "turnover_yi": round(today_turnover / 1e8, 2),
        "ma10": round(today_ma10, 2),
        "ma20": round(today_ma20, 2),
        "ma60": round(today_ma60, 2),
        "vol5": round(vol5_val),
        "vol10": round(vol10_val),
        "vol20": round(vol20_val),
        "pullback_pct": round(pullback * 100, 2),
        "date": str(last['Date'].date()) if hasattr(last['Date'], 'date') else str(last['Date'])[:10],
    }

def main():
    parser = argparse.ArgumentParser(description="MA Pullback Screen")
    parser.add_argument("--data-dir", required=True, help="目录含 <TICKER>.csv")
    parser.add_argument("--output-dir", default="output/strategy", help="输出目录")
    args = parser.parse_args()

    data_dir = args.data_dir
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)

    csv_files = glob.glob(os.path.join(data_dir, "*.csv"))
    if not csv_files:
        print(f"⚠ 数据目录为空: {data_dir}")
        sys.exit(1)

    results = []
    today_str = date.today().isoformat()

    for csv_path in tqdm(csv_files, desc="MA 回调筛选", ncols=80):
        result = screen_one(csv_path)
        if result:
            results.append(result)

    # 排序: 按涨幅降序
    results.sort(key=lambda x: x['pct_change'], reverse=True)

    # ─── 打印 ───
    print(f"\n{'='*70}")
    print(f"  📈 MA 多头排列 + 回调放量反弹  日期: {today_str}")
    print(f"{'='*70}")

    if not results:
        print("  共 0 只股票满足条件")
    else:
        for r in results:
            name_str = f" {r['name']}" if r.get('name') else ""
            print(f"  {r['ticker']}{name_str}  "
                  f"收盘 {r['close']}  涨幅 {r['pct_change']:+.2f}%  "
                  f"成交额 {r['turnover_yi']:.2f}亿  "
                  f"回调 {r['pullback_pct']:.1f}%")
        print(f"\n  共 {len(results)} 只股票满足条件")

    # ─── 保存 JSON ───
    out_file = os.path.join(output_dir, f"screen_ma_pullback_{today_str}.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    latest_file = os.path.join(output_dir, "screen_ma_pullback_latest.json")
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"  💾 {out_file}")
    print(f"{'='*70}\n")

if __name__ == "__main__":
    main()
