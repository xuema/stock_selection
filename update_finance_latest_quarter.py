#!/usr/bin/env python3
"""
把 Excel 里的财务数据刷到最新已披露报告期（营收增长/净利同比增长/销售毛利率/净资产收益率/资产负债率）。

数据源: 东财 datacenter 报表接口（akshare），两个接口各几秒返回全市场。
替代 1_update_finiance_data_quartly.py 的浏览器逐股抓取（4600 只 × 5 页 ≈ 25 小时）。

写入 final_rankings_with_details_latest.xlsx，列位置与原文件保持一致，
并把报告期写进原本空白的 D 列，让文件自己声明数据口径。

用法:
    python3 update_finance_latest_quarter.py              # 自动选最新已披露报告期
    python3 update_finance_latest_quarter.py --period 20260630
    python3 update_finance_latest_quarter.py --dry-run
"""

import os
import re
import sys
import warnings
import argparse
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(BASE, "final_rankings_with_details_latest.xlsx")
LEGACY = os.path.join(BASE, "final_rankings_with_details_Q1.xlsx")

# ── 列位置 (0-indexed, 与原文件一致, 改动会破坏所有下游脚本) ──
COL_CODE = 0      # A 代码
COL_NAME = 1      # B 名称
COL_PERIOD = 3    # D 报告期 (原为空白列)
COL_REVENUE = 4   # E 营收增长
COL_PROFIT = 5    # F 净利同比增长
COL_GROSS = 6     # G 销售毛利率
COL_ROE = 7       # H 净资产收益率
COL_DEBT = 8      # I 资产负债率

MIN_ROWS = 3000   # 某报告期至少这么多票披露，才算可用

# Excel 列 ← 接口列
FIELDS = [
    ("营收", COL_REVENUE, "营业总收入-同比增长"),
    ("净利", COL_PROFIT,  "净利润-同比增长"),
    ("毛利", COL_GROSS,   "销售毛利率"),
    ("ROE",  COL_ROE,     "净资产收益率"),
]


def _quiet_fn(fn, *a, **kw):
    """akshare 内部 tqdm 走 stderr，两个流都要压掉才能拿到干净输出"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out, err = sys.stdout, sys.stderr
        devnull = open(os.devnull, "w")
        sys.stdout = sys.stderr = devnull
        try:
            return fn(*a, **kw)
        finally:
            sys.stdout, sys.stderr = out, err
            devnull.close()


def fetch(fn, *a, **kw):
    """接口翻页偶发失败，重试 3 次"""
    last = None
    for _ in range(3):
        try:
            return _quiet_fn(fn, *a, **kw)
        except Exception as e:
            last = e
    raise last


def _yjbb(period):
    import akshare as ak
    return fetch(ak.stock_yjbb_em, date=period)


def _zcfz(period):
    import akshare as ak
    return fetch(ak.stock_zcfz_em, date=period)


def candidate_periods(today):
    out = []
    for y in range(today.year - 3, today.year + 1):
        for m, d in [(3, 31), (6, 30), (9, 30), (12, 31)]:
            q = date(y, m, d)
            if q <= today:
                out.append(q)
    return sorted(out, reverse=True)


def pick_period(explicit, min_rows):
    """返回 (报告期, 已取到的业绩表)，避免下面再取一次"""
    if explicit:
        return explicit, None
    print("🔎 探测最新已披露报告期")
    for q in candidate_periods(date.today()):
        p = q.strftime("%Y%m%d")
        try:
            df = _yjbb(p)
        except Exception as e:
            print(f"  {p}: 取数失败 {type(e).__name__}")
            continue
        n = len(df)
        print(f"  {p}: 业绩报表 {n} 行 " + ("→ 采用" if n >= min_rows else "→ 披露不足，回退上一期"))
        if n >= min_rows:
            return p, df
    raise SystemExit("❌ 没有任何报告期有足够披露数据")


def pct(v):
    """接口的数值 → 原文件的 '12.34%' 字符串口径"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "-"
    if f != f:
        return "-"
    return f"{f:.2f}%"


