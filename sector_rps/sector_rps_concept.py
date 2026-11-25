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
import argparse
import concurrent.futures
import os
import shutil
import socket
import sys
import time
import threading
from datetime import datetime, timedelta

from board_filter import split_boards

warnings.filterwarnings("ignore")

# 主口径：保持原 6 周期不变，HTML 面板(sector_rps_template.html)硬编码依赖这些键
RPS_PERIODS = [5, 10, 20, 30, 60, 120]
# 对齐通达信「板块指数RPS」的周期口径，只增列不改主口径
RPS_PERIODS_TDX = [5, 10, 15, 20, 50]
ALL_PERIODS = sorted(set(RPS_PERIODS) | set(RPS_PERIODS_TDX))

# RPS_DATA_DIR 只用于测试/试运行，避免把试跑结果写进 cron 依赖的真实快照
OUTPUT_DIR = Path(os.environ.get("RPS_DATA_DIR") or Path(__file__).parent / "data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_DIR = OUTPUT_DIR / "history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
KLINE_CACHE_DIR = OUTPUT_DIR / "kline_cache"
KLINE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

BASE_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
BASE_BOARD_LIST = "https://push2.eastmoney.com/api/qt/clist/get"

# 代理抖动时整轮请求会一起失败，靠两道闸门兜底：
#   连通性预检失败 → 立刻退出，不跑满 550 次超时
#   覆盖率低于 MIN_COVER_RATIO → 不覆盖上一份可用快照
MIN_COVER_RATIO = 0.6
MIN_BOARDS = 300
PROBE_BOARDS = 3
# 连续失败这么多板块就判定数据源整体不可用，不再把 550 次超时跑满
MAX_STREAK_FAIL = 25


PIN_HOSTS = ("push2.eastmoney.com", "push2his.eastmoney.com")
DOH_ENDPOINTS = ("https://223.5.5.5/resolve", "https://dns.google/resolve")
# 东财 push2 走 trafficmanager，不同 CDN 节点表现差别很大(同一时刻有节点 200、有节点 502)，
# DoH 拿到的又只是其中一两个，所以候选池要合并多个来源，再逐个实测筛掉坏节点。
FALLBACK_IPS = {
    "push2.eastmoney.com": ["120.79.191.232", "119.3.232.150", "120.76.218.228", "101.226.30.206", "61.129.129.196"],
    "push2his.eastmoney.com": ["120.79.191.232", "119.3.232.150", "120.76.218.228", "117.184.40.129", "103.220.167.80"],
}
PROBE_SPECS = {
    "push2.eastmoney.com": (BASE_BOARD_LIST, {"pn": "1", "pz": "1", "fltt": "2", "invt": "2",
                                              "fid": "f3", "fs": "m:90 t:3 f:!50", "fields": "f12"}),
    "push2his.eastmoney.com": (BASE_KLINE, {"secid": "90.BK1031", "fields1": "f1", "fields2": "f51,f53",
                                            "klt": "101", "fqt": "1", "beg": "20260101", "end": "20261231"}),
}
_pinned_ips = {}
_pinned_attempted = False
_pin_slot = {}
_direct_sess = None


def _doh_lookup(host):
    sess = requests.Session()
    sess.trust_env = False
    ips = []
    for url in DOH_ENDPOINTS:
        try:
            answers = (sess.get(url, params={"name": host, "type": "A"}, timeout=6).json() or {}).get("Answer") or []
        except Exception:
            continue
        for a in answers:
            val = str(a.get("data", ""))
            if a.get("type") == 1 and val.split(".")[0].isdigit() and val not in ips:
                ips.append(val)
    return ips


def _ip_probe(host, ip):
    """把解析临时锁死到这一个 IP，看它能不能真出数据。"""
    saved = _pinned_ips.get(host)
    _pinned_ips[host] = [ip]
    try:
        url, params = PROBE_SPECS[host]
        return _http_get(url, params, 5).status_code == 200
    except Exception:
        return False
    finally:
        if saved:
            _pinned_ips[host] = saved


def pin_eastmoney_dns():
    """接管这两个域名的解析，其余域名不受影响。"""
    global _pinned_attempted
    _pinned_attempted = True
    for host in PIN_HOSTS:
        pool = _doh_lookup(host)
        pool += [ip for ip in FALLBACK_IPS.get(host, []) if ip not in pool]
        if pool:
            _pinned_ips[host] = pool
            _pin_slot[host] = 0
    if not _pinned_ips:
        print("  ⚠️ DoH 也没解析到东财真实 IP，保持原解析")
        return False

    real_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):
        ips = _pinned_ips.get(host)
        if ips:
            host = ips[_pin_slot.get(host, 0) % len(ips)]
        return real_getaddrinfo(host, *args, **kwargs)

    socket.getaddrinfo = getaddrinfo

    # 先实测再定池：坏节点直接踢掉，免得把整轮 retries 耗在连不通的 IP 上
    for host in list(_pinned_ips):
        pool = _pinned_ips[host][:4]
        good = [ip for ip in pool if _ip_probe(host, ip)]
        detail = f"{host}: 可用 {len(good)}/{len(pool)}"
        if good:
            _pinned_ips[host] = good
            _pin_slot[host] = 0
        print("  🔌 " + detail)
    print("  🔌 绑定节点 " + "  ".join(f"{h}→{'/'.join(v)}" for h, v in _pinned_ips.items()))
    return True


