#!/usr/bin/env python3
"""Generate sector_rps.html with inline JSON data, plus per-trade-date history files."""
import json
import os
from pathlib import Path

base = Path(__file__).parent.parent
docs = Path(os.environ.get("RPS_DOCS_DIR") or base / "docs")
data_dir = Path(os.environ.get("RPS_DATA_DIR") or Path(__file__).parent / "data")
history_dir = data_dir / "history"
data_file = data_dir / "sector_rps.json"

# 历史包只带页面真正读到的字段：整份快照 456KB/天，砍到这里约 120KB/天
UI_FIELDS = ["code", "name", "close", "RPS5", "RPS10", "RPS20", "RPS30", "RPS60", "RPS120",
             "RPS_avg", "RPS_5v10", "RPS_5v20", "ret_5", "ret_120",
             "mf_5", "mf_5_pct", "MF5_rank", "money_sig"]
META_FIELDS = ["date", "session", "generated_at", "fund_asof", "kline_cover"]


def slim(payload):
    out = {k: payload.get(k) for k in META_FIELDS}
    out["sectors"] = [{k: s.get(k) for k in UI_FIELDS} for s in payload.get("sectors", [])]
    return out


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  ⚠️ 跳过读不动的快照 {path.name}: {exc}")
        return None


def collect_days():
    """每个交易日取一份快照，定版优先——盘中那根 K 线不完整。"""
    days = {}
    for path in sorted(history_dir.glob("sector_rps_*_*.json")):
        payload = load(path)
        if not payload or not payload.get("date"):
            continue
        cur = days.get(payload["date"])
        if cur is None or (cur[1].get("session") != "final" and payload.get("session") == "final"):
            days[payload["date"]] = (path, payload)
    live = load(data_file) if data_file.exists() else None
    if live and live.get("date") and live["date"] not in days:
        days[live["date"]] = (data_file, live)
    return days


with open(data_file, "r") as f:
    data = json.load(f)

js_data = json.dumps(data, ensure_ascii=False)

template_path = Path(__file__).parent / "sector_rps_template.html"
with open(template_path, "r", encoding="utf-8") as f:
    template = f.read()

html = template.replace("__JSON_DATA__", js_data)

docs.mkdir(parents=True, exist_ok=True)
with open(docs / "sector_rps.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"Written {docs / 'sector_rps.html'} ({len(html)} bytes)")

js_content = f"var SECTOR_RPS_DATA = {js_data};"
with open(docs / "sector_rps_data.js", "w", encoding="utf-8") as f:
    f.write(js_content)
print(f"Written {docs / 'sector_rps_data.js'} ({len(js_content)} bytes)")

# ─── 历史回看：每日一个 js，下拉列表按需加载，避免把全年数据塞进首屏 ───
hist_dir = docs / "rps_history"
hist_dir.mkdir(parents=True, exist_ok=True)
days = collect_days()
index = []
total_kb = 0
for date in sorted(days, reverse=True):
    _, payload = days[date]
    day = slim(payload)
    body = f"window.SECTOR_RPS_DAY = {json.dumps(day, ensure_ascii=False, separators=(',', ':'))};"
    (hist_dir / f"{date}.js").write_text(body, encoding="utf-8")
    total_kb += len(body) // 1024
    sectors = day["sectors"]
    index.append({
        "date": date,
        "session": day.get("session"),
        "cover": day.get("kline_cover"),
        "money": sum(1 for s in sectors if s.get("mf_5_pct") is not None),
        "boards": len(sectors),
    })

dates_js = "window.SECTOR_RPS_DATES = " + json.dumps(index, ensure_ascii=False, separators=(',', ':')) + ";"
(hist_dir / "dates.js").write_text(dates_js, encoding="utf-8")
print(f"Written {hist_dir}/  ({len(index)} 个交易日, 合计 {total_kb} KB)")
for item in index[:7]:
    print(f"    {item['date']} {item['session']} 板块{item['boards']} 资金{item['money']} 覆盖{item['cover']}")
