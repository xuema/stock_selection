#!/usr/bin/env python3
"""
RPS趋势策略 V2 — RPS20>=70 且 RPS120>=85

核心逻辑:
  1. RPS计算: 全市场 20日/120日 收益率百分位排名
  2. 入选条件 (全部满足):
     - RPS_20 >= 70  (前30%)
     - RPS_120 >= 85 (前15%)
  3. 市值过滤: 总市值 >= 50亿
  4. 流动性过滤: 20日日均成交额 >= 1亿
  5. 放量过滤: 当日成交量 >= 近5日均量 × 1.2
  6. ATR(14) 动态止损 = 收盘价 − 2.0×ATR
  7. 排序: score = RPS_20 + RPS_120 → 输出全部匹配

数据来源: data_cache_daily/*.csv (Date,Close,High,Low,Open,Volume)
          stock_fundamentals_cache.json (市值)

用法:
    python3 screen_rps_trend_v2.py
    python3 screen_rps_trend_v2.py --top 10     # 只取Top10
    python3 screen_rps_trend_v2.py --no-mcap-filter   # 跳过市值过滤
    python3 screen_rps_trend_v2.py --no-amount-filter # 跳过成交额过滤
"""

import os, sys, json, glob, argparse, numpy as np, pandas as pd
from tqdm import tqdm
from datetime import date

# ═══ 可调参数 ═══
PARAMS = dict(
    max_hold_count   = 5,       # 最大持仓数
    min_market_cap   = 50.0,    # 最小市值（亿元）
    min_daily_amount = 1.0,     # 20日日均成交额（亿元）
    rps_day_min      = 70,      # 20日RPS最小值
    rps_month_min    = 85,      # 120日RPS最小值
    volume_ratio_min = 1.2,     # 5日均量放量倍数
    atr_period       = 14,      # ATR计算周期
    atr_multiplier   = 2.0,     # ATR动态止损倍数
)

_CACHE = {}
_BASE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ═══ 名称 & 基本面 ═══
def _load_names():
    if "names" in _CACHE: return _CACHE["names"]
    _CACHE["names"] = {}
    for p in [_BASE + "/stock_names.json", _BASE + "/../stock_names.json"]:
        if os.path.exists(p):
            try:
                with open(p) as f: _CACHE["names"] = json.load(f); return _CACHE["names"]
            except: pass
    return _CACHE["names"]

def _name(t):
    if "names" not in _CACHE: _load_names()
    return _CACHE["names"].get(t, "")

def _load_fund():
    if "fund" in _CACHE: return _CACHE["fund"]
    _CACHE["fund"] = {}
    fp = _BASE + "/stock_fundamentals_cache.json"
    if os.path.exists(fp):
        try:
            with open(fp) as f: _CACHE["fund"] = json.load(f)
        except: pass
    return _CACHE["fund"]

def _mcap(t):
    if "fund" not in _CACHE: _load_fund()
    return _CACHE["fund"].get(t, {}).get("mcap_yi", None)

# ═══ 指标 ═══
def _atr(df, w=14):
    """计算ATR (Average True Range)"""
    prev = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev).abs(),
        (df["Low"] - prev).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(w).mean()

def _calc_rps(returns_dict):
    """全市场RPS: 百分位排名 × 100"""
    if not returns_dict: return {}
    df_ret = pd.DataFrame(list(returns_dict.items()), columns=["code", "ret"])
    df_ret["rps"] = df_ret["ret"].rank(pct=True) * 100
    return dict(zip(df_ret["code"], df_ret["rps"]))

