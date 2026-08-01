#!/usr/bin/env python3
"""
RPS多周期趋势跟踪 Pro — 选股脚本

策略逻辑 (参考 spec_rps_multi_period_trend_pro.md):
  1. 股票池过滤: 市值>=50亿, 排除ST
  2. 大盘择时: 沪深300收盘价 > MA150 → 才允许信号
  3. RPS计算: 20日/120日相对价格强度(全市场百分位排名)
  4. 入选条件(全部满足):
     - RPS_20 >= 85 (前15%)
     - RPS_120 >= 80 (前20%)
     - 当前价 >= 近180日最高价 × 90% (窗口可调)
     - 当日成交量 >= 近5日均量 × 1.8 (放量突破)
  5. 排序: score = RPS_20 + RPS_120 → 取Top10 (max_hold_count × 2)
  6. ATR(14)计算 → 动态止损价 = 收盘价 − 2×ATR
  7. 硬止损价 = 收盘价 × (1 − 8%)

数据来源: data_cache_daily/*.csv (Date,Close,High,Low,Open,Volume)
          stock_fundamentals_cache.json (市值)

用法:
    python3 screen_rps_trend_pro.py                        # 默认(180日窗口)
    python3 screen_rps_trend_pro.py --high-window 250      # 改成250日
    python3 screen_rps_trend_pro.py --top 5                # 只取Top5
    python3 screen_rps_trend_pro.py --no-market-filter     # 跳过大盘择时
"""

import os, sys, json, glob, argparse, numpy as np, pandas as pd
from tqdm import tqdm
from datetime import date

