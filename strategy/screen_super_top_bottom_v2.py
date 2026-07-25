#!/usr/bin/env python3
"""
超级顶底 v2 - 评分排序 + 量比 + ATR止损提示

规则:
  买入: 趋势线上穿11  →  量比>1.2  →  评分排序取Top30
  卖出: 趋势线下穿89
  过滤: 市值>=80亿(无其他基本面条件)
  止损: 输出2*ATR建议止损价(供实盘参考, 不做自动卖出)

指标:
  RSV    = (CLOSE-LLV(LOW,27))/(HHV(HIGH,27)-LLV(LOW,27))*100
  趋势线  = 3*SMA(RSV,5,1) - 2*SMA(SMA(RSV,5,1),3,1)

输出: JSON文件 + 控制台打印
"""

import os, sys, json, glob, argparse
import pandas as pd, numpy as np
from tqdm import tqdm
from datetime import date

# ─── 可调参数 ───
PARAMS = dict(
    n_rsv=27,
    sma1_n=5, sma1_m=1,
    sma2_n=3, sma2_m=1,
    buy_th=11,
    sell_th=89,
    min_mcap=80,       # 亿
    vol_window=10,
    vol_ratio_min=1.2,
    atr_window=14,
    atr_mult=2.0,
    top_n=20,          # 买入只取TopN
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

def _fund_path():
    fp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fund.json")
    return fp if os.path.exists(fp) else None

_fund_cache = {}

def _load_fund():
    global _fund_cache
    fp = _fund_path()
    if fp:
        try:
            with open(fp) as f: _fund_cache = json.load(f)
        except: pass
    return _fund_cache

def _mcap(t):
    return _fund_cache.get(t, {}).get("mcap_yi", None)

# ─── 指标计算 ───
def _sma_td(series, n, m):
    """通达信 SMA: Y[i] = (m/n)*X[i] + (1-m/n)*Y[i-1]"""
    x = series.values.astype(np.float64)
    out = np.full(len(x), np.nan)
    α = m / n
    first = next((i for i, v in enumerate(x) if np.isfinite(v)), None)
    if first is None: return pd.Series(out, index=series.index)
    out[first] = x[first]
    for i in range(first + 1, len(x)):
        if np.isfinite(x[i]):
            out[i] = α * x[i] + (1 - α) * (out[i-1] if np.isfinite(out[i-1]) else x[i])
    return pd.Series(out, index=series.index)


def _atr(df, w=14):
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"]  - df["Close"].shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(w).mean()


def _calc_trend(df):
    ll  = df["Low"].rolling(PARAMS["n_rsv"]).min()
    hh  = df["High"].rolling(PARAMS["n_rsv"]).max()
    den = (hh - ll).replace(0, np.nan)
    rsv = (df["Close"] - ll) / den * 100
    s1  = _sma_td(rsv, PARAMS["sma1_n"], PARAMS["sma1_m"])
    s2  = _sma_td(s1,  PARAMS["sma2_n"], PARAMS["sma2_m"])
    return 3 * s1 - 2 * s2


def _score(trend_val, vratio):
    """评分: 距11距离(0~100) + 量比加成(0~30)"""
    s_trend = max(0, 100 * (1 - (trend_val - PARAMS["buy_th"]) / 25))
    s_vol   = min(30, (vratio - PARAMS["vol_ratio_min"]) * 30)
    return round(s_trend + s_vol, 1)


# ─── 核心扫描 ───
def check_stock(filepath):
    ticker = os.path.basename(filepath).replace(".csv", "")
    # 剔除 ST / *ST 股票
    nm = _name(ticker)
    if nm and ('ST' in nm.upper()):
        return ticker, None, {}
    try:
        df = pd.read_csv(filepath, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
        for c in ["Close","High","Low","Volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df.dropna(subset=["Close","High","Low"], inplace=True)
    except: return ticker, None, {}

    need_bars = max(PARAMS["n_rsv"], PARAMS["sma1_n"], PARAMS["sma2_n"]) + PARAMS["vol_window"] + 5
    if len(df) < need_bars: return ticker, None, {}

    # 基本面: 市值>=80亿
    mc = _mcap(ticker)
    if mc is not None and float(mc) < PARAMS["min_mcap"]:
        return ticker, None, {}

    trend = _calc_trend(df)
    if len(trend) < 2: return ticker, None, {}
    tn_raw, tp_raw = trend.iloc[-1], trend.iloc[-2]
    if not np.isfinite(tn_raw) or not np.isfinite(tp_raw): return ticker, None, {}

    tn, tp = float(tn_raw), float(tp_raw)
    close_now = float(df["Close"].iloc[-1])
    date_str  = df["Date"].iloc[-1].strftime("%Y-%m-%d")

    # 量比
    vol_now  = df["Volume"].iloc[-1]
    vol_avg  = df["Volume"].iloc[-PARAMS["vol_window"]:-1].mean()
    vratio   = vol_now / vol_avg if vol_avg > 0 else 1.0

    # ATR
    atr_val = _atr(df, PARAMS["atr_window"]).iloc[-1]
    atr_round = round(atr_val, 2) if np.isfinite(atr_val) else None

    # —— 卖出 ——
    if tp >= PARAMS["sell_th"] and tn < PARAMS["sell_th"]:
        stop_price = round(close_now + PARAMS["atr_mult"] * atr_val, 2) if atr_val and np.isfinite(atr_val) else None
        return ticker, "sell", {
            "date": date_str, "close": round(close_now, 2),
            "trend_line": round(tn, 2), "trend_prev": round(tp, 2),
            "v_ratio": round(vratio, 2), "atr": atr_round, "mcap_yi": mc,
            "signal_note": "趋势线下穿89 → 卖出", "name": _name(ticker),
            "atr_stop_price(反向)": stop_price,
        }

    # —— 买入 ——
    if tp <= PARAMS["buy_th"] and tn > PARAMS["buy_th"]:
        if vratio < PARAMS["vol_ratio_min"]:
            return ticker, None, {}  # 量比不够，过滤
        score = _score(tn, vratio)

        # 2*ATR止损参考价
        stop_price = round(close_now - PARAMS["atr_mult"] * atr_val, 2) if atr_val and np.isfinite(atr_val) else None

        return ticker, "buy", {
            "date": date_str, "close": round(close_now, 2),
            "trend_line": round(tn, 2), "trend_prev": round(tp, 2),
            "v_ratio": round(vratio, 2), "atr": atr_round,
            "score": score, "mcap_yi": mc,
            "atr_stop_price": stop_price,  # 2*ATR止损建议价
            "signal_note": "趋势线上穿11 → 买入", "name": _name(ticker),
        }

    return ticker, None, {}


# ─── JSON输出 ───
def save_json(signal_type, results, output_dir):
    today = date.today().strftime("%Y-%m-%d")
    os.makedirs(output_dir, exist_ok=True)
    prefix = f"screen_super_top_bottom_{signal_type}"
    sname = "超级顶底 买入信号(Top20+评分)" if signal_type == "buy" else "超级顶底 卖出信号"
    stocks = [{"ticker": t, "name": d.get("name","") or _name(t),
               **{k:v for k,v in d.items() if k!="name"}} for t, d in results]
    payload = {"strategy": prefix, "strategy_name": sname, "signal_type": signal_type,
               "screen_date": today, "total_scanned": _total_scanned,
               "total_matched": len(results), "stocks": stocks}
    dated, latest = os.path.join(output_dir, f"{prefix}_{today}.json"), os.path.join(output_dir, f"{prefix}_latest.json")
    for p in [dated, latest]:
        with open(p, "w", encoding="utf-8") as f: json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n💾 JSON 已保存 ({signal_type}):\n   {dated}\n   {latest}")


_total_scanned = 0


def main():
    ap = argparse.ArgumentParser(description="超级顶底 v2 - 评分排序 + 量比Top20")
    ap.add_argument("--data-dir", default="/Users/skyler/workspace/stock_selection/data_cache_daily")
    ap.add_argument("--output-dir", default="/Users/skyler/workspace/stock_selection/output/strategy")
    ap.add_argument("--top", type=int, default=None, help="买入信号只取TopN (默认显示全部)")
    args = ap.parse_args()

    if args.top: PARAMS["top_n"] = args.top

    csvs = sorted(glob.glob(os.path.join(args.data_dir, "*.csv")))
    print(f"共找到 {len(csvs)} 只股票，开始扫描…\n")
    global _total_scanned; _total_scanned = len(csvs)
    _load_fund()

    buy_results, sell_results = [], []
    for fp in tqdm(csvs, desc="扫描中"):
        t, sig, d = check_stock(fp)
        if sig == "buy": buy_results.append((t, d))
        elif sig == "sell": sell_results.append((t, d))

    # ── 买入信号按评分降序 → 默认全部, --top N 截取TopN ──
    buy_results.sort(key=lambda x: x[1].get("score", 0), reverse=True)
    if args.top and len(buy_results) > PARAMS["top_n"]:
        buy_top = buy_results[:PARAMS["top_n"]]
        print(f"\n⚠️  共 {len(buy_results)} 个买入信号, 评分降序截取 Top {PARAMS['top_n']} ↓\n")
    else:
        buy_top = buy_results

    print(f"\n{'='*60}")
    print(f"🟢 买入信号 {len(buy_top)} / {len(buy_results)} 只 — 按评分降序排列")
    print(f"{'='*60}\n")
    header = f"  {'排名':>3}  {'代码':<10}  {'名称':<8}  收盘价  日期       趋势线     量比   评分  ATR止损"
    print(header)
    for rank, (t, d) in enumerate(buy_top, 1):
        stop = f"{d.get('atr_stop_price','?')}" if d.get('atr_stop_price') is not None else "N/A"
        print(f"  {rank:>3}  {t:<10}  {d.get('name',_name(t)):<8}  {d['close']:>6}  {d['date']}  t={d['trend_line']:>6}/{d['trend_prev']:>5}  {d['v_ratio']:>4.2f}  ★{d['score']}  {stop}")
    if not buy_top: print("  无")

    print(f"\n🔴 卖出信号: {len(sell_results)} 只\n")
    if sell_results:
        for t, d in sell_results:
            atr_stop = f"{d.get('atr_stop_price(反向)','?')}" if d.get('atr_stop_price(反向)') is not None else "N/A"
            print(f"  {t}  收盘价:{d['close']}  日期:{d['date']}  趋势线={d['trend_line']}/{d['trend_prev']}  ATR反向:{atr_stop}")
    else: print("  无")

    save_json("buy", buy_top, args.output_dir)
    save_json("sell", sell_results, args.output_dir)

    return buy_top, sell_results

if __name__ == "__main__": main()
