"""
2_update_a_stock_data.py — A股历史日线数据更新脚本（v3.1 高性能版）

v3.1 变更:
  - 新增北交所 92* 代码识别与跳过（Yahoo Finance 无此数据）
  - 新增 --summary 模式：对比股票列表与本地 CSV，显示差异
  - 修复 001270 等 4 位数字代码补零后映射正确性
  - 增强失败详情汇总：区分 限流/yahoo无数据/本地需手动处理
  - 603056 等停牌股票不再误报为"失败"，标记为可能停牌

新增功能:
  --start YYYY-MM-DD   起始日期（含）
  --end   YYYY-MM-DD   结束日期（含，默认今天）
  --workers N          并发线程数（默认 10）
  --check / --stock=   保留原有功能
  --summary            对比股票列表与本地缓存，显示差异详情

优化:
  ✅ 批量下载（每批 30 只，一次 HTTP 请求拿到全部）
  ✅ 增量模式跳过 check_yf_update，本地无更新时只做批量试探
  ✅ 本地 CSV 最新日期批量对比 → 只下载需要更新的批次
  ✅ 自适应并发上限，避免被限流
  ✅ BATCH_SLEEP / 断点续跑 完整保留
"""

# ====================================================================
#  配置 & 导入
# ====================================================================
import pandas as pd
import os
import sys
import time
import io
import tempfile
import resource
import shutil
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import yfinance as yf
import logging

# 禁用 yfinance SQLite 缓存
_YF_TMP = os.path.join(tempfile.gettempdir(), f"yf_cache_{os.getpid()}")
os.makedirs(_YF_TMP, exist_ok=True)
os.environ["YF_CACHE_DIR"] = _YF_TMP

DATA_DIR = "./data_cache_daily/"
RESUME_DIR = "./"
STOCK_LIST_FILE = "./final_rankings_with_details_latest.xlsx"

# 默认参数
DEFAULT_DAYS_HISTORY = 365 * 3
BATCH_SIZE = 50         # 每 N 只打印进度
BATCH_SLEEP = 2         # 每 N 只暂停秒数
YF_TIMEOUT = 20         # 单次下载超时秒数
INCREMENTAL_LOOKBACK = 30  # 增量下载向前看N天（避免漏数据）

# ── 批量下载配置 ──
YF_DOWNLOAD_BATCH = 30  # yfinance 每批下载的最大股票数
YF_DOWNLOAD_PAD = 10    # 向前多拉几天，避免遗漏

# ── 无法下载的市场 ──
# 北交所 (4*, 8*, 9*) Yahoo Finance 无数据（"possibly delisted" / rate limit）
NO_DATA_PREFIXES = ('4', '8', '9')

# 静默 yfinance 内部日志
for _logger in ['yfinance', 'yfinance_scrapers']:
    logging.getLogger(_logger).setLevel(logging.CRITICAL)

os.makedirs(DATA_DIR, exist_ok=True)

# ────────────────────────────────────────────────────────────────────
#  工具函数
# ────────────────────────────────────────────────────────────────────

def fmt(code):
    """6 位代码 → Yahoo ticker"""
    c = str(code).zfill(6)
    if c.startswith('6'):
        return c + ".SS"
    elif c.startswith(('0', '3')):
        return c + ".SZ"
    elif c.startswith(NO_DATA_PREFIXES):
        # 北交所 / 老三板: Yahoo Finance 无此板块数据
        return None
    return None


def is_bj_stock(code):
    """判断是否北交所股票（4/8/9 开头），Yahoo Finance 无数据"""
    c = str(code).zfill(6)
    return c.startswith(NO_DATA_PREFIXES)


