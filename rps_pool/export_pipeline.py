#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 rps_pool 的每日筛选结果导出成 daily_screen.sh 流水线的 JSON 约定。

流水线约定(见 output/strategy/index.html 与 tools/gen_stock_images.py):
  output/strategy/screen_<prefix>_latest.json     最新一次
  output/strategy/screen_<prefix>_YYYY-MM-DD.json 按日留档
  JSON 形如 {strategy, strategy_name, screen_date, total_scanned, total_matched, stocks:[...]}
  stocks[].ticker 用 6 位代码, 前端据此查 stock_names.json

产出两个 prefix:
  screen_rps_pool_dual  策略1/策略2 入选(合并, 用 strat 字段区分)
  screen_rps_pool_sell  周线RSI死叉卖出提示

用法:
  python3 export_pipeline.py                       # 用 out/screen 最新一天
  python3 export_pipeline.py --date 20261123 --output-dir ../output/strategy
"""
import argparse, glob, json, os, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE_DIR = os.path.join(C.REPO, "output", "strategy")


def latest_screen_dir(date: str | None = None) -> str:
    ds = sorted(os.path.basename(p) for p in glob.glob(os.path.join(C.OUT, "screen", "*"))
                if os.path.isdir(p))
    if not ds:
        raise SystemExit("out/screen 为空, 先跑 screen_daily.py")
    want = date or ds[-1]
    d = os.path.join(C.OUT, "screen", want.replace("-", ""))
    if not os.path.isdir(d):
        raise SystemExit(f"没有 {d}")
    return d


def _r(x, n=3):
    return None if x is None else round(float(x), n)


def build_dash(data: dict) -> list[dict]:
    """策略1/策略2 合并成一张表: strat = 'S1' / 'S2' / 'S1+S2', 两边都入选的排最前"""
    def key(r):
        return r["code"]
    by = {}
    for tag, rows in (("S1", data.get("s1", [])), ("S2", data.get("s2", []))):
        for r in rows:
            e = by.setdefault(r["code"], {"ticker": r["code"], "name": r.get("name", ""),
                                          "date": data["date"], "close": _r(r.get("close"), 2),
                                          "rps_120": _r(r.get("rps120"), 1),
                                          "rps_250": _r(r.get("rps250"), 1),
                                          "rps_sum": _r((r.get("rps120") or 0) + (r.get("rps250") or 0), 1),
                                          "newhigh_pct": _r(r.get("newhigh"), 4),
                                          "wk_rsi1": _r(r.get("wrsi1"), 1),
                                          "wk_rsi2": _r(r.get("wrsi2"), 1),
                                          "gold_days": r.get("golddays"),
                                          "turnover_pct": _r(r.get("turnover"), 2),
                                          "fund_pct": _r(r.get("fund"), 2),
                                          "north_yi": _r(r.get("north_yi"), 2),
                                          "strat": [], "buy_price": _r(r.get("close"), 2)})
            e["strat"].append(tag)
    out = []
    for e in by.values():
        e["strat"] = "+".join(sorted(set(e["strat"])))
        e["both"] = e["strat"] == "S1+S2"
        out.append(e)
    out.sort(key=lambda x: (not x["both"], x["strat"], -(x["rps_sum"] or 0)))
    for x in out:
        x.pop("both", None)
    return out


def build_sell(data: dict) -> list[dict]:
    return [{"ticker": r["code"], "name": r.get("name", ""), "date": data["date"],
             "close": _r(r.get("close"), 2), "dead_days": r.get("days"),
             "pick_age": r.get("pick_age"), "wk_rsi1": _r(r.get("wrsi1"), 1),
             "wk_rsi2": _r(r.get("wrsi2"), 1), "rps_sum": _r(r.get("rps_sum"), 1),
             "was": "+".join([t for t, ok in (("S1", r.get("was_s1")), ("S2", r.get("was_s2"))) if ok]) or "-"}
            for r in data.get("sell", [])]


def write(doc: dict, prefix: str, outdir: str) -> str:
    os.makedirs(outdir, exist_ok=True)
    dated = os.path.join(outdir, f"screen_{prefix}_{doc['screen_date']}.json")
    latest = os.path.join(outdir, f"screen_{prefix}_latest.json")
    txt = json.dumps(doc, ensure_ascii=False, indent=2)
    open(dated, "w", encoding="utf-8").write(txt)
    open(latest, "w", encoding="utf-8").write(txt)
    return dated


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="out/screen 下的日期, 默认最新")
    ap.add_argument("--output-dir", default=PIPE_DIR)
    ap.add_argument("--no-archive", action="store_true", help="只写 latest, 不写按日文件")
    a = ap.parse_args()

    sdir = latest_screen_dir(a.date)
    data = json.load(open(os.path.join(sdir, "dashboard.json"), encoding="utf-8"))
    dash, sell = build_dash(data), build_sell(data)

    meta = {"total_scanned": data.get("pool_n"), "screen_date": data["date"],
            "rps_passed": data.get("sxhcg_n"),
            "pool_rule": "最新季报 基金持股/流通股 > %.1f%% + 北向席位持股市值 > %.0f 万 + 上市满 %d 天"
            % (C.POOL["fund_ratio_min"], C.POOL["north_cap_min"] / 1e4, C.POOL["min_list_days"])}
    docs = [
        ("rps_pool_dual", {**meta, "strategy": "rps_pool_dual",
                           "strategy_name": "RPS池·双策略入选(S1=周线RSI确认 / S2=接近一年新高)",
                           "total_matched": len(dash), "stocks": dash}),
        ("rps_pool_sell", {**meta, "strategy": "rps_pool_sell",
                           "strategy_name": "RPS池·卖出提示(周线RSI死叉)",
                           "total_matched": len(sell), "stocks": sell}),
    ]
    n = 0
    for prefix, doc in docs:
        if a.no_archive:
            fp = os.path.join(a.output_dir, f"screen_{prefix}_latest.json")
            os.makedirs(a.output_dir, exist_ok=True)
            open(fp, "w", encoding="utf-8").write(json.dumps(doc, ensure_ascii=False, indent=2))
        else:
            fp = write(doc, prefix, a.output_dir)
        n += 1
        print(f"  {os.path.basename(fp)}  {doc['total_matched']} 条")
    print(f"导出 -> {a.output_dir}  (源 {sdir})")
    return n


if __name__ == "__main__":
    main()
