#!/usr/bin/env python3
"""
A股概念板块RPS分析
- 仅概念板块
- RPS周期: 5/10/20/30/60/120日
- 输出: 表格 + 可视化
"""

import requests
import pandas as pd
import numpy as np
from pathlib import Path
import warnings
import json
import concurrent.futures
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

RPS_PERIODS = [5, 10, 20, 30, 60, 120]
OUTPUT_DIR = Path("data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASE_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
BASE_BOARD_LIST = "https://push2.eastmoney.com/api/qt/clist/get"


# ─── 获取概念板块列表 ───
def fetch_concept_boards():
    all_boards = []
    for page in range(1, 15):
        params = {
            "pn": page, "pz": 100, "po": "1", "np": "1", "fltt": "2", "invt": "2",
            "fid": "f3", "fs": "m:90 t:3 f:!50",
            "fields": "f2,f3,f4,f12,f14"
        }
        resp = requests.get(BASE_BOARD_LIST, params=params, timeout=10)
        items = resp.json().get("data", {}).get("diff", [])
        if not items:
            break
        for item in items:
            all_boards.append({"code": item["f12"], "name": item["f14"]})
        if len(items) < 100:
            break
    return all_boards


# ─── 获取单个板块K线 ───
def fetch_board_kline(board_code):
    try:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=200)).strftime("%Y%m%d")
        params = {
            "secid": f"90.{board_code}",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101", "fqt": "1",
            "beg": start_date, "end": end_date,
            "lmt": "300",
        }
        resp = requests.get(BASE_KLINE, params=params, timeout=10)
        klines = resp.json().get("data", {}).get("klines", [])
        if not klines:
            return None
        records = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 3:
                records.append({
                    "date": parts[0],
                    "close": float(parts[2]),
                })
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df if len(df) >= 120 else None
    except Exception:
        return None


# ─── 并发获取所有K线 ───
def fetch_all_klines(boards):
    print(f"  并发获取 {len(boards)} 个板块K线...")
    kline_data = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_code = {executor.submit(fetch_board_kline, b["code"]): b for b in boards}
        done = 0
        for future in concurrent.futures.as_completed(future_to_code):
            board = future_to_code[future]
            done += 1
            if done % 100 == 0:
                print(f"    进度: {done}/{len(boards)}")
            df = future.result()
            if df is not None:
                kline_data[board["code"]] = df
    print(f"  成功: {len(kline_data)}/{len(boards)}")
    return kline_data


# ─── 计算RPS ───
def calculate_rps(kline_data, board_info, periods=RPS_PERIODS):
    results = []
    for code, df in kline_data.items():
        close = df["close"]
        latest = close.iloc[-1]
        name = next((b["name"] for b in board_info if b["code"] == code), code)
        
        row = {"code": code, "name": name, "latest_date": df["date"].iloc[-1].strftime("%Y-%m-%d"), "close": round(latest, 2)}
        for p in periods:
            if len(close) > p:
                past = close.iloc[-(p + 1)]
                row[f"ret_{p}"] = round((latest - past) / past * 100, 2)
            else:
                row[f"ret_{p}"] = np.nan
        results.append(row)
    
    rps_df = pd.DataFrame(results)
    
    # 计算RPS排名
    for p in periods:
        col = f"ret_{p}"
        if col in rps_df.columns:
            rank = rps_df[col].rank(method="min", ascending=True)
            valid = rps_df[col].notna().sum()
            rps_df[f"RPS{p}"] = (rank / valid * 100).round(1)
    
    # 综合RPS
    rps_cols = [f"RPS{p}" for p in periods]
    rps_df["RPS_avg"] = rps_df[rps_cols].mean(axis=1).round(1)
    
    # RPS变化 (短期vs中期)
    rps_df["RPS_5v20"] = (rps_df["RPS5"] - rps_df["RPS20"]).round(1)
    rps_df["RPS_20v60"] = (rps_df["RPS20"] - rps_df["RPS60"]).round(1)
    rps_df["RPS_5v60"] = (rps_df["RPS5"] - rps_df["RPS60"]).round(1)
    
    return rps_df