# ═══ 逐股分析 ═══
def analyze_stock(filepath, args):
    ticker = os.path.basename(filepath).replace(".csv", "")
    nm = _name(ticker)
    if nm and ('ST' in nm.upper() or '退' in nm):
        return ticker, False, {"filtered": "ST/退市"}

    try:
        df = pd.read_csv(filepath, parse_dates=["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        for c in ["Close", "High", "Low", "Open", "Volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df.dropna(subset=["Close", "High", "Low", "Volume"], inplace=True)
    except:
        return ticker, False, {"filtered": "read_error"}

    need_bars = max(120, PARAMS["atr_period"]) + 5
    if len(df) < need_bars:
        return ticker, False, {"filtered": f"bars不足: {len(df)}/{need_bars}"}

    # ── 市值过滤 ──
    mc = _mcap(ticker)
    if not args.no_mcap_filter:
        if mc is not None and float(mc) < PARAMS["min_market_cap"]:
            return ticker, False, {"filtered": f"市值不足: {mc}亿"}

    # ── 流动性过滤: 20日日均成交额 >= 1亿 ──
    avg_amount_yi = None
    if not args.no_amount_filter:
        df["amount"] = df["Close"] * df["Volume"]
        avg_amount_20 = df["amount"].iloc[-20:].mean()
        avg_amount_yi = avg_amount_20 / 1e8
        if avg_amount_yi < PARAMS["min_daily_amount"]:
            return ticker, False, {"filtered": f"日均成交额不足: {avg_amount_yi:.2f}亿"}

    close_now = float(df["Close"].iloc[-1])
    date_str  = df["Date"].iloc[-1].strftime("%Y-%m-%d")

    # ── RPS收益率 ──
    ret_20  = (close_now / float(df["Close"].iloc[-20]))  - 1.0
    ret_120 = (close_now / float(df["Close"].iloc[-120])) - 1.0

    # ── 量比 ──
    vol_now   = float(df["Volume"].iloc[-1])
    vol_avg_5 = float(df["Volume"].iloc[-6:-1].mean())
    vol_ratio = vol_now / vol_avg_5 if vol_avg_5 > 0 else 1.0

    if vol_ratio < PARAMS["volume_ratio_min"]:
        return ticker, False, {
            "filtered": f"放量不足: {vol_ratio:.2f}x",
            "ret_20": round(ret_20, 4),
            "ret_120": round(ret_120, 4),
            "vol_ratio": round(vol_ratio, 2),
        }

    # ── ATR & 止损价 ──
    atr_val = float(_atr(df, PARAMS["atr_period"]).iloc[-1])
    atr_round = round(atr_val, 2) if np.isfinite(atr_val) else None
    atr_stop  = round(close_now - PARAMS["atr_multiplier"] * atr_val, 2) \
                if atr_val and np.isfinite(atr_val) else None

    return ticker, True, {
        "date":           date_str,
        "close":          round(close_now, 2),
        "ret_20":         round(ret_20, 4),
        "ret_120":        round(ret_120, 4),
        "vol_ratio":      round(vol_ratio, 2),
        "atr":            atr_round,
        "atr_stop_2x":    atr_stop,
        "mcap_yi":        mc,
        "avg_amount_yi":  round(avg_amount_yi, 2) if avg_amount_yi else None,
        "name":           nm,
    }

# ═══ JSON 输出 ═══
def save_json(buy_list, output_dir):
    today = date.today().strftime("%Y-%m-%d")
    os.makedirs(output_dir, exist_ok=True)

    stocks_out = []
    for ticker, d in buy_list:
        stocks_out.append({
            "ticker":        ticker,
            "name":          d.get("name", "") or _name(ticker),
            "date":          d.get("date"),
            "close":         d.get("close"),
            "rps_20":        d.get("rps_20"),
            "rps_120":       d.get("rps_120"),
            "score":         d.get("score"),
            "volume_ratio":  d.get("vol_ratio"),
            "atr_14":        d.get("atr"),
            "atr_stop_2x":   d.get("atr_stop_2x"),
            "mcap_yi":       d.get("mcap_yi"),
            "avg_amount_yi": d.get("avg_amount_yi"),
        })

    payload = {
        "strategy":       "screen_rps_trend_v2",
        "strategy_name":  "RPS趋势策略 V2",
        "signal_type":    "buy",
        "screen_date":    today,
        "params":         {k: PARAMS[k] for k in [
            "rps_day_min", "rps_month_min", "volume_ratio_min",
            "atr_period", "atr_multiplier", "min_market_cap", "min_daily_amount"]},
        "total_matched":  len(stocks_out),
        "stocks":         stocks_out,
    }

    dated  = os.path.join(output_dir, f"screen_rps_trend_v2_{today}.json")
    latest = os.path.join(output_dir, "screen_rps_trend_v2_latest.json")
    for p in [dated, latest]:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n💾 JSON 已保存:\n   {dated}\n   {latest}")

# ═══ 主流程 ═══
def main():
    ap = argparse.ArgumentParser(description="RPS趋势策略 V2 — RPS20>=70 且 RPS120>=85")
    ap.add_argument("--data-dir", default="/Users/skyler/workspace/stock_selection/data_cache_daily")
    ap.add_argument("--output-dir", default="/Users/skyler/workspace/stock_selection/output/strategy")
    ap.add_argument("--top", type=int, default=None, help="只取TopN（默认=不截断）")
    ap.add_argument("--no-mcap-filter", action="store_true", help="跳过市值过滤")
    ap.add_argument("--no-amount-filter", action="store_true", help="跳过日均成交额过滤")
    ap.add_argument("--rps-day", type=int, default=70, help="20日RPS阈值（默认70）")
    ap.add_argument("--rps-month", type=int, default=85, help="120日RPS阈值（默认85）")
    args = ap.parse_args()

    PARAMS["rps_day_min"]   = args.rps_day
    PARAMS["rps_month_min"] = args.rps_month
    N = args.top  # None = 不截断

    print(f"╔{'═'*58}╗")
    print(f"║  📊 RPS趋势策略 V2                              ║")
    top_label = f"Top{N}" if N is not None else "全部"
    print(f"║     RPS20≥{PARAMS['rps_day_min']}  RPS120≥{PARAMS['rps_month_min']}  "
          f"放量≥{PARAMS['volume_ratio_min']:.1f}x  |  {top_label}         ║")
    print(f"╚{'═'*58}╝\n")

    csvs = sorted(glob.glob(os.path.join(args.data_dir, "*.csv")))
    print(f"📁 共 {len(csvs)} 只股票，开始扫描…\n")

    # ── 逐股分析 ──
    results = {}
    ret_20_map, ret_120_map = {}, {}
    for fp in tqdm(csvs, desc="扫描中"):
        ticker, passed, detail = analyze_stock(fp, args)
        if not passed: continue
        results[ticker] = detail
        ret_20_map[ticker]  = detail["ret_20"]
        ret_120_map[ticker] = detail["ret_120"]

    print(f"\n✅ 通过基础过滤 (市值/量/量比): {len(results)} 只\n")

    # ── 全市场RPS ──
    rps_20  = _calc_rps(ret_20_map)
    rps_120 = _calc_rps(ret_120_map)

    # ── RPS条件筛选 ──
    candidates = []
    for ticker, d in results.items():
        r20 = rps_20.get(ticker)
        r120 = rps_120.get(ticker)
        if r20 is None or r120 is None: continue
        if r20  < PARAMS["rps_day_min"]:   continue
        if r120 < PARAMS["rps_month_min"]: continue
        d["rps_20"]  = round(r20,  1)
        d["rps_120"] = round(r120, 1)
        d["score"]   = round(r20 + r120, 1)
        candidates.append((ticker, d))

    print(f"📋 RPS 过滤后: {len(candidates)} 只满足全部条件\n")

    # ── 排序 ──
    candidates.sort(key=lambda x: x[1]["score"], reverse=True)
    if N is not None and len(candidates) > N:
        buy_list = candidates[:N]
        print(f"⚠️  共 {len(candidates)} 只满足条件 → Top{N}\n")
    else:
        buy_list = candidates

    # ── 打印 ──
    print(f"{'='*115}")
    print(f"🟢 买入信号 Top{len(buy_list)} — 按 Score 降序")
    print(f"{'='*115}")
    hdr = (f"  {'排名':>3}  {'代码':>6}  {'名称':<8}  {'收盘价':>7}  "
           f"{'RPS20':>5}  {'RPS120':>6}  {'Score':>5}  "
           f"{'量比':>4}  {'ATR(14)':>6}  {'2×ATR止损':>9}  "
           f"{'市值(亿)':>7}  {'日均亿':>6}")
    print(hdr)
    print(f"{'─'*115}")
    for rank, (t, d) in enumerate(buy_list, 1):
        nm  = d.get('name', '') or _name(t)
        atr = d['atr'] if d.get('atr') else 'N/A'
        as_ = str(d['atr_stop_2x']) if d.get('atr_stop_2x') else 'N/A'
        mc  = d.get('mcap_yi', '?') if d.get('mcap_yi') else '?'
        am  = d.get('avg_amount_yi', '?') if d.get('avg_amount_yi') else '?'
        print(f"  {rank:>3}  {t:>6}  {nm:<8}  {d['close']:>7.2f}  "
              f"{d['rps_20']:>5.1f}  {d['rps_120']:>6.1f}  {d['score']:>5.1f}  "
              f"{d['vol_ratio']:>4.1f}x  {atr:>6}  {as_:>9}  "
              f"{str(mc):>7}  {str(am):>6}")
    print(f"{'─'*115}")
    print(f"  说明: 2×ATR止损=收盘价−2.0×ATR  |  Score=RPS20+RPS120\n")

    if not buy_list:
        print("😐 当前无股票满足全部条件。")

    save_json(buy_list, args.output_dir)

if __name__ == "__main__":
    main()
