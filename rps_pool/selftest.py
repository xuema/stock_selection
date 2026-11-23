#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指标引擎自检: 用独立写的朴素实现(循环版)交叉验证向量化版本。

  python3 selftest.py
"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import indicators as I


def naive_rsi1(Close, period=12):
    """按"当日收盘价充当本周临时周收盘"的口径, 逐日重算周线 RSI1"""
    out = {}
    for code in Close.columns:
        s = Close[code].dropna()
        if len(s) < period * 6:
            continue
        vals, idx = [], []
        for i in range(len(s)):
            sub = s.iloc[:i + 1]
            wk = sub.groupby(sub.index.to_period("W-FRI")).last()
            d = wk.diff().dropna()
            ag = al = None
            for x in d.to_numpy():
                g, l = max(x, 0.0), max(-x, 0.0)
                if ag is None:
                    ag, al = g, l
                else:
                    ag = ag + (g - ag) / period
                    al = al + (l - al) / period
            r = np.nan if (ag is None or ag + al == 0) else 100 * ag / (ag + al)
            ok = len(wk) >= period + 1
            vals.append(r if ok else np.nan)
            idx.append(s.index[i])
        out[code] = pd.Series(vals, index=pd.DatetimeIndex(idx))
    return pd.DataFrame(out)


def naive_weekly(Close, period=12, sig=5):
    """真·周线: 只在每周末用最终周收盘算, 返回周频 RSI1/RSI2"""
    wk = Close.groupby(Close.index.to_period("W-FRI")).last()
    r1 = I.RSI(wk, period)
    return r1, I.MA(r1, sig)


