#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第一步 · 构建股票池

条件(全部满足):
  A. 最新季度 基金持股 / 流通股本 > 3%
  B. 最新季度 北向持股市值 > 3000 万元   (十大流通股东席位口径; 可 --no-north 关闭)
  C. 上市满 1 年
  D. 本机有日线数据(否则无法算指标)      可 --no-data 关闭

输出 out/pool/ :
  pool_<报告期>.csv   入选明细
  pool_latest.csv     同上一份的副本(每日脚本读它)
  pool_codes_latest.txt
  rejected_<报告期>.csv  落选原因审计

用法:
  python3 build_pool.py
  python3 build_pool.py --date 20260930 --no-north
"""
import argparse, glob, os, shutil, sys
from datetime import date, datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

POOL_OUT = os.path.join(C.OUT, "pool")


def qdir(rid: date) -> str:
    return os.path.join(C.QUARTER_DIR, C.yyyymmdd(rid))


def price_codes() -> set[str]:
    """有日线数据的代码 (优先 5y 缓存, 回退 legacy 缓存)"""
    for base in (C.HIST_DIR, C.LEGACY_DAILY):
        if os.path.isdir(base) and len(glob.glob(os.path.join(base, "*.csv"))) > 50:
            return {os.path.basename(p)[:-4] for p in glob.glob(os.path.join(base, "*.csv"))
                    if len(os.path.basename(p)) == 10}
    return set()


def build(rid: date, use_north=True, need_data=True, min_days=None, skip_st=True) -> pd.DataFrame:
    min_days = min_days if min_days is not None else C.POOL["min_list_days"]
    d = qdir(rid)
    f = pd.read_csv(os.path.join(d, "fund_hold.csv"), dtype={"code": str})
    f["code"] = f["code"].str.zfill(6)
    print(f"基金持股 全量 {len(f)} 只, 报告期 {f['report_date'].iloc[0] if len(f) else rid}")

    L = pd.read_csv(os.path.join(d, "listing.csv"), dtype={"code": str})
    L["code"] = L["code"].str.zfill(6)
    L = L.drop_duplicates("code")

    n = None
    if use_north:
        n = pd.read_csv(os.path.join(d, "north_hold.csv"), dtype={"code": str})
        n["code"] = n["code"].str.zfill(6)
        print(f"北向席位 覆盖 {len(n)} 只")

    # ── A: 基金持股 > 3% ──
    step = f[f["fund_ratio_float"] > C.POOL["fund_ratio_min"]].copy()
    print(f"  A 基金持股>{C.POOL['fund_ratio_min']}% : {len(step)}")

    # ── C: 上市满 1 年 ──
    step = step.merge(L[["code", "list_date"]], on="code", how="left")
    step["list_date"] = pd.to_datetime(step["list_date"], errors="coerce")
    cutoff = pd.Timestamp(datetime.now() - timedelta(days=min_days))
    ok_list = step[step["list_date"].notna() & (step["list_date"] <= cutoff)]
    print(f"  C 上市满{min_days}天 : {len(ok_list)}  "
          f"(无上市日期 {int(step['list_date'].isna().sum())})")
    step = ok_list.copy()

    if skip_st:
        bad = step["name"].astype(str).str.contains("ST|退", na=False)
        print(f"  剔除 ST/退市标记 : {int(bad.sum())}")
        step = step[~bad].copy()

    # ── B: 北向 > 3000万 ──
    if use_north:
        step = step.merge(n[["code", "north_shares", "north_value", "north_ratio_float"]],
                          on="code", how="left")
        before = len(step)
        step = step[step["north_value"].fillna(-1) > C.POOL["north_cap_min"]]
        print(f"  B 北向市值>{C.POOL['north_cap_min']/1e8:.2f}亿 : {len(step)}  "
              f"(十大股东口径未覆盖 {before - len(step)})")
    else:
        step["north_shares"], step["north_value"] = None, None

    # ── D: 本机有数据 ──
    if need_data:
        have = price_codes()
        if have:
            before = len(step)
            step = step[step["code"].isin(have)]
            print(f"  D 本机有日线 : {len(step)} (缺数据 {before - len(step)})")

    step = step.sort_values("fund_ratio_float", ascending=False).reset_index(drop=True)
    step.insert(0, "rank", range(1, len(step) + 1))
    step["report_date"] = rid.isoformat()
    step["built_at"] = datetime.now().strftime("%F %T")
    return step


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="报告期 YYYYMMDD, 默认最近已披露季度")
    ap.add_argument("--no-north", action="store_true", help="不启用北向条件")
    ap.add_argument("--no-data", action="store_true", help="不要求本机已有日线")
    ap.add_argument("--min-list-days", type=int)
    a = ap.parse_args()
    os.makedirs(POOL_OUT, exist_ok=True)

    rid = (date(int(a.date[:4]), int(a.date[4:6]), int(a.date[6:]))
           if a.date else C.latest_report_day())
    df = build(rid, use_north=not a.no_north, need_data=not a.no_data,
               min_days=a.min_list_days)
    if df.empty:
        print("!! 股票池为空, 检查上游抓取是否成功")
        return

    tag = C.yyyymmdd(rid)
    p1 = os.path.join(POOL_OUT, f"pool_{tag}.csv")
    df.to_csv(p1, index=False, encoding="utf-8-sig")
    p2 = os.path.join(POOL_OUT, "pool_latest.csv")
    shutil.copyfile(p1, p2)
    with open(os.path.join(POOL_OUT, "pool_codes_latest.txt"), "w") as f:
        f.write("\n".join(df["code"]) + "\n")

    # 审计: 基金持股表里落选的票, 标出是哪一条卡掉的
    f = pd.read_csv(os.path.join(qdir(rid), "fund_hold.csv"), dtype={"code": str})
    f["code"] = f["code"].str.zfill(6)
    L = pd.read_csv(os.path.join(qdir(rid), "listing.csv"), dtype={"code": str})
    L["code"] = L["code"].str.zfill(6)
    L = L.drop_duplicates("code")
    aud = f.merge(L[["code", "list_date"]], on="code", how="left")
    ld = pd.to_datetime(aud["list_date"], errors="coerce")
    aud["_A"] = aud["fund_ratio_float"] > C.POOL["fund_ratio_min"]
    aud["_C"] = ld.notna() & (ld <= pd.Timestamp.now() - pd.Timedelta(days=C.POOL["min_list_days"]))
    if not a.no_north:
        n = pd.read_csv(os.path.join(qdir(rid), "north_hold.csv"), dtype={"code": str})
        n["code"] = n["code"].str.zfill(6)
        aud = aud.merge(n[["code", "north_value"]], on="code", how="left")
        aud["_B"] = aud["north_value"].fillna(-1) > C.POOL["north_cap_min"]
    else:
        aud["_B"] = True
    aud["passed"] = aud["_A"] & aud["_B"] & aud["_C"]
    cols = [c for c in ["code", "name", "fund_ratio_float", "north_value", "list_date",
                        "_A", "_B", "_C", "passed"] if c in aud]
    aud.loc[~aud["passed"].astype(bool), cols].to_csv(
        os.path.join(POOL_OUT, f"rejected_{tag}.csv"), index=False, encoding="utf-8-sig")

    print(f"\n股票池 {len(df)} 只  ->  {p1}")
    print(f"           副本  ->  {p2}")
    print(f"        代码清单  ->  {os.path.join(POOL_OUT, 'pool_codes_latest.txt')}")
    print(df[["code", "name", "fund_ratio_float", "north_value", "list_date"]].head(15).to_string())


if __name__ == "__main__":
    main()
