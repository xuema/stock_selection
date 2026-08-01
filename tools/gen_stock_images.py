#!/usr/bin/env python3
"""生成策略选股图片网格，用 Pillow。"""
import json, os, shutil, sys
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "strategy"

STRATEGY_CONFIGS = [
    {"prefix": "screen_hot_sectors",        "title": "RSP热门板块", "is_hot_sectors": True},
    {"prefix": "screen_rsp_trend_break",   "title": "RSP趋势突破"},
    {"prefix": "screen_rps_trend_v2",      "title": "RPS中长期龙头"},
    {"prefix": "screen_rps_trend_pro",     "title": "RPS超强势"},
    {"prefix": "screen_rsi_golden_cross",  "title": "RSI金叉"},
    {"prefix": "screen_signals",           "title": "EXPMA+多因子"},
    {"prefix": "screen_ma_pullback",       "title": "MA回调"},
    {"prefix": "screen_super_top_bottom_buy",  "title": "超级顶底买入"},
    {"prefix": "screen_super_top_bottom_sell", "title": "超级顶底卖出"},
    {"prefix": "screen_rsi_stb_resonance", "title": "RSI共振"},
    {"prefix": "screen_active_midcap",     "title": "活跃中盘股"},
]

def load_stocks(json_path):
    with open(json_path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("stocks", [])

def load_hot_sectors(json_path):
    with open(json_path) as f:
        data = json.load(f)
    return data

def get_font(size):
    for path in [
        "/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Microsoft/SimHei.ttf",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except:
                pass
    return ImageFont.load_default()

def generate_hot_sectors_image(prefix, title, json_path):
    data = load_hot_sectors(json_path)
    sectors = data.get("sectors", [])
    sector_top5 = data.get("sector_top5", {})
    if not sectors:
        return None

    date_str = json_path.stem.split("_")[-1]
    if "-" in date_str:
        date_short = date_str.replace("-", "")[4:]
    else:
        date_short = date_str

    cols = 6
    cell_w, cell_h = 108, 32
    gap = 4
    margin = 24
    header_h = 70

    # Calculate total rows
    total_items = 0
    sector_headers = []
    for sec in sectors[:10]:
        sec_name = sec["sector"]
        sector_headers.append(sec_name)
        total_items += 1  # sector header
        top5 = sector_top5.get(sec_name, [])
        total_items += len(top5)

    rows = (total_items + cols - 1) // cols
    img_w = cols * (cell_w + gap) + margin * 2 - gap
    img_h = header_h + rows * (cell_h + gap) + margin * 2

    BG = (13, 17, 23)
    CELL_BG = (22, 27, 34)
    SECTOR_BG = (30, 40, 50)
    BORDER = (48, 54, 61)
    ACCENT = (88, 166, 255)
    GREEN = (52, 211, 153)
    RED = (248, 113, 113)
    TEXT = (230, 237, 243)
    MUTED = (139, 148, 158)

    img = Image.new("RGB", (img_w, img_h), BG)
    draw = ImageDraw.Draw(img)

    title_font = get_font(20)
    sub_font = get_font(13)
    cell_font = get_font(14)
    sector_font = get_font(13)

    # Title
    tb = draw.textbbox((0,0), title, font=title_font)
    tw = tb[2] - tb[0]
    draw.text(((img_w - tw)//2, 14), title, fill=ACCENT, font=title_font)

    sub_y = 40
    draw.line([(margin, sub_y), (img_w - margin, sub_y)], fill=BORDER, width=1)

    sub_text = f"{date_str}  |  板块排名 + Top5强势股"
    sb = draw.textbbox((0,0), sub_text, font=sub_font)
    sw = sb[2] - sb[0]
    draw.text(((img_w - sw)//2, 44), sub_text, fill=MUTED, font=sub_font)

    y_start = header_h + margin
    item_idx = 0

    for sec in sectors[:10]:
        sec_name = sec["sector"]
        score = sec["score"]
        avg_rsp = sec["avg_rsp"]

        # Sector header row
        col = item_idx % cols
        row = item_idx // cols
        x = margin + col * (cell_w + gap)
        y = y_start + row * (cell_h + gap)

        draw.rounded_rectangle([(x,y), (x+cell_w, y+cell_h)], radius=4, fill=SECTOR_BG, outline=BORDER, width=1)

        # Sector name with score
        label = f"{sec_name} ★{score}"
        lb = draw.textbbox((0,0), label, font=sector_font)
        lw = lb[2] - lb[0]
        draw.text((x + (cell_w-lw)//2, y + (cell_h - (lb[3]-lb[1]))//2 - 1), label, fill=GREEN, font=sector_font)

        item_idx += 1

        # Top 5 stocks for this sector
        top5 = sector_top5.get(sec_name, [])
        for s in top5:
            col = item_idx % cols
            row = item_idx // cols
            x = margin + col * (cell_w + gap)
            y = y_start + row * (cell_h + gap)

            draw.rounded_rectangle([(x,y), (x+cell_w, y+cell_h)], radius=4, fill=CELL_BG, outline=BORDER, width=1)

            # Show ticker and RSP
            cell_text = f"{s['ticker']} {s['rsp']:+.2f}"
            cb = draw.textbbox((0,0), cell_text, font=cell_font)
            ctw = cb[2] - cb[0]
            color = GREEN if s["rsp"] > 0 else RED
            draw.text((x + (cell_w-ctw)//2, y + (cell_h - (cb[3]-cb[1]))//2 - 1), cell_text, fill=color, font=cell_font)

            item_idx += 1

    today_short = datetime.now().strftime("%m%d")
    filename = f"{prefix}_{today_short}.png"
    out = OUTPUT_DIR / filename
    img.save(str(out), "PNG")
    shutil.copy2(out, OUTPUT_DIR / f"{prefix}_latest.png")

    total_stocks = sum(len(sector_top5.get(s["sector"], [])) for s in sectors[:10])
    return {"title": f"{title} {today_short}", "image": filename, "count": total_stocks, "base": prefix}

def generate_image(prefix, title, json_path):
    stocks = load_stocks(json_path)
    if not stocks:
        return None

    date_str = json_path.stem.split("_")[-1]

    # Parse date: could be "2026-07-15" or "0715"
    if "-" in date_str:
        date_short = date_str.replace("-", "")[4:]  # "20260715" -> "0715"
    else:
        date_short = date_str

    codes = [s["ticker"] for s in stocks[:200]]
    count = len(codes)

    cols = 6
    rows = (count + cols - 1) // cols
    cell_w, cell_h = 108, 32
    gap = 4
    margin = 24
    header_h = 60
    img_w = cols * (cell_w + gap) + margin * 2 - gap
    img_h = header_h + rows * (cell_h + gap) + margin * 2

    # Colors
    BG = (13, 17, 23)
    CELL_BG = (22, 27, 34)
    BORDER = (48, 54, 61)
    ACCENT = (88, 166, 255)
    TEXT = (230, 237, 243)
    MUTED = (139, 148, 158)

    img = Image.new("RGB", (img_w, img_h), BG)
    draw = ImageDraw.Draw(img)

    title_font = get_font(20)
    sub_font = get_font(13)
    cell_font = get_font(14)

    # Title
    title_text = f"{title}"
    tb = draw.textbbox((0,0), title_text, font=title_font)
    tw = tb[2] - tb[0]
    draw.text(((img_w - tw)//2, 14), title_text, fill=ACCENT, font=title_font)

    # Border line
    sub_y = 40
    draw.line([(margin, sub_y), (img_w - margin, sub_y)], fill=BORDER, width=1)

    # Subtitle
    sub_text = f"{date_str}  |  共 {count} 只"
    sb = draw.textbbox((0,0), sub_text, font=sub_font)
    sw = sb[2] - sb[0]
    draw.text(((img_w - sw)//2, 44), sub_text, fill=MUTED, font=sub_font)

    # Grid
    y_start = header_h + margin
    for i, code in enumerate(codes):
        col = i % cols
        row = i // cols
        x = margin + col * (cell_w + gap)
        y = y_start + row * (cell_h + gap)

        # Cell bg with rounded rect
        draw.rounded_rectangle([(x,y), (x+cell_w, y+cell_h)], radius=4, fill=CELL_BG, outline=BORDER, width=1)

        # Code centered
        cb = draw.textbbox((0,0), code, font=cell_font)
        cw = cb[2] - cb[0]
        ch = cb[3] - cb[1]
        draw.text((x + (cell_w-cw)//2, y + (cell_h-ch)//2 - 1), code, fill=TEXT, font=cell_font)

    # Save
    today_short = datetime.now().strftime("%m%d")
    filename = f"{prefix}_{today_short}.png"
    out = OUTPUT_DIR / filename
    img.save(str(out), "PNG")

    # Also copy as _latest
    shutil.copy2(out, OUTPUT_DIR / f"{prefix}_latest.png")

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
        if cfg.get("is_hot_sectors"):
            result = generate_hot_sectors_image(prefix, title, json_path)
        else:
            result = generate_image(prefix, title, json_path)
        if result:
            image_index.append(result)
            print(f"   ✅ {result['image']} + {prefix}_latest.png ({result['count']}只)")
        else:
            skipped.append(title)

    with open(OUTPUT_DIR / "image_index.json", "w") as f:
        json.dump(image_index, f, ensure_ascii=False, indent=2)
    print(f"\n📋 image_index.json → {len(image_index)} 张图片")
    if skipped:
        print(f"⚠️ 跳过: {', '.join(skipped)}")

if __name__ == "__main__":
    main()
