#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第二步 · 每日筛选: 策略1(RPS+周线RSI) 与 策略2(RPS+接近一年新高)

口径:
  基础池   = 第一步股票池(季度更新)
  RPS 选股 = 通达信 SXHCG1..5 全套(见 indicators.sxhcg)
  策略1    = SXHCG 且 周线RSI1>RSI2 且 RSI1>RSI3(50轴)  -> 中期多头确认
             信号新鲜度 = 距今多少个交易日出现周线金叉
  策略2    = SXHCG 且 CLOSE/HHV(HIGH,250) > 0.90        -> 接近一年新高
  买入价   = 当日最后一根日线收盘(本机每日 13:50 抓取 => 收盘前约1小时的价格)

输出 out/screen/<日期>/ :
  strategy1.csv strategy2.csv  all_pool.csv  summary.txt  dashboard.json
用法:
  python3 screen_daily.py
  python3 screen_daily.py --asof 2026-11-20 --top 30
"""
import argparse, json, os, sys, time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import indicators as I
import poolio

SCREEN = os.path.join(C.OUT, "screen")
SELL_WIN = 5           # 近几个交易日内的周线死叉算"卖出提示"(每日跑, 一周窗口够用)
LOOKBACK_HELD = 120  # 近多少个交易日内入选过策略才算"可能还持着"


def load_pool() -> pd.DataFrame:
    return poolio.load_pool()


def bars_needed(rsi_lookback: int) -> int:
    p = C.RPS
    return max(rsi_lookback, p["w_slow"] + p["count250_days"] + 20, 400)


def run(asof: str | None, top: int, dirn: str | None, min_list_days_pool: int,
        a_sell_win: int = SELL_WIN) -> dict:
    pool = load_pool()
    names = dict(zip(pool["code"], pool.get("name", pd.Series(dtype=str))))
    fs = poolio.float_shares(pool)

    rn = C.RPS["w_slow"] + C.RPS["count250_days"] + 30
    nb = bars_needed(1200) + 60
    print(f"载入日线: dir={dirn or C.HIST_DIR} 近{nb}根 (需>= {rn}) ...")
    t0 = time.time()
    P = I.load(dirn=dirn, start=None, min_bars=rn, fix_ohlc=True)
    # 截到 asof
    idx = P["Close"].index
    if asof:
        cut = pd.Timestamp(asof)
        keep = idx[idx <= cut]
        if len(keep) < rn:
            raise SystemExit(f"asof={asof} 之后只有 {len(keep)} 根, 不够算 MA250")
        for f in ("Open", "High", "Low", "Close", "Volume", "_hasdata"):
            P[f] = P[f].loc[keep]
    P["Close"] = P["Close"].iloc[-nb:]
    for f in ("Open", "High", "Low", "Close", "Volume", "_hasdata"):
        P[f] = P[f].iloc[-nb:]
    P["_first"] = P["_first"]
    print(f"  {P['Close'].shape[1]} 只 x {P['Close'].shape[0]} 根, {time.time()-t0:.1f}s")

    poolcols = [c for c in pool["code"] if c in P["Close"].columns]
    miss = sorted(set(pool["code"]) - set(poolcols))
    print(f"股票池 {len(pool)} 只, 其中有日线 {len(poolcols)} 只"
          + (f", 缺 {len(miss)} 只(示例 {miss[:6]})" if miss else ""))

    F = I.sxhcg(P, focus=poolcols, newhigh_ratio=C.RPS["hhv250_ratio"], float_shares=fs)
    W = I.weekly_rsi_daily(P["Close"][poolcols], C.WK_RSI["rsi_period"], C.WK_RSI["sig_window"],
                           C.WK_RSI["mid_line"], C.WK_RSI["three_line"], C.WK_RSI["slow_window"],
                           lookback_days=0)
    last = P["Close"].index[-1]
    date_str = last.strftime("%Y-%m-%d")

    base = F["SXHCG"].loc[last]
    detail = {k: F[k].loc[last] for k in ("SXHCG1", "SXHCG2", "SXHCG3", "SXHCG31",
                                          "SXHCG32", "SXHCG4", "SXHCG5")}
    detail["all"] = base
    d = pd.DataFrame(detail)
    d.index.name = "code"
    d = d.reindex(poolcols)
    d["name"] = d.index.map(lambda c: names.get(c, ""))
    d["close"] = P["Close"][poolcols].loc[last]
    d["RPS120"] = F["RPS120"][poolcols].loc[last] if hasattr(F["RPS120"], "loc") else F["RPS120"].loc[last]
    d["RPS250"] = F["RPS250"].loc[last]
    d["RPS_sum"] = d["RPS120"] + d["RPS250"]
    d["ret120"] = P["Close"][poolcols].loc[last] / P["Close"][poolcols].loc[
        P["Close"].index[-1 - C.RPS["w_fast"]]] - 1
    d["ret250"] = P["Close"][poolcols].loc[last] / P["Close"][poolcols].loc[
        P["Close"].index[-1 - C.RPS["w_slow"]]] - 1
    d["newhigh_C250"] = F["newhigh"].loc[last]
    d["newhigh_H250"] = F["newhigh_h"].loc[last]
    d["ma20"] = F["ma20"].loc[last]
    d["ma250"] = F["ma250"].loc[last]
    d["dd20"] = F["dd"].loc[last]
    d["turnover"] = F["turn"].loc[last]
    d["fund_ratio_float"] = pool.set_index("code")["fund_ratio_float"].reindex(d.index)
    d["north_value_yi"] = pool.set_index("code")["north_value"].reindex(d.index) / 1e8

    # 周线 RSI 状态
    for k in ("w_rsi1", "w_rsi2", "w_rsi3"):
        d[k] = W[k].loc[last]
    above = W["w_above"].loc[last].astype(bool)
    d["wk_state"] = np.where(above, "多头", "空头")
    gold_hist = W["w_gold"][poolcols].astype(float)
    dead_hist = W["w_dead"][poolcols].astype(float)
    since = pd.Series(np.nan, index=d.index)
    since_d = pd.Series(np.nan, index=d.index)
    gdates, ddates = gold_hist.loc[:last], dead_hist.loc[:last]
    for c in d.index:
        s = gdates[c][gdates[c] > 0]
        if len(s):
            since[c] = len(gdates.loc[s.index[-1]:last]) - 1
        s2_ = ddates[c][ddates[c] > 0]
        if len(s2_):
            since_d[c] = len(ddates.loc[s2_.index[-1]:last]) - 1
    d["wk_gold_days"] = since
    d["wk_dead_days"] = since_d
    d["wk_confirmed"] = above & (d["w_rsi1"] > d["w_rsi3"])
    d["wk_dead_now"] = W["w_dead"].loc[last].astype(bool)

    s1 = d[(d["all"]) & d["wk_confirmed"]].copy()
    s1["_fresh"] = s1["wk_gold_days"].fillna(999)
    s1 = s1.sort_values(["_fresh", "RPS_sum"], ascending=[True, False]).drop(columns="_fresh")
    s2 = d[(d["all"]) & (d["newhigh_H250"] > 0.90)].copy()
    s2 = s2.sort_values("newhigh_H250", ascending=False)

    # 卖出提示: 只给"近期确实入选过策略"的票 -> 否则全池都在跌时会有几百条噪音
    held = F["SXHCG"] & F["live"]
    s1h = held & W["w_above"] & (W["w_rsi1"] > W["w_rsi3"])
    s2h = held & (F["newhigh_h"] > 0.90)
    recent_pick = (s1h | s2h).rolling(LOOKBACK_HELD, min_periods=1).max().astype(bool).loc[last]
    d["recent_pick"] = recent_pick
    sell = d[(d["wk_dead_days"] <= a_sell_win) & d["recent_pick"]].copy()
    sell = sell.sort_values("wk_dead_days")
    # 附加信息: 这只票最近一次"在策略里"是几个交易日前、当时属于哪个策略
    #   (死叉当根 w_above 已经翻 False, 所以"死叉那天还在不在策略"必然为否 -> 改成看回看窗口)
    T = len(P["Close"])
    pos = pd.DataFrame(np.where((s1h | s2h).to_numpy(), np.arange(T)[:, None], np.nan),
                       index=s1h.index, columns=s1h.columns).ffill().iloc[-1]
    for nm, M in (("was_s1", s1h), ("was_s2", s2h)):
        sell[nm] = M.rolling(LOOKBACK_HELD, min_periods=1).max().astype(bool).loc[last]
    sell["pick_age"] = ((T - 1) - pos).reindex(sell.index)

    cand = d[d["all"]].copy()
    outdir = os.path.join(SCREEN, date_str.replace("-", ""))
    os.makedirs(outdir, exist_ok=True)
    if top:
        s1.head(top).to_csv(os.path.join(outdir, "strategy1.csv"), encoding="utf-8-sig")
        s2.head(top).to_csv(os.path.join(outdir, "strategy2.csv"), encoding="utf-8-sig")
    else:
        s1.to_csv(os.path.join(outdir, "strategy1.csv"), encoding="utf-8-sig")
        s2.to_csv(os.path.join(outdir, "strategy2.csv"), encoding="utf-8-sig")
    cand.to_csv(os.path.join(outdir, "all_pool.csv"), encoding="utf-8-sig")
    sell.to_csv(os.path.join(outdir, "sell_alerts.csv"), encoding="utf-8-sig")

    # 落选归因: 在股票池里但 RPS 条件差一点的
    near = d[(~d["all"])].copy()
    fails = near[["SXHCG1", "SXHCG2", "SXHCG3", "SXHCG4", "SXHCG5"]].apply(
        lambda r: "+".join([c.replace("SXHCG", "") for c in r.index if not r[c]]) or "-", axis=1)
    near["未过"] = fails
    near.sort_values(["未过", "RPS_sum"], ascending=[True, False]).to_csv(
        os.path.join(outdir, "near_miss.csv"), encoding="utf-8-sig")

    summary = _summary(date_str, pool, d, s1, s2, sell, miss, a_sell_win)
    open(os.path.join(outdir, "summary.txt"), "w", encoding="utf-8").write(summary)
    dump_dash(outdir, date_str, d, s1, s2, sell, P, pool, names, a_sell_win)
    print(summary)
    return {"date": date_str, "s1": s1, "s2": s2, "detail": d, "outdir": outdir}


def _summary(date_str, pool, d, s1, s2, sell, miss, a_sw=SELL_WIN) -> str:
    ln = []
    A = lambda n: f"{n:>10}"
    ln.append("=" * 74)
    ln.append(f" 每日筛选  {date_str}   (买入参考 = 当日最后一根日线收盘 = 13:50 快照价)")
    ln.append("=" * 74)
    ln.append(f"股票池 {len(pool)} 只 | 有日线 {len(d)} 只 | 缺数据 {len(miss)} 只")
    ln.append(f"过 RPS 选股(SXHCG 全条) {int(d['all'].sum())} 只")
    ln.append(f"  ├ 策略1 RPS+周线RSI多头确认 : {len(s1)} 只")
    ln.append(f"  └ 策略2 RPS+接近一年新高>0.90: {len(s2)} 只")
    ln.append(f"卖出提示(近 {a_sw} 个交易日内出现周线RSI死叉, 且近 {LOOKBACK_HELD} 日内入选过策略) {len(sell)} 只")
    try:                                        # 池子新鲜度: 季报期落后就提醒跑 run_quarterly.sh
        rd = pd.to_datetime(pool["report_date"]).max().date()
        need = C.latest_report_day()
        ln.append(f"股票池季报期 {rd}" + ("" if rd >= need else
                    f"  ⚠ 已落后于应有的 {need}, 请跑 ./run_quarterly.sh 或 ./run_all.sh"))
    except Exception:                           # noqa: BLE001
        pass
    ln.append("")
    for tag, s in (("策略1 (RPS + 周线RSI确认)", s1), ("策略2 (RPS + 接近一年新高)", s2)):
        ln.append(f"── {tag}  前 15 ──")
        if s.empty:
            ln.append("  (今日无入选)")
        else:
            ln.append(f"  {'代码':<8}{'名称':<10}{'收盘':>8}{'RPS120':>8}{'RPS250':>8}"
                      f"{'距新高':>7}{'周RSI1':>8}{'金叉N日':>8}")
            for c, r in s.head(15).iterrows():
                ln.append(f"  {c:<8}{str(r['name'])[:9]:<10}{r['close']:>8.2f}"
                          f"{r['RPS120']:>8.1f}{r['RPS250']:>8.1f}{r['newhigh_H250']:>7.3f}"
                          f"{r['w_rsi1']:>8.1f}{(r['wk_gold_days'] if pd.notna(r['wk_gold_days']) else -1):>8.0f}")
        ln.append("")
    if not sell.empty:
        ln.append(f"── 卖出提示 (周线RSI死叉, 参考卖点) 前 {min(12,len(sell))} ──")
        ln.append(f"  {'代码':<8}{'名称':<10}{'收盘':>8}{'几天前死叉':>10}{'周RSI1':>8}{'周RSI2':>8}"
                  f"{'上次入选':>9}{'曾在':>6}")
        for c, r in sell.head(12).iterrows():
            ln.append(f"  {c:<8}{str(r['name'])[:9]:<10}{r['close']:>8.2f}{r['wk_dead_days']:>10.0f}"
                      f"{r['w_rsi1']:>8.1f}{r['w_rsi2']:>8.1f}"
                      f"{(f"{r['pick_age']:.0f}日前" if pd.notna(r['pick_age']) else '-'):>9}"
                      f"{(''.join([t for t, ok in (('S1', r['was_s1']), ('S2', r['was_s2'])) if ok]) or '-'):>6}")
        ln.append("")
    ln.append("参数: RPS120+RPS250>%d, C>MA20, 30日内>=25天站MA250&MA200, 20日结构回撤<=25%%," % C.RPS["sum_min"])
    ln.append("      C/HHV(C,250)>%.2f, 10/20日线多头, 换手<%.0f%%; 周线RSI(%d)/MA(%d)/轴%.0f"
              % (C.RPS["hhv250_ratio"], C.RPS["turnover_max"], C.WK_RSI["rsi_period"],
                 C.WK_RSI["sig_window"], C.WK_RSI["mid_line"]))
    return "\n".join(ln)


def dump_dash(outdir, date_str, d, s1, s2, sell, P, pool, names, a_sell_win=SELL_WIN):
    """给 HTML 看板用的最小数据包"""
    def pack(s):
        return [{"code": c, "name": str(r["name"]), "close": round(float(r["close"]), 3),
                 "rps120": round(float(r["RPS120"]), 1), "rps250": round(float(r["RPS250"]), 1),
                 "newhigh": round(float(r["newhigh_H250"]), 4),
                 "wrsi1": None if pd.isna(r["w_rsi1"]) else round(float(r["w_rsi1"]), 1),
                 "wrsi2": None if pd.isna(r["w_rsi2"]) else round(float(r["w_rsi2"]), 1),
                 "golddays": None if pd.isna(r["wk_gold_days"]) else int(r["wk_gold_days"]),
        "deaddays": None if pd.isna(r["wk_dead_days"]) else int(r["wk_dead_days"]),
                 "turnover": None if pd.isna(r["turnover"]) else round(float(r["turnover"]), 2),
                 "dd20": None if pd.isna(r["dd20"]) else round(float(r["dd20"]), 3),
                 "fund": None if pd.isna(r["fund_ratio_float"]) else round(float(r["fund_ratio_float"]), 2),
                 "north_yi": None if pd.isna(r["north_value_yi"]) else round(float(r["north_value_yi"]), 2),
                 } for c, r in s.iterrows()]
    # 近 250 日走势给看板画线
    hist = {}
    for c in set(list(s1.index[:12]) + list(s2.index[:12])):
        if c in P["Close"].columns:
            x = P["Close"][c].loc[:date_str].tail(250)
            hist[c] = {"dates": x.index.strftime("%Y-%m-%d").tolist(),
                       "close": [None if pd.isna(v) else round(float(v), 3) for v in x]}
    js = {"date": date_str, "pool_n": int(len(pool)), "sxhcg_n": int(d["all"].sum()),
          "s1": pack(s1), "s2": pack(s2), "hist": hist,
          "sell": [{"code": c, "name": str(r["name"]), "close": round(float(r["close"]), 3),
                    "days": None if pd.isna(r["wk_dead_days"]) else int(r["wk_dead_days"]),
                    "wrsi1": None if pd.isna(r["w_rsi1"]) else round(float(r["w_rsi1"]), 1),
                    "wrsi2": None if pd.isna(r["w_rsi2"]) else round(float(r["w_rsi2"]), 1),
                    "rps_sum": round(float(r["RPS_sum"]), 1),
                    "was_s1": bool(r["was_s1"]), "was_s2": bool(r["was_s2"]),
                    "pick_age": None if pd.isna(r["pick_age"]) else int(r["pick_age"])}
                   for c, r in sell.iterrows()],
          "sell_win": a_sell_win, "pick_lookback": LOOKBACK_HELD,
          "params": {**{k: v for k, v in C.RPS.items()},
                     "wk": {k: v for k, v in C.WK_RSI.items()}}}
    with open(os.path.join(outdir, "dashboard.json"), "w", encoding="utf-8") as f:
        json.dump(js, f, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", help="回看某交易日 YYYY-MM-DD")
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--dir", help="日线目录, 默认 5y 缓存")
    ap.add_argument("--min-list-days", type=int, default=0)
    ap.add_argument("--sell-win", type=int, default=SELL_WIN, help="卖出提示回看天数")
    a = ap.parse_args()
    run(a.asof, a.top, a.dir, a.min_list_days, a.sell_win)


if __name__ == "__main__":
    main()
