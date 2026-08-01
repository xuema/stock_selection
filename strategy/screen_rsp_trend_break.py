#!/usr/bin/env python3
"""
RSP趋势突破策略 — RSP > RSP_MA60 且 RSP_MA20 > RSP_MA60

核心逻辑:
  1. RSP (Relative Strength Price) = 股价 / 基准指数价格 × 1000  (相对强度)
  2. RSP_MA20 = RSP的20日均线
  3. RSP_MA60 = RSP的60日均线
  4. 买入条件: RSP > RSP_MA60  AND  RSP_MA20 > RSP_MA60
     → RSP站上60日线 且 20日均线也在60日线上方 (趋势看涨)
  5. ATR(14) 动态止损 = 收盘价 - 2.0×ATR
  6. 放量过滤: 当日成交量 >= 近5日均量 × 1.2
  7. 市值过滤: 总市值 >= 50亿
  8. 流动性过滤: 20日日均成交额 >= 1亿

基准指数: 沪深300 (000300) 或上证指数 (000001)

用法:
    python3 screen_rsp_trend_break.py
    python3 screen_rsp_trend_break.py --index 000001   # 用上证指数作基准
    python3 screen_rsp_trend_break.py --top 10         # 只取Top10
    python3 screen_rsp_trend_break.py --no-mcap-filter  # 跳过市值过滤
    python3 screen_rsp_trend_break.py --no-amount-filter # 跳过成交额过滤
"""

import os, sys, json, glob, argparse, numpy as np, pandas as pd
from tqdm import tqdm
from datetime import date

