#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日线历史: yfinance 批量前复权回填 + 每日增量(带复权漂移检测)

为什么不用新浪/东财 kline:
  新浪 CN_MarketData 是"不复权", 高股息票一年漂移 ~2%, 会把 MA250 / HHV(C,250) / RPS250
  全部扭曲; 东财 push2his 虽给前复权+换手率, 但并发稍高就被限流。
  yfinance 默认 auto_adjust=True => Close 就是前复权, 且可一次批量下 100 只, 全市场 6 年 ~15 分钟。

产出: {REPO}/data_cache_daily_5y/{code}.csv
  Date,Open,High,Low,Close,Volume   (与 legacy data_cache_daily 同构, 只是更长)

模式:
  --build   首次全量回填(可断点续跑, 已存在文件跳过)
  --update  每日增量: 拉近 30 天; 若与已存数据重叠段价格比偏离 1 超过阈值 => 说明期间发生除权,
            该票整段重下, 避免"头部旧价未复权、尾部已复权"的错位
  --rebuild 强制全量重下

用法:
  python3 fetch_history.py --build
  python3 fetch_history.py --build --limit 200 --period 6y
  python3 fetch_history.py --update --codes-file out/pool/pool_codes_latest.txt
"""
import argparse, os, sys, time, json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

COLS = ["Date", "Open", "High", "Low", "Close", "Volume"]
DRIFT = 0.002          # 重叠段价格比偏离 0.2% 视为发生除权


def tick(c: str) -> str:
    c = c.zfill(6)
    if c[0] in ("6", "9", "5"):
        return f"{c}.SS"
    if c[:2] in ("00", "30", "12", "15", "16", "18"):
        return f"{c}.SZ"
    return f"{c}.BJ"


def code_of(tk: str) -> str:
    return tk.split(".")[0].zfill(6)


def legacy_universe() -> list[str]:
    out = []
    for f in sorted(os.listdir(C.LEGACY_DAILY)):
        if len(f) == 10 and f.endswith(".csv") and f[:6].isdigit() and f != "000300.csv":
            out.append(f[:6])
    return out


def full_universe() -> list[str]:
    """legacy 缓存 ∪ 最新股票池 ∪ 季度抓取的 A 股名录(含少量已退市, 下不到数据会自动跳过)。

    legacy 缓存本身是不全的(缺 600036 这类), 所以必须并上名录, 否则 RPS 横截面有偏。
    """
    s = set(legacy_universe())
    p = os.path.join(C.OUT, "pool", "pool_codes_latest.txt")
    if os.path.exists(p):
        s |= {ln.strip()[:6] for ln in open(p, encoding="utf-8") if ln.strip()[:6].isdigit()}
    d = os.path.join(C.QUARTER_DIR, C.yyyymmdd(C.latest_report_day()), "listing.csv")
    if os.path.exists(d):
        try:
            L = pd.read_csv(d, dtype=str)
            ok = L[L["sec_type"].astype(str).str.contains("主板|科创板|创业板", na=False)]
            s |= {c[:6] for c in ok["code"].astype(str) if c[:6].isdigit()}
        except Exception as e:                                  # noqa: BLE001
            print(f"  ! listing.csv 解析失败: {e}")
    return sorted(s)


def download(tk_list: list[str], period=None, start=None) -> pd.DataFrame:
    """返回 MultiIndex columns (ticker, field)"""
    import yfinance as yf
    kw = dict(tickers=tk_list, interval="1d", group_by="ticker", threads=True,
              auto_adjust=True, progress=False)
    if start:
        kw["start"] = start
    else:
        kw["period"] = period or "6y"
    try:
        return yf.download(**kw)
    except Exception as e:                                  # noqa: BLE001
        print(f"    ! 批量下载失败({len(tk_list)}只): {type(e).__name__}: {e}")
        return pd.DataFrame()


def write_one(code: str, df: pd.DataFrame) -> int:
    d = df.dropna(subset=["Close"]).copy()
    if len(d) < 2:
        return 0
    if "Date" in d.columns:
        dates = pd.to_datetime(d["Date"].values).strftime("%Y-%m-%d")
    else:
        dates = pd.to_datetime(d.index).strftime("%Y-%m-%d")
    o = pd.DataFrame({"Date": dates,
                      "Open": d["Open"].astype(float).round(4).values,
                      "High": d["High"].astype(float).round(4).values,
                      "Low": d["Low"].astype(float).round(4).values,
                      "Close": d["Close"].astype(float).round(4).values,
                      "Volume": d["Volume"].fillna(0).astype("int64").values})
    o = o[o.Volume >= 0].drop_duplicates("Date").sort_values("Date").reset_index(drop=True)
    os.makedirs(C.HIST_DIR, exist_ok=True)
    p = os.path.join(C.HIST_DIR, f"{code}.csv")
    tmp = p + ".tmp"
    o.to_csv(tmp, index=False, encoding="utf-8-sig")
    os.replace(tmp, p)
    return len(o)


def slice_ticker(big: pd.DataFrame, tk: str):
    if big.empty or tk not in big.columns.get_level_values(0):
        return None
    x = big[tk].copy()
    if isinstance(x.columns, pd.MultiIndex):
        x.columns = [c[0] if isinstance(c, tuple) else c for c in x.columns]
    keep = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in x.columns]
    return x[keep]


def run_batch(codes: list[str], period: str, chunk: int, mode: str,
              workers_sleep: float, verbose_every: int = 500) -> dict:
    done = failed = empty = 0
    t0 = time.time()
    re_full = []
    for i in range(0, len(codes), chunk):
        part = codes[i:i + chunk]
        tks = [tick(c) for c in part]
        if mode == "update":
            start = (pd.Timestamp.now() - pd.Timedelta(days=45)).strftime("%Y-%m-%d")
            big = download(tks, start=start)
        else:
            big = download(tks, period=period)
        for c, tk in zip(part, tks):
            x = slice_ticker(big, tk)
            if x is None or x.dropna(subset=["Close"]).empty:
                if mode == "update":
                    re_full.append(c)
                else:
                    empty += 1
                continue
            path = os.path.join(C.HIST_DIR, f"{c}.csv")
            if mode == "update" and os.path.exists(path):
                old = pd.read_csv(path)
                if old.empty:
                    re_full.append(c)
                    continue
                oc = old.set_index("Date")["Close"].astype(float)
                nx = x["Close"].astype(float).dropna()
                nx.index = pd.to_datetime(nx.index).strftime("%Y-%m-%d")
                ov = [d for d in nx.index if d in oc.index]
                if len(ov) < 5:
                    re_full.append(c)          # 重叠太少, 无法判断漂移 => 保守整段重下
                    continue
                ratio = np.array([nx[d] / oc[d] for d in ov], dtype=float)
                if np.nanmax(np.abs(ratio - 1.0)) > DRIFT:
                    re_full.append(c)          # 期间除权, 全序列重下
                    continue
                merged = pd.concat([old[old.Date < min(ov)],
                                    pd.DataFrame({"Date": nx.index,
                                                  "Open": x["Open"].values,
                                                  "High": x["High"].values,
                                                  "Low": x["Low"].values,
                                                  "Close": nx.values,
                                                  "Volume": x["Volume"].values})])
                n = write_one(c, merged.reset_index(drop=True))
            else:
                n = write_one(c, x)
            if n:
                done += 1
            else:
                empty += 1
        el = time.time() - t0
        if (i // chunk + 1) % 4 == 0 or i + chunk >= len(codes):
            r = (i + chunk) / el if el else 0
            print(f"  [{min(i+chunk, len(codes))}/{len(codes)}] ok={done} empty={empty} "
                  f"{el:.0f}s {r:.1f}只/s eta={max(0,(len(codes)-i-chunk))/max(r,.01)/60:.1f}min",
                  flush=True)
        if workers_sleep:
            time.sleep(workers_sleep)
    return {"done": done, "empty": empty, "need_full": re_full,
            "sec": round(time.time() - t0, 1)}


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--build", action="store_true")
    g.add_argument("--update", action="store_true")
    g.add_argument("--rebuild", action="store_true")
    ap.add_argument("--codes", help="逗号分隔")
    ap.add_argument("--codes-file")
    ap.add_argument("--period", default="6y")
    ap.add_argument("--chunk", type=int, default=100)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--universe", default="full",
                    choices=["full", "legacy", "pool"], help="full=名录∪缓存, 修正 legacy 缺票")
    ap.add_argument("--sleep", type=float, default=1.0, help="每批之间歇口, 防 Yahoo 限流")
    a = ap.parse_args()
    os.makedirs(C.HIST_DIR, exist_ok=True)

    if a.codes:
        uni = [c.strip().zfill(6) for c in a.codes.split(",") if c.strip()]
    elif a.codes_file:
        uni = [ln.strip()[:6] for ln in open(a.codes_file, encoding="utf-8") if ln.strip()[:6].isdigit()]
    elif a.universe == "pool":
        uni = [c for c in full_universe()
               if os.path.exists(os.path.join(C.OUT, "pool", "pool_codes_latest.txt"))]
        pp = os.path.join(C.OUT, "pool", "pool_codes_latest.txt")
        uni = sorted({ln.strip()[:6] for ln in open(pp, encoding="utf-8") if ln.strip()[:6].isdigit()})
    elif a.universe == "legacy":
        uni = legacy_universe()
    else:
        uni = full_universe()
    have = {f[:-4] for f in os.listdir(C.HIST_DIR) if f.endswith(".csv")}
    mode = "update" if a.update else "build"
    todo = uni if (a.rebuild or a.update) else [c for c in uni if c not in have]
    if a.limit:
        todo = todo[:a.limit]
    print(f"universe={len(uni)} todo={len(todo)} mode={mode} period={a.period} chunk={a.chunk}")

    res = run_batch(todo, a.period, a.chunk, mode, a.sleep)
    print(f"首轮: {res}")

    # update 模式下把"疑似除权/缺失"的票整段重下
    if mode == "update" and res["need_full"]:
        print(f"除权/缺失需整段重下 {len(res['need_full'])} 只")
        res2 = run_batch(res["need_full"], a.period, a.chunk, "build", a.sleep)
        print(f"补下: {res2}")
        res["refull"] = res2

    with open(os.path.join(C.DATA, "history_status.json"), "w", encoding="utf-8") as f:
        json.dump({"mode": mode, "period": a.period, "universe": len(uni), **res,
                   "at": time.strftime("%F %T")}, f, ensure_ascii=False, indent=2)
    print(f"完成 ok={res['done']} empty={res['empty']} 用时 {res['sec']}s")


if __name__ == "__main__":
    main()
