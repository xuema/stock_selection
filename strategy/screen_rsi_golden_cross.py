#!/usr/bin/env python3
"""
筛选满足 RSI(12,56) 刚金叉 的股票
RSI(12) 上穿 RSI_MA(56)

基本面过滤(默认开启):
  - 市值 >= 50亿  且  净利同比增长(Q1)>0

输出:
  - JSON → screen_rsi_golden_cross_<YYYY-MM-DD>.json
  - JSON → screen_rsi_golden_cross_latest.json
"""

import os, sys, json, glob, argparse
import pandas as pd, numpy as np
from tqdm import tqdm
from datetime import date
from fund_filter import _check_fund, _load_fundamentals
import fund_filter

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

def calc_rsi(series, period=12):
    delta = series.diff()
    gain = delta.clip(lower=0); loss = (-delta).clip(lower=0)
    rs = gain.ewm(span=period, adjust=False).mean() / loss.ewm(span=period, adjust=False).mean().replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def _fi(t, key):
    """从 fund_filter 缓存取值"""
    d = fund_filter._FUND_CACHE.get(t, {})
    return d.get(key)

def check_stock(filepath, min_mcap_yi=50, min_jl_growth=0):
    ticker = os.path.basename(filepath).replace(".csv", "")
    try:
        df = pd.read_csv(filepath, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
        for c in ["Close","High","Low","Volume"]: df[c] = pd.to_numeric(df[c], errors="coerce")
        df.dropna(subset=["Close"], inplace=True)
    except: return ticker, False, {}

    if len(df) < 60: return ticker, False, {}

    rsi = calc_rsi(df["Close"], 12)
    rsi_ma = rsi.rolling(56).mean()
    if np.isnan(rsi.iloc[-1]) or np.isnan(rsi_ma.iloc[-1]): return ticker, False, {}

    cross = (rsi.iloc[-2] < rsi_ma.iloc[-2]) & (rsi.iloc[-1] > rsi_ma.iloc[-1])
    if not cross: return ticker, False, {}

    # 成交额过滤
    if df["Close"].iloc[-1] * df["Volume"].iloc[-1] < 300_000_000: return ticker, False, {}

    # 基本面过滤
    if not _check_fund(ticker, min_mcap_yi, min_jl_growth): return ticker, False, {}

    return ticker, True, {
        "date": df["Date"].iloc[-1].strftime("%Y-%m-%d"),
        "close": round(float(df["Close"].iloc[-1]), 2),
        "volume": int(df["Volume"].iloc[-1]),
        "rsi12": round(float(rsi.iloc[-1]), 2),
        "rsi_ma56": round(float(rsi_ma.iloc[-1]), 2),
        "mcap_yi": _fi(ticker, "mcap_yi"),
        "jl_growth_pct": _fi(ticker, "jl_growth_pct"),
        "name": _name(ticker),
    }

def save_json(results, output_dir, strategy="rsi_golden_cross", strategy_name="RSI(12,56) 金叉"):
    today = date.today().strftime("%Y-%m-%d")
    os.makedirs(output_dir, exist_ok=True)
    stocks = [{"ticker": t, "name": d.get("name","") or _name(t), **{k:v for k,v in d.items() if k!="name"}} for t, d in results]
    payload = {"strategy": strategy, "strategy_name": strategy_name, "screen_date": today,
               "total_scanned": _total_scanned, "total_matched": len(results), "stocks": stocks}
    dated = os.path.join(output_dir, f"screen_{strategy}_{today}.json")
    latest = os.path.join(output_dir, f"screen_{strategy}_latest.json")
    for path in [dated, latest]:
        with open(path, "w", encoding="utf-8") as f: json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n💾 JSON 已保存:\n   {dated}\n   {latest}")

_total_scanned = 0

def main():
    ap = argparse.ArgumentParser(description="RSI(12,56) 金叉选股")
    ap.add_argument("--data-dir", default="/Users/skyler/workspace/stock_selection/data_cache_daily")
    ap.add_argument("--output-dir", default="/Users/skyler/workspace/stock_selection/output/strategy")
    ap.add_argument("--no-fundamental-filter", action="store_true", help="跳过基本面过滤")
    ap.add_argument("--no-json", action="store_true")
    args = ap.parse_args(); load_fund = not args.no_fundamental_filter

    csvs = sorted(glob.glob(os.path.join(args.data_dir, "*.csv")))
    print(f"共找到 {len(csvs)} 只股票，开始扫描{'(含基本面过滤)' if load_fund else ''}…\n")

    global _total_scanned
    _total_scanned = len(csvs)

    if load_fund: _load_fundamentals()

    results = []
    for fp in tqdm(csvs, desc="扫描中"):
        t, ok, d = check_stock(fp)
        if ok: results.append((t, d))

    if results:
        print(f"\n{'='*60}\n✅ 共 {len(results)} 只股票满足条件\n")
        for t, d in results:
            mc = d.get('mcap_yi','?'); jl = d.get('jl_growth_pct','?')
            print(f"  {t}  收盘价:{d['close']}  日期:{d['date']}")
            print(f"    RSI12={d['rsi12']} > RSI_MA56={d['rsi_ma56']} (金叉) | 市值={mc}亿 净利={jl}%\n")
    else: print("\n未找到满足条件的股票。")

    if not args.no_json: save_json(results, args.output_dir)
    return results

if __name__ == "__main__": main()
