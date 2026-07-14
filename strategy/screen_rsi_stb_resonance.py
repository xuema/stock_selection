#!/usr/bin/env python3
"""
双重共振筛选：同时满足 RSI 金叉 + 超级顶底买入信号

1. RSI(12) 上穿 RSI_MA(56) 且成交额 ≥ 3亿
2. 超级顶底趋势线上穿 11

输出:
  - JSON → output/screen_rsi_stb_resonance_<YYYY-MM-DD>.json
  - JSON → output/screen_rsi_stb_resonance_latest.json（每日覆盖）
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


# ─── RSI ───
def calc_rsi(series, period=12):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ─── 超级顶底 SMA（通达信递推） ───
def _sma_td(series: pd.Series, n: int, m: int) -> pd.Series:
    x = series.astype(np.float64).values
    result = np.full(len(series), np.nan, dtype=np.float64)
    alpha = m / n
    first_valid = None
    for i in range(len(x)):
        if np.isfinite(x[i]):
            first_valid = i
            result[i] = x[i]
            break
    if first_valid is None:
        return pd.Series(result, index=series.index)
    for i in range(first_valid + 1, len(series)):
        if np.isfinite(x[i]):
            prev = result[i - 1] if np.isfinite(result[i - 1]) else x[i]
            result[i] = alpha * x[i] + (1.0 - alpha) * prev
    return pd.Series(result, index=series.index)


def calc_trend_line(df: pd.DataFrame) -> pd.Series:
    low_n = df["Low"].rolling(window=27).min()
    high_n = df["High"].rolling(window=27).max()
    denom = (high_n - low_n).replace(0, np.nan)
    rsv = (df["Close"] - low_n) / denom * 100.0
    sma1 = _sma_td(rsv, 5, 1)
    sma2 = _sma_td(sma1, 3, 1)
    return 3.0 * sma1 - 2.0 * sma2


def check_stock(filepath):
    ticker = os.path.basename(filepath).replace(".csv", "")
    try:
        df = pd.read_csv(filepath, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
        for col in ["Close", "High", "Low", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df.dropna(subset=["Close", "Volume"], inplace=True)
    except Exception:
        return ticker, False, {}

    if len(df) < 60:
        return ticker, False, {}

    # RSI 金叉
    rsi = calc_rsi(df["Close"], 12)
    rsi_ma = rsi.rolling(window=56).mean()
    if np.isnan(rsi.iloc[-1]) or np.isnan(rsi_ma.iloc[-1]):
        return ticker, False, {}
    rsi_cross = (rsi.iloc[-2] < rsi_ma.iloc[-2]) & (rsi.iloc[-1] > rsi_ma.iloc[-1])

    # 成交额过滤
    if df["Close"].iloc[-1] * df["Volume"].iloc[-1] < 300_000_000:
        return ticker, False, {}

    # 超级顶底买入
    trend = calc_trend_line(df)
    if len(trend) < 2:
        return ticker, False, {}
    t_now = trend.iloc[-1]
    t_prev = trend.iloc[-2]
    if not np.isfinite(t_now) or not np.isfinite(t_prev):
        return ticker, False, {}
    stb_buy = (t_prev <= 11.0) & (t_now > 11.0)

    if rsi_cross and stb_buy:
        details = {
            "date": df["Date"].iloc[-1].strftime("%Y-%m-%d"),
            "close": round(float(df["Close"].iloc[-1]), 2),
            "volume": int(df["Volume"].iloc[-1]),
            "rsi12": round(float(rsi.iloc[-1]), 2),
            "rsi_ma56": round(float(rsi_ma.iloc[-1]), 2),
            "trend_line": round(float(t_now), 2),
            "trend_prev": round(float(t_prev), 2),
            "name": _name(ticker),
        }
        return ticker, True, details

    return ticker, False, {}


def save_json(results, output_dir):
    today_str = date.today().strftime("%Y-%m-%d")
    os.makedirs(output_dir, exist_ok=True)

    stocks = []
    for ticker, d in results:
        name = d.get("name", "") or _name(ticker)
        stocks.append({"ticker": ticker, "name": name, **{k: v for k, v in d.items() if k != "name"}})

    payload = {
        "strategy": "rsi_stb_resonance",
        "strategy_name": "RSI 金叉 + 超级顶底 双重共振",
        "screen_date": today_str,
        "total_scanned": _total_scanned,
        "total_matched": len(results),
        "stocks": stocks,
    }

    dated_path = os.path.join(output_dir, f"screen_rsi_stb_resonance_{today_str}.json")
    with open(dated_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    latest_path = os.path.join(output_dir, "screen_rsi_stb_resonance_latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n💾 JSON 已保存:")
    print(f"   {dated_path}")
    print(f"   {latest_path}")
    return dated_path, latest_path


_total_scanned = 0


def main():
    parser = argparse.ArgumentParser(description="RSI 金叉 + 超级顶底 双重共振选股")
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

    print(f"\n{'='*60}")
    print(f"🔗 RSI 金叉 + 超级顶底 双重共振: {len(results)} 只\n")
    for ticker, d in results:
        print(f"  {ticker}  收盘价:{d['close']}  日期:{d['date']}")
        print(f"    RSI12={d['rsi12']} > RSI_MA56={d['rsi_ma56']} (金叉)")
        print(f"    趋势线={d['trend_line']} 前日={d['trend_prev']} (上穿11)")
        print()
    if not results:
        print("  无")

    if not args.no_json:
        save_json(results, output_dir)

    return results


if __name__ == "__main__":
    main()
