#!/usr/bin/env python3
"""
超级顶底 - 副图指标选股

指标逻辑:
  RSV_DD   = (CLOSE - LLV(LOW,27)) / (HHV(HIGH,27) - LLV(LOW,27)) * 100
  SMA1     = SMA(RSV_DD, 5, 1)       -- 通达信 SMA: SMA(x,n,m) = (m*x + (n-m)*prev_SMA) / n
  SMA2     = SMA(SMA1, 3, 1)
  趋势线    = 3 * SMA1 - 2 * SMA2

信号:
  买入: CROSS(趋势线, 11)  → 趋势线上穿 11（超卖区回升 → 准备买入）
  卖出: CROSS(89, 趋势线)  → 89 上穿趋势线，即趋势线下穿 89（超买区回落 → 准备卖出）

输出:
  - 终端打印买入 / 卖出信号
  - JSON 保存到 output/strategy/screen_super_top_bottom_buy_<YYYY-MM-DD>.json
  - JSON 保存到 output/strategy/screen_super_top_bottom_sell_<YYYY-MM-DD>.json
  - *_latest.json 指针文件（每日覆盖）
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


# ─── 指标计算 ───
def _sma_td(series: pd.Series, n: int, m: int) -> pd.Series:
    """
    通达信 SMA:  Y[i] = (m*X[i] + (n-m)*Y[i-1]) / n
    等价于       Y[i] = (m/n)*X[i] + (1 - m/n)*Y[i-1]
    初始值 Y[first_valid] = X[first_valid]（跳过前导 NaN）
    """
    x = series.astype(np.float64).values
    result = np.full(len(series), np.nan, dtype=np.float64)
    alpha = m / n

    # 找到第一个有效值作为种子
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
    """计算 超级顶底 趋势线"""
    low_n = df["Low"].rolling(window=27).min()
    high_n = df["High"].rolling(window=27).max()
    denom = high_n - low_n
    denom = denom.replace(0, np.nan)
    rsv_dd = (df["Close"] - low_n) / denom * 100.0

    sma1 = _sma_td(rsv_dd, n=5, m=1)
    sma2 = _sma_td(sma1, n=3, m=1)
    trend = 3.0 * sma1 - 2.0 * sma2
    return trend


def check_stock(filepath):
    """
    检查单只股票的超级顶底信号。
    返回 (ticker, signal_type, details_dict)
      signal_type = 'buy' | 'sell' | None
    """
    ticker = os.path.basename(filepath).replace(".csv", "")
    try:
        df = pd.read_csv(filepath, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
        for col in ["Close", "High", "Low"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df.dropna(subset=["Close", "High", "Low"], inplace=True)
    except Exception:
        return ticker, None, {}

    if len(df) < 30:
        return ticker, None, {}

    trend = calc_trend_line(df)

    if len(trend) < 2:
        return ticker, None, {}

    t_now = trend.iloc[-1]
    t_prev = trend.iloc[-2]

    if not np.isfinite(t_now) or not np.isfinite(t_prev):
        return ticker, None, {}

    signal = None
    details = {}

    # 买入: CROSS(趋势线, 11)  前天<=11, 今天>11  (上穿)
    if t_prev <= 11.0 and t_now > 11.0:
        signal = "buy"
        details = {
            "date": df["Date"].iloc[-1].strftime("%Y-%m-%d"),
            "close": round(float(df["Close"].iloc[-1]), 2),
            "trend_line": round(float(t_now), 2),
            "trend_prev": round(float(t_prev), 2),
            "signal_note": "趋势线上穿11 → 准备买入",
            "name": _name(ticker),
        }

    # 卖出: CROSS(89, 趋势线)  前天>=89, 今天<89  (趋势线下穿89)
    elif t_prev >= 89.0 and t_now < 89.0:
        signal = "sell"
        details = {
            "date": df["Date"].iloc[-1].strftime("%Y-%m-%d"),
            "close": round(float(df["Close"].iloc[-1]), 2),
            "trend_line": round(float(t_now), 2),
            "trend_prev": round(float(t_prev), 2),
            "signal_note": "趋势线下穿89 → 准备卖出",
            "name": _name(ticker),
        }

    return ticker, signal, details


# ─── JSON 保存 ───
def save_json(signal_type, results, output_dir):
    """保存结果为 JSON"""
    today_str = date.today().strftime("%Y-%m-%d")
    os.makedirs(output_dir, exist_ok=True)

    stocks = []
    for ticker, d in results:
        name = d.get("name", "") or _name(ticker)
        stocks.append({"ticker": ticker, "name": name, **{k: v for k, v in d.items() if k != "name"}})

    if signal_type == "buy":
        prefix = "screen_super_top_bottom_buy"
        strategy_name = "超级顶底 买入信号"
    else:
        prefix = "screen_super_top_bottom_sell"
        strategy_name = "超级顶底 卖出信号"

    payload = {
        "strategy": prefix,
        "strategy_name": strategy_name,
        "signal_type": signal_type,
        "screen_date": today_str,
        "total_scanned": _total_scanned,
        "total_matched": len(results),
        "stocks": stocks,
    }

    dated_path = os.path.join(output_dir, f"{prefix}_{today_str}.json")
    with open(dated_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    latest_path = os.path.join(output_dir, f"{prefix}_latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n💾 JSON 已保存 ({signal_type}):")
    print(f"   {dated_path}")
    print(f"   {latest_path}")
    return dated_path, latest_path


_total_scanned = 0


# ─── 主函数 ───
def main():
    parser = argparse.ArgumentParser(description="超级顶底 趋势线选股")
    parser.add_argument("--data-dir",
                        default="/Users/skyler/workspace/stock_selection/data_cache_daily",
                        help="股票 CSV 数据目录")
    parser.add_argument("--output-dir",
                        default="/Users/skyler/workspace/stock_selection/output/strategy",
                        help="JSON 输出目录")
    parser.add_argument("--no-json", action="store_true", help="不保存 JSON 文件")
    args = parser.parse_args()

    data_dir = args.data_dir
    output_dir = args.output_dir

    csv_files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    print(f"共找到 {len(csv_files)} 只股票，开始扫描…\n")

    global _total_scanned
    _total_scanned = len(csv_files)

    buy_results = []
    sell_results = []

    for filepath in tqdm(csv_files, desc="扫描中"):
        ticker, signal, details = check_stock(filepath)
        if signal == "buy":
            buy_results.append((ticker, details))
        elif signal == "sell":
            sell_results.append((ticker, details))

    # === 输出结果 ===
    print(f"\n{'='*60}")
    print(f"🟢 买入信号 (趋势线上穿11): {len(buy_results)} 只\n")
    for ticker, d in buy_results:
        print(f"  {ticker}  收盘价:{d['close']}  日期:{d['date']}  {d['trend_line']:.2f}")
    if not buy_results:
        print("  无")

    print(f"\n🔴 卖出信号 (趋势线下穿89): {len(sell_results)} 只\n")
    for ticker, d in sell_results:
        print(f"  {ticker}  收盘价:{d['close']}  日期:{d['date']}  {d['trend_line']:.2f}")
    if not sell_results:
        print("  无")

    # JSON 输出
    if not args.no_json:
        save_json("buy", buy_results, output_dir)
        save_json("sell", sell_results, output_dir)

    return buy_results, sell_results


if __name__ == "__main__":
    main()
