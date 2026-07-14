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

基本面过滤(默认开启):
  - 市值 >= 50亿  且  净利同比增长(Q1) > 0

输出: JSON → screen_ma_pullback_<YYYY-MM-DD>.json + latest.json
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

def screen_one(csv_path, mc=50, jl=0):
    try:
        df = pd.read_csv(csv_path, parse_dates=['Date'])
        df = df.sort_values('Date').reset_index(drop=True)
        for c in ['Close','Volume','High','Low']: df[c] = pd.to_numeric(df.get(c, df['Close']), errors='coerce')
    except: return None
    if len(df) < 60 or df['Close'].isna().any() or df['Volume'].isna().any():
        return None

    close, volume, high = df['Close'], df['Volume'], df['High']
    ma10, ma20, ma60 = close.rolling(10).mean(), close.rolling(20).mean(), close.rolling(60).mean()
    vol5, vol10, vol20 = volume.rolling(5).mean(), volume.rolling(10).mean(), volume.rolling(20).mean()

    last = df.iloc[-1]
    today_close = last['Close']; today_vol = last['Volume']
    v5, v10, v20 = vol5.iloc[-1], vol10.iloc[-1], vol20.iloc[-1]
    m10, m20, m60 = ma10.iloc[-1], ma20.iloc[-1], ma60.iloc[-1]
    if any(np.isnan(x) for x in [v5,v10,v20,m10,m20,m60]): return None

    ma20_5d_ago = ma20.iloc[-5] if len(df) >= 5 else None
    if ma20_5d_ago is None or not (m20 > ma20_5d_ago): return None  # ②
    if not (m10 > m20 > m60): return None  # ①
    if not (today_close > m20): return None  # ③

    recent_high = high.iloc[-20:].max()
    recent_low = df['Low'].iloc[-10:].min()
    if recent_high <= 0: return None
    pullback = (recent_high - recent_low) / recent_high
    if not (0.05 <= pullback <= 0.15): return None  # ④
    if not (v5 < v10 < v20): return None  # ⑤
    if not (v5 < v20 * 0.7): return None  # ⑥

    prev_close = df.iloc[-2]['Close']
    if prev_close <= 0: return None
    pct = (today_close - prev_close) / prev_close
    if not (pct > 0.02): return None  # ⑦
    if not (today_vol > v5 * 1.2): return None  # ⑧
    turnover = today_close * today_vol
    if not (turnover > 3e8): return None  # ⑨

    # 基本面过滤
    ticker = os.path.basename(csv_path).replace(".csv", "")
    if not _check_fund(ticker, mc, jl): return None

    return {
        "ticker": ticker, "name": _name(ticker),
        "close": round(today_close, 2), "pct_change": round(pct * 100, 2),
        "turnover_yi": round(turnover / 1e8, 2),
        "ma10": round(m10, 2), "ma20": round(m20, 2), "ma60": round(m60, 2),
        "vol5": round(v5), "vol10": round(v10), "vol20": round(v20),
        "pullback_pct": round(pullback * 100, 2),
        "date": str(last['Date'].date()) if hasattr(last['Date'], 'date') else str(last['Date'])[:10],
        "mcap_yi": _fi(ticker, "mcap_yi"),
        "jl_growth_pct": _fi(ticker, "jl_growth_pct"),
    }

_total_scanned = 0

def main():
    ap = argparse.ArgumentParser(description="MA 多头排列+回调选股")
    ap.add_argument("--data-dir", default="/Users/skyler/workspace/stock_selection/data_cache_daily")
    ap.add_argument("--output-dir", default="/Users/skyler/workspace/stock_selection/output/strategy")
    ap.add_argument("--no-fundamental-filter", action="store_true", help="跳过基本面过滤")
    args = ap.parse_args(); load_f = not args.no_fundamental_filter

    csvs = sorted(glob.glob(os.path.join(args.data_dir, "*.csv")))
    print(f"共找到 {len(csvs)} 只股票，开始扫描{'(含基本面过滤)' if load_f else ''}…\n")
    global _total_scanned; _total_scanned = len(csvs)
    if load_f: fund_filter._load_fundamentals()

    results = []
    today_str = date.today().isoformat()
    for p in tqdm(csvs, desc="MA 回调筛选"):
        r = screen_one(p)
        if r: results.append(r)
    results.sort(key=lambda x: x['pct_change'], reverse=True)

    print(f"\n{'='*70}\n  📈 MA 多头排列 + 回调放量反弹  日期: {today_str}\n{'='*70}")
    if not results: print("  共 0 只股票满足条件")
    else:
        for r in results:
            print(f"  {r['ticker']} {r.get('name','')} | 收盘 {r['close']}  涨幅 {r['pct_change']:+.2f}%  "
                  f"成交额 {r['turnover_yi']:.2f}亿  回调 {r['pullback_pct']:.1f}%  "
                  f"市值={r.get('mcap_yi','?')}亿 净利增长={r.get('jl_growth_pct','?')}%")
        print(f"\n  共 {len(results)} 只")

    out = os.path.join(args.output_dir, f"screen_ma_pullback_{today_str}.json")
    latest = os.path.join(args.output_dir, "screen_ma_pullback_latest.json")
    for pf in [out, latest]:
        with open(pf, "w", encoding="utf-8") as f: json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n💾 JSON 已保存:\n   {out}\n   {latest}\n{'='*70}\n")

if __name__ == "__main__": main()
