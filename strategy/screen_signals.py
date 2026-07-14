#!/usr/bin/env python3
"""
筛选同时满足以下买入信号的股票：
1. EXPMA(5,29) 金叉  2. VOL(8,89) 金叉  3. CR(26) 白线在所有均线上方

基本面过滤(默认开启):
  - 市值 >= 50亿  且  净利同比增长(Q1) > 0

输出: JSON → screen_signals_<YYYY-MM-DD>.json + screen_signals_latest.json
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

def ema(s, span): return s.ewm(span=span, adjust=False).mean()

def calc_cr(df, period=26):
    mid = (df["High"] + df["Low"]) / 2
    ms = mid.shift(1)
    pm = np.maximum(0, df["High"] - ms)
    mm = np.maximum(0, ms - df["Low"])
    return pm.rolling(period).sum() / mm.rolling(period).sum().replace(0, np.nan) * 100

def _fi(t, k):
    return fund_filter._FUND_CACHE.get(t, {}).get(k)

def check_stock(filepath, mc=50, jl=0):
    ticker = os.path.basename(filepath).replace(".csv", "")
    try:
        df = pd.read_csv(filepath, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
        for c in ["Close","High","Low","Volume"]: df[c] = pd.to_numeric(df[c], errors="coerce")
        df.dropna(subset=["Close","Volume"], inplace=True)
    except: return ticker, False, {}
    if len(df) < 90: return ticker, False, {}

    e5, e29 = ema(df["Close"],5), ema(df["Close"],29)
    if not ((e5.iloc[-2] < e29.iloc[-2]) & (e5.iloc[-1] > e29.iloc[-1])):
        return ticker, False, {}

    v8, v89 = df["Volume"].rolling(8).mean(), df["Volume"].rolling(89).mean()
    if not ((v8.iloc[-2] < v89.iloc[-2]) & (v8.iloc[-1] > v89.iloc[-1])):
        return ticker, False, {}

    cr = calc_cr(df, 26)
    cr_ok = all(np.isfinite(cr.iloc[-1]) and cr.iloc[-1] > cr.rolling(w).mean().iloc[-1]
               for w in [11,19,35,53])
    if not cr_ok: return ticker, False, {}

    # 基本面过滤
    if not _check_fund(ticker, mc, jl): return ticker, False, {}

    return ticker, True, {
        "date": df["Date"].iloc[-1].strftime("%Y-%m-%d"),
        "close": round(float(df["Close"].iloc[-1]), 2),
        "ema5": round(float(e5.iloc[-1]), 2),
        "ema29": round(float(e29.iloc[-1]), 2),
        "vol_ma8": round(float(v8.iloc[-1])),
        "vol_ma89": round(float(v89.iloc[-1])),
        "cr": round(float(cr.iloc[-1]), 2) if np.isfinite(cr.iloc[-1]) else None,
        "mcap_yi": _fi(ticker, "mcap_yi"),
        "jl_growth_pct": _fi(ticker, "jl_growth_pct"),
        "name": _name(ticker),
    }

def save_json(results, output_dir):
    today = date.today().strftime("%Y-%m-%d")
    os.makedirs(output_dir, exist_ok=True)
    stocks = [{"ticker": t, "name": d.get("name","") or _name(t), **{k:v for k,v in d.items() if k!="name"}} for t, d in results]
    payload = {"strategy": "expma_vol_cr_signals", "strategy_name": "EXPMA+VOL+CR 多因子信号",
               "screen_date": today, "total_scanned": _total_scanned, "total_matched": len(results), "stocks": stocks}
    dated, latest = os.path.join(output_dir, f"screen_signals_{today}.json"), os.path.join(output_dir, "screen_signals_latest.json")
    for p in [dated, latest]:
        with open(p, "w", encoding="utf-8") as f: json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n💾 JSON 已保存:\n   {dated}\n   {latest}")

_total_scanned = 0

def main():
    ap = argparse.ArgumentParser(description="EXPMA+VOL+CR 多因子选股")
    ap.add_argument("--data-dir", default="/Users/skyler/workspace/stock_selection/data_cache_daily")
    ap.add_argument("--output-dir", default="/Users/skyler/workspace/stock_selection/output/strategy")
    ap.add_argument("--no-fundamental-filter", action="store_true", help="跳过基本面过滤")
    ap.add_argument("--no-json", action="store_true")
    args = ap.parse_args(); load_f = not args.no_fundamental_filter

    csvs = sorted(glob.glob(os.path.join(args.data_dir, "*.csv")))
    print(f"共找到 {len(csvs)} 只股票，开始扫描{'(含基本面过滤)' if load_f else ''}…\n")
    global _total_scanned; _total_scanned = len(csvs)
    if load_f: fund_filter._load_fundamentals()

    results = []
    for fp in tqdm(csvs, desc="扫描中"):
        t, ok, d = check_stock(fp)
        if ok: results.append((t, d))

    if results:
        print(f"\n{'='*60}\n✅ 共 {len(results)} 只股票满足全部买入信号\n")
        for t, d in results:
            print(f"  {t}  收盘价:{d['close']}  日期:{d['date']}  市值={d.get('mcap_yi','?')}亿 净利={d.get('jl_growth_pct','?')}%")
            print(f"    EMA5={d['ema5']} > EMA29={d['ema29']} | CR={d['cr']}\n")
    else: print("\n未找到满足条件的股票。")

    if not args.no_json: save_json(results, args.output_dir)
    return results

if __name__ == "__main__": main()