def rotate_eastmoney_ip():
    """同一时刻不同出口 IP 表现不一致(有的 200 有的 502)，失败就换下一个再试。"""
    for host, ips in _pinned_ips.items():
        if len(ips) > 1:
            _pin_slot[host] = _pin_slot.get(host, 0) + 1


def _http_get(url, params, timeout):
    global _direct_sess
    if not _pinned_ips:
        return requests.get(url, params=params, timeout=timeout)
    if _direct_sess is None:
        _direct_sess = requests.Session()
        _direct_sess.trust_env = False   # 走代理会让上游重新解析回假 IP，必须直连
    return _direct_sess.get(url, params=params, timeout=timeout)


def _get_json(url, params, retries=4, pause=1.5, timeout=10):
    """东财接口在代理断连时抛 ProxyError/RemoteDisconnected，重试后仍失败返回 None。"""
    for attempt in range(retries):
        try:
            resp = _http_get(url, params, timeout)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        if attempt < retries - 1:
            rotate_eastmoney_ip()
            time.sleep(pause)
    if not _pinned_attempted and pin_eastmoney_dns():
        return _get_json(url, params, retries=2, pause=pause, timeout=timeout)
    return None


def _diff_of(payload):
    data = (payload or {}).get("data") or {}
    diff = data.get("diff") or []
    return list(diff.values()) if isinstance(diff, dict) else diff


# ─── 获取概念板块列表 ───
def fetch_concept_boards(max_pages=15):
    all_boards = []
    for page in range(1, max_pages + 1):
        params = {
            "pn": page, "pz": 100, "po": "1", "np": "1", "fltt": "2", "invt": "2",
            "fid": "f3", "fs": "m:90 t:3 f:!50",
            "fields": "f2,f3,f4,f12,f14"
        }
        items = _diff_of(_get_json(BASE_BOARD_LIST, params))
        if not items:
            if page > 1:
                print(f"    板块列表止于第 {page - 1} 页(第 {page} 页重试后仍无数据)")
            break
        for item in items:
            if item.get("f12"):
                all_boards.append({"code": item["f12"], "name": item["f14"]})
        if len(items) < 100:
            break
    return all_boards


def load_boards_snapshot():
    """clist 不可用时用上一份快照的板块名单：算 RPS 只需要 code/name，名单不会天天变。"""
    for path in (OUTPUT_DIR / "sector_rps.prev.json", OUTPUT_DIR / "sector_rps.json"):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        boards = [{"code": s["code"], "name": s["name"]}
                  for s in payload.get("sectors", []) if s.get("code") and s.get("name")]
        if len(boards) >= MIN_BOARDS:
            print(f"  ↩️ 名单来源 {path.name}({len(boards)} 个，快照日期 {payload.get('date')})，K线仍走实时接口")
            return boards
    return []


# ─── 获取板块资金流(主力净流入) ───
# 单次 clist/get 请求即同时返回今日(f62/f184)、5日(f164/f165)、10日(f174/f175)，
# stat 参数只切换服务端排序口径、不影响字段填充，因此不需要按窗口重复请求。
# 净额字段单位是元，净占比字段已是 %。
FUND_FIELDS = "f12,f14,f62,f184,f164,f165,f174,f175"


def _fund_val(raw, scale=1.0):
    try:
        if raw in (None, "-", ""):
            return np.nan
        return float(raw) * scale
    except (TypeError, ValueError):
        return np.nan


def fetch_fund_flow(max_pages=12, retries=6):
    rows = {}
    for page in range(1, max_pages + 1):
        params = {
            "pn": page, "pz": 100, "po": "1", "np": "1", "fltt": "2", "invt": "2",
            "fid": "f62", "fs": "m:90 t:3 f:!50", "stat": "1",
            "fields": FUND_FIELDS,
        }
        payload = _get_json(BASE_BOARD_LIST, params, retries=retries, pause=2)
        data = (payload or {}).get("data")
        if not data:
            print(f"    资金流第 {page} 页获取失败，跳过该页")
            continue
        items = _diff_of(payload)
        if not items:
            break
        for it in items:
            code = it.get("f12")
            if not code:
                continue
            rows[code] = {
                "mf_today": _fund_val(it.get("f62"), 1e-8),
                "mf_today_pct": _fund_val(it.get("f184")),
                "mf_5": _fund_val(it.get("f164"), 1e-8),
                "mf_5_pct": _fund_val(it.get("f165")),
                "mf_10": _fund_val(it.get("f174"), 1e-8),
                "mf_10_pct": _fund_val(it.get("f175")),
            }
        if len(rows) >= (data.get("total") or 0):
            break

    if not rows:
        return None
    df = pd.DataFrame.from_dict(rows, orient="index").reset_index(names="code")
    print(f"    资金流获取 {len(df)} 个板块主力净流入")
    return df


