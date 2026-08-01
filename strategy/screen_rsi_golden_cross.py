#!/usr/bin/env python3
"""
RSI(12,56) 金叉 v2 — 量比过滤 + 评分排序 + ST剔除

金叉规则:
  RSI(12) 上穿 RSI_MA(56)

过滤:
  - ST/*ST 股票剔除
  - 市值 >= 50亿 且 净利同比增长(Q1)>0 (fund_filter)
  - 量比(当日/过去10日均量) >= 1.2
  - 日成交额 >= 3亿

评分:
  穿越角度(0~100) + 量比加成(0~30)

输出:
  - 按评分降序排列
  - 默认输出全部信号, --top N 可截取TopN
  - JSON → screen_rsi_golden_cross_<YYYY-MM-DD>.json
  - JSON → screen_rsi_golden_cross_latest.json
"""

import os, sys, json, glob, argparse
import pandas as pd, numpy as np
from tqdm import tqdm
from datetime import date
from fund_filter import _check_fund, _load_fundamentals
import fund_filter

# ─── 可调参数 ───
PARAMS = dict(
    rsi_period=12,
    rsi_ma=56,
    vol_window=10,
    vol_ratio_min=1.2,
    min_mcap_yi=50,
    min_jl_growth=0,
    min_turnover=300_000_000,  # 3亿
    top_n=0,  # 0=全部
)

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

# ─── 指标计算 ───
def calc_rsi(series, period=12):
    delta = series.diff()
    gain = delta.clip(lower=0); loss = (-delta).clip(lower=0)
    rs = gain.ewm(span=period, adjust=False).mean() / loss.ewm(span=period, adjust=False).mean().replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def _fi(t, key):
    """从 fund_filter 缓存取值"""
    d = fund_filter._FUND_CACHE.get(t, {})
    return d.get(key)

def _calc_score(rsi_cross_angle, vratio):
    """
    评分 = 穿越角度得分(0~100) + 量比得分(0~30)

    穿越角度: RSI 穿越 RSI_MA 的幅度差
      差值越大(金叉越猛), 得分越高, 上限100 (差值>=20分)
    """
    s_angle = min(100, max(0, rsi_cross_angle * 5))      # 1点差=5分, 20点=100分
    s_vol   = min(30, max(0, (vratio - PARAMS["vol_ratio_min"]) * 30 / 2))  # 量比1.2=0分, 3.2=30分
    return round(s_angle + s_vol, 1)