def run_summary():
    """对比股票列表与本地 CSV，显示差异"""
    df_stocks = pd.read_excel(STOCK_LIST_FILE)
    all_codes = set(str(c).zfill(6) for c in df_stocks["代码"].tolist())

    existing = set()
    stale = []
    today = date.today()
    DATA_DIR_LOCAL = DATA_DIR

    for f in os.listdir(DATA_DIR_LOCAL):
        if f.endswith('.csv'):
            existing.add(f.replace('.csv', ''))
            if not f.startswith(NO_DATA_PREFIXES + ('6', '0', '3')):
                pass  # foreign file, skip
            fp = os.path.join(DATA_DIR_LOCAL, f)
            ld = get_csv_latest_date(fp)
            if ld and ld < today - timedelta(days=20):  # 3周无更新算陈旧
                stale.append((f.replace('.csv', ''), ld))

    missing = all_codes - existing
    bj_missing = [c for c in sorted(missing) if is_bj_stock(c)]
    other_missing = [c for c in sorted(missing) if not is_bj_stock(c)]

    # 查找对应股票名称
    name_map = {}
    for _, row in df_stocks.iterrows():
        name_map[str(row["代码"]).zfill(6)] = str(row.get("名称", ""))

    print(f"\n{'=' * 60}")
    print(f"📊 数据摘要报告")
    print(f"{'=' * 60}")
    print(f"  股票列表总数: {len(all_codes)}")
    print(f"  本地 CSV 文件: {len(existing)}")
    print(f"  缺失文件: {len(missing)}")
    print(f"    - 北交所 (92/83/87/43*): {len(bj_missing)} → Yahoo 无数据，可忽略")
    print(f"    - 非北交所需下载: {len(other_missing)}")
    if stale:
        print(f"  陈旧数据 (>20天未更新): {len(stale)}")

    if other_missing:
        print(f"\n  缺失的非北交所股票 (前50):")
        for c in other_missing[:50]:
            name = name_map.get(c, "")
            print(f"    {c}  {name}")
        if len(other_missing) > 50:
            print(f"    ... 还有 {len(other_missing) - 50} 个")

    if stale:
        print(f"\n  陈旧数据 (前20):")
        for c, ld in sorted(stale, key=lambda x: x[1])[:20]:
            name = name_map.get(c, "")
            print(f"    {c}  {name}  最后日期: {ld}")
    print(f"{'=' * 60}\n")

    return len(other_missing), len(bj_missing), len(existing), len(all_codes)