# ─── 可视化 ───
def plot_rps(rps_df, periods=RPS_PERIODS):
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    
    font_path = "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/86ba2c91f017a3749571a82f2c6d890ac7ffb2fb.asset/AssetData/PingFang.ttc"
    fm.fontManager.addfont(font_path)
    plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti SC", "STHeiti"]
    plt.rcParams["axes.unicode_minus"] = False
    
    # ── 图1: 综合RPS TOP20 ──
    fig, axes = plt.subplots(2, 3, figsize=(22, 14))
    fig.suptitle("A股概念板块 RPS 分析", fontsize=20, fontweight="bold", y=0.98)
    
    # TOP20 综合RPS
    top20 = rps_df.nlargest(20, "RPS_avg")[["name", "RPS_avg"]].sort_values("RPS_avg", ascending=True)
    colors = plt.cm.RdYlGn(np.linspace(0.3, 0.9, len(top20)))
    ax = axes[0, 0]
    bars = ax.barh(top20["name"], top20["RPS_avg"], color=colors)
    ax.set_xlabel("综合RPS", fontsize=11)
    ax.set_title("综合RPS TOP20", fontsize=13, fontweight="bold")
    for bar, val in zip(bars, top20["RPS_avg"]):
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2, f"{val:.1f}", va="center", fontsize=9)
    
    # ─ 图2: RPS变化 TOP20 (RPS5 - RPS20) ──
    rising = rps_df[(rps_df["RPS5"] > 50) & (rps_df["RPS5"] > rps_df["RPS20"])].copy()
    rising = rising.nlargest(20, "RPS_5v20")[["name", "RPS_5v20", "RPS5", "RPS20", "RPS60"]].sort_values("RPS_5v20", ascending=True)
    ax = axes[0, 1]
    if not rising.empty:
        colors_rise = plt.cm.YlOrRd(np.linspace(0.3, 0.9, len(rising)))
        bars2 = ax.barh(rising["name"], rising["RPS_5v20"], color=colors_rise)
        ax.set_xlabel("RPS5 - RPS20 (上升幅度)", fontsize=11)
        ax.set_title("短期活跃度提升 TOP20", fontsize=13, fontweight="bold")
        for bar, row in zip(bars2, rising.itertuples()):
            ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2, f"{row.RPS_5v20:+.1f}", va="center", fontsize=9)
    else:
        ax.set_title("短期活跃度提升 TOP20", fontsize=13, fontweight="bold")
        ax.text(0.5, 0.5, "无符合条件的板块", ha="center", va="center", transform=ax.transAxes)
    
    # ── 图3: 各周期RPS散点 ──
    ax = axes[0, 2]
    x_labels = [f"RPS{p}" for p in periods]
    for i, (_, row) in enumerate(rps_df.iterrows()):
        vals = [row[f"RPS{p}"] for p in periods]
        is_top = row["RPS_avg"] >= 90
        ax.plot(x_labels, vals, "o-", alpha=0.08 if not is_top else 0.6, 
                markersize=3, linewidth=1.0, color="gray" if not is_top else "red")
    ax.set_ylabel("RPS值", fontsize=11)
    ax.set_title("所有板块RPS趋势 (TOP高亮)", fontsize=13, fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.axhline(y=50, color="k", linestyle="--", alpha=0.3)
    ax.axhline(y=80, color="r", linestyle="--", alpha=0.3)
    ax.axhline(y=90, color="r", linestyle="-", alpha=0.5, label="强信号")
    ax.legend(fontsize=9)
    
    # ── 图4: 重点关注板块 ──
    # RPS5>80 且 RPS5>RPS20 且 RPS20>RPS60 (持续走强)
    focus = rps_df[
        (rps_df["RPS5"] >= 80) & 
        (rps_df["RPS5"] > rps_df["RPS20"]) &
        (rps_df["RPS20"] > rps_df["RPS60"])
    ].sort_values("RPS_5v20", ascending=False).head(15)
    
    ax = axes[1, 0]
    if not focus.empty:
        # 多周期RPS对比
        focus_sorted = focus.sort_values("RPS5", ascending=False)
        x = np.arange(len(focus_sorted))
        width = 0.12
        for i, p in enumerate(periods):
            offset = (i - 2.5) * width
            vals = focus_sorted[f"RPS{p}"].values
            ax.bar(x + offset, vals, width, label=f"RPS{p}", alpha=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(focus_sorted["name"], rotation=45, ha="right", fontsize=9)
        ax.set_ylabel("RPS值", fontsize=11)
        ax.set_title("重点关注板块: 各周期RPS对比", fontsize=13, fontweight="bold")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3, axis="y")
        ax.axhline(y=50, color="k", linestyle="--", alpha=0.3)
        ax.axhline(y=80, color="r", linestyle="--", alpha=0.3)
    else:
        ax.set_title("重点关注板块", fontsize=13, fontweight="bold")
        ax.text(0.5, 0.5, "无符合条件的板块", ha="center", va="center", transform=ax.transAxes)
    
    # ── 图5: RPS5 vs RPS20 散点图 ──
    ax = axes[1, 1]
    sc = ax.scatter(rps_df["RPS20"], rps_df["RPS5"], 
                    c=rps_df["RPS_5v20"], cmap="coolwarm", s=30, alpha=0.6)
    ax.plot([0, 100], [0, 100], "k--", alpha=0.3)
    ax.set_xlabel("RPS20", fontsize=11)
    ax.set_ylabel("RPS5", fontsize=11)
    ax.set_title("RPS5 vs RPS20 散点", fontsize=13, fontweight="bold")
    plt.colorbar(sc, ax=ax, label="RPS5-RPS20")
    ax.grid(True, alpha=0.3)
    
    # ── 图6: 涨幅分布 ──
    ax = axes[1, 2]
    for p in periods:
        col = f"ret_{p}"
        valid = rps_df[col].dropna()
        ax.hist(valid, bins=60, alpha=0.4, label=f"{p}日", density=True)
    ax.set_xlabel("区间涨跌幅 (%)", fontsize=11)
    ax.set_ylabel("密度", fontsize=11)
    ax.set_title("各周期涨幅分布", fontsize=13, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plot_path = OUTPUT_DIR / "sector_rps_concept.png"
    fig.savefig(plot_path, dpi=150, bbox_inches="tight")
    print(f"  总览图: {plot_path}")
    plt.close(fig)
    
    # ─ 各周期TOP15独立图 ──
    for p in periods:
        rps_col = f"RPS{p}"
        if rps_col not in rps_df.columns:
            continue
        top15 = rps_df.nlargest(15, rps_col)[["name", rps_col]].sort_values(rps_col, ascending=True)
        fig, ax = plt.subplots(figsize=(12, 6))
        colors = plt.cm.RdYlGn(np.linspace(0.4, 0.9, len(top15)))
        bars = ax.barh(top15["name"], top15[rps_col], color=colors)
        ax.set_xlabel(f"RPS{p}", fontsize=11)
        ax.set_title(f"概念板块 RPS{p} TOP15", fontsize=13, fontweight="bold")
        for bar, val in zip(bars, top15[rps_col]):
            ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2,
                    f"{val:.1f}", va="center", fontsize=10, fontweight="bold")
        ax.grid(True, alpha=0.3, axis="x")
        plt.tight_layout()
        p_path = OUTPUT_DIR / f"concept_rps{p}_top15.png"
        fig.savefig(p_path, dpi=150, bbox_inches="tight")
        print(f"  {rps_col} TOP15: {p_path}")
        plt.close(fig)


# ── 打印结果 ───
def print_summary(rps_df, periods=RPS_PERIODS):
    print("\n" + "="*100)
    print("  综合RPS TOP20")
    print("="*100)
    top20 = rps_df.nlargest(20, "RPS_avg")
    header = f"{'排名':<4} {'板块':<18} {'收盘':>8} "
    for p in periods:
        header += f" RPS{p:<4} "
    header += f" RPS均值"
    print(header)
    print("-" * 100)
    for i, (_, row) in enumerate(top20.iterrows(), 1):
        line = f"{i:<4} {row['name']:<18} {row['close']:>8.2f} "
        for p in periods:
            val = row.get(f"RPS{p}", np.nan)
            line += f" {val:>5.1f} "
        line += f" {row['RPS_avg']:>5.1f}"
        print(line)
    
    # 保存CSV
    csv_path = OUTPUT_DIR / "concept_rps_full.csv"
    cols = ["code", "name", "latest_date", "close"] + [f"ret_{p}" for p in periods] + [f"RPS{p}" for p in periods] + ["RPS_avg", "RPS_5v20", "RPS_20v60", "RPS_5v60"]
    rps_df[cols].to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n  完整数据: {csv_path}")
    
    # 重点关注板块
    print("\n" + "="*100)
    print("  🔥 活跃度提升板块 (RPS5>70 且 RPS5>RPS20)")
    print("="*100)
    if "RPS5" in rps_df.columns and "RPS20" in rps_df.columns:
        rising = rps_df[
            (rps_df["RPS5"] > 70) & 
            (rps_df["RPS5"] > rps_df["RPS20"])
        ].sort_values("RPS_5v20", ascending=False)
        if not rising.empty:
            print(f"  {'板块':<18} RPS5    RPS10   RPS20   RPS60   RPS5-RPS20")
            print("  " + "-" * 80)
            for _, row in rising.head(20).iterrows():
                delta = row["RPS_5v20"]
                print(f"  {row['name']:<18} {row['RPS5']:>5.1f}  {row['RPS10']:>5.1f}  {row['RPS20']:>5.1f}  {row['RPS60']:>5.1f}  {delta:>+7.1f}")
        else:
            print("  无符合条件的板块")
    
    # 持续走强板块
    print("\n" + "="*100)
    print("   持续走强板块 (RPS5>80 且 RPS5>RPS20>RPS60)")
    print("="*100)
    focus = rps_df[
        (rps_df["RPS5"] >= 80) & 
        (rps_df["RPS5"] > rps_df["RPS20"]) &
        (rps_df["RPS20"] > rps_df["RPS60"])
    ].sort_values("RPS_5v20", ascending=False)
    if not focus.empty:
        print(f"  {'板块':<18} RPS5    RPS20   RPS60   5v20    20v60")
        print("  " + "-" * 70)
        for _, row in focus.head(15).iterrows():
            print(f"  {row['name']:<18} {row['RPS5']:>5.1f}  {row['RPS20']:>5.1f}  {row['RPS60']:>5.1f}  {row['RPS_5v20']:>+6.1f}  {row['RPS_20v60']:>+6.1f}")
    else:
        print("  无符合条件的板块")


# ─── Main ───
def main():
    print("="*60)
    print("  A股概念板块 RPS 分析")
    print("="*60)
    
    boards = fetch_concept_boards()
    print(f"  获取 {len(boards)} 个概念板块")
    
    kline_data = fetch_all_klines(boards)
    if not kline_data:
        print("  未能获取到数据")
        return
    
    print("\n  计算RPS...")
    rps_df = calculate_rps(kline_data, boards)
    
    print("\n  生成可视化...")
    plot_rps(rps_df)
    
    print_summary(rps_df)

    # ── 导出 JSON 供可视化使用 ──
    json_path = OUTPUT_DIR / "sector_rps.json"
    export_data = {
        "date": rps_df["latest_date"].mode().iloc[0] if len(rps_df) else datetime.now().strftime("%Y-%m-%d"),
        "sectors": []
    }
    for _, row in rps_df.iterrows():
        export_data["sectors"].append({
            "code": row["code"],
            "name": row["name"],
            "close": row["close"],
            "latest_date": row["latest_date"],
            **{f"ret_{p}": round(float(row.get(f"ret_{p}", 0)), 2) if pd.notna(row.get(f"ret_{p}")) else 0 for p in periods},
            **{f"RPS{p}": round(float(row.get(f"RPS{p}", 0)), 1) if pd.notna(row.get(f"RPS{p}")) else 0 for p in periods},
            "RPS_avg": round(float(row["RPS_avg"]), 1),
            "RPS_5v20": round(float(row["RPS_5v20"]), 1),
            "RPS_20v60": round(float(row["RPS_20v60"]), 1),
            "RPS_5v60": round(float(row["RPS_5v60"]), 1),
        })
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
    print(f"  数据JSON: {json_path} ({len(export_data['sectors'])} sectors)")

    print("\n  完成!")


if __name__ == "__main__":
    main()
