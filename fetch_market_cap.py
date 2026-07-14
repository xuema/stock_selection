#!/usr/bin/env python3
"""
获取全部股票的流通市值，缓存为 JSON 文件。
使用 yfinance 的 info['marketCap'] 作为流通市值近似值。

输出: market_cap_cache.json (代码→市值映射，单位：人民币元)

注意: 首次运行约需 30-60 分钟获取全部 ~4000 只股票。
用法: python3 fetch_market_cap.py  (或指定 --min-yi 50 看统计)
"""
import os, json, glob, time, sys
import yfinance as yf
from tqdm import tqdm

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data_cache_daily")
CACHE_FILE = os.path.join(BASE, "market_cap_cache.json")

def fmt(code):
    c = str(code).zfill(6)
    if c.startswith('6'): return c + ".SS"
    if c.startswith(('0','3')): return c + ".SZ"
    return None

def fetch_all(batch_size=50, sleep_between=3):
    csv_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.csv")))
    codes = []
    for f in csv_files:
        ticker = os.path.basename(f).replace(".csv", "")
        if fmt(ticker):
            codes.append((ticker, fmt(ticker)))

    if not codes:
        print(f"⚠️  {DATA_DIR} 下没有找到 CSV 文件！")
        print(f"   请确认目录: {DATA_DIR}")
        return {}

    print(f"共 {len(codes)} 只股票，开始获取市值…")
    cache = {}
    for bi in range(0, len(codes), batch_size):
        sub = codes[bi:bi+batch_size]
        for code, yt in tqdm(sub, desc=f"批 {bi//batch_size+1}"):
            try:
                info = yf.Ticker(yt).info
                mc = info.get("marketCap")
                if mc and mc > 0:
                    cache[code] = int(mc)
            except:
                pass
        if bi + batch_size < len(codes):
            time.sleep(sleep_between)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print(f"\n💾 已保存 {len(cache)} 只市值到 {CACHE_FILE}")

    if cache:
        yi_vals = [v/1e8 for v in cache.values()]
        print(f"  市值范围: {min(yi_vals):.1f}亿 ~ {max(yi_vals):.1f}亿")
        mid = sorted(yi_vals)[len(yi_vals)//2]
        print(f"  中位数:   {mid:.1f}亿")
    else:
        print("  (未获取到任何市值数据)")

    return cache

if __name__ == "__main__":
    fetch_all()