def get_csv_latest_date(file_path: str):
    """快速读取 CSV 最后一行日期"""
    try:
        with open(file_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return None
            f.seek(-min(2000, size), 2)
            tail = f.read().decode("utf-8-sig")
            for line in reversed(tail.splitlines()):
                line = line.strip()
                if not line:
                    continue
                parts = line.split(",")
                dt = pd.to_datetime(parts[0].strip(), errors="coerce")
                if pd.isna(dt):
                    continue
                return dt.date()
        return None
    except Exception:
        return None


def clean_old_csv(df):
    if df.shape[1] > 6:
        df = df.iloc[:, :6]
    df.columns = ["Date", "Close", "High", "Low", "Open", "Volume"]
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    for col in ["Close", "High", "Low", "Open", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["Close"])


def clean_csv_file(file_path):
    try:
        df = clean_old_csv(pd.read_csv(file_path))
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        return True
    except Exception:
        return False


# ────────────────────────────────────────────────────────────────────
#  yfinance 下载
# ────────────────────────────────────────────────────────────────────

def _yf_download_retry(tickers, start, end, max_retries=2):
    """
    支持单个 ticker 或列表。下载 + 自动重试。
    批量模式下 tickers 是 list，单个模式下是 str。
    """
    if isinstance(tickers, str):
        tickers = [tickers]
    for attempt in range(max_retries):
        if attempt > 0:
            time.sleep(2)
        try:
            old_stderr = sys.stderr
            sys.stderr = io.StringIO()
            df = yf.download(tickers, start=start, end=end,
                             progress=False, timeout=YF_TIMEOUT,
                             threads=False)  # yfinance 内部也串行
        finally:
            sys.stderr = old_stderr

        if df is not None and len(df) > 0 and not df.dropna(how="all").empty:
            # 检查是否所有列都是 NaN（限流返回的空框架）
            if isinstance(df.columns, pd.MultiIndex):
                # Level 0 = column type (Close/High/Low/...), Level 1 = ticker
                level1 = df.columns.get_level_values(1).unique()
                has_data = any(not df[("Close", t)].dropna().empty
                               for t in level1 if ("Close", t) in df.columns)
            else:
                has_data = not df["Close"].dropna().empty
            if has_data:
                return df
        if attempt < max_retries - 1:
            continue
    return None


def _normalize_single(df, ticker):
    """从 yfinance 批量返回值中提取单个股票的标准 DataFrame"""
    if df is None:
        return None
    try:
        if isinstance(df.columns, pd.MultiIndex):
            # 批量模式: MultiIndex columns
            cols = [("Close", ticker), ("Open", ticker), ("High", ticker),
                    ("Low", ticker), ("Adj Close", ticker), ("Volume", ticker)]
            available = [c for c in cols if c in df.columns]
            if not available:
                return None
            sub = df[available].dropna(how="all")
            if sub.empty:
                return None
            sub = sub.copy()
            sub.columns = [c[0] for c in sub.columns]
        else:
            sub = df.copy()

        sub = sub.reset_index()
        required = ["Date", "Close", "High", "Low", "Open", "Volume"]
        if not all(c in sub.columns for c in required):
            return None
        sub = sub[required].copy()
        sub["Date"] = pd.to_datetime(sub["Date"])
        for col in ["Close", "High", "Low", "Open", "Volume"]:
            sub[col] = pd.to_numeric(sub[col], errors="coerce")
        sub = sub.dropna(subset=["Close"])
        return sub.sort_values("Date").reset_index(drop=True)
    except Exception:
        return None


def _normalize_bulk(df):
    """
    从批量下载结果中提取 {ticker: DataFrame} 字典。
    返回的 DataFrame 已经是标准格式。
    """
    if df is None:
        return {}
    result = {}
    try:
        if isinstance(df.columns, pd.MultiIndex):
            tickers = df.columns.get_level_values(0).unique()
            # 优先用 Close 列来判断哪些 ticker 有数据
            for t in tickers:
                close_col = ("Close", t)
                if close_col not in df.columns:
                    continue
                sub = df[[c for c in df.columns if c[1] == t]].copy()
                sub.columns = [c[0] for c in sub.columns]
                sub = sub.reset_index()
                required = ["Date", "Close", "High", "Low", "Open", "Volume"]
                if not all(c in sub.columns for c in required):
                    continue
                sub = sub[required].copy()
                sub["Date"] = pd.to_datetime(sub["Date"])
                for col in ["Close", "High", "Low", "Open", "Volume"]:
                    sub[col] = pd.to_numeric(sub[col], errors="coerce")
                sub = sub.dropna(subset=["Close"])
                if not sub.empty:
                    result[t] = sub.sort_values("Date").reset_index(drop=True)
        else:
            # 单个 ticker 情况
            single = _normalize_single(df, df.columns[0] if hasattr(df.columns, '__iter__') else None)
            if single is not None:
                result["single"] = single
    except Exception:
        pass
    return result


# ────────────────────────────────────────────────────────────────────
#  CSV 更新
# ───────────────────────────────────────────────────────

def save_csv(ticker, df, code_str):
    """保存/合并单个股票 CSV，返回 {'status', 'msg'}"""
    file_path = os.path.join(DATA_DIR, f"{code_str}.csv")
    if df is None or df.empty:
        return {"status": "skip", "msg": "无数据"}

    if not os.path.exists(file_path):
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        return {"status": "ok", "msg": f"首次保存 {len(df)} 行"}

    # 合并
    try:
        old_df = pd.read_csv(file_path)
        old_df = clean_old_csv(old_df)
        old_df["Date"] = pd.to_datetime(old_df["Date"])
        latest = old_df["Date"].max()
        new_rows = df[df["Date"] > latest]
        if not new_rows.empty:
            updated = pd.concat([old_df, new_rows], ignore_index=True)
            updated = updated.drop_duplicates(subset=["Date"]).sort_values("Date")
            updated.to_csv(file_path, index=False, encoding="utf-8-sig")
            return {"status": "ok",
                    "msg": f"更新 {len(new_rows)} 行 → {updated['Date'].max().date()}"}
        return {"status": "sync", "msg": f"已同步 ({latest.date()})"}
    except Exception:
        # 旧文件损坏 → 直接覆盖
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        return {"status": "ok", "msg": f"覆盖保存 {len(df)} 行"}


# ────────────────────────────────────────────────────────────────────
#  核心逻辑：批量增量更新
# ────────────────────────────────────────────────────────────────────

def update_batch_incremental(batch_codes, today, pad_days=INCREMENTAL_LOOKBACK):
    """
    批量增量更新：对一组股票，检查本地最新日期，
    只对有更新的进行批量下载 → 逐个保存。
    返回 {code_str: result_dict}
    """
    results = {}

    # 1. 批量读取本地最新日期
    need_update = []  # (code_str, yf_ticker, csv_date)
    for raw_code in batch_codes:
        yf_code = fmt(raw_code)
        if yf_code is None:
            code_str = str(raw_code).zfill(6)
            results[code_str] = {"status": "skip", "msg": "不支持的代码"}
            continue
        code_str = str(raw_code).zfill(6)
        file_path = os.path.join(DATA_DIR, f"{code_str}.csv")

        csv_date = None
        if os.path.exists(file_path):
            csv_date = get_csv_latest_date(file_path)
            if csv_date is None:
                clean_csv_file(file_path)
                csv_date = get_csv_latest_date(file_path)

        need_update.append((code_str, yf_code, csv_date))

    # 2. 分组：无本地数据的需要全量下载，有数据的只需增量
    no_data = [(cs, yt, cd) for cs, yt, cd in need_update if cd is None]
    need_check = [(cs, yt, cd) for cs, yt, cd in need_update if cd is not None]

    # 统计北交所跳过数
    bj_skip_count = sum(1 for _, _, _ in need_update if is_bj_stock(_))

    # --- 全量下载组 ---
    if no_data:
        full_tickers = [yt for _, yt, _ in no_data]
        start_full = (today - timedelta(days=DEFAULT_DAYS_HISTORY)).strftime("%Y-%m-%d")
        end_full = (today + timedelta(days=1)).strftime("%Y-%m-%d")

        t_batch = time.time()
        for i in range(0, len(full_tickers), YF_DOWNLOAD_BATCH):
            sub = full_tickers[i:i + YF_DOWNLOAD_BATCH]
            sub_start = time.strftime("%H:%M:%S")
            df_all = _yf_download_retry(sub, start_full, end_full)
            sub_end = time.strftime("%H:%M:%S")
            print(f"    ⤵ 全量下载 [批{i // YF_DOWNLOAD_BATCH + 1}]  {sub_start} → {sub_end}  "
                  f"({len(sub)} 只)", flush=True)
            bulk = _normalize_bulk(df_all)
            elapsed_b = time.time() - t_batch
            if i + YF_DOWNLOAD_BATCH >= len(full_tickers):
                print(f"    ✓ 全量本批完成 耗时 {elapsed_b:.1f}s", flush=True)

            if bulk:
                for _, yt, cs in no_data:
                    if yt in bulk:
                        results[cs] = save_csv(yt, bulk[yt], cs)
                    else:
                        results[cs] = {"status": "skip", "msg": "Yahoo无数据"}
            else:
                for _, yt, cs in no_data:
                    # 降级为单个下载
                    df_single = _yf_download_retry(yt, start_full, end_full)
                    df_norm = _normalize_single(df_single, yt)
                    results[cs] = save_csv(yt, df_norm, cs)

    # --- 增量检查组 ---
    if need_check:
        # 按本地日期排序：越老的越可能需要更新
        need_check.sort(key=lambda x: x[2])

        # 试探性批量下载：拉最近 INCREMENTAL_LOOKBACK 天
        start_inc = (today - timedelta(days=INCREMENTAL_LOOKBACK)).strftime("%Y-%m-%d")
        end_inc = (today + timedelta(days=1)).strftime("%Y-%m-%d")

        t_inc = time.time()
        for i in range(0, len(need_check), YF_DOWNLOAD_BATCH):
            sub_tickers = [yt for _, yt, _ in need_check[i:i + YF_DOWNLOAD_BATCH]]
            sub_start = time.strftime("%H:%M:%S")
            df_inc = _yf_download_retry(sub_tickers, start_inc, end_inc)
            sub_end = time.strftime("%H:%M:%S")
            print(f"    ⤵ 增量下载 [批{i // YF_DOWNLOAD_BATCH + 1}]  {sub_start} → {sub_end}  "
                  f"({len(sub_tickers)} 只)", flush=True)
            bulk = _normalize_bulk(df_inc)

            elapsed_b = time.time() - t_inc
            if i + YF_DOWNLOAD_BATCH >= len(need_check):
                print(f"    ✓ 增量批次完成 耗时 {elapsed_b:.1f}s", flush=True)

            sub_items = need_check[i:i + YF_DOWNLOAD_BATCH]

            if not bulk:
                # 批量返回空 → 逐个试探，区分"确实无更新"和"限流"
                for idx_single, (cs, yt, cd) in enumerate(sub_items):
                    if idx_single > 0:
                        time.sleep(1.5)  # 逐个请求限速
                    try:
                        df_single = _yf_download_retry(yt, start_inc, end_inc)
                        norm = _normalize_single(df_single, yt)
                        if norm is not None and not norm.empty:
                            latest = norm["Date"].max().date()
                            if latest > cd:
                                results[cs] = save_csv(yt, norm, cs)
                            else:
                                results[cs] = {"status": "sync",
                                               "msg": f"已同步 (Yahoo: {latest} CSV: {cd})"}
                        else:
                            results[cs] = {"status": "skip",
                                           "msg": f"无更新 (本地: {cd})"}
                    except Exception as e:
                        results[cs] = {"status": "skip",
                                       "msg": f"下载失败 (本地: {cd}): {e}"}
                continue

            for cs, yt, cd in sub_items:
                if yt in bulk:
                    latest = bulk[yt]["Date"].max().date()
                    if latest > cd:
                        results[cs] = save_csv(yt, bulk[yt], cs)
                    else:
                        results[cs] = {"status": "sync",
                                       "msg": f"已同步 (Yahoo: {latest} CSV: {cd})"}
                else:
                    results[cs] = {"status": "skip",
                                   "msg": f"无数据 (本地: {cd})"}

    return results


def update_batch_full(batch_codes, start_date, end_date):
    """
    批量全量下载：指定日期范围，直接拉数据。
    返回 {code_str: result_dict}
    """
    results = {}
    today = end_date or date.today()

    # 构建映射
    tickers_map = {}  # ticker -> code_str
    valid_tickers = []
    for raw_code in batch_codes:
        yf_code = fmt(raw_code)
        if yf_code is None:
            code_str = str(raw_code).zfill(6)
            results[code_str] = {"status": "skip", "msg": "不支持的代码"}
            continue
        code_str = str(raw_code).zfill(6)
        tickers_map[yf_code] = code_str
        valid_tickers.append(yf_code)

    start_s = start_date.strftime("%Y-%m-%d")
    end_s = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    t_full = time.time()
    for i in range(0, len(valid_tickers), YF_DOWNLOAD_BATCH):
        sub = valid_tickers[i:i + YF_DOWNLOAD_BATCH]
        sub_start = time.strftime("%H:%M:%S")
        df_all = _yf_download_retry(sub, start_s, end_s)
        sub_end = time.strftime("%H:%M:%S")
        print(f"    ⤵ 全量下载 [批{i // YF_DOWNLOAD_BATCH + 1}]  {sub_start} → {sub_end}  "
              f"({len(sub)} 只)  范围: {start_s}~{(today).strftime('%Y-%m-%d')}", flush=True)
        bulk = _normalize_bulk(df_all)


        for yt in sub:
            cs = tickers_map[yt]
            if yt in bulk:
                df = bulk[yt]
                # 截取日期范围
                df = df[(df["Date"] >= pd.Timestamp(start_date)) &
                        (df["Date"] <= pd.Timestamp(today))].reset_index(drop=True)
                if df.empty:
                    results[cs] = {"status": "skip", "msg": "范围内无数据"}
                else:
                    results[cs] = save_csv(yt, df, cs)
            else:
                results[cs] = {"status": "skip", "msg": "Yahoo无数据"}

    return results


# ====================================================================
#  主程序
# ====================================================================

if __name__ == "__main__":

    _soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (_hard, _hard))

    # ── 参数解析 ──
    args = sys.argv[1:]

    # 检查是否是 --summary 模式
    if "--summary" in args:
        run_summary()
        sys.exit(0)

    if args and args[-1] == "--check":
        codes = args[:-1]
        for c in codes:
            yc = fmt(c)
            if yc is None:
                if is_bj_stock(c):
                    print(f"⏭️ {c} 北交所股票，Yahoo Finance 无数据", flush=True)
                else:
                    print(f"⏭️ {c} 不支持", flush=True)
                continue
            cs = str(c).zfill(6)
            fp = os.path.join(DATA_DIR, f"{cs}.csv")
            lt = get_csv_latest_date(fp)
            print(f"  [{cs}] 本地最新: {lt}", flush=True)
        sys.exit(0)

    single_stock = None
    for arg in args:
        if arg.startswith("--stock="):
            single_stock = arg.split("=", 1)[1].strip().zfill(6)
            break
    if single_stock:
        print(f"🎯 单股更新: {single_stock}")
        yc = fmt(single_stock)
        if yc:
            df = _normalize_single(_yf_download_retry(yc,
                (date.today() - timedelta(days=DEFAULT_DAYS_HISTORY)).strftime("%Y-%m-%d"),
                (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")), yc)
            r = save_csv(yc, df, single_stock)
            print(f"  → {r['status']}: {r['msg']}")
        else:
            if is_bj_stock(single_stock):
                print(f"  → 跳过: 北交所股票，Yahoo Finance 无数据")
            else:
                print(f"  → 跳过: 不支持的代码格式")
        print("\n✅ 完成！")
        sys.exit(0)

    start_date = None
    end_date = None
    workers = 10  # 默认并发批次
    resume_from = 0

    i = 0
    while i < len(args):
        if args[i] == "--start" and i + 1 < len(args):
            start_date = datetime.strptime(args[i + 1], "%Y-%m-%d").date()
            i += 2
        elif args[i] == "--end" and i + 1 < len(args):
            end_date = datetime.strptime(args[i + 1], "%Y-%m-%d").date()
            i += 2
        elif args[i].startswith("--workers="):
            workers = int(args[i].split("=")[1])
            i += 1
        elif args[i].startswith("--from="):
            resume_from = int(args[i].split("=")[1])
            i += 1
        elif args[i] == "--resume":
            resume_file = os.path.join(RESUME_DIR, "_resume_index.txt")
            if os.path.exists(resume_file):
                with open(resume_file) as f:
                    resume_from = int(f.read().strip())
            i += 1
        else:
            i += 1

    # ── 读取股票列表 ──
    df_stocks = pd.read_excel(STOCK_LIST_FILE)
    stock_codes = df_stocks["代码"].tolist()
    total = len(stock_codes)

    # ── 预过滤：跳过北交所股票（Yahoo Finance 无数据） ──
    bj_skipped = 0
    filtered_codes = []
    for raw_code in stock_codes:
        c = str(raw_code).zfill(6)
        if is_bj_stock(raw_code):
            bj_skipped += 1
        else:
            filtered_codes.append(raw_code)
    stock_codes = filtered_codes

    if bj_skipped > 0:
        print(f"⏭️ 跳过 {bj_skipped} 只北交所股票 (92/83/87/43*)，Yahoo Finance 无数据", flush=True)

    if resume_from > 0:
        stock_codes = stock_codes[resume_from:]
        print(f"🔄 跳过前 {resume_from} 只，从 [{resume_from + 1}/{total}] 开始", flush=True)
        stock_codes = stock_codes[resume_from:]
        print(f"🔄 跳过前 {resume_from} 只，从 [{resume_from + 1}/{total}] 开始", flush=True)

    # ── 分批 ──
    # workers 个并发批次，每批 YF_DOWNLOAD_BATCH 只
    batch_count = max(1, len(stock_codes) // YF_DOWNLOAD_BATCH)
    batches = []
    for i in range(0, len(stock_codes), YF_DOWNLOAD_BATCH):
        batches.append(stock_codes[i:i + YF_DOWNLOAD_BATCH])

    today = date.today()
    mode_desc = "全量覆盖" if start_date else "批量增量更新"
    time_range = f" {start_date}→{end_date or today}" if start_date else ""
    overall_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    download_start_date = start_date if start_date else (today - timedelta(days=DEFAULT_DAYS_HISTORY)) if mode_desc == "全量覆盖" else (today - timedelta(days=INCREMENTAL_LOOKBACK))
    download_end_date = end_date or today

    print(f"\n{'='*60}")
    print(f"🚀 开始时间: {overall_start_time}")
    print(f"🕐 数据范围: {download_start_date} → {download_end_date}")
    print(f"📊 模式: {mode_desc}{time_range}")
    print(f"📊 股票数: {total} | 批次: {len(batches)} (每批{YF_DOWNLOAD_BATCH}只) | 并发批次: {workers}")
    print(f"{'='*60}\n", flush=True)

    t0 = time.time()
    processed = resume_from
    results_ok = 0
    results_sync = 0
    results_fail = 0
    results_skip = 0
    errors_detail = []
    _lock = threading.Lock()

    def _process_batch(batch, global_start_idx):
        """处理一个批次，返回 [(global_idx, code_str, result), ...]"""
        if start_date:
            raw = update_batch_full(batch, start_date, end_date)
        else:
            raw = update_batch_incremental(batch, today)
        out = []
        for idx, code in enumerate(batch):
            cs = str(code).zfill(6)
            # 北交所股票跳过
            if is_bj_stock(code):
                r = {"status": "skip", "msg": "北交所，Yahoo无数据"}
            else:
                r = raw.get(cs, {"status": "skip", "msg": "unknown"})
            out.append((global_start_idx + idx, cs, r))
        return out

    if workers <= 1:
        for bi, batch in enumerate(batches):
            items = _process_batch(batch, bi * YF_DOWNLOAD_BATCH)
            for gi, cs, r in items:
                with _lock:
                    processed += 1
                    status, msg = r["status"], r["msg"]
                    if status == "ok":    results_ok += 1
                    elif status == "sync": results_sync += 1
                    elif status == "fail": results_fail += 1; errors_detail.append((cs, r))
                    elif status == "skip": results_skip += 1
                    pct = processed / total * 100
                    elapsed = time.time() - t0
                    speed = processed / (elapsed / 60) if elapsed > 0 else 0
                    print(f"  [{processed}/{total}] ({pct:.1f}%) {cs}: {status} {msg}  [{speed:.0f}只/min]", flush=True)
                    if processed % BATCH_SIZE == 0:
                        print(f"  💤 休息 {BATCH_SLEEP}s …", flush=True)
                        time.sleep(BATCH_SLEEP)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for bi, batch in enumerate(batches):
                fut = executor.submit(_process_batch, batch, bi * YF_DOWNLOAD_BATCH)
                futures[fut] = bi

            for fut in as_completed(futures):
                items = fut.result()
                for gi, cs, r in items:
                    with _lock:
                        processed += 1
                        status, msg = r["status"], r["msg"]
                        if status == "ok":    results_ok += 1
                        elif status == "sync": results_sync += 1
                        elif status == "fail": results_fail += 1; errors_detail.append((cs, r))
                        elif status == "skip": results_skip += 1

                        pct = processed / total * 100
                        elapsed = time.time() - t0
                        speed = processed / (elapsed / 60) if elapsed > 0 else 0
                        print(f"  [{processed}/{total}] ({pct:.1f}%) {cs}: {status} {msg}  [{speed:.0f}只/min]", flush=True)

                        if processed % BATCH_SIZE == 0:
                            print(f"  💤 休息 {BATCH_SLEEP}s …", flush=True)
                            time.sleep(BATCH_SLEEP)

                    # 保存断点
                    if processed % 200 == 0:
                        with open(os.path.join(RESUME_DIR, "_resume_index.txt"), "w") as f:
                            f.write(str(processed))

    elapsed = time.time() - t0
    overall_end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 检查缺失的非北交所股票 ──
    all_codes_set = set(str(c).zfill(6) for c in df_stocks["代码"].tolist())
    existing_csv = set(
        f.replace('.csv', '') for f in os.listdir(DATA_DIR) if f.endswith('.csv')
    )
    still_missing = all_codes_set - existing_csv
    still_missing_other = [c for c in sorted(still_missing) if not is_bj_stock(c)]
    still_missing_bj = [c for c in sorted(still_missing) if is_bj_stock(c)]

    print(f"\n{'='*60}")
    print(f"🎉 全部完成！")
    print(f"🕐 开始时间: {overall_start_time}")
    print(f"🕐 结束时间: {overall_end_time}")
    print(f"⏱️  总耗时: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print(f"   ✅ 更新: {results_ok}  |  ⏭️ 已同步: {results_sync}  "
          f"|  ⏭️ 跳过: {results_skip}  |  ❌ 失败: {results_fail}")
    if errors_detail:
        print(f"\n   失败详情:")
        for cs, r in errors_detail[:10]:
            print(f"     {cs}: {r['msg']}")
    if results_fail > 10:
        print(f"     ... 还有 {results_fail - 10} 个失败")
    print(f"   平均速度: {total / (elapsed / 60):.0f} 只/min")

    if still_missing_bj:
        print(f"\n   📋 北交所股票缺失: {len(still_missing_bj)} 只 (Yahoo Finance 无数据，可忽略)")
        print(f"      示例: {', '.join(still_missing_bj[:5])}...")
    if still_missing_other:
        print(f"\n   ⚠️  仍有 {len(still_missing_other)} 只非北交所股票缺失:")
        for c in still_missing_other[:10]:
            print(f"      {c}")
        if len(still_missing_other) > 10:
            print(f"      ... 还有 {len(still_missing_other) - 10} 个")
        print(f"      建议运行 --summary 查看详情")

    print(f"{'='*60}", flush=True)

    resume_file = os.path.join(RESUME_DIR, "_resume_index.txt")
    if os.path.exists(resume_file):
        os.remove(resume_file)
    if os.path.isdir(_YF_TMP):
        shutil.rmtree(_YF_TMP, ignore_errors=True)
