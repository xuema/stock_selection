#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""池/流通股本读取 —— screen_daily / backtest / bt_sweep 共用。

流通股本(用于 SXHCG5 换手率)来自东财"主力数据-基金持仓":
  float_shares_calc = 基金合计持股数 / (基金持股占流通股比例/100)
它覆盖全部有基金持仓的票(约 3800 只), 不只是池内的 600 只, 这样 universe=all 的
对照回测也能真正执行换手率条件。
"""
import glob
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

POOL_CSV = os.path.join(C.OUT, "pool", "pool_latest.csv")


def load_pool(path: str | None = None) -> pd.DataFrame:
    p = path or POOL_CSV
    if not os.path.exists(p):
        raise SystemExit(f"股票池不存在({p}), 先跑 fetch_quarterly.py + build_pool.py")
    df = pd.read_csv(p, dtype={"code": str})
    df["code"] = df["code"].str.zfill(6)
    return df


def _from_fund_hold() -> dict[str, float]:
    out: dict[str, float] = {}
    for d in sorted(glob.glob(os.path.join(C.QUARTER_DIR, "*"))):
        fp = os.path.join(d, "fund_hold.csv")
        if not os.path.exists(fp):
            continue
        try:
            t = pd.read_csv(fp, dtype={"code": str}, usecols=["code", "float_shares_calc"])
        except Exception:                                        # noqa: BLE001
            continue
        t["code"] = t["code"].str.zfill(6)
        for c, v in zip(t["code"], pd.to_numeric(t["float_shares_calc"], errors="coerce")):
            if np.isfinite(v) and v > 1e7:                       # <1000万股 视为脏数据
                out[c] = float(v)
    return out


def float_shares(pool: pd.DataFrame | None = None) -> dict[str, float]:
    m = _from_fund_hold()
    if pool is None:
        pool = load_pool() if os.path.exists(POOL_CSV) else pd.DataFrame(columns=["code"])
    if len(pool) and "float_shares_calc" in pool.columns:
        for c, v in zip(pool["code"], pd.to_numeric(pool["float_shares_calc"], errors="coerce")):
            if np.isfinite(v) and v > 1e7:
                m[c] = float(v)                                  # 池内口径优先
    return m


if __name__ == "__main__":
    p = load_pool()
    m = float_shares(p)
    print(f"池 {len(p)} 只, 流通股本可用 {len(m)} 只")
