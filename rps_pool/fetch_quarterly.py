#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第一步 · 季度数据抓取

抓三张季度表, 落到 data/quarter/<报告期>/ :
  fund_hold.csv   东财"主力数据-基金持仓"       -> 基金持股占流通股比例
  north_hold.csv  东财 F10 前十大流通股东 北向席位 -> 北向持股市值 (近似口径)
  listing.csv     东财 F10 公司基本资料          -> 上市日期 / 证券类型
  meta.json       抓取时间、来源、行数

用法:
  python3 fetch_quarterly.py                 # 自动取最近已披露完的季度
  python3 fetch_quarterly.py --date 20260930
"""
import argparse, json, os, sys, time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import emhttp as H

DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"
ZLSJ = "https://data.eastmoney.com/dataapi/zlsj/list"
REF = "https://data.eastmoney.com/"


def dcb(page_size=500, max_pages=400, sleep=0.12, **kw):
    """datacenter-web 报表分页拉全表 -> list[dict]"""
    rows, page = [], 1
    while page <= max_pages:
        p = dict(kw); p.update({"pageSize": str(page_size), "pageNumber": str(page),
                                "source": "WEB", "client": "WEB"})
        j = H.get(DC, params=p, referer=REF, timeout=30)
        if not j.get("success"):
            if page == 1:
                raise RuntimeError(f"{kw.get('reportName')} -> {j.get('message')}")
            break
        res = j.get("result") or {}
        d = res.get("data") or []
        if not d:
            break
        rows.extend(d)
        pages = res.get("pages") or 1
        if page >= pages:
            break
        page += 1
        time.sleep(sleep)
    return rows


def zlsj_pages(report: str, typ: str = "1", page_size: int = 500, sleep: float = 0.15):
    """东财 主力数据(基金/QFII/社保...) 持仓, 按报告期分页"""
    rows, page = [], 1
    while True:
        p = {"date": report, "type": typ, "zjc": "0", "sortField": "HOLD_VALUE", "sortDirec": "1",
             "pageNum": str(page), "pageSize": str(page_size), "p": str(page), "pageNo": str(page)}
        j = H.get(ZLSJ, params=p, referer="https://data.eastmoney.com/zlsj/", timeout=30)
        d = j.get("data") or []
        if not d:
            break
        rows.extend(d)
        pages = j.get("pages") or 1
        if page >= pages:
            break
        page += 1
        time.sleep(sleep)
    return rows


# ─────────────────────────────────────────────────────────
def fetch_fund_hold(rid: str) -> list[dict]:
    raw = zlsj_pages(rid, "1")
    out = []
    for r in raw:
        ratio = r.get("FREESHARES_RATIO")          # 基金持股 / 流通股 %
        ts = r.get("TOTAL_SHARES")                 # 基金合计持股数
        if ratio is None or ts is None:
            continue
        cap = ts / (ratio / 100.0) if ratio else None   # 反推流通股本(股)
        out.append({"code": str(r.get("SECURITY_CODE", "")).zfill(6),
                    "name": r.get("SECURITY_NAME_ABBR"),
                    "report_date": (r.get("REPORT_DATE") or "")[:10],
                    "fund_hold_shares": float(ts),
                    "fund_hold_value": float(r.get("HOLD_VALUE") or 0),
                    "fund_ratio_float": float(ratio),
                    "fund_ratio_total": float(r.get("TOTALSHARES_RATIO") or 0),
                    "fund_num": int(r.get("HOULD_NUM") or 0),
                    "float_shares_calc": cap})
    return out


def fetch_north_hold(rid: str) -> list[dict]:
    """前十大流通股东中的北向席位合计 (近似口径)。"""
    flt = f"(END_DATE='{rid}')"
    raw = dcb(reportName="RPT_F10_EH_FREEHOLDERS", filter=flt,
              sortColumns="SECURITY_CODE", sortTypes="1",
              columns="SECURITY_CODE,SECURITY_NAME_ABBR,END_DATE,HOLDER_NAME,"
                      "HOLD_NUM,HOLDER_MARKET_CAP,FREE_HOLDNUM_RATIO,HOLDER_RANK,SHARES_TYPE")
    agg, names = {}, {}
    for r in raw:
        hn = str(r.get("HOLDER_NAME") or "")
        if any(x in hn for x in C.POOL["north_excludes"]):
            continue
        if not any(k in hn for k in C.POOL["north_keys"]):
            continue
        code = str(r.get("SECURITY_CODE") or "").zfill(6)
        a = agg.setdefault(code, {"code": code, "name": r.get("SECURITY_NAME_ABBR"),
                                  "report_date": (r.get("END_DATE") or "")[:10],
                                  "north_shares": 0.0, "north_value": 0.0,
                                  "north_ratio_float": 0.0, "north_rank": 99})
        a["north_shares"] += float(r.get("HOLD_NUM") or 0)
        a["north_value"] += float(r.get("HOLDER_MARKET_CAP") or 0)
        a["north_ratio_float"] += float(r.get("FREE_HOLDNUM_RATIO") or 0)
        a["north_rank"] = min(a["north_rank"], int(r.get("HOLDER_RANK") or 99))
        names[hn] = names.get(hn, 0) + 1
    print(f"    命中席位: {sorted(names.items(), key=lambda x: -x[1])[:8]}")
    # 席位披露缺失市值时, 用 持股数 反推(调用方会用最新收盘价补齐)
    for a in agg.values():
        if a["north_value"] == 0 and a["north_shares"] > 0:
            a["north_value"] = None
    return sorted(agg.values(), key=lambda x: x["code"])


def fetch_listing() -> list[dict]:
    raw = dcb(reportName="RPT_F10_BASIC_ORGINFO",
              filter='(SECURITY_TYPE_CODE="058001001")',
              sortColumns="SECURITY_CODE", sortTypes="1",
              columns="SECURITY_CODE,SECURITY_NAME_ABBR,LISTING_DATE,SECURITY_TYPE,"
                      "TRADE_MARKET_TYPE,ORG_CODE")
    seen, out = set(), []
    for r in raw:
        code = str(r.get("SECURITY_CODE") or "").zfill(6)
        if code in seen:
            continue
        seen.add(code)
        ld = (r.get("LISTING_DATE") or "")[:10]
        out.append({"code": code, "name": r.get("SECURITY_NAME_ABBR"), "list_date": ld or None,
                    "sec_type": r.get("SECURITY_TYPE")})
    return out


def write_csv(path: str, rows: list[dict]) -> None:
    import csv
    if not rows:
        open(path, "w").close()
        return
    cols = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="报告期 YYYYMMDD, 默认最近已披露季度")
    ap.add_argument("--only", choices=["fund", "north", "listing"])
    a = ap.parse_args()

    rd = date(int(a.date[:4]), int(a.date[4:6]), int(a.date[6:])) if a.date else C.latest_report_day()
    rid = rd.strftime("%Y-%m-%d")
    d = os.path.join(C.QUARTER_DIR, C.yyyymmdd(rd))
    os.makedirs(d, exist_ok=True)
    print(f"报告期 = {rid}   ->  {d}")

    t0, meta = time.time(), {"report_date": rid, "fetched_at": time.strftime("%F %T")}
    jobs = [("fund_hold.csv", "基金持股", lambda: fetch_fund_hold(rid)),
            ("north_hold.csv", "北向席位(十大流通股东口径)", lambda: fetch_north_hold(rid)),
            ("listing.csv", "上市日期", fetch_listing)]
    for fn, label, f in jobs:
        if a.only and a.only != fn.split("_")[0]:
            continue
        if os.path.exists(os.path.join(d, fn)):
            print(f"  · {label}: 已存在, 跳过 (删文件可重抓)")
            meta[label] = "cached"
            continue
        s = time.time()
        try:
            rows = f()
        except Exception as e:                                    # noqa: BLE001
            print(f"  ✗ {label} 失败: {type(e).__name__}: {e}")
            meta[label] = f"ERROR {e}"
            continue
        write_csv(os.path.join(d, fn), rows)
        meta[label] = {"rows": len(rows), "sec": round(time.time() - s, 1)}
        print(f"  ✓ {label}: {len(rows)} 行, {time.time()-s:.1f}s")

    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"完成, 总耗时 {time.time()-t0:.1f}s")
    print("下一步: python3 build_pool.py")


if __name__ == "__main__":
    main()
