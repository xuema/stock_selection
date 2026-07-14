#!/usr/bin/env python3
"""
双重共振筛选：同时满足 RSI 金叉 + 超级顶底买入信号

1. RSI(12) 上穿 RSI_MA(56) 且成交额 ≥ 3亿
2. 超级顶底趋势线上穿 11

基本面过滤(默认开启):
  - 市值 >= 50亿  且  净利同比增长(Q1) > 0

输出: screen_rsi_stb_resonance_<YYYY-MM-DD>.json + latest.json
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

def calc_rsi(series, period=12):
    delta = series.diff()
    gain, loss = delta.clip(lower=0), (-delta).clip(lower=0)
    rs = gain.ewm(span=period, adjust=False).mean() / loss.ewm(span=period, adjust=False).mean().replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def _sma_td(series, n, m):
    x = series.astype(np.float64).values
    result = np.full(len(x), np.nan, dtype=np.float64)
    alpha, fv = m / n, None
    for i in range(len(x)):
        if np.isfinite(x[i]): fv = i; result[i] = x[i]; break
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
    return 3 * _sma_td(rsv, 5, 1) - 2 * _sma_td(_sma_td(rsv, 5, 1), 3, 1)

def check_stock(filepath, mc=50, jl=0):
    ticker = os.path.basename(filepath).replace(".csv", "")
    try:
        df = pd.read_csv(filepath, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
        for c in ["Close","High","Low","Volume"]: df[c] = pd.to_numeric(df[c], errors="coerce")
        df.dropna(subset=["Close","Volume"], inplace=True)
    except: return ticker, False, {}
    if len(df) < 60: return ticker, False, {}

    # 基本面过滤
    if not _check_fund(ticker, mc, jl): return ticker, False, {}

    # RSI 金叉
    rsi = calc_rsi(df["Close"], 12)
    rsi_ma = rsi.rolling(56).mean()
    if np.isnan(rsi.iloc[-1]) or np.isnan(rsi_ma.iloc[-1]): return ticker, False, {}
    rsi_cross = (rsi.iloc[-2] < rsi_ma.iloc[-2]) & (rsi.iloc[-1] > rsi_ma.iloc[-1])
    if not rsi_cross: return ticker, False, {}

    # 成交额过滤
    if df["Close"].iloc[-1] * df["Volume"].iloc[-1] < 3e8: return ticker, False, {}

    # 超级顶底买入
    trend = calc_trend_line(df)
    if len(trend) < 2: return ticker, False, {}
    t_now, t_prev = trend.iloc[-1], trend.iloc[-2]
    if not np.isfinite(t_now) or not np.isfinite(t_prev): return ticker, False, {}
    stb_buy = (t_prev <= 11) & (t_now > 11)
    if not stb_buy: return ticker, False, {}

    return ticker, True, {
        "date": df["Date"].iloc[-1].strftime("%Y-%m-%d"),
        "close": round(float(df["Close"].iloc[-1]), 2),
        "volume": int(df["Volume"].iloc[-1]),
        "rsi12": round(float(rsi.iloc[-1]), 2),
        "rsi_ma56": round(float(rsi_ma.iloc[-1]), 2),
        "trend_line": round(t_now, 2), "trend_prev": round(t_prev, 2),
        "mcap_yi": _fi(ticker, "mcap_yi"),
        "jl_growth_pct": _fi(ticker, "jl_growth_pct"),
        "name": _name(ticker),
    }

def save_json(results, output_dir):
    today = date.today().strftime("%Y-%m-%d")
    os.makedirs(output_dir, exist_ok=True)
    stocks = [{"ticker": t, "name": d.get("name","") or _name(t), **{k:v for k,v in d.items() if k!="name"}} for t, d in results]
    payload = {"strategy": "rsi_stb_resonance", "strategy_name": "RSI 金叉 + 超级顶底 双重共振",
               "screen_date": today, "total_scanned": _total_scanned, "total_matched": len(results), "stocks": stocks}
    dated, latest = os.path.join(output_dir, f"screen_rsi_stb_resonance_{today}.json"), os.path.join(output_dir, "screen_rsi_stb_resonance_latest.json")
    for p in [dated, latest]:
        with open(p, "w", encoding="utf-8") as f: json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n💾 JSON 已保存:\n   {dated}\n   {latest}")

_total_scanned = 0

def main():
    ap = argparse.ArgumentParser(description="RSI 金叉 + 超级顶底 双重共振选股")
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

    print(f"\n{'='*60}\n🔗 RSI 金叉 + 超级顶底 双重共振: {len(results)} 只\n")
    for t, d in results:
        print(f"  {t}  收盘价:{d['close']}  日期:{d['date']}  市值={d.get('mcap_yi')}亿 净利={d.get('jl_growth_pct')}%")
        print(f"    RSI12={d['rsi12']} 趋势线={d['trend_line']} (上穿11)\n")
    if not results: print("  无")

    if not args.no_json: save_json(results, args.output_dir)
    return results

if __name__ == "__main__": main()
