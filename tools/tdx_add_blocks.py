#!/usr/bin/env python3
"""
将每日选股结果添加到 Mac 版通达信自选股板块中。

用法:
  python3 tdx_add_blocks.py [--date YYYY-MM-DD] [--dry-run]
"""

import json
import os
import sys
import glob
import argparse
from datetime import datetime, timezone, timedelta

# ─── 配置 ───
STRATEGY_DIR = "/Users/skyler/workspace/stock_selection/output/strategy"
STOCK_NAMES_PATH = "/Users/skyler/workspace/stock_selection/stock_names.json"
TDX_USER_GUEST = os.path.expanduser(
    "~/Library/Containers/com.tdx.mac2022/Data/Documents/user_guest"
)
BLOCKNEW_CFG = os.path.join(TDX_USER_GUEST, "blocknew.cfg")

RECORD_SIZE = 120
NAME_FIELD_SIZE = 50
ID_FIELD_SIZE = 70

# 策略文件名 → (板块ID(≤8), 显示中文名)
STRATEGY_MAP = {
    "screen_rsi_golden_cross":      ("RSI_JC",   "RSI金叉"),
    "screen_rsi_stb_resonance":     ("RSI_GZ",   "RSI共振"),
    "screen_signals":               ("EXPMA",    "EXPMA"),
    "screen_super_top_bottom_buy":  ("CJDD_MR",  "超级顶底买入"),
    "screen_super_top_bottom_sell": ("CJDD_MC",  "超级顶底卖出"),
    "screen_ma_pullback":           ("MA_HT",    "MA回调"),
}


def get_tdx_code(ticker: str) -> str:
    sc = "1" if ticker.startswith("6") else "0"
    return f"{sc}{ticker}"


def load_stock_names():
    with open(STOCK_NAMES_PATH, "r") as f:
        return json.load(f)


def read_blocknew_cfg():
    if not os.path.exists(BLOCKNEW_CFG):
        return []
    with open(BLOCKNEW_CFG, "rb") as f:
        data = f.read()
    entries = []
    for i in range(0, len(data), RECORD_SIZE):
        rec = data[i:i + RECORD_SIZE]
        if len(rec) < RECORD_SIZE:
            break
        try:
            name = rec[:NAME_FIELD_SIZE].split(b"\x00")[0].decode("gbk").strip()
        except:
            name = ""
        try:
            bid = rec[NAME_FIELD_SIZE:NAME_FIELD_SIZE + ID_FIELD_SIZE].split(b"\x00")[0].decode("ascii").strip()
        except:
            bid = ""
        if name or bid:
            entries.append((name, bid))
    return entries


def write_blocknew_cfg(entries):
    with open(BLOCKNEW_CFG, "wb") as f:
        for name, bid in entries:
            rec = bytearray(RECORD_SIZE)
            nb = name.encode("gbk", errors="replace")[:NAME_FIELD_SIZE]
            rec[:len(nb)] = nb
            ib = bid.encode("ascii")[:ID_FIELD_SIZE]
            rec[NAME_FIELD_SIZE:NAME_FIELD_SIZE + len(ib)] = ib
            f.write(rec)


def write_blk(bid: str, tickers: list):
    path = os.path.join(TDX_USER_GUEST, f"{bid}.blk")
    data = b"".join(f"{get_tdx_code(t)}\r\n".encode("ascii") for t in sorted(tickers))
    with open(path, "wb") as f:
        f.write(data)


def write_blkdict(bid: str, tickers: list, json_path: str, today_str: str):
    path = os.path.join(TDX_USER_GUEST, f"{bid}.blkdict")
    # build price map
    price_map = {}
    try:
        with open(json_path) as f:
            raw = json.load(f)
        stocks = raw.get("stocks", []) if isinstance(raw, dict) else raw
        for s in stocks:
            t = s.get("ticker")
            if t:
                price_map[t] = str(s.get("close", "0.00"))
    except Exception:
        pass

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        '<plist version="1.0">',
        '<dict>',
    ]
    for t in sorted(tickers):
        price = price_map.get(t, "0.00")
        lines.append(f'\t<key>{t}</key>')
        lines.append(f'\t<string>{today_str}|{price}</string>')
    lines += ['</dict>', '</plist>', '']
    with open(path, "wb") as f:
        f.write("\n".join(lines).encode("utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    date_str = args.date or datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    date_suffix = date_str[5:].replace("-", "")  # 月日 = 0715

    stock_names = load_stock_names()
    if not os.path.exists(TDX_USER_GUEST):
        print(f"❌ 目录不存在: {TDX_USER_GUEST}")
        sys.exit(1)

    # Read existing entries & stale cleanup
    existing = read_blocknew_cfg()
    existing_ids = {bid for _, bid in existing}

    # Load strategy results
    latest_files = sorted(glob.glob(os.path.join(STRATEGY_DIR, "*_latest.json")))
    strategies = []
    for lf in latest_files:
        fname = os.path.basename(lf).replace("_latest.json", "")
        if fname not in STRATEGY_MAP:
            continue
        with open(lf) as f:
            raw = json.load(f)
        stocks = raw.get("stocks", []) if isinstance(raw, dict) else raw
        tickers = [s["ticker"] for s in stocks if "ticker" in s]
        if not tickers:
            continue

        bid_base, cn_name = STRATEGY_MAP[fname]
        # If same base id already exists (from earlier date), add suffix
        if bid_base in existing_ids:
            bid = f"{bid_base}_{date_suffix}"
        else:
            bid = bid_base
        display_name = f"{cn_name}_{date_suffix}"

        strategies.append({
            "source_file": lf,
            "bid": bid,
            "display": display_name,
            "tickers": tickers,
        })

    if not strategies:
        print("❌ 今天没有选出的股票")
        sys.exit(0)

    # Show summary
    total = 0
    for s in strategies:
        print(f"  🟢 {s['display']} ({s['bid']}): {len(s['tickers'])} 只")
        for t in s["tickers"][:3]:
            print(f"     • {t} {stock_names.get(t, '?')}")
        if len(s["tickers"]) > 3:
            print(f"     ... 等 {len(s['tickers'])} 只")
        total += len(s["tickers"])
    print(f"\n📈 合计: {total} 只")

    if args.dry_run:
        print("\n🔍 模拟模式")
        return

    # Clean stale entries
    clean_existing = [(n, b) for n, b in existing if os.path.exists(os.path.join(TDX_USER_GUEST, f"{b}.blk"))]
    if len(clean_existing) != len(existing):
        stale = set(existing) - set(clean_existing)
        for _, bid in stale:
            for ext in (".blk", ".blkdict"):
                p = os.path.join(TDX_USER_GUEST, f"{bid}{ext}")
                if os.path.exists(p):
                    os.remove(p)
        write_blocknew_cfg(clean_existing)
        existing = clean_existing

    # Write
    for s in strategies:
        write_blk(s["bid"], s["tickers"])
        write_blkdict(s["bid"], s["tickers"], s["source_file"], date_str.replace("-", ""))
        existing.append((s["display"], s["bid"]))
        print(f"  ✅ {s['display']} → {s['bid']} ({len(s['tickers'])} 只)")

    write_blocknew_cfg(existing)

    print(f"\n📂 {TDX_USER_GUEST}:")
    for f in sorted(os.listdir(TDX_USER_GUEST)):
        sz = os.path.getsize(os.path.join(TDX_USER_GUEST, f))
        print(f"   {f} ({sz})")
    print(f"\n🎯 完成! 共 {len(strategies)} 个板块, {total} 只股票")
    print("📱 请重启通达信金融终端")


if __name__ == "__main__":
    main()