# ═══ 可调参数 ═══
PARAMS = dict(
    max_hold_count   = 5,       # 最大持仓数
    min_market_cap   = 50.0,    # 最小市值（亿元）
    min_daily_amount = 1.0,     # 20日日均成交额（亿元）
    atr_period       = 14,      # ATR计算周期
    atr_multiplier   = 2.0,     # ATR移动止损倍数
    volume_ratio_min = 1.2,     # 放量突破倍数
    index_code       = "000300", # 基准指数代码
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

def _load_index(data_dir, idx_code):
    """加载基准指数数据"""
    idx_file = f"{idx_code}.csv"
    p = os.path.join(data_dir, idx_file)
    if not os.path.exists(p):
        return None
    try:
        df = pd.read_csv(p, parse_dates=["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        df.dropna(subset=["Close"], inplace=True)
        return df
    except Exception as e:
        print(f"⚠️  加载指数失败 {idx_file}: {e}")
        return None

# ═══ 逐股分析 ═══
def analyze_stock(filepath, idx_df, args):
    ticker = os.path.basename(filepath).replace(".csv", "")
    nm = _name(ticker)
    if nm and ('ST' in nm.upper() or '退' in nm):
        return ticker, False, {"filtered": "ST/退市"}

    try:
        df = pd.read_csv(filepath, parse_dates=["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        for c in ["Close","High","Low","Open","Volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df.dropna(subset=["Close","High","Low","Volume"], inplace=True)
    except:
        return ticker, False, {"filtered": "read_error"}

    need_bars = max(60, PARAMS["atr_period"]) + 5
    if len(df) < need_bars:
        return ticker, False, {"filtered": f"bars不足: {len(df)}/{need_bars}"}

    # 对齐指数数据
    if idx_df is not None:
        common_dates = set(df["Date"]) & set(idx_df["Date"])
        if len(common_dates) < 60:
            return ticker, False, {"filtered": "指数数据不足"}
        idx_aligned = idx_df[idx_df["Date"].isin(common_dates)].sort_values("Date").reset_index(drop=True)
        stock_aligned = df[df["Date"].isin(common_dates)].sort_values("Date").reset_index(drop=True)
        if len(idx_aligned) < 60 or len(stock_aligned) < 60:
            return ticker, False, {"filtered": "对齐后数据不足"}
    else:
        idx_aligned = None
        stock_aligned = df

    # ── 市值过滤 ──
    if not args.no_mcap_filter:
        mc = _mcap(ticker)
        if mc is not None and float(mc) < PARAMS["min_market_cap"]:
            return ticker, False, {"filtered": f"市值不足: {mc}亿"}
    else:
        mc = _mcap(ticker)

    # ── 流动性过滤: 20日日均成交额 >= 1亿 ──
    if not args.no_amount_filter:
        df["amount"] = df["Close"] * df["Volume"]
        avg_amount_20 = df["amount"].iloc[-20:].mean()
        avg_amount_yi = avg_amount_20 / 1e8
        if avg_amount_yi < PARAMS["min_daily_amount"]:
            return ticker, False, {"filtered": f"日均成交额不足: {avg_amount_yi:.2f}亿"}
    else:
        avg_amount_yi = None

    close_now = float(stock_aligned["Close"].iloc[-1])
    date_str  = stock_aligned["Date"].iloc[-1].strftime("%Y-%m-%d")

    # ── 计算RSP (Relative Strength Price) ──
    if idx_aligned is not None:
        base_price = float(idx_aligned["Close"].iloc[0])
        base_prices = idx_aligned["Close"].values
        ratio = stock_aligned["Close"].values / base_prices
        rsp = ratio * 1000
    else:
        rsp = stock_aligned["Close"].values

    # ── RSP均线 ──
    rsp_series = pd.Series(rsp)
    rsp_ma20 = float(rsp_series.rolling(20).mean().iloc[-1])
    rsp_ma60 = float(rsp_series.rolling(60).mean().iloc[-1])
    rsp_now  = float(rsp_series.iloc[-1])

    # ── 核心条件: RSP > RSP_MA60 AND RSP_MA20 > RSP_MA60 ──
    rsp_above_60   = rsp_now > rsp_ma60
    ma20_above_60  = rsp_ma20 > rsp_ma60
    signal = rsp_above_60 and ma20_above_60

    if not signal:
        return ticker, False, {
            "filtered": "RSP未满足",
            "rsi_signal": False,
            "rsp_now": round(rsp_now, 2),
            "rsp_ma20": round(rsp_ma20, 2),
            "rsp_ma60": round(rsp_ma60, 2),
            "rsp_above_60": rsp_above_60,
            "ma20_above_60": ma20_above_60,
        }

    # ── 量比 ──
    vol_now = float(stock_aligned["Volume"].iloc[-1])
    vol_avg_5 = float(stock_aligned["Volume"].iloc[-6:-1].mean())
    vol_ratio = vol_now / vol_avg_5 if vol_avg_5 > 0 else 1.0

    if vol_ratio < PARAMS["volume_ratio_min"]:
        return ticker, False, {
            "filtered": f"放量不足: {vol_ratio:.1f}x",
            "rsp_now": round(rsp_now, 2),
            "rsp_ma20": round(rsp_ma20, 2),
            "rsp_ma60": round(rsp_ma60, 2),
            "vol_ratio": round(vol_ratio, 2),
        }

    # ── ATR & 止损价 ──
    atr_val = float(_atr(stock_aligned, PARAMS["atr_period"]).iloc[-1])
    atr_round = round(atr_val, 2) if np.isfinite(atr_val) else None
    atr_stop  = round(close_now - PARAMS["atr_multiplier"] * atr_val, 2) \
                if atr_val and np.isfinite(atr_val) else None

    return ticker, True, {
        "date":            date_str,
        "close":           round(close_now, 2),
        "rsp_now":         round(rsp_now, 2),
        "rsp_ma20":        round(rsp_ma20, 2),
        "rsp_ma60":        round(rsp_ma60, 2),
        "vol_ratio":       round(vol_ratio, 2),
        "atr":             atr_round,
        "atr_stop_2x":     atr_stop,
        "mcap_yi":         mc,
        "avg_amount_yi":   round(avg_amount_yi, 2) if avg_amount_yi else None,
        "name":            nm,
    }

# ═══ JSON 输出 ═══
def save_json(buy_list, output_dir, index_code="000300"):
    today = date.today().strftime("%Y-%m-%d")
    os.makedirs(output_dir, exist_ok=True)

    stocks_out = []
    for ticker, d in buy_list:
        stocks_out.append({
            "ticker":       ticker,
            "name":         d.get("name","") or _name(ticker),
            "date":         d.get("date"),
            "close":        d.get("close"),
            "rsp":          d.get("rsp_now"),
            "rsp_ma20":     d.get("rsp_ma20"),
            "rsp_ma60":     d.get("rsp_ma60"),
            "volume_ratio": d.get("vol_ratio"),
            "atr_14":       d.get("atr"),
            "atr_stop_2x":  d.get("atr_stop_2x"),
            "mcap_yi":      d.get("mcap_yi"),
            "avg_amount_yi": d.get("avg_amount_yi"),
        })

    payload = {
        "strategy":       "screen_rsp_trend_break",
        "strategy_name":  "RSP趋势突破策略",
        "screen_date":   today,
        "index":          index_code,
        "params":         {k: PARAMS[k] for k in [
            "min_market_cap","min_daily_amount","atr_multiplier",
            "atr_period","volume_ratio_min","max_hold_count"]},
        "total_matched":  len(stocks_out),
        "stocks":         stocks_out,
    }

    dated  = os.path.join(output_dir, f"screen_rsp_trend_break_{today}.json")
    latest = os.path.join(output_dir, "screen_rsp_trend_break_latest.json")
    for p in [dated, latest]:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n💾 JSON 已保存:\n   {dated}\n   {latest}")

# ═══ 主流程 ═══
def main():
    ap = argparse.ArgumentParser(description="RSP趋势突破策略 — RSP>RSP_MA60 且 RSP_MA20>RSP_MA60")
    ap.add_argument("--data-dir", default="/Users/skyler/workspace/stock_selection/data_cache_daily")
    ap.add_argument("--output-dir", default="/Users/skyler/workspace/stock_selection/output/strategy")
    ap.add_argument("--index", default=PARAMS["index_code"], help="基准指数代码 (默认000300)")
    ap.add_argument("--top", type=int, default=None, help="只取TopN (默认max_hold*2=10)")
    ap.add_argument("--volume-ratio", type=float, default=1.2, help="放量倍数 (默认1.2)")
    ap.add_argument("--no-mcap-filter", action="store_true", help="跳过市值过滤")
    ap.add_argument("--no-amount-filter", action="store_true", help="跳过日均成交额过滤")
    args = ap.parse_args()

    PARAMS["index_code"]       = args.index
    PARAMS["volume_ratio_min"] = args.volume_ratio
    N = args.top  # None = 不截断，输出全部匹配

    print(f"╔{'═'*58}╗")
    print(f"║  📈 RSP趋势突破策略                           ║")
    print(f"║     RSP > RSP_MA60 且 RSP_MA20 > RSP_MA60    ║")
    top_label = f"Top{N}" if N is not None else "全部"
    print(f"║     基准: {args.index}  |  放量: {args.volume_ratio}x  |  {top_label}         ║")
    print(f"╚{'═'*58}╝\n")

    csvs = sorted(glob.glob(os.path.join(args.data_dir, "*.csv")))
    print(f"📁 共 {len(csvs)} 只股票，基准指数: {args.index}，开始扫描…\n")

    # 加载指数
    idx_df = _load_index(args.data_dir, args.index)
    if idx_df is not None:
        print(f"📈 指数加载成功: {len(idx_df)} 天数据\n")
    else:
        print("⚠️  未找到指数数据，将使用绝对价格信号\n")

    # 逐股分析
    results = {}
    for fp in tqdm(csvs, desc="扫描中"):
        ticker, passed, detail = analyze_stock(fp, idx_df, args)
        if not passed: continue
        results[ticker] = detail

    print(f"\n✅ 满足 RSP>RSP_MA60 且 RSP_MA20>RSP_MA60: {len(results)} 只\n")

    # 排序: 按 RSP 相对偏离度 (rsp_now / rsp_ma60 - 1) 降序
    scored = []
    for ticker, d in results.items():
        d["deviation"] = (d["rsp_now"] / d["rsp_ma60"] - 1) * 100 if d["rsp_ma60"] > 0 else 0
        d["score"] = d["deviation"]
        scored.append((ticker, d))

    scored.sort(key=lambda x: x[1]["score"], reverse=True)
    if N is not None and len(scored) > N:
        buy_list = scored[:N]
        print(f"⚠️  共 {len(scored)} 只满足条件 → Top{N}\n")
    else:
        buy_list = scored

    # 打印结果
    print(f"{'='*120}")
    print(f"🟢 买入信号 Top{len(buy_list)} — 按 RSP偏离度 降序")
    print(f"{'='*120}")
    hdr = (f"  {'排名':>3}  {'代码':>6}  {'名称':<8}  {'收盘价':>7}  "
           f"{'RSP':>8}  {'MA20':>8}  {'MA60':>8}  {'偏离%':>5}  "
           f"{'量比':>4}  {'ATR':>6}  {'2×ATR止损':>9}  {'市值(亿)':>7}  {'日均亿':>6}")
    print(hdr)
    print(f"{'─'*120}")
    for rank, (t, d) in enumerate(buy_list, 1):
        nm  = d.get('name','') or _name(t)
        atr = d['atr'] if d.get('atr') else 'N/A'
        as_ = str(d['atr_stop_2x']) if d.get('atr_stop_2x') else 'N/A'
        mc  = d.get('mcap_yi','?') if d.get('mcap_yi') else '?'
        am  = d.get('avg_amount_yi','?') if d.get('avg_amount_yi') else '?'
        print(f"  {rank:>3}  {t:>6}  {nm:<8}  {d['close']:>7.2f}  "
              f"{d['rsp_now']:>8.2f}  {d['rsp_ma20']:>8.2f}  {d['rsp_ma60']:>8.2f}  "
              f"{d['deviation']:>+5.1f}%  {d['vol_ratio']:>4.1f}x  "
              f"{atr:>6}  {as_:>9}  {str(mc):>7}  {str(am):>6}")
    print(f"{'─'*120}")
    print(f"  说明: RSP偏离% = (RSP/MA60 - 1)×100,  2×ATR止损 = 收盘价 − 2.0×ATR\n")

    if not buy_list:
        print("😐 当前无股票满足全部条件。")

    save_json(buy_list, args.output_dir, index_code=args.index)

if __name__ == "__main__":
    main()