# ═══ 可调参数 ═══
PARAMS = dict(
    max_hold_count   = 5,      # 最大持仓数
    min_market_cap   = 50.0,   # 最小市值（亿元）
    high_window      = 180,    # 近N日最高价窗口
    rps_day_min      = 85,     # 20日RPS最小值
    rps_month_min    = 80,     # 120日RPS最小值
    near_high_ratio  = 0.90,   # 近N日最高价比例
    volume_ratio_min = 1.2,    # 放量倍数 (1.2x)
    hard_stop_loss   = 0.08,   # 8% 硬止损
    atr_period       = 14,     # ATR周期
    atr_multiplier   = 2.0,    # ATR止损倍数
    market_ma_period = 150,    # 大盘均线周期
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
    prev = df["Close"].shift(1)
    tr = pd.concat([df["High"]-df["Low"], (df["High"]-prev).abs(), (df["Low"]-prev).abs()], axis=1).max(axis=1)
    return tr.rolling(w).mean()

def _calc_rps(returns_dict):
    """全市场RPS: 百分位排名 × 100"""
    if not returns_dict: return {}
    df_ret = pd.DataFrame(list(returns_dict.items()), columns=["code", "ret"])
    df_ret["rps"] = df_ret["ret"].rank(pct=True) * 100
    return dict(zip(df_ret["code"], df_ret["rps"]))

def _check_market_bull(index_df, ma_period=150):
    """大盘择时: 收盘价 > MA(period)。自适应数据长度。"""
    n = min(ma_period, len(index_df) - 1)
    if n < 10: return False
    ma = index_df["Close"].rolling(n).mean().iloc[-1]
    return index_df["Close"].iloc[-1] > ma

def _load_index(index_path):
    if not os.path.exists(index_path): return None
    try:
        df = pd.read_csv(index_path, parse_dates=["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        df.dropna(subset=["Close"], inplace=True)
        return df
    except: return None

# ═══ 逐股分析 ═══
def analyze_stock(filepath):
    ticker = os.path.basename(filepath).replace(".csv", "")
    nm = _name(ticker)
    if nm and ('ST' in nm.upper()):
        return ticker, False, {"filtered": "ST"}
    try:
        df = pd.read_csv(filepath, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
        for c in ["Close","High","Low","Open","Volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df.dropna(subset=["Close","High","Low","Volume"], inplace=True)
    except:
        return ticker, False, {"filtered": "read_error"}

    available = len(df)
    high_window = min(PARAMS["high_window"], available)
    need_bars = max(120, high_window)
    if available < need_bars:
        return ticker, False, {"filtered": f"bars不足: {available}/{need_bars}"}

    mc = _mcap(ticker)
    if mc is not None and float(mc) < PARAMS["min_market_cap"]:
        return ticker, False, {"filtered": f"市值不足: {mc}亿"}

    close_now = float(df["Close"].iloc[-1])
    date_str  = df["Date"].iloc[-1].strftime("%Y-%m-%d")

    # RPS收益率
    ret_20  = (close_now / float(df["Close"].iloc[-20]))  - 1.0
    ret_120 = (close_now / float(df["Close"].iloc[-120])) - 1.0

    # 近N日最高价比例
    high_N = float(df["Close"].rolling(high_window).max().iloc[-1])
    high_ratio = close_now / high_N if high_N > 0 else 0

    # 量比
    vol_now = float(df["Volume"].iloc[-1])
    vol_avg_5 = float(df["Volume"].iloc[-6:-1].mean())
    vol_ratio = vol_now / vol_avg_5 if vol_avg_5 > 0 else 1.0

    # ATR & 止损价
    atr_val = float(_atr(df, PARAMS["atr_period"]).iloc[-1])
    atr_round = round(atr_val, 2) if np.isfinite(atr_val) else None
    atr_stop  = round(close_now - PARAMS["atr_multiplier"] * atr_val, 2) \
                if atr_val and np.isfinite(atr_val) else None
    hard_stop = round(close_now * (1.0 - PARAMS["hard_stop_loss"]), 2)

    return ticker, True, {
        "date":          date_str,
        "close":         round(close_now, 2),
        "ret_20":        round(ret_20, 4),
        "ret_120":       round(ret_120, 4),
        "high_N":        round(high_N, 2),
        "high_window":   high_window,
        "high_ratio":    round(high_ratio, 3),
        "vol_ratio":     round(vol_ratio, 2),
        "atr":           atr_round,
        "atr_stop_2x":   atr_stop,
        "hard_stop_8pct": hard_stop,
        "mcap_yi":       mc,
        "name":          nm,
    }

# ═══ JSON 输出 ═══
def save_json(buy_list, output_dir, market_ok=True):
    today = date.today().strftime("%Y-%m-%d")
    os.makedirs(output_dir, exist_ok=True)

    stocks_out = []
    for ticker, d in buy_list:
        stocks_out.append({
            "ticker":         ticker,
            "name":           d.get("name","") or _name(ticker),
            "date":           d.get("date"),
            "close":          d.get("close"),
            "rps_20":         d.get("rps_20"),
            "rps_120":        d.get("rps_120"),
            "score":          d.get("score"),
            "volume_ratio":   d.get("vol_ratio"),
            "high_ratio":     d.get("high_ratio"),
            "high_window":    d.get("high_window", PARAMS["high_window"]),
            "atr_14":         d.get("atr"),
            "atr_stop_2x":    d.get("atr_stop_2x"),    # 2×ATR动态止损价
            "hard_stop_8pct": d.get("hard_stop_8pct"),  # 8%硬止损价
            "mcap_yi":        d.get("mcap_yi"),
        })

    payload = {
        "strategy":       "screen_rps_trend_pro",
        "strategy_name":  "RPS多周期趋势跟踪 Pro",
        "signal_type":    "buy",
        "screen_date":    today,
        "market_bullish": market_ok,
        "params":         {k: PARAMS[k] for k in [
            "rps_day_min","rps_month_min","near_high_ratio","volume_ratio_min",
            "atr_multiplier","hard_stop_loss","min_market_cap","max_hold_count","high_window"]},
        "total_matched":  len(stocks_out),
        "stocks":         stocks_out,
    }

    dated  = os.path.join(output_dir, f"screen_rps_trend_pro_{today}.json")
    latest = os.path.join(output_dir, "screen_rps_trend_pro_latest.json")
    for p in [dated, latest]:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n💾 JSON 已保存:\n   {dated}\n   {latest}")

# ═══ 主流程 ═══
def main():
    ap = argparse.ArgumentParser(description="RPS多周期趋势跟踪 Pro — 强势股趋势跟踪 + ATR止损")
    ap.add_argument("--data-dir", default="/Users/skyler/workspace/stock_selection/data_cache_daily")
    ap.add_argument("--output-dir", default="/Users/skyler/workspace/stock_selection/output/strategy")
    ap.add_argument("--top", type=int, default=None, help="只取TopN（默认max_hold*2=10）")
    ap.add_argument("--high-window", type=int, default=180, help="近N日最高价窗口（默认180）")
    ap.add_argument("--no-market-filter", action="store_true", help="跳过大盘择时")
    ap.add_argument("--rps-day", type=int, default=85, help="20日RPS阈值")
    ap.add_argument("--rps-month", type=int, default=80, help="120日RPS阈值")
    args = ap.parse_args()

    PARAMS["rps_day_min"]   = args.rps_day
    PARAMS["rps_month_min"] = args.rps_month
    PARAMS["high_window"]   = args.high_window
    N = args.top  # None = 不截断，输出全部

    print(f"╔{'═'*58}╗")
    print(f"║  📊 RPS多周期趋势跟踪 Pro                           ║")
    top_label = f"Top{N}" if N is not None else "全部"
    print(f"║     RPS20>={PARAMS['rps_day_min']}  RPS120>={PARAMS['rps_month_min']}  "
          f"近高>={PARAMS['near_high_ratio']:.0%}  "
          f"放量>={PARAMS['volume_ratio_min']:.1f}x             ║")
    print(f"║     大盘择时: MA{PARAMS['market_ma_period']}  |  {top_label}         ║")
    print(f"╚{'═'*58}╝\n")

    csvs = sorted(glob.glob(os.path.join(args.data_dir, "*.csv")))
    print(f"📁 共 {len(csvs)} 只股票，开始扫描…\n")

    # 大盘择时
    market_bull = True
    if not args.no_market_filter:
        idx_path = os.path.join(os.path.dirname(args.data_dir), "000300.csv")
        if not os.path.exists(idx_path):
            idx_path = os.path.join(args.data_dir, "000300.csv")
        idx_df = _load_index(idx_path)
        if idx_df is not None and len(idx_df) >= 20:
            market_bull = _check_market_bull(idx_df, PARAMS["market_ma_period"])
            n = min(PARAMS["market_ma_period"], len(idx_df)-1)
            ma = idx_df["Close"].rolling(n).mean().iloc[-1]
            last = idx_df["Close"].iloc[-1]
            status = "🟢 看多 (允许开仓)" if market_bull else "🔴 看空 (禁止开仓)"
            print(f"📈 大盘择时: 沪深300={last:.0f}  MA{n}={ma:.0f}  → {status}\n")
        else:
            print("⚠️  无沪深300数据，跳过大盘择时\n")

    if not market_bull:
        print("🔴 大盘看空，按策略不产生信号。")
        save_json([], args.output_dir, market_ok=False)
        return

    # 逐股分析
    results = {}
    ret_20_map, ret_120_map = {}, {}
    for fp in tqdm(csvs, desc="扫描中"):
        ticker, passed, detail = analyze_stock(fp)
        if not passed: continue
        results[ticker] = detail
        ret_20_map[ticker]  = detail["ret_20"]
        ret_120_map[ticker] = detail["ret_120"]

    print(f"\n✅ 通过基础过滤: {len(results)} 只\n")

    # 全市场RPS
    rps_20  = _calc_rps(ret_20_map)
    rps_120 = _calc_rps(ret_120_map)

    # 入选条件
    candidates = []
    for ticker, d in results.items():
        r20, r120 = rps_20.get(ticker), rps_120.get(ticker)
        if r20 is None or r120 is None: continue
        if r20  < PARAMS["rps_day_min"]:   continue
        if r120 < PARAMS["rps_month_min"]: continue
        if d["high_ratio"] < PARAMS["near_high_ratio"]:  continue
        if d["vol_ratio"]  < PARAMS["volume_ratio_min"]: continue
        d["rps_20"]  = round(r20,  1)
        d["rps_120"] = round(r120, 1)
        d["score"]   = round(r20 + r120, 1)
        candidates.append((ticker, d))

    print(f"📋 RPS+近高+放量 过滤后: {len(candidates)} 只满足全部条件\n")

    candidates.sort(key=lambda x: x[1]["score"], reverse=True)
    if N is not None and len(candidates) > N:
        buy_list = candidates[:N]
        print(f"⚠️  共 {len(candidates)} 只满足条件 → Top{N}\n")
    else:
        buy_list = candidates
        print(f"📋 全部 {len(buy_list)} 只\n")

    # 打印
    print(f"{'='*115}")
    print(f"🟢 买入信号 Top{len(buy_list)} — 按 Score 降序")
    print(f"{'='*115}")
    hdr = (f"  {'排名':>3}  {'代码':>6}  {'名称':<8}  {'收盘价':>7}  {'RPS20':>5}  "
           f"{'RPS120':>6}  {'Score':>5}  {'量比':>4}  {'近高%':>5}  "
           f"{'ATR(14)':>6}  {'2×ATR止损':>9}  {'8%止损':>8}")
    print(hdr)
    print(f"{'─'*115}")
    for rank, (t, d) in enumerate(buy_list, 1):
        hp  = round(d["high_ratio"] * 100, 1)
        as_ = f"{d['atr_stop_2x']}" if d.get('atr_stop_2x') else "N/A"
        hs  = f"{d['hard_stop_8pct']}" if d.get('hard_stop_8pct') else "N/A"
        print(f"  {rank:>3}  {t:>6}  {(d.get('name') or _name(t)):<8}  "
              f"{d['close']:>7.2f}  {d['rps_20']:>5.1f}  {d['rps_120']:>6.1f}  "
              f"{d['score']:>5.1f}  {d['vol_ratio']:>4.1f}x  {hp:>4.1f}%  "
              f"{d['atr']:>6.2f}  {as_:>9}  {hs:>8}")
    print(f"{'─'*115}")
    print(f"  说明: 2×ATR止损=收盘价−2.0×ATR,  8%止损=收盘价×92%\n")

    save_json(buy_list, args.output_dir, market_ok=True)

if __name__ == "__main__":
    main()
