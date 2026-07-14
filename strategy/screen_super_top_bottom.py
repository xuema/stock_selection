#!/usr/bin/env python3
"""
超级顶底 - 副图指标选股

指标逻辑:
  RSV_DD   = (CLOSE - LLV(LOW,27)) / (HHV(HIGH,27) - LLV(LOW,27)) * 100
  SMA1     = SMA(RSV_DD, 5, 1)       -- 通达信 SMA
  SMA2     = SMA(SMA1, 3, 1)
  趋势线    = 3 * SMA1 - 2 * SMA2

信号:
  买入: CROSS(趋势线, 11)  → 趋势线上穿 11
  卖出: CROSS(89, 趋势线)  → 趋势线下穿 89

基本面过滤(默认开启):
  - 市值 >= 50亿  且  净利同比增长(Q1) > 0

输出: screen_super_top_bottom_buy_<YYYY-MM-DD>.json + sell.json
"""

import os, sys, json, glob, argparse
import pandas as pd, numpy as np
from tqdm import tqdm
from datetime import date
import fund_filter
from fund_filter import _check_fund

# ─── 股票名称映射 ───
_NAMES_CACHE = {}

def _load_names():
    global _NAMES_CACHE
    if _NAMES_CACHE: return _NAMES_CACHE
    for p in [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stock_names.json"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "stock_names.json"),
        "/Users/skyler/workspace/stock_selection/stock_names.json",
    ]:
        if os.path.exists(p):
            try:
                with open(p) as f: _NAMES_CACHE = json.load(f); return _NAMES_CACHE
            except: pass
    return _NAMES_CACHE

def _name(t):
    if not _NAMES_CACHE: _load_names()
    return _NAMES_CACHE.get(t, "")

def _fi(t, k):
    return fund_filter._FUND_CACHE.get(t, {}).get(k)

# ─── 指标计算 ───
def _sma_td(series, n, m):
    """通达信 SMA: Y[i] = (m/n)*X[i] + (1-m/n)*Y[i-1]"""
    x = series.astype(np.float64).values
    result = np.full(len(x), np.nan, dtype=np.float64)
    alpha = m / n
    fv = None
    for i in range(len(x)):
        if np.isfinite(x[i]):
            fv = i; result[i] = x[i]; break
    if fv is None: return pd.Series(result, index=series.index)
    for i in range(fv + 1, len(x)):
        if np.isfinite(x[i]):
            prev = result[i-1] if np.isfinite(result[i-1]) else x[i]
            result[i] = alpha * x[i] + (1 - alpha) * prev
    return pd.Series(result, index=series.index)

def calc_trend_line(df):
    low_n = df["Low"].rolling(27).min()
    high_n = df["High"].rolling(27).max()
    denom = (high_n - low_n).replace(0, np.nan)
    rsv = (df["Close"] - low_n) / denom * 100
    sma1 = _sma_td(rsv, 5, 1)
    sma2 = _sma_td(sma1, 3, 1)
    return 3 * sma1 - 2 * sma2