# ─── 资金第二来源：datacenter-web ───
# push2 与 datacenter-web 是不同 CDN 池：2026-11-25 晚 push2 全部节点 502 时，这里照常出 433 个板块。
# 口径已核对：与 clist f184 在 336 个可比板块上，当日主力净占比中位差 0.0000pp（最大 0.36pp）。
# 局限：该报表只存"当日"一天，5/10 日窗口只能靠 push2 或下面的本地累计。
DC_FUND_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
DC_FUND_REPORT = "RPT_CONCEPT_FUNDFLOW"
MONEY_LOG = HISTORY_DIR / "money_daily.csv"
MONEY_LOG_DAYS_MIN = 5      # 攒满 5 个交易日才开始出本地 5 日窗口
MONEY_LOG_MIN_BOARDS = 50   # 凑满窗口的板块太少时不值得一用，宁可显示缺失


def fetch_fund_datacenter(retries=4):
    rows, page, dc_date = {}, 1, None
    while page <= 5:
        params = {"reportName": DC_FUND_REPORT, "columns": "ALL", "pageSize": "500",
                  "pageNumber": str(page), "source": "WEB", "client": "WEB"}
        payload = _get_json(DC_FUND_URL, params, retries=retries, pause=2)
        res = (payload or {}).get("result") or {}
        items = res.get("data") or []
        if not items:
            print(f"    资金兜底第 {page} 页未取到" + ("" if payload else "（接口整体不可用）"))
            break
        for it in items:
            code = it.get("BOARD_CODE")
            if not code:
                continue
            # 东财口径的"主力" = 超大单 + 大单
            net = (it.get("SUPERDEAL_NET") or 0) + (it.get("BIGDEAL_NET") or 0)
            pct = (it.get("SUPERDEAL_NET_RATIO") or 0) + (it.get("BIGDEAL_NET_RATIO") or 0)
            rows[code] = {"mf_today": round(net * 1e-8, 4), "mf_today_pct": round(pct, 4)}
            dc_date = (it.get("TRADE_DATE") or "")[:10]
        if page >= (res.get("pages") or 1):
            break
        page += 1
    if not rows:
        return None, None
    df = pd.DataFrame.from_dict(rows, orient="index").reset_index(names="code")
    print(f"    资金兜底(datacenter) {len(df)} 个板块，数据日期 {dc_date}")
    return df, dc_date


def fill_from_frame(rps_df, add_df, cols, label):
    """只填 rps_df 里为空的那些格，绝不覆盖 push2 已经取到的值。"""
    if add_df is None or add_df.empty:
        return rps_df, 0
    merged = rps_df[["code"]].merge(add_df, on="code", how="left", suffixes=("", "_alt"))
    filled = 0
    for col in cols:
        before = rps_df[col].isna()
        rps_df[col] = rps_df[col].where(~before, merged[col])
        filled = max(filled, int((before & rps_df[col].notna()).sum()))
    if filled:
        print(f"    ↩️ {label} 补上 {filled} 个板块的 {'/'.join(cols)}")
    return rps_df, filled


def append_money_daily(rps_df, data_date):
    """逐日累存当日主力净额与成交额；攒够 5 天后 5 日窗口不再依赖 push2 可用性。"""
    keep = rps_df.loc[rps_df["mf_today"].notna(), ["code", "name", "mf_today", "mf_today_pct", "amount"]].copy()
    if keep.empty:
        return None
    keep.insert(0, "date", data_date)
    old = None
    if MONEY_LOG.exists():
        try:
            old = pd.read_csv(MONEY_LOG, dtype={"code": str})
        except Exception as exc:
            print(f"    ⚠️ 资金累计表读不动({exc.__class__.__name__})，本轮重建")
    frames = []
    if old is not None and not old.empty:
        frames.append(old[old["date"] != data_date])   # 只丢旧的同日行，本轮这份必须留下
    if not keep.empty:
        frames.append(keep)
    out = pd.concat(frames, ignore_index=True)
    out.to_csv(MONEY_LOG, index=False, encoding="utf-8-sig")
    return out


def mf5_from_log(log, data_date, need=MONEY_LOG_DAYS_MIN, min_boards=MONEY_LOG_MIN_BOARDS):
    """近 need 个交易日窗口：净额除以同期成交额合计，与东财 5 日净占比同式。"""
    if log is None or log.empty:
        return None
    days = sorted(d for d in log["date"].unique() if d <= data_date)[-need:]
    if len(days) < need:
        print(f"    资金累计表只有 {len(days)}/{need} 天，5 日窗口继续等 push2")
        return None
    if days[-1] != data_date:
        print(f"    ⚠️ 资金累计表最新只到 {days[-1]}，不含 {data_date}，本轮不用它补 5 日窗口")
        return None
    sub = log[log["date"].isin(days)]
    grp = sub.groupby("code")
    full = grp["date"].nunique()[lambda x: x == need].index
    if len(full) < min_boards:
        print(f"    资金累计表里凑满 {need} 天的板块只有 {len(full)} 个(<{min_boards})，不足以来补 5 日窗口")
        return None
    net = grp["mf_today"].sum().reindex(full)
    turn = grp["amount"].sum().reindex(full).replace(0, np.nan)
    print(f"    ↩️ 用本地累计算 5 日窗口（{days[0]}~{days[-1]}，{len(full)} 个板块）")
    return pd.DataFrame({"code": full, "mf_5": net.round(4).values,
                         "mf_5_pct": (net / turn * 100).round(4).values})


