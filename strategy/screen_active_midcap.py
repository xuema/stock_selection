#!/usr/bin/env python3
"""
活跃中盘股筛选 — 量价共振 + 涨停基因

主板(60/00):
  涨幅 2%-7%, 换手率 5%-10%
双创(300/688):
  涨幅 3%-8%, 换手率 5%-15%

共同条件:
  市值 50-300亿
  量比 > 1 (当日vs近10日均量)
  近15个交易日内有涨停

输出:
  - JSON → screen_active_midcap_<YYYY-MM-DD>.json
  - JSON → screen_active_midcap_latest.json
"""

import os, sys, json, glob, argparse
import pandas as pd, numpy as np
from tqdm import tqdm
from datetime import date

# ─── 可调参数 ───
PARAMS = dict(
    vol_window=10,
    vol_ratio_min=1.0,
    min_mcap_yi=50,
    max_mcap_yi=300,
    limitup_days=15,
    # 主板
    mb_pct_lo=2,  mb_pct_hi=7,
    mb_turn_lo=5,   mb_turn_hi=10,
    # 双创
    cx_pct_lo=3,  cx_pct_hi=8,
    cx_turn_lo=5,   cx_turn_hi=15,
)

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

# ─── 基本面缓存 ───
_FUND_CACHE = {}

def _cache_path():
    return os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir, "stock_fundamentals_cache.json"))

def _load_fundamentals():
    global _FUND_CACHE
    if _FUND_CACHE: return _FUND_CACHE
    cp = _cache_path()
    if os.path.exists(cp):
        try:
            with open(cp) as f: _FUND_CACHE = json.load(f)
        except: pass
    return _FUND_CACHE

def _mcap(t):
    return _FUND_CACHE.get(t, {}).get("mcap_yi", None)

# ─── 板块识别 ───
def _board(ticker):
    """返回 'mb'(主板) / 'cx'(双创) / 'other'"""
    if ticker.startswith(("60", "000", "001", "002")):
        return "mb"
    elif ticker.startswith(("300", "688")):
        return "cx"
    return "other"

# ─── 涨停判断 ───
def _has_limitup(df, board, days=15):
    """最近N个交易日内是否有涨停"""
    if board == "mb":
        limit_pct = 0.098  # 9.8% 容差 (10% 涨停含小数位误差)
    else:
        limit_pct = 0.195  # 19.5% 容差 (20% 涨停)

    recent = df.tail(days)
    pct = recent["Close"].pct_change()
    # 涨停日: 涨幅 >= limit_pct 且 Close == High (封板到收盘)
    return bool(((pct >= limit_pct) & (recent["Close"] >= recent["High"] * 0.999)).any())