def check_stock(filepath, mc=50, jl=0):
    ticker = os.path.basename(filepath).replace(".csv", "")
    try:
        df = pd.read_csv(filepath, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
        for c in ["Close","High","Low"]: df[c] = pd.to_numeric(df[c], errors="coerce")
        df.dropna(subset=["Close","High","Low"], inplace=True)
    except: return ticker, None, {}
    if len(df) < 30: return ticker, None, {}

    # 基本面过滤
    if not _check_fund(ticker, mc, jl): return ticker, None, {}

    trend = calc_trend_line(df)
    if len(trend) < 2: return ticker, None, {}
    t_now, t_prev = trend.iloc[-1], trend.iloc[-2]
    if not np.isfinite(t_now) or not np.isfinite(t_prev): return ticker, None, {}

    if t_prev <= 11 and t_now > 11:
        return ticker, "buy", {
            "date": df["Date"].iloc[-1].strftime("%Y-%m-%d"),
            "close": round(float(df["Close"].iloc[-1]), 2),
            "trend_line": round(t_now, 2), "trend_prev": round(t_prev, 2),
            "signal_note": "趋势线上穿11 → 准备买入",
            "mcap_yi": _fi(ticker, "mcap_yi"),
            "jl_growth_pct": _fi(ticker, "jl_growth_pct"),
            "name": _name(ticker),
        }
    elif t_prev >= 89 and t_now < 89:
        return ticker, "sell", {
            "date": df["Date"].iloc[-1].strftime("%Y-%m-%d"),
            "close": round(float(df["Close"].iloc[-1]), 2),
            "trend_line": round(t_now, 2), "trend_prev": round(t_prev, 2),
            "signal_note": "趋势线下穿89 → 准备卖出",
            "mcap_yi": _fi(ticker, "mcap_yi"),
            "jl_growth_pct": _fi(ticker, "jl_growth_pct"),
            "name": _name(ticker),
        }
    return ticker, None, {}

def save_json(signal_type, results, output_dir):
    today = date.today().strftime("%Y-%m-%d")
    os.makedirs(output_dir, exist_ok=True)
    prefix = f"screen_super_top_bottom_{signal_type}"
    sname = "超级顶底 买入信号" if signal_type == "buy" else "超级顶底 卖出信号"
    stocks = [{"ticker": t, "name": d.get("name","") or _name(t), **{k:v for k,v in d.items() if k!="name"}} for t, d in results]
    payload = {"strategy": prefix, "strategy_name": sname, "signal_type": signal_type,
               "screen_date": today, "total_scanned": _total_scanned, "total_matched": len(results), "stocks": stocks}
    dated, latest = os.path.join(output_dir, f"{prefix}_{today}.json"), os.path.join(output_dir, f"{prefix}_latest.json")
    for p in [dated, latest]:
        with open(p, "w", encoding="utf-8") as f: json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n💾 JSON 已保存 ({signal_type}):\n   {dated}\n   {latest}")

_total_scanned = 0

def main():
    ap = argparse.ArgumentParser(description="超级顶底 趋势线选股")
    ap.add_argument("--data-dir", default="/Users/skyler/workspace/stock_selection/data_cache_daily")
    ap.add_argument("--output-dir", default="/Users/skyler/workspace/stock_selection/output/strategy")
    ap.add_argument("--no-fundamental-filter", action="store_true", help="跳过基本面过滤")
    ap.add_argument("--no-json", action="store_true")
    args = ap.parse_args(); load_f = not args.no_fundamental_filter

    csvs = sorted(glob.glob(os.path.join(args.data_dir, "*.csv")))
    print(f"共找到 {len(csvs)} 只股票，开始扫描{'(含基本面过滤)' if load_f else ''}…\n")
    global _total_scanned; _total_scanned = len(csvs)
    if load_f: fund_filter._load_fundamentals()

    buy_results, sell_results = [], []
    for fp in tqdm(csvs, desc="扫描中"):
        t, sig, d = check_stock(fp)
        if sig == "buy": buy_results.append((t, d))
        elif sig == "sell": sell_results.append((t, d))

    print(f"\n{'='*60}")
    print(f"🟢 买入信号: {len(buy_results)} 只\n")
    for t, d in buy_results:
        print(f"  {t}  收盘价:{d['close']}  日期:{d['date']}  趋势线={d['trend_line']}  市值={d.get('mcap_yi','?')}亿 净利={d.get('jl_growth_pct','?')}%")
    if not buy_results: print("  无")

    print(f"\n🔴 卖出信号: {len(sell_results)} 只\n")
    for t, d in sell_results:
        print(f"  {t}  收盘价:{d['close']}  日期:{d['date']}  趋势线={d['trend_line']}  市值={d.get('mcap_yi','?')}亿 净利={d.get('jl_growth_pct','?')}%")
    if not sell_results: print("  无")

    if not args.no_json:
        save_json("buy", buy_results, args.output_dir)
        save_json("sell", sell_results, args.output_dir)

    return buy_results, sell_results

if __name__ == "__main__": main()
