#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""指标引擎: 通达信公式 -> pandas/numpy 向量化

两个入口共用同一套函数, 保证"每日选股"和"回测"口径完全一致:
  screen_daily.py  取最后一根日线 -> 今日入选
  backtest.py      取整个时间轴   -> 逐日重放

宽表约定: 行=交易日(全市场统一日历), 列=股票代码。
停牌/未上市日: 价格前向填充、成交量记 0 (否则横截面排名无法对齐)。

性能: 变长窗口的 HHVBARS/LLVBARS/COUNT 是 O(kmax) 次全表滚动, 所以只对 focus
      列(股票池)计算, 全市场只算 RPS 需要的收益率与均线。
"""
from __future__ import annotations
import os, sys, glob
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

FIELDS = ["Open", "High", "Low", "Close", "Volume"]


# ══════════════════════ 1. 载入宽表 ══════════════════════
def load(dirn: str | None = None, codes: list[str] | None = None,
         start: str | None = None, min_bars: int = 60, fix_ohlc: bool = True) -> dict:
    dirn = dirn or C.HIST_DIR
    if not os.path.isdir(dirn):
        raise SystemExit(f"缺少日线缓存 {dirn}, 先跑 fetch_history.py --build")
    files = sorted(glob.glob(os.path.join(dirn, "*.csv")))
    if codes is not None:
        keep = {c.zfill(6) for c in codes}
        files = [f for f in files if os.path.basename(f)[:6] in keep]
    rec, bad = {}, []
    for fp in files:
        code = os.path.basename(fp)[:6]
        try:
            d = pd.read_csv(fp, usecols=FIELDS + ["Date"])
        except Exception:                                    # noqa: BLE001
            bad.append(code)
            continue
        d["Date"] = pd.to_datetime(d["Date"], errors="coerce")
        for c in FIELDS:
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d = d.dropna(subset=["Date", "Close", "High", "Low"]).sort_values("Date")
        d = d.drop_duplicates("Date", keep="last").set_index("Date")
        if start:
            d = d[d.index >= pd.Timestamp(start)]
        if len(d) < min_bars:
            bad.append(code)
            continue
        if fix_ohlc:                       # yfinance Open 已知不可靠; High/Low 按 Close 夹紧
            d["High"] = np.maximum(d["High"], d["Close"])
            d["Low"] = np.minimum(d["Low"], d["Close"])
            d["High"] = np.maximum(d["High"], d["Low"])
        d["Volume"] = d["Volume"].fillna(0)
        rec[code] = d
    if not rec:
        raise SystemExit("没有可用日线")
    idx = pd.DatetimeIndex(sorted({ts for d in rec.values() for ts in d.index}))
    out = {}
    for f in FIELDS:
        m = pd.DataFrame({c: d[f] for c, d in rec.items()}).reindex(idx)
        m = m.ffill() if f in ("Close", "High", "Low") else m.fillna(0.0)
        out[f] = m
    out["_first"] = pd.Series({c: d.index[0] for c, d in rec.items()})
    out["_bars"] = pd.Series({c: len(d) for c, d in rec.items()})
    out["_hasdata"] = pd.DataFrame({c: pd.Series(d["Volume"].to_numpy() > 0, index=d.index)
                                    for c, d in rec.items()}).reindex(idx).fillna(False)
    out["_bad"] = bad
    out["_spike"] = sanitize(out)
    return out


def sanitize(out: dict) -> int:
    """单日跳变 >35% 且次日又跳回来 = 数据毛刺(复权因子/源错误) -> 当日 OHLC 用前值替换。
    真实涨跌停(主板10%/创业科创20%/北交30%)不会同时满足"次日反向跳回"。"""
    Cc = out["Close"]
    r = Cc / Cc.shift(1) - 1.0
    big = r.abs() > 0.35
    spike = big & big.shift(-1).fillna(False)
    if not bool(spike.to_numpy().any()):
        return 0
    for f in ("Open", "High", "Low", "Close"):
        out[f] = out[f].mask(spike, out[f].shift(1))
    out["Volume"] = out["Volume"].mask(spike, 0.0)
    return int(spike.to_numpy().sum())


def live_mask(P: dict) -> pd.DataFrame:
    """当日该票真的有行情(已上市且当日有成交)"""
    Cc = P["Close"]
    fp = Cc.index.searchsorted(P["_first"].reindex(Cc.columns).to_numpy(dtype="datetime64[ns]"))
    started = np.arange(len(Cc))[:, None] >= fp[None, :]
    hd = P["_hasdata"].reindex(index=Cc.index, columns=Cc.columns, fill_value=False).to_numpy()
    return pd.DataFrame(started & hd, index=Cc.index, columns=Cc.columns)


def col_view(P: dict, cols: list[str]) -> dict:
    keep = [c for c in cols if c in P["Close"].columns]
    Q = {f: P[f][keep] for f in ("Open", "High", "Low", "Close", "Volume")}
    Q["_first"] = P["_first"][keep]
    Q["_bars"] = P["_bars"][keep]
    Q["_hasdata"] = P["_hasdata"][keep]
    return Q


# ══════════════════════ 2. 通达信原语 ══════════════════════
def MA(X, n): return X.rolling(n, min_periods=n).mean()
def HHV(X, n): return X.rolling(n, min_periods=n).max()
def LLV(X, n): return X.rolling(n, min_periods=n).min()
def REF(X, n): return X.shift(n)


def COUNT(cond: pd.DataFrame, n: int) -> pd.DataFrame:
    return cond.astype(float).rolling(n, min_periods=n).sum()


def EVERY(cond: pd.DataFrame, n: int) -> pd.DataFrame:
    return COUNT(cond, n) >= n


def _bars_since_ext(X: pd.DataFrame, n: int, want_max: bool) -> pd.DataFrame:
    """HHVBARS/LLVBARS(X,n): 到窗口内极值点的周期数。并列取最靠右(最近)的一根。"""
    v = X.to_numpy(dtype=np.float64, copy=False)
    T, N = v.shape
    res = np.full((T, N), np.nan)
    sv = v * (1.0 if want_max else -1.0)
    _nan = np.full(N, np.nan)
    for t in range(n - 1, T):
        w = sv[t - n + 1:t + 1]
        ok = np.isfinite(w).any(axis=0)
        if not ok.any():
            continue
        # 倒序后 argmax -> 并列时命中"最近"的那根, 其下标即 bars-since
        dist = np.argmax(np.where(np.isnan(w), -np.inf, w)[::-1], axis=0)
        res[t, ok] = dist[ok]
    return pd.DataFrame(res, index=X.index, columns=X.columns)


def HHVBARS(X, n): return _bars_since_ext(X, n, True)
def LLVBARS(X, n): return _bars_since_ext(X, n, False)


def RSI(Close, n: int) -> pd.DataFrame:
    """通达信 RSI := SMA(MAX(C-REF(C,1),0),N,1) / SMA(ABS(C-REF(C,1)),N,1) * 100
    SMA(X,N,1) 等价 ewm(alpha=1/N, adjust=False)。"""
    d = Close.diff()
    up = d.clip(lower=0.0)
    dn = d.abs()
    a = 1.0 / n
    au = up.ewm(alpha=a, adjust=False).mean()
    ad = dn.ewm(alpha=a, adjust=False).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        r = 100.0 * au / ad
    return r.where(ad > 0)


def _ref_var(X: pd.DataFrame, K: pd.DataFrame) -> pd.DataFrame:
    """REF(X, K) 且 K 逐 bar 逐票不同: 返回 X[t-K, c]"""
    xv = X.to_numpy(dtype=float)
    kv = K.to_numpy(dtype=float)
    T, N = xv.shape
    t = np.arange(T)[:, None]
    k = np.nan_to_num(kv, nan=0.0, posinf=0.0, neginf=0.0).astype(np.int64)
    k = np.clip(k, 0, T - 1)
    rows = t - k
    ok = rows >= 0
    rr = np.where(ok, rows, 0)
    cc = np.tile(np.arange(N), (T, 1))
    vals = xv[rr, cc]
    vals = np.where(ok & np.isfinite(kv), vals, np.nan)
    return pd.DataFrame(vals, index=X.index, columns=X.columns)


def _count_var(cond: pd.DataFrame, K: pd.DataFrame, kmax: int) -> pd.DataFrame:
    """COUNT(cond, K), K 变长 (0<=K<=kmax), 含当日那根。K=0 或 NaN -> 0"""
    cv = np.nan_to_num(cond.to_numpy(dtype=float))
    T, N = cv.shape
    cs = np.vstack([np.zeros((1, N)), np.cumsum(cv, axis=0)])        # (T+1, N)
    kv = np.nan_to_num(K.to_numpy(dtype=float), nan=0.0).astype(np.int64)
    kv = np.clip(kv, 0, kmax)
    t = np.arange(T)[:, None]
    cc = np.tile(np.arange(N), (T, 1))
    a = t - kv + 1
    ok = (a >= 0) & (kv > 0)
    out = cs[1:][np.broadcast_to(t, (T, N)), cc] - cs[np.where(ok, a, 0), cc]
    return pd.DataFrame(np.where(ok, out, 0.0), index=cond.index, columns=cond.columns)


def LLVBARS_var(X: pd.DataFrame, K: pd.DataFrame, kmax: int = 20) -> pd.DataFrame:
    """LLVBARS(X, K), K 变长。K=0 -> 0"""
    res = pd.DataFrame(0.0, index=X.index, columns=X.columns)
    for k in range(1, int(kmax) + 1):
        lk = LLVBARS(X, k)
        sel = (K.round() == k)
        res = res.where(~sel, lk)
    return res.where(K.round() > 0, 0.0)


# ══════════════════════ 3. RPS ══════════════════════
def ret_n(Close, n, live=None):
    r = Close / Close.shift(n) - 1.0
    return r.where(live) if live is not None else r


def RPS(ret: pd.DataFrame) -> pd.DataFrame:
    """逐日横截面百分位 x100 (对应通达信 EXTDATA_USER 的 120/250 日 RPS)"""
    return ret.rank(axis=1, pct=True, method="average") * 100.0


# ══════════════════════ 4. 周线 RSI(以交易为生) ══════════════════════
def weekly_rsi_daily(Close: pd.DataFrame, period: int = 12, sig: int = 5,
                     mid: float = 50.0, three_line: bool = False, slow: int = 24,
                     lookback_days: int = 0) -> pd.DataFrame:
    """把周线 RSI 三线落到每一根日线上。

    当周尚未走完时, 用"当日收盘价"当作该周的临时周收盘 -> 每日 13:50 看到的状态
    就等于周线图上"本周走到现在"的状态。

    RSI1 = 周线 RSI(period)   RSI2 = MA(RSI1, sig)   RSI3 = mid 轴 或 MA(RSI1, slow)
    平滑用递推 alpha=1/period (等价通达信 SMA(X,N,1)), 而非经典 seed 初始化。
    """
    Cl = Close.iloc[-lookback_days:] if lookback_days else Close
    wk = Cl.index.to_period("W-FRI")
    wkey = pd.Index(sorted(set(wk)))
    wpos = pd.Series(np.arange(len(wkey)), index=wkey)
    dpos = pd.Series(wk, index=Cl.index).map(wpos).to_numpy()          # 每日属于第几周
    W = Cl.groupby(wk, observed=True).last().reindex(wkey)             # 周收盘(最终)
    Wv = W.to_numpy(float)
    NW, NC = Wv.shape

    prev = np.vstack([np.full((1, NC), np.nan), Wv[:-1]])
    d = Wv - prev
    gain = np.where(np.isnan(d), np.nan, np.maximum(d, 0.0))
    loss = np.where(np.isnan(d), np.nan, np.maximum(-d, 0.0))
    a = 1.0 / period
    # NaN 周(未上市/整周停牌) 由 ewm 跳过 -> AG/AL 顺延, 不会被当成 0 而压低
    AG = pd.DataFrame(gain, index=wkey).ewm(alpha=a, adjust=False).mean().to_numpy()
    AL = pd.DataFrame(loss, index=wkey).ewm(alpha=a, adjust=False).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        RSIw = np.where(AL + AG == 0, np.nan, 100.0 * AG / (AG + AL))
    nvalid = np.cumsum(np.isfinite(Wv), axis=0)
    RSIw = np.where(nvalid >= period + 1, RSIw, np.nan)
    RSIdf = pd.DataFrame(RSIw, index=wkey, columns=Cl.columns)

    # 前一周的 AG/AL
    AGp = np.vstack([np.full((1, NC), np.nan), AG[:-1]])
    ALp = np.vstack([np.full((1, NC), np.nan), AL[:-1]])
    Cw_prev = prev

    def _ma_incl_now(k):
        """MA(RSI1, k) 含"本周临时值": 先取前 k-1 周均值, 再与本周合成。k<=1 -> 本周值本身"""
        if k <= 1:
            return None
        return RSIdf.rolling(k - 1, min_periods=k - 1).mean().shift(1).to_numpy()

    m_sig = _ma_incl_now(sig)          # 前 sig-1 周 RSI1 均值
    m_slow = _ma_incl_now(slow) if three_line else None

    # 落到每一根日线: 本周临时周收盘 = 当日收盘
    cw = Cl.to_numpy(float)
    base = Cw_prev[dpos]                                   # 上周最终收盘
    agp = AGp[dpos]
    alp = ALp[dpos]
    with np.errstate(invalid="ignore"):
        gp = np.maximum(cw - base, 0.0)
        lp = np.maximum(base - cw, 0.0)
        ag2 = np.where(np.isnan(agp), np.nan, agp * (1 - a) + gp * a)
        al2 = np.where(np.isnan(alp), np.nan, alp * (1 - a) + lp * a)
        r1 = np.where((ag2 + al2) == 0, np.nan, 100.0 * ag2 / (ag2 + al2))
    r1 = np.where(np.isnan(m_sig[dpos]), np.nan, r1)
    r2 = (m_sig[dpos] * (sig - 1) + r1) / float(sig)       # = MA(RSI1, sig) 含本周
    r1df = pd.DataFrame(r1, index=Cl.index, columns=Cl.columns)
    r2df = pd.DataFrame(r2, index=Cl.index, columns=Cl.columns)
    if three_line:
        r3 = (m_slow[dpos] * (slow - 1) + r1) / float(slow)
        r3df = pd.DataFrame(r3, index=Cl.index, columns=Cl.columns)
    else:
        r3df = pd.DataFrame(mid, index=Cl.index, columns=Cl.columns)

    above = (r1df > r2df) & r1df.notna()
    prev_above = above.shift(1, fill_value=False).astype(bool)
    gold = above & ~prev_above
    weak = r1df.notna() & (r1df < r3df)
    dead = (~above) & prev_above & weak                    # 字面: 下穿当根且 RSI1<RSI3
    dead_state = (~above) & weak                           # 状态: 已处于下方且 RSI1<RSI3
    full = {}
    for nm, df in (("w_rsi1", r1df), ("w_rsi2", r2df), ("w_rsi3", r3df),
                   ("w_above", above), ("w_gold", gold), ("w_dead", dead),
                   ("w_dead_state", dead_state)):
        full[nm] = df.reindex(Close.index)
    return full


def weekly_rsi_plain(Close: pd.DataFrame, period: int = 12, sig: int = 5,
                     mid: float = 50.0) -> dict:
    """真周线口径(只在周末用最终周收盘计算), 供 selftest 交叉验证用。
    返回周频 DataFrame: rsi1 / rsi2 / rsi3 / above / gold / dead"""
    W = Close.groupby(Close.index.to_period("W-FRI")).last()
    r1 = RSI(W, period)
    r2 = MA(r1, sig)
    r3 = pd.DataFrame(mid, index=W.index, columns=W.columns)
    above = (r1 > r2) & r1.notna()
    prev = above.shift(1, fill_value=False).astype(bool)
    weak = r1.notna() & (r1 < r3)
    return {"rsi1": r1, "rsi2": r2, "rsi3": r3, "above": above,
            "gold": above & ~prev, "dead": (~above) & prev & weak}


# ══════════════════════ 5. RPS 选股公式全套 ══════════════════════
def sxhcg(P: dict, focus: list[str] | None = None, params: dict | None = None,
          newhigh_ratio: float | None = None, float_shares: dict | None = None,
          rps_cache: dict | None = None, rank_cols: list[str] | None = None) -> dict:
    """SXHCG1..5 及合成。返回布尔宽表 + 关键中间量。

    focus 之外的票只参与 RPS 横截面排名, 不算变长窗口那些慢条件。
    rank_cols: 限定 RPS 横截面的样本集(默认 None = 缓存里的全部股票, 即通达信那样
      全市场排名)。传股票池进去 => "池内分位", 阈值含义会变, 见 README。
    """
    p = dict(C.RPS)
    if params:
        p.update(params)
    nh = p["hhv250_ratio"] if newhigh_ratio is None else newhigh_ratio
    Close, High, Low, Vol = P["Close"], P["High"], P["Low"], P["Volume"]
    live = live_mask(P)
    cols = [c for c in (focus if focus is not None else Close.columns) if c in Close.columns]

    rc = list(Close.columns) if rank_cols is None else [c for c in rank_cols if c in Close.columns]
    if not set(cols) <= set(rc):
        raise SystemExit("rank_cols 必须包含 focus(否则池外的票没有排名)")
    key = (p["w_fast"], p["w_slow"], tuple(rc) if rank_cols is not None else None)
    got = None
    if rps_cache is not None:
        got = rps_cache.get(key)
    if got is None:
        sub = {"Close": Close[rc], "High": High[rc], "Low": Low[rc],
               "Volume": Vol[rc], "_first": P["_first"][rc], "_hasdata": P["_hasdata"][rc]}
        live_rc = live_mask(sub) if rank_cols is not None else live[rc]
        got = (RPS(ret_n(Close[rc], p["w_fast"], live_rc)),
               RPS(ret_n(Close[rc], p["w_slow"], live_rc)))
        if rps_cache is not None:
            rps_cache[key] = got
    r120, r250 = got
    s1_full = (r120 + r250) > p["sum_min"]
    s1 = s1_full[cols]

    # SXHCG2  (均线只在 focus 上算, 全市场只算 RPS 需要的东西)
    Q = col_view(P, cols)
    q20, q10 = MA(Q["Close"], 20), MA(Q["Close"], 10)
    q200, q250 = MA(Q["Close"], 200), MA(Q["Close"], 250)
    g20 = Q["Close"] > q20
    c250 = COUNT(Q["Close"] > q250, p["count250_days"])
    c200 = COUNT(Q["Close"] > q200, p["count250_days"])
    c20_10 = COUNT(g20, 10)
    c10_4, c20_4 = COUNT(Q["Close"] > q10, 4), COUNT(g20, 4)
    s2 = g20 & (c250 >= p["count250_need"]) & (c200 >= p["count250_need"]) & \
        ((c20_10 >= 9) | ((c10_4 >= 3) & (c20_4 >= 3)))

    # SXHCG3: 20 日内高低点结构回撤 + 距一年新高
    hhb = HHVBARS(Q["High"], 20)
    llb = LLVBARS_var(Q["Low"], hhb, kmax=20)
    hi = _ref_var(Q["High"], hhb)
    lo = _ref_var(Q["Low"], llb)
    dd = (hi - lo) / hi
    s31 = (dd <= p["dd_limit"]) & (_count_var((dd > p["dd_limit"]), hhb, 20) == 0)
    nh_c = Q["Close"] / HHV(Q["Close"], 250)[cols]
    nh_h = Q["Close"] / HHV(Q["High"], 250)[cols]        # 策略2: C/HHV(H,250) > 0.9
    s32 = nh_c > nh
    s3 = s31 & s32

    # SXHCG4
    up20, up10 = q20 >= q20.shift(1), q10 >= q10.shift(1)
    stack = q10 >= q20
    s41 = EVERY(up20, p["ma20_up_days"]) & EVERY(stack, p["ma20_up_days"])
    s42 = up10 & up20 & stack
    s4 = s41 | s42

    # SXHCG5: 日线换手率 < 10%
    if float_shares:
        fs = pd.Series(float_shares).reindex(cols).astype(float).replace(0, np.nan)
        turn = Q["Volume"].div(fs, axis=1) * 100.0
        s5 = (turn < p["turnover_max"]) | turn.isna()
    else:
        turn = pd.DataFrame(np.nan, index=Q["Close"].index, columns=cols)
        s5 = pd.DataFrame(True, index=Q["Close"].index, columns=cols)

    allc = s1 & s2 & s3 & s4 & s5
    rt120, rt250 = ret_n(Close, p["w_fast"], live), ret_n(Close, p["w_slow"], live)
    return dict(SXHCG1=s1, SXHCG2=s2, SXHCG3=s3, SXHCG31=s31, SXHCG32=s32, SXHCG4=s4,
                SXHCG5=s5, SXHCG=allc, RPS120=r120, RPS250=r250, SXHCG1_all=s1_full,  # 排名口径布尔
                ma10=q10, ma20=q20, ma250=q250, dd=dd, hhb=hhb, turn=turn,
                newhigh=nh_c, newhigh_h=nh_h, live=live[cols],
                cols=cols, ret120=rt120, ret250=rt250)
