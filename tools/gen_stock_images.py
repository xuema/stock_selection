#!/usr/bin/env python3
"""生成策略选股图片网格，每个策略一张 PNG，并同时生成 *_latest.png 软链接。"""

import json, os, sys
from pathlib import Path
from datetime import datetime
import subprocess

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "strategy"

STRATEGY_CONFIGS = [
    {"prefix": "screen_rsi_golden_cross", "title": "RSI金叉"},
    {"prefix": "screen_signals", "title": "EXPMA+多因子"},
    {"prefix": "screen_ma_pullback", "title": "MA回调", "enabled": False},
    {"prefix": "screen_super_top_bottom_buy", "title": "超级顶底买入"},
    {"prefix": "screen_super_top_bottom_sell", "title": "超级顶底卖出"},
    {"prefix": "screen_rsi_stb_resonance", "title": "RSI共振"},
]


def find_latest_json(prefix):
    files = list(OUTPUT_DIR.glob(f"{prefix}_*.json"))
    files = [f for f in files if "_latest" not in f.name]
    if not files:
        return None
    return max(files, key=lambda f: f.name)


def load_stocks(json_path):
    with open(json_path, "r") as f:
        data = json.load(f)
    return data.get("stocks", data if isinstance(data, list) else [])


def generate_image(prefix, title, json_path):
    stocks = load_stocks(json_path)
    if not stocks:
        return None

    date_str = json_path.stem.split("_")[-1]
    codes = [s["ticker"] for s in stocks[:200]]
    count = len(codes)

    cols = 6
    rows = (count + cols - 1) // cols + 1
    cell_w, cell_h = 110, 34
    margin_x, margin_y = 24, 24
    header_h = 48
    img_w = cols * cell_w + margin_x * 2
    img_h = header_h + rows * cell_h + margin_y * 2

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body{{background:#1a1a2e;color:#eee;font-family:'SF Mono','Fira Code',monospace;margin:0;padding:{margin_y}px {margin_x}px 0}}
.h1{{font-size:22px;font-weight:700;text-align:center;padding:12px 0 6px;border-bottom:2px solid #e94560;margin-bottom:6px}}
.h2{{font-size:14px;color:#999;text-align:center;margin-bottom:14px}}
.grid{{display:grid;grid-template-columns:repeat({cols},{cell_w}px);gap:6px 0;justify-content:center}}
.cell{{background:#16213e;border:1px solid #0f3460;border-radius:4px;padding:6px 10px;text-align:center;font-size:15px;letter-spacing:1px}}
</style></head><body>
<div class="h1">{title}</div>
<div class="h2">{date_str} | 共 {count} 只</div>
<div class="grid">
{''.join(f'<div class="cell">{c}</div>' for c in codes)}
</div></body></html>"""

    tmp_html = OUTPUT_DIR / f"_tmp_{prefix}.html"
    tmp_html.write_text(html, encoding="utf-8")

    today_short = datetime.now().strftime("%m%d")
    filename = f"{prefix}_{today_short}.png"
    out = OUTPUT_DIR / filename

    try:
        subprocess.run(
            ["wkhtmltoimage", "--width", str(img_w), "--height", str(img_h),
             "--background", "#1a1a2e", str(tmp_html), str(out)],
            capture_output=True, timeout=120,
        )
    except FileNotFoundError:
        img_w_px = 800; img_h_px = 600
        html_full = f"""<html><head><meta charset="utf-8">
<style>body{{background:#1a1a2e;color:#eee;font-family:monospace;padding:40px}}
h1{{font-size:24px;text-align:center;color:#e94560}}h2{{color:#888;text-align:center}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:8px;margin-top:20px}}
.cell{{background:#16213e;border:1px solid #0f3460;border-radius:6px;padding:8px 8px;text-align:center;font-size:14px}}</style></head>
<body><h1>{title}</h1><h2>{date_str} | 共{count}只</h2><div class="grid">
{''.join(f'<div class="cell">{c}</div>' for c in codes)}</div></html>"""
        tmp2 = OUTPUT_DIR / f"_tmp2_{prefix}.html"
        tmp2.write_text(html_full, encoding="utf-8")
        subprocess.run(
            ["wkhtmltoimage", "--width", str(img_w_px),
             "--background", "#1a1a2e", str(tmp2), str(out)],
            capture_output=True, timeout=120,
        )

    if out.exists() and out.stat().st_size > 0:
        return {"title": f"{title} {today_short}", "image": filename, "count": count, "base": prefix}
    return None


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    image_index = []
    skipped = []

    for cfg in STRATEGY_CONFIGS:
        prefix = cfg["prefix"]
        title = cfg["title"]
        if cfg.get("enabled", True) is False:
            skipped.append(f"{title}（已禁用）")
            continue
        json_path = OUTPUT_DIR / f"{prefix}_latest.json"
        if not json_path.exists():
            json_path = find_latest_json(prefix)
        if not json_path:
            skipped.append(title)
            continue

        print(f"🖼️ 生成: {title}")
        result = generate_image(prefix, title, json_path)
        if result:
            image_index.append(result)
            # 创建 latest 图片副本（软链无法推送到 GitHub Pages）
            latest_link = OUTPUT_DIR / f"{prefix}_latest.png"
            target_file = OUTPUT_DIR / result["image"]
            if target_file.exists():
                import shutil
                shutil.copy2(target_file, latest_link)
                print(f"   ✅ {result['image']} + {latest_link.name}")
        else:
            skipped.append(title)
            print(f"   ⚠️ {title} 无数据或生成失败")

    index_path = OUTPUT_DIR / "image_index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(image_index, f, ensure_ascii=False, indent=2)
    print(f"\n📋 image_index.json → {len(image_index)} 张图片")
    if skipped:
        print(f"⚠️ 跳过: {', '.join(skipped)}")


if __name__ == "__main__":
    main()