def to_map(df, api_col):
    """按列取值，不用 itertuples（接口列名带 '-'，会被重命名成 _1/_2）"""
    if api_col not in df.columns:
        raise KeyError(f"接口缺少列 {api_col}，实际列: {list(df.columns)}")
    # 代码可能是 874949 / "600519" / "600519.0"，只取前 6 位数字
    codes = df["股票代码"].astype(str).str.extract(r"(\d{6})")[0]
    return dict(zip(codes, (pct(v) for v in df[api_col])))


def build_maps(period, yj=None):
    if yj is None:
        yj = _yjbb(period)
    print(f"📊 业绩报表 {period}: {len(yj)} 行")
    maps = {name: to_map(yj, api) for name, _, api in FIELDS}

    try:
        zz = _zcfz(period)
        print(f"📊 资产负债报表 {period}: {len(zz)} 行")
        maps["负债"] = to_map(zz, "资产负债率")
    except Exception as e:
        print(f"⚠️  资产负债率取数失败({type(e).__name__})，该列保留原值")
        maps["负债"] = {}
    return maps


def apply_to_workbook(period, maps, dry):
    from openpyxl import load_workbook
    src = XLSX if os.path.exists(XLSX) else LEGACY
    if not os.path.exists(src):
        raise SystemExit(f"❌ 找不到 Excel: {XLSX} 或 {LEGACY}")
    print(f"\n📂 读入 {os.path.basename(src)}")

    wb = load_workbook(src)
    ws = wb.active
    pretty = f"{period[:4]}-{period[4:6]}-{period[6:]}"
    all_cols = FIELDS + [("负债", COL_DEBT, "资产负债率")]

    updated = {name: 0 for name, _, _ in all_cols}
    unmatched = []
    total = 0
    for r in range(2, ws.max_row + 1):
        raw = ws.cell(row=r, column=COL_CODE + 1).value
        if raw is None:
            continue
        m = re.search(r"\d+", str(raw))
        if not m:
            continue
        code = m.group(0).zfill(6)
        total += 1
        touched = False
        for name, col, _api in all_cols:
            val = maps[name].get(code)
            if val is None or val == "-":
                continue          # 接口没这只票或没这个字段 → 保留原值，不写横线
            if not dry:
                ws.cell(row=r, column=col + 1, value=val)
                ws.cell(row=r, column=COL_PERIOD + 1, value=pretty)
            updated[name] += 1
            touched = True
        if not touched:
            unmatched.append(code)

    print(f"\n   表内股票 {total} 只")
    for name, col, api in all_cols:
        print(f"   {name:<4}(列{chr(65+col)}) 更新 {updated[name]:>4} 只  覆盖 {updated[name]/max(1,total)*100:5.1f}%")
    print(f"   完全没匹配上的 {len(unmatched)} 只" + (f": {','.join(unmatched[:8])}…" if unmatched else ""))

    if dry:
        print("\n🔍 dry-run，未保存")
        return None
    if not dry:
        ws.cell(row=1, column=COL_PERIOD + 1, value="报告期")
    wb.save(XLSX)
    print(f"💾 已保存 {XLSX}")
    return XLSX


def main():
    ap = argparse.ArgumentParser(description="刷新财务数据到最新已披露报告期")
    ap.add_argument("--period", help="强制指定报告期 YYYYMMDD，默认自动选最新")
    ap.add_argument("--min-rows", type=int, default=MIN_ROWS)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    period, yj = pick_period(args.period, args.min_rows)
    maps = build_maps(period, yj)
    out = apply_to_workbook(period, maps, args.dry_run)
    print(f"\n✅ 报告期 {period}" + ("" if not out else f" → {os.path.basename(out)}"))
    print("   下一步: python3 export_fundamentals_cache.py   (刷新选股用的 JSON 缓存)")


if __name__ == "__main__":
    main()
