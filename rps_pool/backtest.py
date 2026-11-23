#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第四步 · 回测

买入: 信号当日最后一根日线收盘(= 本机每日 13:50 抓的"收盘前1小时"价)
卖出: 周线 RSI 死叉且 RSI1 < RSI3 当日收盘; 超过 max_hold_days 强制平仓

偏差声明(必须知道):
  * 股票池用"当前"的基金/北向条件回溯历史 -> 前视 + 幸存者偏差。基金持股历史无法批量取得,
    所以这是结构性限制; 加 --universe all 可以看"不依赖股票池"的纯技术面表现作为对照。
  * 换手率用当前流通股本近似历史值。
  * 前复权价格来自 yfinance; 停牌日价格前向填充。

用法:
  python3 backtest.py --start 2023-01-04
  python3 backtest.py --strategy 1 --max-pos 10 --exit stoploss
  python3 backtest.py --universe all --summary-only
"""
import argparse, json, os, sys, time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import indicators as I
import poolio

BTOUT = os.path.join(C.OUT, "backtest")


def build_signals(P, pool, universe, float_shares, min_bar_amount, sell_mode="cross",
                  three_line=None, rps_sum=None):
    cols = [c for c in (pool["code"] if universe == "pool" else P["Close"].columns)
            if c in P["Close"].columns]
    prm = {}
    if rps_sum:
        prm["sum_min"] = rps_sum
    F = I.sxhcg(P, focus=cols, float_shares=float_shares, params=prm or None)
    W = I.weekly_rsi_daily(P["Close"][cols], C.WK_RSI["rsi_period"], C.WK_RSI["sig_window"],
                           C.WK_RSI["mid_line"],
                           C.WK_RSI["three_line"] if three_line is None else three_line,
                           C.WK_RSI["slow_window"])
    tradable = (P["Close"][cols] * P["Volume"][cols]) >= min_bar_amount
    base = F["SXHCG"] & F["live"] & tradable
    s1 = base & W["w_above"] & (W["w_rsi1"] > W["w_rsi3"])
    s2 = base & (F["newhigh_h"] > 0.90)
    exit_w = W["w_dead"] if sell_mode == "cross" else W["w_dead_state"]
    return dict(cols=cols, F=F, W=W, base=base, s1=s1, s2=s2, exit_w=exit_w,
                rps=F["RPS120"] + F["RPS250"])


def simulate(P, S, mask, exit_w, start, end, max_pos, per_pct, cost, slippage,
             max_hold, top_n=3, min_bars_for_warm=300):
    """逐日重放。返回 (trades df, nav df)"""
    Close = P["Close"][S["cols"]]
    idx = Close.index
    lo = np.searchsorted(idx.values, np.datetime64(start)) if start else min_bars_for_warm
    lo = max(min_bars_for_warm, lo)
    hi = len(idx) - 1 if not end else int(np.searchsorted(idx.values, np.datetime64(end)))
    hi = min(hi, len(idx) - 1)

    CV = Close.to_numpy(float)
    MV = mask.to_numpy(bool)
    RP = S["rps"][S["cols"]].to_numpy(float)
    XW = exit_w.reindex(columns=S["cols"]).to_numpy(bool)
    colid = {c: j for j, c in enumerate(S["cols"])}

    cash = 1.0
    pos = {}            # code -> dict(entry, shares, entry_i, entry_px)
    trades, nav = [], []
    total = 1.0
    for t in range(lo, hi + 1):
        d = idx[t]
        # ── 卖出 ──
        for c in list(pos.keys()):
            j = colid[c]
            px = CV[t, j]
            if not np.isfinite(px) or px <= 0:
                continue
            held = t - pos[c]["i"]
            do_exit = bool(XW[t, j]) or held >= max_hold
            if do_exit:
                gross = pos[c]["sh"] * px
                fee = gross * (cost + slippage)
                cash += gross - fee
                trades.append({"code": c, "entry_date": pos[c]["entry_date"], "entry_px": pos[c]["px"],
                               "exit_date": d.strftime("%Y-%m-%d"), "exit_px": round(float(px), 3),
                               "days": held, "ret": (px * (1 - cost - slippage)) /
                               (pos[c]["px"] * (1 + cost + slippage)) - 1.0,
                               "reason": "周线RSI死叉" if XW[t, j] else "超时"})
                del pos[c]
        # ── 买入 ──
        free = max_pos - len(pos)
        if free > 0:
            cand = [(RP[t, colid[c]], c) for c in S["cols"]
                    if MV[t, colid[c]] and c not in pos and np.isfinite(CV[t, colid[c]])]
            cand.sort(reverse=True)
            eq = (cash + sum(p["sh"] * CV[t, colid[k]] for k, p in pos.items()
                             if np.isfinite(CV[t, colid[k]])))
            budget = eq * per_pct
            for rps, c in cand[:free * top_n][:free]:
                j = colid[c]
                px = CV[t, j] * (1 + slippage)
                if not np.isfinite(px) or px <= 0:
                    continue
                alloc = min(budget, cash)
                if alloc < 1e-4:
                    break
                sh = alloc / (px * (1 + cost))
                cash -= alloc
                pos[c] = {"i": t, "px": px, "sh": sh, "entry_date": d.strftime("%Y-%m-%d")}
        mv = sum(p["sh"] * CV[t, colid[k]] for k, p in pos.items()
                 if np.isfinite(CV[t, colid[k]]))
        total = cash + mv
        nav.append({"date": d.strftime("%Y-%m-%d"), "nav": total, "n_pos": len(pos),
                    "cash": cash})
    # 期末强制平仓计入
    tr = pd.DataFrame(trades)
    nv = pd.DataFrame(nav).set_index("date")
    nv["ret"] = nv["nav"].pct_change().fillna(0)
    nv["dd"] = nv["nav"] / nv["nav"].cummax() - 1
    return tr, nv


def metrics(tr, nv, bench=None):
    if nv.empty:
        return {}
    r = nv["ret"].to_numpy(float)
    nav = nv["nav"].to_numpy(float)
    yrs = len(nv) / 244.0
    tot = nav[-1] / nav[0] - 1
    cagr = (nav[-1] / nav[0]) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1
    sharpe = (np.nanmean(r) / np.nanstd(r) * np.sqrt(244)) if np.nanstd(r) else np.nan
    m = {"交易日": len(nv), "年数": round(yrs, 2), "总收益": round(tot, 4),
         "年化": round(cagr, 4), "最大回撤": round(float(dd.min()), 4),
         "夏普": round(float(sharpe), 2), "卡玛": round(float(cagr / abs(dd.min())), 2)
         if dd.min() < 0 else None,
         "交易数": int(len(tr)), "胜率": round(float((tr["ret"] > 0).mean()), 3) if len(tr) else None,
         "平均收益": round(float(tr["ret"].mean()), 4) if len(tr) else None,
         "中位收益": round(float(tr["ret"].median()), 4) if len(tr) else None,
         "平均持有天数": round(float(tr["days"].mean()), 1) if len(tr) else None,
         "盈亏比": (round(float(tr.loc[tr["ret"] > 0, "ret"].mean() /
                          abs(tr.loc[tr["ret"] <= 0, "ret"].mean())), 2)
                   if len(tr) and (tr["ret"] > 0).any() and (tr["ret"] <= 0).any() else None),
         "平均持仓数": round(float(nv["n_pos"].mean()), 2),
         "超时平仓占比": (round(float((tr["reason"] == "超时").mean()), 3) if len(tr) else None),
         "分年": {str(k): round(float(v.iloc[-1] / v.iloc[0] - 1), 4)
                  for k, v in nv["nav"].groupby(pd.to_datetime(nv.index).year)}}
    if bench is not None and len(bench):
        b = bench.reindex(pd.to_datetime(nv.index))
        bb = b.dropna()
        if len(bb) > 30:
            m["基准同期"] = round(float(bb.iloc[-1] / bb.iloc[0] - 1), 4)
            m["基准年化"] = round(float((bb.iloc[-1] / bb.iloc[0]) ** (1 / yrs) - 1), 4)
    return m


def dump_counts(S, a):
    """逐日入选数量 -> out/backtest/counts_<tag>.csv, 供看板"信号强度"曲线
    (不用等 run_daily.sh 攒够历史, 一次回测就有全样本的入选家数)"""
    idx = S["base"].index
    lo, hi = pd.Timestamp(a.start), (pd.Timestamp(a.end) if a.end else idx[-1])
    sl = (idx >= lo) & (idx <= hi)
    df = pd.DataFrame({"sxhcg": S["base"].to_numpy()[sl].sum(axis=1),
                       "s1": S["s1"].to_numpy()[sl].sum(axis=1),
                       "s2": S["s2"].to_numpy()[sl].sum(axis=1)},
                      index=idx[sl].strftime("%Y-%m-%d"))
    df.index.name = "date"
    fp = os.path.join(BTOUT, f"counts_{a.tag or 'main'}.csv")
    os.makedirs(BTOUT, exist_ok=True)
    df.to_csv(fp, encoding="utf-8-sig")
    print(f"逐日入选数 -> {fp}  ({len(df)} 天)")


def load_bench(name="hs300"):
    fp = os.path.join(C.DATA, f"bench_{name}.csv")
    if not os.path.exists(fp):
        return None
    d = pd.read_csv(fp)
    d["Date"] = pd.to_datetime(d["Date"])
    return d.set_index("Date")["Close"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=C.BT["start"])
    ap.add_argument("--end")
    ap.add_argument("--strategy", default="both", choices=["1", "2", "both"])
    ap.add_argument("--universe", default="pool", choices=["pool", "all"])
    ap.add_argument("--max-pos", type=int, default=C.BT["max_positions"])
    ap.add_argument("--dir")
    ap.add_argument("--tag", default="")
    ap.add_argument("--quick", action="store_true", help="只跑股票池, 打印指标不写文件")
    ap.add_argument("--bench", default="hs300", help="基准: hs300/zz500/cybz/none")
    ap.add_argument("--sell-mode", default=C.WK_RSI["sell_mode"], choices=["cross", "state"])
    ap.add_argument("--three-line", action="store_true")
    ap.add_argument("--rps-sum", type=float, default=None)
    ap.add_argument("--counts", action="store_true", help="额外输出逐日入选数量 counts_<tag>.csv")
    a = ap.parse_args()
    os.makedirs(BTOUT, exist_ok=True)

    pool = poolio.load_pool()
    fs = poolio.float_shares(pool)
    print(f"流通股本可用 {len(fs)} 只 (换手率条件覆盖范围)")

    need = C.RPS["w_slow"] + 300
    print(f"载入日线 (>= {need} 根) ...")
    t0 = time.time()
    P = I.load(dirn=a.dir, min_bars=need)
    print(f"  {P['Close'].shape[1]} 只 x {P['Close'].shape[0]} 根, {time.time()-t0:.1f}s")

    print("计算信号 ...")
    t0 = time.time()
    S = build_signals(P, pool, a.universe, fs, C.BT["min_bar_amount"], a.sell_mode,
                      a.three_line, a.rps_sum)
    print(f"  {len(S['cols'])} 只候选, {time.time()-t0:.1f}s")
    if a.counts:
        dump_counts(S, a)
    exit_w = S["exit_w"]
    bench = load_bench(a.bench) if a.bench != "none" else None

    names = dict(zip(pool["code"], pool.get("name", pd.Series(dtype=str))))
    runs = [("策略1", S["s1"])] if a.strategy == "1" else \
           [("策略2", S["s2"])] if a.strategy == "2" else [("策略1", S["s1"]), ("策略2", S["s2"])]
    navs, trs = {}, {}
    for st, mask in runs:
        tr, nv = simulate(P, S, mask, exit_w, a.start, a.end, a.max_pos, C.BT["per_trade_pct"],
                          C.BT["commission"] + C.BT["stamp_tax"], C.BT["slippage"],
                          C.BT["max_hold_days"])
        if not tr.empty:
            tr["name"] = tr["code"].map(lambda c: names.get(c, ""))
            tr = tr.sort_values(["exit_date", "code"])
        m = metrics(tr, nv, bench)
        print(f"\n══ {st} ══  信号日数={int(mask.to_numpy().sum())}")
        for k, v in m.items():
            print(f"   {k:<10}{v}")
        navs[st], trs[st] = nv, tr
    if a.quick:
        return
    for st in navs:
        tg = f"{st}_{a.tag}" if a.tag else st
        trs[st].to_csv(os.path.join(BTOUT, f"trades_{tg}.csv"), index=False, encoding="utf-8-sig")
        navs[st].to_csv(os.path.join(BTOUT, f"nav_{tg}.csv"), encoding="utf-8-sig")
        with open(os.path.join(BTOUT, f"metrics_{tg}.json"), "w", encoding="utf-8") as f:
            json.dump({"strategy": st, "start": a.start, "end": a.end, "universe": a.universe,
                       "max_pos": a.max_pos, "signals": int(sum(int(n.to_numpy().sum())
                                                for k, n in runs if k == st)),
                       **metrics(trs[st], navs[st])}, f, ensure_ascii=False, indent=2)
    nav_all = pd.concat({k: v["nav"] for k, v in navs.items()}, axis=1)
    nav_all.columns = [c[0] for c in nav_all.columns] if isinstance(nav_all.columns, pd.MultiIndex) else list(nav_all.columns)
    if bench is not None:
        b = bench.reindex(pd.to_datetime(nav_all.index))
        nav_all["基准" + a.bench] = (b / b.dropna().iloc[0]).to_numpy()
    nav_all.to_csv(os.path.join(BTOUT, f"nav_all{('_'+a.tag) if a.tag else ''}.csv"),
                   encoding="utf-8-sig")
    print(f"\n输出 -> {BTOUT}")


if __name__ == "__main__":
    main()