def main():
    rng = np.random.default_rng(11)
    idx = pd.bdate_range("2023-01-02", periods=320)
    codes = [f"{600000+i}" for i in range(6)]
    Close = pd.DataFrame(np.exp(np.cumsum(rng.normal(0.0005, 0.02, (len(idx), 6)), 0)),
                         index=idx, columns=codes)
    Close.iloc[:20, 3] = np.nan                       # 未上市
    Close.iloc[100:110, 4] = Close.iloc[99, 4]        # 停牌(价格已 ffill, 量=0)
    Vol = pd.DataFrame(rng.gamma(3, 4e6, (len(idx), 6)), index=idx, columns=codes)
    Vol.iloc[:20, 3] = 0
    Vol.iloc[100:110, 4] = 0
    P = dict(Open=Close, High=Close * 1.01, Low=Close * 0.99, Close=Close, Volume=Vol,
             _first=pd.Series({c: Close[c].first_valid_index() for c in codes}),
             _bars=pd.Series({c: int(Close[c].notna().sum()) for c in codes}),
             _hasdata=Vol > 0)

    # 1) HHVBARS / LLVBARS
    hh = I.HHVBARS(P["High"], 20)
    hhb = I.HHV(P["High"], 20)
    chk = hh.apply(lambda s: s).notna()
    bad = 0
    for c in codes:
        h = P["High"][c].to_numpy(float)
        lo_ = P["Low"][c].to_numpy(float)
        for t in range(19, len(h), 7):
            w = h[t - 19:t + 1]
            k = int(np.argmax(np.nan_to_num(w, nan=-np.inf)[::-1]))
            lw = np.nan_to_num(lo_[t - 19:t + 1], nan=np.inf)
            kl = int(np.argmax((-lw)[::-1]))
            if (abs(hh.iloc[t][c] - k) > 1e-9
                    or abs(I.LLVBARS(P["Low"], 20).iloc[t][c] - kl) > 1e-9):
                bad += 1
    print(f"  HHVBARS/LLVBARS vs 朴素: {'OK' if bad == 0 else f'{bad} 处不符'}")

    # 2) 回撤: HHV(20) 当日 high == REF(H, HHVBARS)   (只看两边都有限的格子)
    hhv20 = I.HHV(P["High"], 20)
    hi = I._ref_var(P["High"], I.HHVBARS(P["High"], 20))
    ok = np.isfinite(hi.to_numpy()) & np.isfinite(hhv20.to_numpy())
    print(f"  REF(H,HHVBARS) == HHV(H,20): {bool(np.allclose(hi.to_numpy()[ok], hhv20.to_numpy()[ok]))}"
          f"  (比较 {int(ok.sum())} 格)")

    # 3) RSI 引擎
    W = I.weekly_rsi_daily(Close, 12, 5)
    n1 = naive_rsi1(Close, 12)
    j = pd.concat([W["w_rsi1"].stack().rename("eng"), n1.stack().rename("naive")], axis=1).dropna()
    print(f"  周线RSI1 向量化 vs 朴素: n={len(j)} 最大偏差={float((j.eng-j.naive).abs().max()):.3e}")
    r1w, r2w = naive_weekly(Close, 12, 5)
    wend = pd.Series(np.arange(len(idx), dtype=float), index=idx).groupby(idx.to_period("W-FRI")).max()
    tail = idx[wend.dropna().to_numpy().astype(int)]
    a2 = W["w_rsi1"].loc[tail].set_axis(r1w.index[:len(tail)])
    j2 = pd.concat([a2.stack().rename("eng"), r1w.stack().rename("ref")], axis=1)
    j2 = j2.dropna()
    print(f"  周末 RSI1 vs 周线直算: n={len(j2)} 最大偏差={float((j2.eng-j2.ref).abs().max()):.3e}")
    b2 = W["w_rsi2"].loc[tail].set_axis(r2w.index[:len(tail)])
    j3 = pd.concat([b2.stack().rename("eng"), r2w.stack().rename("ref")], axis=1).dropna()
    print(f"  周末 RSI2 vs 周线直算: n={len(j3)} 最大偏差={float((j3.eng-j3.ref).abs().max()):.3e}")
    # 金叉/死叉只能在周内状态变化处
    gc = W["w_gold"].sum().sum()
    print(f"  金叉 {int(gc)} 次, 死叉 {int(W['w_dead'].sum().sum())} 次, "
          f"w_above 覆盖率 {float(W['w_above'].mean().mean()):.3f}")

    # 4) SXHCG 各条件与合成
    F = I.sxhcg(P, focus=codes, float_shares={c: 2e8 for c in codes})
    for k in ["SXHCG1", "SXHCG2", "SXHCG3", "SXHCG4", "SXHCG5"]:
        print(f"  {k}: {int(F[k].to_numpy().sum())} / {F[k].size}")
    and_all = (F["SXHCG1"] & F["SXHCG2"] & F["SXHCG3"] & F["SXHCG4"] & F["SXHCG5"])
    print(f"  SXHCG == 五条与: {bool((and_all.to_numpy() == F['SXHCG'].to_numpy()).all())}")
    # 变长 COUNT 与朴素
    cv = I._count_var(F["dd"] > 0.25, F["hhb"], 20)
    ddv, hhbv = F["dd"].to_numpy(), F["hhb"].to_numpy()
    bad = 0
    for t in range(19, len(idx), 11):
        for ci, c in enumerate(codes):
            k = hhbv[t, ci]
            if not np.isfinite(k):
                continue
            k = int(k)
            m = 0 if k == 0 else int(np.nansum([1 if np.isfinite(ddv[t - m2, ci]) and ddv[t - m2, ci] > 0.25
                                                else 0 for m2 in range(k)]))
            if abs(m - cv.iloc[t, ci]) > 1e-9:
                bad += 1
    print(f"  变长 COUNT vs 朴素: {'OK' if bad == 0 else str(bad)+' 处不符'}")
    # 5) live
    print(f"  live 天数合计 {int(F['live'].to_numpy().sum())} (应排除未上市/零量)")


if __name__ == "__main__":
    print("selftest:")
    main()
