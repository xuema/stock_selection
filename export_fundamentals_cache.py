#!/usr/bin/env python3
"""
从财务 Excel 文件中提取股票的净利同比增长和总市值数据，生成 JSON 缓存。

数据口径: 净利同比增长取 Excel 里的最新已披露报告期 (D 列"报告期")，
          总市值来自同一份文件，需要 update_finance_latest_quarter.py 之外
          再刷估值才有更新。
刷新链路: update_finance_latest_quarter.py → 本脚本 → strategy/*.py

输出: stock_fundamentals_cache.json
用法: python3 export_fundamentals_cache.py
"""
import os
import re
import json
from openpyxl import load_workbook

BASE = os.path.dirname(os.path.abspath(__file__))
EXCEL_FILE = os.path.join(BASE, "final_rankings_with_details_latest.xlsx")
CACHE_FILE = os.path.join(BASE, "stock_fundamentals_cache.json")

def export():
    if not os.path.exists(EXCEL_FILE):
        print(f"❌ Excel 不存在: {EXCEL_FILE}")
        return

    print("读取 Excel...")
    wb = load_workbook(EXCEL_FILE, read_only=True, data_only=True)  # data_only=True 读值不读公式
    ws = wb.active

    COL_CODE = 0       # A 代码
    COL_PERIOD = 3     # D 报告期
    COL_JLZZ = 5       # F 净利同比增长
    COL_MCAP = 13      # N 总市值

    cache = {}
    period = None
    # read_only 模式下 ws.cell() 每次都从头扫表，只能一次顺序遍历
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or row[COL_CODE] is None:
            continue
        m = re.search(r"\d{6}", str(row[COL_CODE]))
        if not m:
            continue
        code = m.group(0)
        if period is None and len(row) > COL_PERIOD and row[COL_PERIOD]:
            period = str(row[COL_PERIOD])[:10]

        # 净利同比增长
        jl_growth = None
        jl_raw = row[COL_JLZZ] if len(row) > COL_JLZZ else None
        if jl_raw and jl_raw != '-':
            try:
                jl_growth = float(str(jl_raw).replace('%', ''))
            except (ValueError, TypeError):
                pass

        # 总市值 (格式如 "68亿")
        mcap_yi = None
        mcap_raw = row[COL_MCAP] if len(row) > COL_MCAP else None
        if mcap_raw and mcap_raw != '-':
            try:
                s = str(mcap_raw).lower()
                if '亿' in s:
                    mcap_yi = float(s.replace('亿', '').strip())
                elif '万' in s:
                    mcap_yi = float(s.replace('万', '').strip()) / 10000
            except (ValueError, TypeError):
                pass

        if jl_growth is not None or mcap_yi is not None:
            cache[code] = {}
            if jl_growth is not None:
                cache[code]['jl_growth_pct'] = round(jl_growth, 2)
            if mcap_yi is not None:
                cache[code]['mcap_yi'] = mcap_yi

    wb.close()

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    # 统计
    jl_vals = [v['jl_growth_pct'] for v in cache.values() if 'jl_growth_pct' in v]
    mc_vals = [v['mcap_yi'] for v in cache.values() if 'mcap_yi' in v]
    pos = sum(1 for v in jl_vals if v > 0) if jl_vals else 0

    print(f"💾 已保存 {len(cache)} 只")
    print(f"   净利同比增长口径: 报告期 {period or '未知(旧文件无D列)'}")
    print(f"   净利同比正增长: {pos} 只")
    if mc_vals:
        mc_sorted = sorted(mc_vals)
        print(f"   市值中位数: {mc_sorted[len(mc_sorted)//2]:.1f}亿")

if __name__ == "__main__":
    export()
