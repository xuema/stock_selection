#!/usr/bin/env python3
"""
通达信板块指数(88xxxx) RPS 对照表
- 数据源: 通达信行情服务器 (pytdx)，板块清单来自 tdx_board_list.csv
- RPS周期: 5/10/15/20/50，对齐通达信「板块指数RPS」指标口径
- 输出: data/tdx_rps_full.csv + tdx_rps.json + data/history 快照

pytdx 不可用或行情服务器连不上时，本脚本只告警并以 0 退出，不阻断 daily_screen.sh 主流程。
"""

import argparse
import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parent))
from board_filter import split_boards  # noqa: E402
from sector_rps_concept import detect_session  # noqa: E402

RPS_PERIODS = [5, 10, 15, 20, 50]
MIN_BARS = 60
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "data"
HISTORY_DIR = OUTPUT_DIR / "history"
BOARD_LIST = BASE_DIR / "tdx_board_list.csv"

# 通达信板块指数走 SH 市场；日线 category 在不同服务端取 9 或 4，启动时探测
MARKET = 1
CATEGORY_CANDIDATES = [9, 4, 0]
CONNECT_TIMEOUT = 4
MAX_SERVER_TRIES = 15
SERVERS_FILE = BASE_DIR / "tdx_servers.txt"   # 可选：手写可用服务器 ip:port，一行一个


def load_boards():
    if not BOARD_LIST.exists():
        print(f"  缺少板块清单: {BOARD_LIST}")
        return []
    df = pd.read_csv(BOARD_LIST, dtype={"code": str})
    return [{"code": r.code, "name": r.name, "btype": str(r.btype)} for r in df.itertuples()]


def make_api():
    # raise_exception=True 是必须的：默认 False 会把握手失败吞成"连接成功"，导致假阳性
    from pytdx.hq import TdxHq_API
    return TdxHq_API(raise_exception=True, auto_retry=False)


def candidate_servers():
    if SERVERS_FILE.exists():
        out = []
        for line in SERVERS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if not line:
                continue
            host, _, port = line.partition(":")
            out.append((host.strip(), int(port or 7709)))
        return out
    try:
        from pytdx.config.hosts import hq_hosts as hosts
    except ImportError:
        from pytdx.config.hosts import hq_servers as hosts
    out = []
    for item in hosts[:MAX_SERVER_TRIES]:
        # hq_hosts 是 (名称, ip, port)；老版本 hq_servers 是 (ip, port)
        host, port = (item[1], item[2]) if len(item) >= 3 else (item[0], item[1])
        out.append((host.strip(), int(port)))
    return out


def connect_api():
    """逐台尝试，且必须真拿到一次数据才算连上（握手成功≠可用）。"""
    for host, port in candidate_servers():
        api = make_api()
        try:
            if not api.connect(host, port, time_out=CONNECT_TIMEOUT):
                raise ConnectionError("connect 返回假")
            # 用一次元数据请求验证会话真的可用
            if not api.get_security_count(0):
                raise ConnectionError("会话无响应")
        except Exception:
            try:
                api.disconnect()
            except Exception:
                pass
            continue
        print(f"  已连接并验证: {host}:{port}")
        return api
    print("  通达信行情服务器全部连接失败(握手超时或会话无响应)")
    return None


def probe_category(api, sample_code):
    """挑一个真能返回该板块指数日线的 category 值。"""
    for cat in CATEGORY_CANDIDATES:
        try:
            bars = api.get_index_bars(cat, MARKET, sample_code, 0, 300)
        except Exception:
            continue
        if bars and len(bars) >= MIN_BARS:
            print(f"  探测到可用 category={cat} (样本 {sample_code} 返回 {len(bars)} 根)")
            return cat
    return None


