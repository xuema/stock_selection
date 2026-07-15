#!/usr/bin/env python3
"""生成策略选股图片网格，每个策略一张 PNG，并同时生成 *_latest.png 副本。
使用 Pillow 纯 Python 生成，无需外部依赖。"""

import json, os, shutil
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "strategy"

STRATEGY_CONFIGS = [
    {"prefix": "screen_rsi_golden_cross", "title": "RSI金叉"},
    {"prefix": "screen_signals", "title": "EXPMA+多因子"},
    {"prefix": "screen_ma_pullback", "title": "MA回调", "enabled": False},
    {"prefix": "screen_super_top_bottom_buy", "title": "超级顶底买入"},
    {"prefix": "screen_super_top_bottom_sell", "title": "超级顶底卖出"},
    {"prefix": "screen_rsi_stb_resonance", "title": "RSI共振"},
]

# Colors (dark theme)
BG = (13, 17, 23)
CARD_BG = (22, 27, 34)
BORDER = (48, 54, 61)
TEXT = (230, 237, 243)
ACCENT = (88, 166, 255)

def load_stocks(json_path):
    with open(json_path, "r") as f:
        data = json.load(f)
    return data.get("stocks", data if isinstance(data, list) else [])

def get_font(size):
    for path in [
        "/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Microsoft/SimHei.ttf",
        "/System/Library/Fonts/STHeiti Light.ttc",
    ]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    try:
        return ImageFont.truetype("/Library/Fonts/Arial Unicode.ttf", size)
    except Exception:
        return ImageFont.load_default()

def generate_image(prefix, title, json_path):
    stocks = load_stocks(json_path)
    if not stocks:
        return None

    date_str = json_path.stem.split("_")[-1]
    # Remove year prefix if present (e.g., 2026-07-15 → 0715)
    if "-" in date_str:
        date_short = date_str.replace("-", "")[4:]
    else:
        date_short = date_str

    codes = [s["ticker"] for s in stocks[:200]]
    count = len(codes)

    cols = 6
    rows = (count + cols - 1) // cols
    remainder = count % cols
    if remainder:
        rows += 1

    cell_w, cell_h = 108, 32
    margin = 24
    header_h = 60
    img_w = cols * cell_w + margin * 2 + (cols - 1) * 4
    img_h = header_h + rows * (cell_h + 4) + margin * 2

    img = Image.new("RGB", (img_w, img_h), BG)
    draw = ImageDraw.Draw(img)

    # Fonts
    title_font = get_font(20)
    subtitle_font = get_font(13)
    cell_font = get_font(14)
    header_font = get_font(13)

    # Title
    title_text = f"{title}"
    title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
    tw = title_bbox[2] - title_bbox[0]
    draw.text(((img_w - tw) // 2, 14), title_text, fill=ACCENT, font=title_font)

    # Subtitle line: draw a subtle border under title, then subtitle
    sub_y = 40
    draw.line([(margin, sub_y), (img_w - margin, sub_y)], fill=BORDER, width=1)

    subtitle_text = f"{date_str}  |  共 {count} 只"
    sub_bbox = draw.textbbox((0, 0), subtitle_text, font=subtitle_font)
    sw = sub_bbox[2] - sub_bbox[0]
    draw.text(((img_w - sw) // 2, sub_y + 4), subtitle_text, fill=(139, 148, 158), font=subtitle_font)

    # Grid
    y_start = header_h + margin
    for i, code in enumerate(codes):
        col = i % cols
        row = i // cols
        x = margin + col * (cell_w + 4)
        y = y_start + row * (cell_h + 4)

        # Cell background
        draw.rounded_rectangle(
            [(x, y), (x + cell_w, y + cell_h)],
            radius=4,
            fill=CARD_BG,
            outline=BORDER,
        )

        # Code text center
        code_bbox = draw.textbbox((0, 0), code, font=cell_font)
        cw = code_bbox[2] - code_bbox[0]
        ch = code_bbox[3] - code_bbox[1]
        draw.text(
            (x + (cell_w - cw) // 2, y + (cell_h - ch) // 2 - cell_font.getmask(code).getbbox()[1] if hasattr(cell_font, 'getmask') else y + (cell_h - ch) // 2),
            code,
            fill=TEXT,
            font=cell_font,
        )

    # Save
    today_short = datetime.now().strftime("%m%d")
    filename = f"{prefix}_{today_short}.png"
    out = OUTPUT_DIR / filename
    img.save(out, "PNG")

    # Create latest copy
    latest = OUTPUT_DIR / f"{prefix}_latest.png"
    shutil.copy2(out, latest)

    return {"title": f"{title} {today_short}", "image": filename, "count": count, "base": prefix}

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
            skipped.append(f"{title}（无数据）")
            continue

        print(f"🖼️ 生成: {title}")
        result = generate_image(prefix, title, json_path)
        if result:
            image_index.append(result)
            print(f"   ✅ {result['image']} + _latest.png ({result['count']}只)")
        else:
            skipped.append(title)

    index_path = OUTPUT_DIR / "image_index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(image_index, f, ensure_ascii=False, indent=2)
    print(f"\n📋 image_index.json → {len(image_index)} 张图片")
    if skipped:
        print(f"⚠️ 跳过: {', '.join(skipped)}")

if __name__ == "__main__":
    main()
