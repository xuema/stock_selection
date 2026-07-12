#!/usr/bin/env python3
"""
筛选满足 RSI(12,56) 刚金叉 的股票
RSI(12) 上穿 RSI_MA(56)

输出:
  - 终端打印结果
  - JSON 文件保存到 output/screen_rsi_golden_cross_<YYYY-MM-DD>.json
  - 同时保存到 output/screen_rsi_golden_cross_latest.json（每日覆盖）
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
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "stock_names.json"),
        os.path.join(os.path.expanduser("~"), "workspace", "stock_selection", "stock_names.json"),
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


def calc_rsi(series, period=12):
    """计算 RSI 指标"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def check_stock(filepath):
    """
    检查单只股票是否满足 RSI 金叉信号。
    金叉定义：前一日 RSI12 < RSI12_MA56，今日 RSI12 > RSI12_MA56
    """
    ticker = os.path.basename(filepath).replace(".csv", "")
    try:
        df = pd.read_csv(filepath, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
        # 确保数值列干净
        for col in ["Close", "High", "Low", "Open", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df.dropna(subset=["Close"], inplace=True)
    except Exception:
        return ticker, False, {}

    if len(df) < 60:  # 数据不足，跳过
        return ticker, False, {}

    # 计算 RSI(12)
    rsi = calc_rsi(df["Close"], 12)

    # 计算 RSI 的移动平均线(56)
    rsi_ma = rsi.rolling(window=56).mean()

    if np.isnan(rsi.iloc[-1]) or np.isnan(rsi_ma.iloc[-1]):
        return ticker, False, {}

    # 金叉：前一日 RSI12 < RSI12_MA56，今日 RSI12 > RSI12_MA56
    cross_up = (rsi.iloc[-2] < rsi_ma.iloc[-2]) & (rsi.iloc[-1] > rsi_ma.iloc[-1])

    # 额外过滤：最新成交额 > 1亿元
    if df["Close"].iloc[-1] * df["Volume"].iloc[-1] < 300_000_000:
        return ticker, False, {}

    if cross_up:
        details = {
            "date": df["Date"].iloc[-1].strftime("%Y-%m-%d"),
            "close": round(df["Close"].iloc[-1], 2),
            "volume": int(df["Volume"].iloc[-1]),
            "rsi12": round(rsi.iloc[-1], 2),
            "rsi_ma56": round(rsi_ma.iloc[-1], 2),
            "name": _name(ticker),
        }
        return ticker, True, details

    return ticker, False, {}


def save_json(results, output_dir):
    """保存筛选结果为 JSON"""
    today_str = date.today().strftime("%Y-%m-%d")
    os.makedirs(output_dir, exist_ok=True)

    stocks = []
    for ticker, d in results:
        name = d.get("name", "") or _name(ticker)
        stocks.append({"ticker": ticker, "name": name, **{k: v for k, v in d.items() if k != "name"}})

    payload = {
        "strategy": "rsi_golden_cross",
        "strategy_name": "RSI(12,56) 金叉",
        "screen_date": today_str,
        "total_scanned": _total_scanned,
        "total_matched": len(results),
        "stocks": stocks,
    }

    # 每日 dated 文件
    dated_path = os.path.join(output_dir, f"screen_rsi_golden_cross_{today_str}.json")
    with open(dated_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # latest 指针文件（每日覆盖）
    latest_path = os.path.join(output_dir, "screen_rsi_golden_cross_latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n💾 JSON 已保存:")
    print(f"   {dated_path}")
    print(f"   {latest_path}")
    return dated_path, latest_path


_total_scanned = 0  # module-level counter for save_json


def main():
    parser = argparse.ArgumentParser(description="RSI(12,56) 金叉选股")
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

    # 输出结果
    if results:
        print(f"\n{'='*60}")
        print(f"✅ 共 {len(results)} 只股票满足 RSI(12,56) 金叉条件\n")
        for ticker, d in results:
            print(f"  {ticker}  收盘价:{d['close']}  日期:{d['date']}")
            print(f"    RSI12={d['rsi12']} > RSI_MA56={d['rsi_ma56']} (金叉)")
            print(f"    成交量={d['volume']:,}")
            print()
    else:
        print("\n未找到满足 RSI 金叉条件的股票。")

    # JSON 输出
    if not args.no_json:
        save_json(results, output_dir)

    return results


if __name__ == "__main__":
    main()