MONEY_COLS = ("mf_today", "mf_today_pct", "mf_5", "mf_5_pct", "mf_10", "mf_10_pct")


def load_prev_money(json_path, data_date):
    """读上一份快照的资金列，只认同一个数据日期——跨日结转会算出假资金。"""
    try:
        prev = json.loads(Path(json_path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if prev.get("date") != data_date:
        return None
    rows = {s.get("code"): {c: s.get(c) for c in MONEY_COLS} for s in prev.get("sectors", [])}
    return rows or None


def carry_forward_money(rps_df, prev_money):
    """本轮没取到的资金格，沿用同日上一份快照的值：重跑只能补数，不能把已经补好的抹掉。"""
    if not prev_money:
        return rps_df
    for col in MONEY_COLS:
        if col not in rps_df.columns:
            rps_df[col] = np.nan
        blank = rps_df[col].isna()
        if not blank.any():
            continue
        rps_df.loc[blank, col] = rps_df.loc[blank, "code"].map(
            {c: (v or {}).get(col) for c, v in prev_money.items()})
    kept = int(rps_df["mf_5_pct"].notna().sum())
    print(f"    ↪️ 同日结转后资金覆盖: 5日 {kept} 个 / 当日 "
          f"{int(rps_df['mf_today_pct'].notna().sum())} 个")
    return rps_df


def rank_money(rps_df):
    """净占比排名 + 交叉信号；任何一次补数之后都要重跑，否则分位还是按旧分母算的。"""
    for src, out in (("mf_5_pct", "MF5_rank"), ("mf_today_pct", "MFT_rank")):
        rank = rps_df[src].rank(method="min", ascending=True)
        valid = rps_df[src].notna().sum()
        rps_df[out] = (rank / valid * 100).round(1) if valid else np.nan

    rps_df["mf_5v10"] = (rps_df["mf_5_pct"] - rps_df["mf_10_pct"]).round(2)

    turn = rps_df["RPS_5v10"] > 0
    inflow = rps_df["mf_5_pct"] > 0
    # NaN 参与比较恒为 False，不先排除 notna 会把"无资金数据"误判成背离
    known = rps_df["mf_5_pct"].notna()
    rps_df["money_sig"] = np.select(
        [known & turn & inflow,
         known & turn & ~inflow,
         known & (~turn) & inflow & (rps_df["MF5_rank"] >= 85)],
        ["confirm", "diverge", "accum"], default="")
    return rps_df


# ─── 板块K线本地缓存 ───
# 一轮要取 550 个板块，代理半路断掉时缓存能让下一次运行(13:50 补跑或次日 08:30 定版)接着跑完
def _kline_cache_path(board_code):
    return KLINE_CACHE_DIR / f"{board_code}.csv"


def _read_kline_cache(board_code):
    path = _kline_cache_path(board_code)
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
        if not len(df):
            return None
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
    except Exception:
        return None


def _write_kline_cache(board_code, df):
    try:
        df.assign(date=df["date"].dt.strftime("%Y-%m-%d")).to_csv(
            _kline_cache_path(board_code), index=False, encoding="utf-8")
    except Exception:
        pass


def _fetch_kline_remote(board_code, retries=2):
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
        payload = _get_json(BASE_KLINE, params, retries=retries, pause=1.0)
        klines = ((payload or {}).get("data") or {}).get("klines") or []
        if not klines:
            return None
        records = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 3:
                # fields2: f51日期 f52开 f53收 f54高 f55低 f56量 f57额 → parts[6] 是成交额(元)
                records.append({
                    "date": parts[0],
                    "close": float(parts[2]),
                    "amount": float(parts[6]) if len(parts) >= 7 else np.nan,
                })
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
    except Exception:
        return None


# ─── 获取单个板块K线 ───
def fetch_board_kline(board_code, asof=None, use_cache=True, retries=2):
    cache = _read_kline_cache(board_code) if use_cache else None
    if cache is not None and len(cache) >= 120 and asof is not None and cache["date"].iloc[-1] >= asof:
        return cache
    df = _fetch_kline_remote(board_code, retries=retries)
    if df is None:
        return cache if cache is not None and len(cache) >= 120 else None
    if cache is not None:
        df = (pd.concat([cache, df], ignore_index=True)
              .drop_duplicates("date", keep="last")
              .sort_values("date").reset_index(drop=True))
    _write_kline_cache(board_code, df)
    return df if len(df) >= 120 else None


def probe_asof_date(boards):
    """确认数据源最新交易日，顺带当连通性预检：3 个板块全取不到就判定本轮不可用。"""
    dates = []
    for board in boards[:PROBE_BOARDS]:
        df = fetch_board_kline(board["code"], asof=None, use_cache=False)
        if df is not None and len(df):
            dates.append(df["date"].iloc[-1])
    return max(dates) if dates else None


# ─── 并发获取所有K线 ───
def fetch_all_klines(boards, asof=None):
    print(f"  并发获取 {len(boards)} 个板块K线...")
    kline_data = {}
    lock = threading.Lock()
    streak = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_code = {executor.submit(fetch_board_kline, b["code"], asof=asof): b for b in boards}
        done = 0
        for future in concurrent.futures.as_completed(future_to_code, timeout=1800):
            board = future_to_code[future]
            done += 1
            if done % 100 == 0:
                print(f"    进度: {done}/{len(boards)}")
            try:
                df = future.result()
            except Exception:
                df = None
            with lock:
                if df is None:
                    streak += 1
                else:
                    streak = 0
                    kline_data[board["code"]] = df
                halted = streak >= MAX_STREAK_FAIL
            if halted:
                print(f"    ❌ 连续 {streak} 个板块取不到K线，判定行情源不可用，中断本轮")
                for fut in future_to_code:
                    fut.cancel()
                break
    print(f"  成功: {len(kline_data)}/{len(boards)}")
    return kline_data


# ─── 计算RPS ───
def calculate_rps(kline_data, board_info, periods=ALL_PERIODS):
    results = []
    for code, df in kline_data.items():
        close = df["close"]
        latest = close.iloc[-1]
        name = next((b["name"] for b in board_info if b["code"] == code), code)

        row = {"code": code, "name": name, "latest_date": df["date"].iloc[-1].strftime("%Y-%m-%d"), "close": round(latest, 2)}
        amount = df["amount"].dropna() if "amount" in df else pd.Series(dtype=float)
        if len(amount):
            row["amount"] = round(float(amount.iloc[-1]) / 1e8, 2)
            base = amount.iloc[-6:-1] if len(amount) >= 6 else amount.iloc[:-1]
            row["amount_avg5"] = round(float(base.mean()) / 1e8, 2) if len(base) else np.nan
        else:
            row["amount"] = np.nan
            row["amount_avg5"] = np.nan
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

    # 综合RPS：仍用原 6 周期，保证与历史快照、HTML 面板口径一致
    rps_df["RPS_avg"] = rps_df[[f"RPS{p}" for p in RPS_PERIODS]].mean(axis=1).round(1)
    # 通达信口径综合值
    rps_df["RPS_tdx"] = rps_df[[f"RPS{p}" for p in RPS_PERIODS_TDX]].mean(axis=1).round(1)

    # RPS变化 (短期vs中期)
    rps_df["RPS_5v20"] = (rps_df["RPS5"] - rps_df["RPS20"]).round(1)
    rps_df["RPS_20v60"] = (rps_df["RPS20"] - rps_df["RPS60"]).round(1)
    rps_df["RPS_5v60"] = (rps_df["RPS5"] - rps_df["RPS60"]).round(1)
    rps_df["RPS_20v50"] = (rps_df["RPS20"] - rps_df["RPS50"]).round(1)
    rps_df["RPS_5v10"] = (rps_df["RPS5"] - rps_df["RPS10"]).round(1)

    # 短线转强分档，与 HTML 高亮口径一致：lo=RPS5>RPS10，hi=且三周期峰值>95
    rps_df["turn_tier"] = np.where(rps_df["RPS_5v10"] > 0, "lo", "")
    peak = rps_df[["RPS5", "RPS10", "RPS20"]].max(axis=1)
    rps_df["turn_tier"] = np.where(
        (rps_df["RPS_5v10"] > 0) & (peak > 95), "hi", rps_df["turn_tier"])

    rps_df["amount_ratio5"] = (rps_df["amount"] / rps_df["amount_avg5"]).round(2)

    return rps_df


# ─── 并入板块资金流并给出资金/价格交叉信号 ───
def add_fund_flow(rps_df, mf_df):
    """把 push2 的三层资金字段并进来；缺列一律先建好，后续兜底补数才有地方写。"""
    mf_cols = ["mf_today", "mf_today_pct", "mf_5", "mf_5_pct", "mf_10", "mf_10_pct"]
    if mf_df is None or mf_df.empty:
        for c in mf_cols:
            rps_df[c] = np.nan
    else:
        rps_df = rps_df.merge(mf_df, on="code", how="left")
    for c in [c for c in mf_cols if c not in rps_df.columns]:
        rps_df[c] = np.nan
    return rank_money(rps_df)


# ─── 快照归档 + 强度持续性 ───
def detect_session(now=None):
    now = now or datetime.now()
    hhmm = now.strftime("%H:%M")
    return "intraday" if "09:15" <= hhmm < "15:05" else "final"


def archive_snapshot(rps_df, session):
    latest_date = rps_df["latest_date"].mode().iloc[0]
    cols = (["code", "name", "latest_date", "close", "amount", "amount_ratio5"]
            + [f"RPS{p}" for p in ALL_PERIODS] + ["RPS_avg", "RPS_tdx"]
            + ["RPS_5v10", "RPS_5v20", "mf_5", "mf_5_pct", "mf_today_pct", "MF5_rank", "money_sig"])
    path = HISTORY_DIR / f"concept_rps_{latest_date}_{session}.csv"
    rps_df[cols].to_csv(path, index=False, encoding="utf-8-sig")
    return path, latest_date


def load_history(keep=10):
    """同一 latest_date 优先取 final 快照，其次 intraday。返回 [(date, df)] 时间升序。"""
    frames = {}
    for path in HISTORY_DIR.glob("concept_rps_*.csv"):
        date, _, sess = path.stem[len("concept_rps_"):].rpartition("_")
        if sess not in ("final", "intraday"):
            continue
        if date not in frames or sess == "final":
            try:
                frames[date] = pd.read_csv(path)
            except Exception:
                continue
    return sorted(frames.items())[-keep:]


def add_persistence(rps_df, history):
    """连续强势天数 / 近期强势次数 / RPS_avg 较5次前变化 —— 需要历史快照才能算。"""
    if not history:
        rps_df["strong_streak"] = 0
        rps_df["days_ge90"] = 0
        rps_df["RPS_avg_chg5"] = np.nan
        return rps_df

    snaps = [(d, df.set_index("code")) for d, df in history]
    codes = rps_df["code"].tolist()

    streak = pd.Series(0, index=codes, dtype=float)
    alive = pd.Series(True, index=codes)
    for _, frame in reversed(snaps):
        rps5 = frame["RPS5"].reindex(codes)
        hit = (rps5 >= 85) & alive
        streak.loc[hit[hit].index] += 1
        alive &= rps5.fillna(-1) >= 85

    ge90 = pd.Series(0, index=codes, dtype=float)
    for _, frame in snaps[-10:]:
        hit = (frame["RPS_avg"].reindex(codes) >= 90).fillna(False)
        ge90.loc[hit[hit].index] += 1

    cur = rps_df.set_index("code")["RPS_avg"]
    base = snaps[-6][1] if len(snaps) >= 6 else None
    if base is not None:
        diff = (cur - base["RPS_avg"].reindex(codes)).round(1)
        rps_df["RPS_avg_chg5"] = rps_df["code"].map(diff)
    else:
        rps_df["RPS_avg_chg5"] = np.nan

    rps_df["strong_streak"] = rps_df["code"].map(streak).fillna(0).astype(int)
    rps_df["days_ge90"] = rps_df["code"].map(ge90).fillna(0).astype(int)
    return rps_df


# ─── 可视化 ───
def plot_rps(rps_df, periods=RPS_PERIODS):
    import matplotlib
    matplotlib.use("Agg")  # cron 无 GUI 会话，默认后端在 launchd/cron 下会起不来
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    
    font_path = "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/86ba2c91f017a3749571a82f2c6d890ac7ffb2fb.asset/AssetData/PingFang.ttc"
    # 该路径带 macOS 版本哈希，系统升级后可能失效；缺字体只影响图片，不该拖垮快照
    if os.path.exists(font_path):
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
    all_periods = sorted(set(periods) | set(ALL_PERIODS))
    cols = (["code", "name", "latest_date", "close", "amount", "amount_avg5", "amount_ratio5"]
            + [f"ret_{p}" for p in all_periods] + [f"RPS{p}" for p in all_periods]
            + ["RPS_avg", "RPS_tdx", "RPS_5v10", "RPS_5v20", "RPS_20v60", "RPS_5v60", "RPS_20v50",
               "turn_tier", "strong_streak", "days_ge90", "RPS_avg_chg5"]
            + ["mf_today", "mf_today_pct", "mf_5", "mf_5_pct", "mf_10", "mf_10_pct",
               "MF5_rank", "MFT_rank", "mf_5v10", "money_sig"])
    rps_df[[c for c in cols if c in rps_df.columns]].to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n  完整数据: {csv_path}")

    # 价格转强 × 资金确认 四象限
    if "money_sig" in rps_df.columns and rps_df["mf_5_pct"].notna().any():
        has_mf = rps_df["mf_5_pct"].notna()
        print("\n" + "="*100)
        print("  💰 RPS转强 × 主力资金 交叉")
        print("="*100)
        pos = int((rps_df.loc[has_mf, "mf_5_pct"] > 0).sum())
        print(f"  有资金数据的板块 {int(has_mf.sum())} 个，其中 5日主力净流入为正 {pos} 个"
              f" ({pos / max(1, int(has_mf.sum())) * 100:.0f}%)")
        for label, sig in (("转强+资金确认(可交易候选)", "confirm"),
                           ("转强+资金流出(背离，剔除)", "diverge"),
                           ("未转强+资金最强(潜伏吸筹)", "accum")):
            hit = rps_df[rps_df["money_sig"] == sig].sort_values("mf_5_pct", ascending=False)
            print(f"\n  {label:<24} {len(hit):>3} 个")
            if not hit.empty:
                print(f"  {'板块':<18} RPS5   RPS10  RPS20  Δ5-10  5日净占比  5日净额   资金分位")
                print("  " + "-" * 84)
                for _, row in hit.head(12).iterrows():
                    print(f"  {row['name']:<18} {row['RPS5']:>5.1f}  {row['RPS10']:>5.1f}  "
                          f"{row['RPS20']:>5.1f}  {row['RPS_5v10']:>+5.1f}  "
                          f"{row['mf_5_pct']:>+7.2f}%  {row['mf_5']:>+7.2f}亿  {row['MF5_rank']:>6.1f}")
    
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

    # 通达信口径 (RPS 5/10/15/20/50) TOP15
    print("\n" + "=" * 100)
    print("  通达信口径 RPS(5/10/15/20/50) TOP15")
    print("=" * 100)
    if "RPS_tdx" in rps_df.columns:
        tdx_cols = [f"RPS{p}" for p in RPS_PERIODS_TDX]
        top = rps_df.nlargest(15, "RPS_tdx")
        print(f"  {'板块':<16} {'额(亿)':>7} {'额比':>5} " + " ".join(f"{c:>7}" for c in tdx_cols) + f" {'RPStdx':>7} {'连续':>4} {'90+':>4}")
        print("  " + "-" * 96)
        for _, row in top.iterrows():
            amt = f"{row['amount']:.1f}" if pd.notna(row.get("amount")) else "--"
            rat = f"{row['amount_ratio5']:.2f}" if pd.notna(row.get("amount_ratio5")) else "--"
            vals = " ".join(f"{row[c]:>7.1f}" if pd.notna(row.get(c)) else f"{'--':>7}" for c in tdx_cols)
            print(f"  {row['name']:<16} {amt:>7} {rat:>5} {vals} {row['RPS_tdx']:>7.1f} "
                  f"{row.get('strong_streak', 0):>4} {row.get('days_ge90', 0):>4}")

    # 强度分层：把"持续强"和"刚转强"分开，避免只看榜单排序
    print("\n" + "=" * 100)
    print("  强度分层")
    print("=" * 100)
    tiers = [
        ("持续强势 (RPS_tdx>=90 且 连续>=3日)", lambda d: (d["RPS_tdx"] >= 90) & (d["strong_streak"] >= 3)),
        ("新转强 (RPS_tdx>=85 且 RPS5-RPS20>+5)", lambda d: (d["RPS_tdx"] >= 85) & (d["RPS_5v20"] > 5)),
        ("放量确认 (RPS_tdx>=80 且 成交额比>=1.3)", lambda d: (d["RPS_tdx"] >= 80) & (d["amount_ratio5"] >= 1.3)),
        ("缩量新高 (RPS_tdx>=85 但 成交额比<0.8)", lambda d: (d["RPS_tdx"] >= 85) & (d["amount_ratio5"] < 0.8)),
        ("高位衰减 (RPS_tdx>=85 但 RPS_avg较5日前<-5)", lambda d: (d["RPS_tdx"] >= 85) & (d["RPS_avg_chg5"] < -5)),
    ]
    for label, cond in tiers:
        try:
            hit = rps_df[cond(rps_df)]
        except Exception:
            continue
        names = "  ".join(hit.nlargest(10, "RPS_tdx")["name"]) or "—"
        print(f"  {label:<40} {len(hit):>3} 个: {names}")


# ─── Main ───
def _prev_snapshot_date(json_path):
    """上一份可用快照的数据日期，用来判断这一轮到底有没有拿到新bar。"""
    try:
        with open(json_path, encoding="utf-8") as f:
            return json.load(f).get("date")
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="A股概念板块 RPS 分析")
    parser.add_argument("--session", choices=["intraday", "final", "auto"], default="auto",
                        help="intraday=盘中(东财当日K线未定版), final=收盘后定版; 默认按当前时间自动判断")
    args = parser.parse_args()
    session = detect_session() if args.session == "auto" else args.session

    print("=" * 60)
    print(f"  A股概念板块 RPS 分析  [{session}]")
    print("=" * 60)

    raw_boards = fetch_concept_boards()
    if len(raw_boards) < MIN_BOARDS:
        print(f"  ⚠️ 板块列表只取到 {len(raw_boards)} 个(<{MIN_BOARDS})，改用上一份可用快照的名单")
        raw_boards = load_boards_snapshot()
    if len(raw_boards) < MIN_BOARDS:
        print(f"  ❌ 板块名单不足 {MIN_BOARDS} 个(快照也只有 {len(raw_boards)})，保留上一份快照")
        return 1
    boards, excluded = split_boards(raw_boards)
    print(f"  概念板块 {len(raw_boards)} 个 → 题材口径保留 {len(boards)} 个 / 剔除 {len(excluded)} 个(技术形态·风格·宽基指数)")
    if excluded:
        pd.DataFrame(excluded).to_csv(OUTPUT_DIR / "excluded_boards.csv", index=False, encoding="utf-8-sig")

    asof = probe_asof_date(boards)
    if asof is None:
        print("  ❌ K线接口(push2his)无响应，保留上一份快照")
        return 1
    print(f"  数据源最新交易日: {asof:%Y-%m-%d}")

    kline_data = fetch_all_klines(boards, asof=asof)
    cover = len(kline_data) / max(len(boards), 1)
    if cover < MIN_COVER_RATIO:
        print(f"  ❌ K线覆盖 {len(kline_data)}/{len(boards)} = {cover:.0%}，低于 {MIN_COVER_RATIO:.0%}，保留上一份快照")
        return 1

    print("\n  计算RPS...")
    rps_df = calculate_rps(kline_data, boards)

    print("\n  获取板块资金流(主力净流入)...")
    fund_asof = datetime.now().strftime("%Y-%m-%d %H:%M")
    data_date = asof.strftime("%Y-%m-%d")
    # 快照待会被覆盖，先把上一份的资金列留在内存里做同日结转
    prev_money = load_prev_money(OUTPUT_DIR / "sector_rps.json", data_date)
    fund_df = fetch_fund_flow()
    if fund_df is None:
        print("  ⚠️  资金流(push2)本轮未取到，改用 datacenter 兜底(RPS 仍照常出快照)")
    rps_df = add_fund_flow(rps_df, fund_df)

    # push2 挂了就补当日那一层；5 日/10 日只能等 push2 或靠本地累计满 5 天
    dc_df, dc_date = fetch_fund_datacenter()
    rps_df, _ = fill_from_frame(rps_df, dc_df, ["mf_today", "mf_today_pct"], "datacenter 当日")
    money_log = append_money_daily(rps_df, data_date)
    rps_df, _ = fill_from_frame(rps_df, mf5_from_log(money_log, data_date),
                                ["mf_5", "mf_5_pct"], "本地累计 5 日")
    rps_df = carry_forward_money(rps_df, prev_money)
    rps_df = rank_money(rps_df)

    snapshot_path, snapshot_date = archive_snapshot(rps_df, session)
    print(f"  快照归档: {snapshot_path.name}")
    rps_df = add_persistence(rps_df, load_history())

    print("\n  生成可视化...")
    try:
        plot_rps(rps_df)
    except Exception as exc:
        print(f"  ⚠️  图片生成失败({exc.__class__.__name__}: {exc})，不影响 JSON 快照")

    print_summary(rps_df)

    # ── 导出 JSON 供可视化使用 ──
    json_path = OUTPUT_DIR / "sector_rps.json"
    prev_date = _prev_snapshot_date(json_path)
    if prev_date and snapshot_date <= prev_date:
        print(f"  ⚠️  数据日期未前进(仍是 {prev_date})，东财当日K线可能尚未生成")
    if json_path.exists():
        shutil.copy2(json_path, json_path.with_suffix(".prev.json"))
    export_data = {
        "date": snapshot_date,
        "session": session,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "fund_asof": fund_asof if fund_df is not None else None,
        "kline_cover": f"{len(kline_data)}/{len(boards)}",
        "universe": {"total": len(raw_boards), "theme": len(boards), "excluded": len(excluded)},
        "sectors": []
    }
    for _, row in rps_df.iterrows():
        # 模板用到的键沿用 0 兜底(历史行为)，新键才允许 null，避免 JS 端 toFixed 报错
        def num(key, digits=1, na=0):
            val = row.get(key)
            return round(float(val), digits) if pd.notna(val) else na
        export_data["sectors"].append({
            "code": row["code"],
            "name": row["name"],
            "close": row["close"],
            "latest_date": row["latest_date"],
            "amount": num("amount", 2, None),
            "amount_avg5": num("amount_avg5", 2, None),
            "amount_ratio5": num("amount_ratio5", 2, None),
            **{f"ret_{p}": num(f"ret_{p}", 2) for p in RPS_PERIODS},
            **{f"RPS{p}": num(f"RPS{p}") for p in RPS_PERIODS},
            **{f"ret_{p}": num(f"ret_{p}", 2, None) for p in RPS_PERIODS_TDX if p not in RPS_PERIODS},
            **{f"RPS{p}": num(f"RPS{p}", 1, None) for p in RPS_PERIODS_TDX if p not in RPS_PERIODS},
            "RPS_avg": num("RPS_avg"),
            "RPS_tdx": num("RPS_tdx", 1, None),
            "RPS_5v10": num("RPS_5v10"),
            "RPS_5v20": num("RPS_5v20"),
            "RPS_20v60": num("RPS_20v60"),
            "RPS_5v60": num("RPS_5v60"),
            "RPS_20v50": num("RPS_20v50", 1, None),
            "strong_streak": num("strong_streak", 0),
            "days_ge90": num("days_ge90", 0),
            "RPS_avg_chg5": num("RPS_avg_chg5", 1, None),
            "turn_tier": row.get("turn_tier", "") or "",
            "money_sig": row.get("money_sig", "") or "",
            **{k: num(k, 2, None) for k in
               ("mf_today", "mf_today_pct", "mf_5", "mf_5_pct", "mf_10", "mf_10_pct",
                "MF5_rank", "MFT_rank", "mf_5v10")},
        })
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
    print(f"  数据JSON: {json_path} ({len(export_data['sectors'])} sectors, session={session})")

    # 按交易日留档一份完整快照：sector_rps.json 是覆盖式的，历史回看只能靠这里
    hist_path = HISTORY_DIR / f"sector_rps_{export_data['date']}_{session}.json"
    hist_path.write_text(json.dumps(export_data, ensure_ascii=False), encoding="utf-8")
    print(f"  历史留档: {hist_path.name}")

    print("\n  完成!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
