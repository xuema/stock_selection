#!/usr/bin/env python3
"""为选股结果生成包含股票代码的图片，方便下载查看。"""
import json, os, glob, sys
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timezone, timedelta

STRATEGY_DIR = "/Users/skyler/workspace/stock_selection/output/strategy"

DISPLAY_NAMES = {
    "screen_rsi_golden_cross": "RSI金叉",
    "screen_rsi_stb_resonance": "RSI共振",
    "screen_signals": "EXPMA+多因子",
    "screen_super_top_bottom_buy": "超级顶底买入",
    "screen_super_top_bottom_sell": "超级顶底卖出",
    "screen_ma_pullback": "MA回调",
}

def generate_image(tickers, title, out_path):
    if not tickers:
        return

    cols = 6
    font_sz = 28
    cell_w, cell_h = 130, 50
    pad, title_h = 40, 55
    rows = (len(tickers) + cols - 1) // cols
    w = cols * cell_w + pad * 2
    h = title_h + rows * cell_h + pad * 2

    img = Image.new("RGB", (w, h), "#1a1a2e")
    d = ImageDraw.Draw(img)

    tf = cf = None
    for fp in ["/System/Library/Fonts/PingFang.ttc",
               "/System/Library/Fonts/STHeiti Medium.ttc",
               "/Library/Fonts/Arial Unicode.ttf",
               "/System/Library/Fonts/Menlo.ttc",
               "/System/Library/Fonts/Helvetica.ttc"]:
        if os.path.exists(fp):
            try:
                tf = ImageFont.truetype(fp, 34)
                cf = ImageFont.truetype(fp, font_sz)
                break
            except Exception:
                pass
    tf = tf or ImageFont.load_default()
    cf = cf or ImageFont.load_default()

    d.rectangle([(0, 0), (w, title_h - 5)], fill="#16213e")
    d.text((pad, 11), title, fill="#e94560", font=tf)

    for i, tick in enumerate(sorted(tickers)):
        r, c = divmod(i, cols)
        x1 = pad + c * cell_w + 5
        y1 = title_h + pad + r * cell_h
        x2 = x1 + cell_w - 10
        y2 = y1 + cell_h - 10
        d.rounded_rectangle([(x1, y1), (x2, y2)], radius=8,
                            fill="#0f3460", outline="#533483", width=2)
        tw = d.textlength(tick, font=cf)
        d.text(((x1 + x2 - tw) / 2, y1 + (cell_h - font_sz) / 2 - 2),
               tick, fill="#e6edf3", font=cf)

    img.save(out_path, "PNG")
    return out_path


def main(date_suffix=None):
    if not date_suffix:
        date_suffix = datetime.now(timezone(timedelta(hours=8))).strftime("%m%d")

    imgs = []
    for lf in sorted(glob.glob(os.path.join(STRATEGY_DIR, "*_latest.json"))):
        fn = os.path.basename(lf)
        base = fn.replace("_latest.json", "")
        try:
            with open(lf) as f:
                raw = json.load(f)
        except Exception:
            continue

        stocks = raw.get("stocks", []) if isinstance(raw, dict) else raw
        tickers = [s["ticker"] for s in stocks if "ticker" in s]
        if not tickers:
            continue

        display = DISPLAY_NAMES.get(base, base)
        title = f"{display} {date_suffix}"
        out_name = base + f"_{date_suffix}.png"
        out_path = os.path.join(STRATEGY_DIR, out_name)

        generate_image(tickers, title, out_path)
        imgs.append({"title": title, "image": out_name,
                      "count": len(tickers), "base": base})
        print(f"  🖼️ {title}: {len(tickers)} 只 → {out_name}")

    idx = os.path.join(STRATEGY_DIR, "image_index.json")
    with open(idx, "w") as f:
        json.dump(imgs, f, ensure_ascii=False, indent=2)
    print(f"\n📸 {len(imgs)} 张图片已生成 → image_index.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