# ─── 拉单个板块指数日线 ───
def fetch_bars(api, category, code):
    for attempt in range(2):
        try:
            bars = api.get_index_bars(category, MARKET, code, 0, 300)
            break
        except Exception:
            if attempt:
                return None
            time.sleep(0.3)
    else:
        return None
    if not bars or len(bars) < MIN_BARS:
        return None
    df = pd.DataFrame(bars)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    for col in ("close", "amount", "vol"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def fetch_all(api, category, boards, workers=6):
    """pytdx 连接非线程安全，这里串行拉取；1039 个板块约 2-4 分钟。"""
    out, failed = {}, 0
    for i, b in enumerate(boards, 1):
        df = fetch_bars(api, category, b["code"])
        if df is not None:
            out[b["code"]] = df
        else:
            failed += 1
        if i % 200 == 0:
            print(f"    进度: {i}/{len(boards)} (成功 {len(out)})")
    print(f"  成功: {len(out)}/{len(boards)}，失败 {failed}")
    return out


# ─── 计算 RPS ───
def calculate_rps(bars_data, boards, periods=RPS_PERIODS):
    rows = []
    info = {b["code"]: b for b in boards}
    for code, df in bars_data.items():
        close = df["close"]
        latest = float(close.iloc[-1])
        meta = info.get(code, {})
        row = {
            "code": code,
            "name": meta.get("name", code),
            "btype": meta.get("btype", ""),
            "latest_date": df["datetime"].iloc[-1].strftime("%Y-%m-%d"),
            "close": round(latest, 2),
        }
        amount = df["amount"].dropna()
        if len(amount):
            row["amount"] = round(float(amount.iloc[-1]) / 1e8, 2)
            base = amount.iloc[-6:-1] if len(amount) >= 6 else amount.iloc[:-1]
            row["amount_avg5"] = round(float(base.mean()) / 1e8, 2) if len(base) else np.nan
        else:
            row["amount"] = np.nan
            row["amount_avg5"] = np.nan
        for p in periods:
            if len(close) > p:
                past = float(close.iloc[-(p + 1)])
                row[f"ret_{p}"] = round((latest - past) / past * 100, 2) if past else np.nan
            else:
                row[f"ret_{p}"] = np.nan
        rows.append(row)

    rps_df = pd.DataFrame(rows)
    for p in periods:
        col = f"ret_{p}"
        rank = rps_df[col].rank(method="min", ascending=True)
        valid = rps_df[col].notna().sum()
        rps_df[f"RPS{p}"] = (rank / valid * 100).round(1) if valid else np.nan

    rps_df["RPS_avg"] = rps_df[[f"RPS{p}" for p in periods]].mean(axis=1).round(1)
    rps_df["RPS_5v20"] = (rps_df["RPS5"] - rps_df["RPS20"]).round(1)
    rps_df["RPS_20v50"] = (rps_df["RPS20"] - rps_df["RPS50"]).round(1)
    rps_df["amount_ratio5"] = (rps_df["amount"] / rps_df["amount_avg5"]).round(2)
    return rps_df


def print_summary(rps_df):
    cols = [f"RPS{p}" for p in RPS_PERIODS]
    print("\n" + "=" * 96)
    print("  通达信板块指数 RPS TOP20 (口径 5/10/15/20/50)")
    print("=" * 96)
    print(f"  {'排名':<3} {'代码':<8} {'板块':<14} {'涨幅5d':>7} {'额(亿)':>7} {'额比':>5} "
          + " ".join(f"{c:>7}" for c in cols) + f" {'综合':>6}")
    print("  " + "-" * 92)
    for i, (_, row) in enumerate(rps_df.nlargest(20, "RPS_avg").iterrows(), 1):
        amt = f"{row['amount']:.1f}" if pd.notna(row.get("amount")) else "--"
        rat = f"{row['amount_ratio5']:.2f}" if pd.notna(row.get("amount_ratio5")) else "--"
        r5 = f"{row['ret_5']:+.1f}" if pd.notna(row.get("ret_5")) else "--"
        vals = " ".join(f"{row[c]:>7.1f}" if pd.notna(row.get(c)) else f"{'--':>7}" for c in cols)
        print(f"  {i:<3} {row['code']:<8} {row['name']:<14} {r5:>7} {amt:>7} {rat:>5} {vals} {row['RPS_avg']:>6.1f}")

    print("\n  分层:")
    tiers = [
        ("持续强势 (综合>=90 且 RPS20>RPS50)", lambda d: (d["RPS_avg"] >= 90) & (d["RPS_20v50"] > 0)),
        ("新转强 (综合>=80 且 RPS_5v20>+10)", lambda d: (d["RPS_avg"] >= 80) & (d["RPS_5v20"] > 10)),
        ("放量确认 (综合>=80 且 额比>=1.3)", lambda d: (d["RPS_avg"] >= 80) & (d["amount_ratio5"] >= 1.3)),
        ("缩量新高 (综合>=85 但 额比<0.8)", lambda d: (d["RPS_avg"] >= 85) & (d["amount_ratio5"] < 0.8)),
    ]
    for label, cond in tiers:
        try:
            hit = rps_df[cond(rps_df)]
        except Exception:
            continue
        names = "  ".join(hit.nlargest(10, "RPS_avg")["name"]) or "—"
        print(f"    {label:<32} {len(hit):>3} 个: {names}")


def main():
    parser = argparse.ArgumentParser(description="通达信板块指数 RPS 对照表")
    parser.add_argument("--probe", action="store_true", help="只测连通性与 category 探测，不跑全量")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 个板块(冒烟测试用)")
    parser.add_argument("--session", choices=["intraday", "final", "auto"], default="auto")
    args = parser.parse_args()

    print("=" * 60)
    print("  通达信板块指数 RPS 对照表")
    print("=" * 60)

    try:
        import pytdx  # noqa: F401
    except ImportError:
        print("  pytdx 未安装，跳过通达信对照表。安装: venv/bin/pip install pytdx")
        return 0

    boards = load_boards()
    if not boards:
        return 0
    kept, excluded = split_boards(boards)
    print(f"  板块 {len(boards)} 个 → 保留 {len(kept)} / 剔除 {len(excluded)} (技术形态·风格·宽基)")
    if args.limit:
        kept = kept[:args.limit]

    api = connect_api()
    if api is None:
        print("  连不上通达信行情服务器，跳过对照表(不影响东财主流程)")
        print(f"  可在 {SERVERS_FILE} 里手写可用服务器 ip:port(通达信客户端用的地址)")
        return 0

    try:
        category = probe_category(api, kept[0]["code"])
        if not category:
            print("  板块指数日线探测失败，跳过")
            return 0
        if args.probe:
            sample = fetch_bars(api, category, kept[0]["code"])
            if sample is not None:
                print(f"\n  样本 {kept[0]['code']} {kept[0]['name']}: {len(sample)} 根")
                print(sample.tail(3)[["datetime", "close", "amount"]].to_string(index=False))
            return 0

        bars = fetch_all(api, category, kept)
        if not bars:
            print("  未取到任何板块日线，跳过")
            return 0

        rps_df = calculate_rps(bars, kept)
        session = detect_session() if args.session == "auto" else args.session
        latest_date = rps_df["latest_date"].mode().iloc[0]

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        cols = (["code", "name", "btype", "latest_date", "close", "amount", "amount_avg5", "amount_ratio5"]
                + [f"ret_{p}" for p in RPS_PERIODS] + [f"RPS{p}" for p in RPS_PERIODS]
                + ["RPS_avg", "RPS_5v20", "RPS_20v50"])
        rps_df[cols].to_csv(OUTPUT_DIR / "tdx_rps_full.csv", index=False, encoding="utf-8-sig")
        rps_df[cols].to_csv(HISTORY_DIR / f"tdx_rps_{latest_date}_{session}.csv", index=False, encoding="utf-8-sig")

        def num(row, key, digits=2):
            val = row.get(key)
            return round(float(val), digits) if pd.notna(val) else None
        export = {
            "date": latest_date,
            "session": session,
            "source": "tdx-88xxxx",
            "periods": RPS_PERIODS,
            "universe": {"total": len(boards), "kept": len(kept), "fetched": len(bars), "excluded": len(excluded)},
            "sectors": [
                {
                    "code": row["code"], "name": row["name"], "btype": row["btype"],
                    "close": row["close"], "latest_date": row["latest_date"],
                    "amount": num(row, "amount"), "amount_avg5": num(row, "amount_avg5"),
                    "amount_ratio5": num(row, "amount_ratio5"),
                    **{f"ret_{p}": num(row, f"ret_{p}") for p in RPS_PERIODS},
                    **{f"RPS{p}": num(row, f"RPS{p}", 1) for p in RPS_PERIODS},
                    "RPS_avg": num(row, "RPS_avg", 1),
                    "RPS_5v20": num(row, "RPS_5v20", 1),
                    "RPS_20v50": num(row, "RPS_20v50", 1),
                }
                for _, row in rps_df.iterrows()
            ],
        }
        json_path = OUTPUT_DIR / "tdx_rps.json"
        json_path.write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")

        print_summary(rps_df)
        print(f"\n  CSV: {OUTPUT_DIR / 'tdx_rps_full.csv'}")
        print(f"  JSON: {json_path} ({len(export['sectors'])} sectors, session={session})")
    finally:
        try:
            api.disconnect()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