# ─── 核心扫描 ───
def check_stock(filepath, min_mcap_yi=50, min_jl_growth=0):
    ticker = os.path.basename(filepath).replace(".csv", "")

    # 剔除 ST / *ST
    nm = _name(ticker)
    if nm and ('ST' in nm.upper()):
        return ticker, False, {}

    try:
        df = pd.read_csv(filepath, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
        for c in ["Close","High","Low","Volume"]: df[c] = pd.to_numeric(df[c], errors="coerce")
        df.dropna(subset=["Close"], inplace=True)
    except: return ticker, False, {}

    need_bars = max(PARAMS["rsi_ma"], PARAMS["rsi_period"]) + PARAMS["vol_window"] + 5
    if len(df) < need_bars: return ticker, False, {}

    rsi = calc_rsi(df["Close"], PARAMS["rsi_period"])
    rsi_ma = rsi.rolling(PARAMS["rsi_ma"]).mean()
    if np.isnan(rsi.iloc[-1]) or np.isnan(rsi_ma.iloc[-1]): return ticker, False, {}

    # 金叉检测
    cross = (rsi.iloc[-2] < rsi_ma.iloc[-2]) & (rsi.iloc[-1] > rsi_ma.iloc[-1])
    if not cross: return ticker, False, {}

    # 穿越角度 = RSI12 穿越时刻超出 RSI_MA56 的幅度
    cross_angle = rsi.iloc[-1] - rsi_ma.iloc[-1]

    # 成交额过滤
    turnover = df["Close"].iloc[-1] * df["Volume"].iloc[-1]
    if turnover < PARAMS["min_turnover"]: return ticker, False, {}

    # 量比
    vol_now  = df["Volume"].iloc[-1]
    vol_avg  = df["Volume"].iloc[-PARAMS["vol_window"]:-1].mean()
    vratio   = vol_now / vol_avg if vol_avg > 0 else 1.0
    if vratio < PARAMS["vol_ratio_min"]: return ticker, False, {}

    # 基本面过滤
    if not _check_fund(ticker, min_mcap_yi, min_jl_growth): return ticker, False, {}

    # 评分
    score = _calc_score(cross_angle, vratio)

    return ticker, True, {
        "date": df["Date"].iloc[-1].strftime("%Y-%m-%d"),
        "close": round(float(df["Close"].iloc[-1]), 2),
        "volume": int(df["Volume"].iloc[-1]),
        "rsi12": round(float(rsi.iloc[-1]), 2),
        "rsi_ma56": round(float(rsi_ma.iloc[-1]), 2),
        "cross_angle": round(float(cross_angle), 2),
        "v_ratio": round(float(vratio), 2),
        "turnover_yi": round(turnover / 100_000_000, 2),
        "score": score,
        "mcap_yi": _fi(ticker, "mcap_yi"),
        "jl_growth_pct": _fi(ticker, "jl_growth_pct"),
        "name": _name(ticker),
    }

# ─── JSON输出 ───
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
    ap = argparse.ArgumentParser(description="RSI(12,56) 金叉 v2 — 量比过滤 + 评分排序")
    ap.add_argument("--data-dir", default="/Users/skyler/workspace/stock_selection/data_cache_daily")
    ap.add_argument("--output-dir", default="/Users/skyler/workspace/stock_selection/output/strategy")
    ap.add_argument("--top", type=int, default=None, help="只取评分TopN (默认显示全部)")
    ap.add_argument("--no-fundamental-filter", action="store_true", help="跳过基本面过滤")
    args = ap.parse_args()
    load_fund = not args.no_fundamental_filter

    if args.top: PARAMS["top_n"] = args.top

    csvs = sorted(glob.glob(os.path.join(args.data_dir, "*.csv")))
    print(f"共找到 {len(csvs)} 只股票，开始扫描{'(含基本面过滤)' if load_fund else ''}…\n")

    global _total_scanned
    _total_scanned = len(csvs)

    if load_fund: _load_fundamentals()
    _load_names()

    results = []
    for fp in tqdm(csvs, desc="扫描中"):
        t, ok, d = check_stock(fp, PARAMS["min_mcap_yi"], PARAMS["min_jl_growth"])
        if ok: results.append((t, d))

    # 按评分降序
    results.sort(key=lambda x: x[1].get("score", 0), reverse=True)

    top_n = PARAMS["top_n"]
    if top_n and len(results) > top_n:
        results_display = results[:top_n]
        print(f"\n⚠️  共 {len(results)} 个买入信号, 评分降序截取 Top {top_n} ↓\n")
    else:
        results_display = results

    # ── 输出 ──
    print(f"\n{'='*70}")
    print(f"🟢 RSI金叉 {len(results_display)} / {len(results)} 只 — 按评分降序")
    print(f"{'='*70}\n")
    header = f"  {'排名':>3}  {'代码':<10}  {'名称':<8}  收盘价   日期         评分   RSI12   RSI_MA56  角度   量比  成交额(亿)"
    print(header)
    for rank, (t, d) in enumerate(results_display, 1):
        print(f"  {rank:>3}  {t:<10}  {d.get('name',''):<8}  {d['close']:>7}  {d['date']}  ★{d['score']:>5.1f}  {d['rsi12']:>6.2f}  {d['rsi_ma56']:>7.2f}  {d['cross_angle']:>5.2f}  {d['v_ratio']:>4.2f}  {d['turnover_yi']:>6.2f}")
    if not results_display: print("  无")

    if results_display:
        mc_info = []
        for t, d in results_display:
            mc = d.get('mcap_yi'); jl = d.get('jl_growth_pct')
            mc_str = f"{mc}亿" if mc is not None else "N/A"
            jl_str = f"{jl:+.2f}%" if jl is not None else "N/A"
            mc_info.append(f"  {t}  市值={mc_str} 净利增长={jl_str}")
        print(f"\n📊 基本面:\n" + "\n".join(mc_info))

    save_json(results_display, args.output_dir)
    return results_display

if __name__ == "__main__": main()
