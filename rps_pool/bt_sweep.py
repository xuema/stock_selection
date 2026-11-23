#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回测参数敏感性: 一次载入, 逐组复用信号, 输出 out/backtest/sweep.csv

  python3 bt_sweep.py --start 2022-01-04
"""
import argparse, itertools, os, sys, time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import indicators as I
import poolio
from backtest import build_signals, simulate, metrics, load_bench, BTOUT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2022-01-04")
    ap.add_argument("--bench", default="hs300")
    a = ap.parse_args()
    os.makedirs(BTOUT, exist_ok=True)

    pool = poolio.load_pool()
    fs = poolio.float_shares(pool)
    P = I.load(min_bars=C.RPS["w_slow"] + 300)
    print(f"载入 {P['Close'].shape}")
    bench = load_bench(a.bench) if a.bench != "none" else None

    grid = []
    for uni in ("pool", "all"):
        for st in ("1", "2"):
            for sm in ("cross", "state"):
                for mp in (5, 10, 20):
                    for tl in (False, True):
                        for rs in (185, 180):
                            grid.append(dict(universe=uni, strategy=st, sell_mode=sm,
                                             max_pos=mp, three_line=tl, rps_sum=rs))
    # 只保留: 基准 + 单因子变化
    base = dict(universe="pool", strategy="1", sell_mode="cross", max_pos=10,
                three_line=False, rps_sum=185)
    keep = [base]
    for k, vals in (("strategy", ("2",)), ("sell_mode", ("state",)), ("max_pos", (5, 20)),
                    ("three_line", (True,)), ("rps_sum", (180,)), ("universe", ("all",))):
        for v in vals:
            d = dict(base); d[k] = v
            if d not in keep:
                keep.append(d)
    # 两个策略的完整单因子表
    for st in ("1", "2"):
        for k, vals in (("sell_mode", ("cross", "state")), ("max_pos", (5, 10, 20)),
                        ("three_line", (False, True)), ("universe", ("pool", "all"))):
            for v in vals:
                d = dict(base); d["strategy"] = st; d[k] = v
                if d not in keep:
                    keep.append(d)
    print(f"组合数 {len(keep)}")

    cache, rows = {}, []
    for g in keep:
        ck = (g["universe"], g["three_line"], g["rps_sum"])
        if ck not in cache:
            t0 = time.time()
            cache[ck] = build_signals(P, pool, g["universe"], fs, C.BT["min_bar_amount"],
                                      "cross", g["three_line"], g["rps_sum"])
            print(f"  信号 {ck} {time.time()-t0:.1f}s")
        S = cache[ck]
        W = S["W"]
        S = dict(S, exit_w=W["w_dead"] if g["sell_mode"] == "cross" else W["w_dead_state"])
        mask = S["s1"] if g["strategy"] == "1" else S["s2"]
        tr, nv = simulate(P, S, mask, S["exit_w"], a.start, None, g["max_pos"],
                          C.BT["per_trade_pct"], C.BT["commission"] + C.BT["stamp_tax"],
                          C.BT["slippage"], C.BT["max_hold_days"])
        m = metrics(tr, nv, bench)
        ann = m.pop("分年", {})
        rows.append({**g, **{k: v for k, v in m.items()},
                     **{f"{y}年": v for y, v in ann.items()}})
        print("  ", g, "→ 年化", m.get("年化"), "回撤", m.get("最大回撤"))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(BTOUT, "sweep.csv"), index=False, encoding="utf-8-sig")
    cols = ["universe", "strategy", "sell_mode", "max_pos", "three_line", "rps_sum",
            "总收益", "年化", "最大回撤", "夏普", "卡玛", "胜率", "盈亏比", "交易数", "平均持有天数"]
    cols = [c for c in cols if c in df.columns]
    print("\n" + df[cols].to_string(index=False))
    print(f"\n-> {os.path.join(BTOUT, 'sweep.csv')}")


if __name__ == "__main__":
    main()