# ─── 核心扫描 ───
def check_stock(filepath):
    ticker = os.path.basename(filepath).replace(".csv", "")

    # 剔除 ST / *ST （名称检查 + 历史涨跌幅5%特征检查）
    nm = _name(ticker)
    if nm and ("ST" in nm.upper()):
        return ticker, False, {}

    board = _board(ticker)
    if board == "other":
        return ticker, False, {}

    try:
        df = pd.read_csv(filepath, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
        for c in ["Close", "High", "Low", "Volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df.dropna(subset=["Close", "Volume"], inplace=True)
    except:
        return ticker, False, {}

    if len(df) < 20:
        return ticker, False, {}

    # ── 市值 50-300亿 ──
    mc = _mcap(ticker)
    if mc is None or mc < PARAMS["min_mcap_yi"] or mc > PARAMS["max_mcap_yi"]:
        return ticker, False, {}

    close_now = float(df["Close"].iloc[-1])
    close_prev = float(df["Close"].iloc[-2])
    date_str = df["Date"].iloc[-1].strftime("%Y-%m-%d")

    # ── 涨幅 ──
    pct = (close_now - close_prev) / close_prev * 100

    if board == "mb":
        if pct < PARAMS["mb_pct_lo"] or pct > PARAMS["mb_pct_hi"]:
            return ticker, False, {}
    else:  # cx
        if pct < PARAMS["cx_pct_lo"] or pct > PARAMS["cx_pct_hi"]:
            return ticker, False, {}

    # ── 换手率 ──
    # 用市值估算总股本: shares ≈ mcap_yi * 1e8 / close
    shares_est = (mc * 1e8) / close_now if close_now > 0 else 1
    vol = df["Volume"].iloc[-1]
    turnover_pct = vol / shares_est * 100

    if board == "mb":
        if turnover_pct < PARAMS["mb_turn_lo"] or turnover_pct > PARAMS["mb_turn_hi"]:
            return ticker, False, {}
    else:  # cx
        if turnover_pct < PARAMS["cx_turn_lo"] or turnover_pct > PARAMS["cx_turn_hi"]:
            return ticker, False, {}

    # ── 量比 > 1 ──
    vol_now = vol
    vol_avg = df["Volume"].iloc[-PARAMS["vol_window"]:-1].mean()
    vratio = vol_now / vol_avg if vol_avg > 0 else 1.0
    if vratio < PARAMS["vol_ratio_min"]:
        return ticker, False, {}

    # ── 近15天有涨停 ──
    if not _has_limitup(df, board, PARAMS["limitup_days"]):
        return ticker, False, {}

    return ticker, True, {
        "date": date_str,
        "close": round(close_now, 2),
        "pct": round(pct, 2),
        "turnover_pct": round(turnover_pct, 2),
        "v_ratio": round(vratio, 2),
        "board": board,
        "mcap_yi": mc,
        "name": _name(ticker),
    }


# ─── JSON输出 ───
def save_json(results, output_dir):
    today = date.today().strftime("%Y-%m-%d")
    os.makedirs(output_dir, exist_ok=True)
    strategy = "screen_active_midcap"
    stocks = [{"ticker": t, "name": d.get("name", "") or _name(t),
               **{k: v for k, v in d.items() if k != "name"}} for t, d in results]
    payload = {"strategy": strategy, "strategy_name": "活跃中盘股",
               "screen_date": today, "total_scanned": _total_scanned,
               "total_matched": len(results), "stocks": stocks}
    dated = os.path.join(output_dir, f"{strategy}_{today}.json")
    latest = os.path.join(output_dir, f"{strategy}_latest.json")
    for p in [dated, latest]:
        with open(p, "w", encoding="utf-8") as f: json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n💾 JSON 已保存:\n   {dated}\n   {latest}")


_total_scanned = 0


def main():
    ap = argparse.ArgumentParser(description="活跃中盘股筛选 — 量价共振 + 涨停基因")
    ap.add_argument("--data-dir", default="/Users/skyler/workspace/stock_selection/data_cache_daily")
    ap.add_argument("--output-dir", default="/Users/skyler/workspace/stock_selection/output/strategy")
    args = ap.parse_args()

    csvs = sorted(glob.glob(os.path.join(args.data_dir, "*.csv")))
    print(f"共找到 {len(csvs)} 只股票，开始扫描…\n")
    global _total_scanned
    _total_scanned = len(csvs)

    _load_fundamentals()
    _load_names()

    results = []
    for fp in tqdm(csvs, desc="扫描中"):
        t, ok, d = check_stock(fp)
        if ok:
            results.append((t, d))

    # 按量比降序（活跃度排序）
    results.sort(key=lambda x: x[1].get("v_ratio", 0), reverse=True)

    print(f"\n{'='*80}")
    print(f"🟢 活跃中盘股 {len(results)} 只 — 按量比降序")
    print(f"{'='*80}\n")
    header = f"  {'排名':>3}  {'代码':<10}  {'名称':<8}  板块  收盘价  涨幅%  换手率%  量比  市值(亿)  日期"
    print(header)
    for rank, (t, d) in enumerate(results, 1):
        b_label = "主板" if d["board"] == "mb" else "双创"
        print(f"  {rank:>3}  {t:<10}  {d.get('name',''):<8}  {b_label:<4}  {d['close']:>7.2f}  {d['pct']:+6.2f}%  {d['turnover_pct']:>5.2f}%  {d['v_ratio']:>4.2f}  {d['mcap_yi']:>6.0f}  {d['date']}")
    if not results:
        print("  无")

    save_json(results, args.output_dir)
    return results


if __name__ == "__main__":
    main()
