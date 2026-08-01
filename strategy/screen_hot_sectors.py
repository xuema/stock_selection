#!/usr/bin/env python3
"""
RSP热门板块筛选 — 基于行业映射的相对强度分析

核心逻辑:
  1. 用 sector_mapping.json 中的行业数据对股票分组（yfinance行业）
  2. 计算每只股票的RSP（相对沪深300强度差值）
  3. 按行业统计：板块内RSP均值 + 板块涨幅 + 领涨股数量
  4. 综合评分排序，输出Top板块 + 板块内强势股

用法:
    python3 screen_hot_sectors.py
    python3 screen_hot_sectors.py --top 10         # 只取Top10板块
    python3 screen_hot_sectors.py --min-stocks 3   # 板块最少3只股票
    python3 screen_hot_sectors.py --lookback 20    # 近N天RSP
"""

import os, sys, json, glob, argparse
import pandas as pd, numpy as np
from tqdm import tqdm
from datetime import date
from collections import defaultdict

# ─── 可调参数 ───
PARAMS = dict(
    lookback=3,           # RSP计算周期（天），默认3天看短线热度
    min_stocks=3,         # 板块最少股票数
    top_n=15,             # 输出TopN板块
    index_code="000300",  # 基准指数
)

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ─── 名称 & 基本面缓存 ───
_NAMES_CACHE = {}
_FUND_CACHE = {}
_SECTOR_CACHE = {}

def _load_names():
    global _NAMES_CACHE
    if _NAMES_CACHE: return _NAMES_CACHE
    for p in [_BASE + "/stock_names.json", _BASE + "/../stock_names.json"]:
        if os.path.exists(p):
            try:
                with open(p) as f: _NAMES_CACHE = json.load(f); return _NAMES_CACHE
            except: pass
    return _NAMES_CACHE

def _name(t):
    if not _NAMES_CACHE: _load_names()
    return _NAMES_CACHE.get(t, "")

def _load_fund():
    global _FUND_CACHE
    if _FUND_CACHE: return _FUND_CACHE
    fp = _BASE + "/stock_fundamentals_cache.json"
    if os.path.exists(fp):
        try:
            with open(fp) as f: _FUND_CACHE = json.load(f)
        except: pass
    return _FUND_CACHE

def _mcap(t):
    if not _FUND_CACHE: _load_fund()
    return _FUND_CACHE.get(t, {}).get("mcap_yi", None)

# ─── 行业映射加载 ───
def _load_sectors():
    """加载行业映射（sector_mapping.json 或 关键词兜底）"""
    global _SECTOR_CACHE
    if _SECTOR_CACHE: return _SECTOR_CACHE

    # 优先从 sector_mapping.json 加载
    fp = _BASE + "/sector_mapping.json"
    if os.path.exists(fp):
        try:
            with open(fp) as f: _SECTOR_CACHE = json.load(f)
            return _SECTOR_CACHE
        except: pass

    # 兜底：关键词映射
    _SECTOR_CACHE = _build_sector_fallback()
    return _SECTOR_CACHE

def _get_sector(ticker):
    """获取股票的行业"""
    if not _SECTOR_CACHE: _load_sectors()
    entry = _SECTOR_CACHE.get(ticker, {})
    sector = entry.get('sector', '') if isinstance(entry, dict) else ''
    return sector if sector else None

# ─── 板块英文名→中文名映射 ───
SECTOR_CN = {
    'Technology': '科技',
    'Healthcare': '医药生物',
    'Electronics': '电子',
    'Energy': '能源',
    'Consumer Discretionary': '可选消费',
    'Consumer Defensive': '必选消费',
    'Communication Services': '传媒通信',
    'Communication': '传媒通信',
    'Industrials': '工业制造',
    'Materials': '化工材料',
    'Financials': '金融',
    'Financial Services': '金融',
    'Real Estate': '房地产',
    'Utilities': '公用事业',
    'Logistics': '物流',
    'Consumer Cyclical': '可选消费',
    'Basic Materials': '基础材料',
}

def _sector_cn(en_name):
    """板块英文名转中文"""
    return SECTOR_CN.get(en_name, en_name)

def _build_sector_fallback():
    """关键词兜底映射"""
    _load_names()
    mapping = {}
    rules = [
        ('Technology', ['科技', '软件', '信息', '数码', '网络', '电脑', '智能', 'AI', '数据']),
        ('Healthcare', ['生物', '医药', '药业', '制药', '医疗', '健康', '诊断']),
        ('Electronics', ['电子', '光电', '电器', '微电子', '半导体', '芯片']),
        ('Energy', ['能源', '电力', '电气', '电能', '太阳能']),
        ('Consumer Discretionary', ['食品', '饮料', '酒业', '白酒', '啤酒', '乳业', '汽车', '服装', '服饰', '零售', '百货']),
        ('Communication', ['传媒', '影视', '游戏', '文化', '出版', '通信', '电信']),
        ('Industrials', ['机械', '机电', '装备', '精密', '自动化', '工程', '建筑']),
        ('Materials', ['化工', '化学', '材料', '新材', '矿业', '有色', '金属', '稀土']),
        ('Financials', ['银行', '证券', '保险', '信托', '期货', '金服', '金融']),
        ('Real Estate', ['地产', '置业', '房产', '置地']),
        ('Utilities', ['水务', '环保', '燃气', '供水']),
        ('Logistics', ['物流', '供应链', '仓储', '快递', '运输']),
    ]
    for t, nm in _NAMES_CACHE.items():
        for sector, keywords in rules:
            if any(kw in nm for kw in keywords):
                mapping[t] = {'sector': sector, 'industry': ''}
                break
    return mapping

# ─── 指数加载 ───
def _load_index(data_dir, idx_code):
    idx_file = os.path.join(data_dir, f"{idx_code}.csv")
    if not os.path.exists(idx_file):
        # 尝试000001
        alt = os.path.join(data_dir, "000001.csv")
        if os.path.exists(alt):
            idx_file = alt
        else:
            return None
    try:
        df = pd.read_csv(idx_file, parse_dates=["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        df.dropna(subset=["Close"], inplace=True)
        return df
    except:
        return None

# ─── RSP计算 ───
def calc_rsp(stock_df, idx_df, lookback=20):
    """计算股票相对指数的RSP值
    RSP = 股票收益率 - 指数收益率（百分点差值）
    正值 = 跑赢指数，负值 = 跑输
    """
    if idx_df is None:
        close = stock_df["Close"].values
        if len(close) < lookback:
            return None, None
        pct = (close[-1] / close[-lookback] - 1) * 100
        return pct / 10, pct  # 无基准时，用绝对涨幅/10代替

    # 对齐日期
    common = set(stock_df["Date"]) & set(idx_df["Date"])
    if len(common) < lookback:
        return None, None

    s = stock_df[stock_df["Date"].isin(common)].sort_values("Date").reset_index(drop=True)
    i = idx_df[idx_df["Date"].isin(common)].sort_values("Date").reset_index(drop=True)

    if len(s) < lookback or len(i) < lookback:
        return None, None

    s_close = s["Close"].values[-lookback:]
    i_close = i["Close"].values[-lookback:]

    stock_gain = s_close[-1] / s_close[0] - 1.0
    idx_gain = i_close[-1] / i_close[0] - 1.0

    # RSP: 相对收益率差（百分点）
    rsp = stock_gain - idx_gain
    stock_pct = stock_gain * 100

    return rsp, stock_pct

# ─── 单股分析 ───
def analyze_stock(filepath, idx_df, lookback=20):
    ticker = os.path.basename(filepath).replace(".csv", "")
    nm = _name(ticker)

    # 剔除ST/退市
    if nm and ("ST" in nm.upper() or "退" in nm):
        return None

    # 获取行业
    sector = _get_sector(ticker)
    if not sector:
        return None

    try:
        df = pd.read_csv(filepath, parse_dates=["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        for c in ["Close", "Volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df.dropna(subset=["Close"], inplace=True)
    except:
        return None

    if len(df) < lookback + 5:
        return None

    rsp, stock_ret = calc_rsp(df, idx_df, lookback)
    if rsp is None:
        return None

    close_now = float(df["Close"].iloc[-1])
    mc = _mcap(ticker)

    return {
        "ticker": ticker,
        "name": nm,
        "sector": sector,
        "rsp": round(rsp, 4),
        "pct": round(stock_ret, 2),
        "close": round(close_now, 2),
        "mcap_yi": mc,
        "date": df["Date"].iloc[-1].strftime("%Y-%m-%d"),
    }

# ─── 板块聚合 ───
def aggregate_sectors(stock_results, min_stocks=3):
    """按板块聚合统计"""
    sector_data = defaultdict(lambda: {"tickers": [], "rsp_values": [], "pcts": []})

    for s in stock_results:
        sec = s["sector"]
        sector_data[sec]["tickers"].append(s["ticker"])
        sector_data[sec]["rsp_values"].append(s["rsp"])
        sector_data[sec]["pcts"].append(s["pct"])

    results = []
    for sec, data in sector_data.items():
        n = len(data["tickers"])
        if n < min_stocks:
            continue

        avg_rsp = np.mean(data["rsp_values"])
        avg_pct = np.mean(data["pcts"])
        median_pct = np.median(data["pcts"])
        max_pct = max(data["pcts"])
        min_pct = min(data["pcts"])

        # 领涨股数量（涨幅>板块中位数）
        n_leaders = sum(1 for p in data["pcts"] if p > median_pct)

        # 板块得分 = RSP权重40% + 涨幅权重40% + 领涨比例20%
        rsp_score = min(100, max(0, (avg_rsp + 0.05) * 1000))  # RSP差值-5%~5% → 0~100
        pct_score = min(100, max(0, (avg_pct + 5) * 10))       # 涨幅-5%~5% → 0~100
        leader_score = (n_leaders / n) * 100                   # 领涨比例0~1 → 0~100

        score = round(rsp_score * 0.4 + pct_score * 0.4 + leader_score * 0.2, 1)

        results.append({
            "sector": sec,
            "n_stocks": n,
            "avg_rsp": round(avg_rsp, 4),
            "avg_pct": round(avg_pct, 2),
            "median_pct": round(median_pct, 2),
            "max_pct": round(max_pct, 2),
            "n_leaders": n_leaders,
            "score": score,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results

# ─── JSON输出 ───
def save_json(sector_results, all_stocks, output_dir):
    today = date.today().strftime("%Y-%m-%d")
    os.makedirs(output_dir, exist_ok=True)

    # 板块结果
    sectors_out = []
    for s in sector_results:
        sectors_out.append({
            "sector": _sector_cn(s["sector"]),
            "sector_en": s["sector"],
            "n_stocks": s["n_stocks"],
            "avg_rsp": s["avg_rsp"],
            "avg_pct": s["avg_pct"],
            "median_pct": s["median_pct"],
            "max_pct": s["max_pct"],
            "n_leaders": s["n_leaders"],
            "score": s["score"],
        })

    # 板块内股票详情（Top板块的股票）
    top_sectors_en = set(s["sector"] for s in sector_results[:10])
    stocks_out = []
    for s in all_stocks:
        if s["sector"] in top_sectors_en:
            stocks_out.append({
                "ticker": s["ticker"],
                "name": s["name"],
                "sector": _sector_cn(s["sector"]),
                "sector_en": s["sector"],
                "rsp": s["rsp"],
                "pct": s["pct"],
                "close": s["close"],
                "mcap_yi": s.get("mcap_yi"),
                "date": s["date"],
            })

    # 每个板块RSP前5强势股
    sector_top5 = {}
    for sec_data in sector_results:
        sec_en = sec_data["sector"]
        # 筛选该板块的股票，按RSP降序取5只
        sec_stocks = [s for s in all_stocks if s["sector"] == sec_en]
        sec_stocks.sort(key=lambda x: x["rsp"], reverse=True)
        top5 = []
        for s in sec_stocks[:5]:
            top5.append({
                "ticker": s["ticker"],
                "name": s["name"],
                "rsp": round(s["rsp"], 3),
                "pct": round(s["pct"], 2),
                "close": s["close"],
            })
        sector_top5[_sector_cn(sec_en)] = top5

    payload = {
        "strategy": "screen_hot_sectors",
        "strategy_name": "RSP热门板块",
        "screen_date": today,
        "params": {k: PARAMS[k] for k in ["lookback", "min_stocks", "top_n"]},
        "total_sectors": len(sectors_out),
        "total_stocks": len(stocks_out),
        "sectors": sectors_out,
        "stocks": stocks_out,
        "sector_top5": sector_top5,
    }

    dated = os.path.join(output_dir, f"screen_hot_sectors_{today}.json")
    latest = os.path.join(output_dir, "screen_hot_sectors_latest.json")
    for p in [dated, latest]:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n💾 JSON 已保存:\n   {dated}\n   {latest}")

# ─── 主流程 ───
def main():
    ap = argparse.ArgumentParser(description="RSP热门板块筛选 — 找出相对强度最强的板块")
    ap.add_argument("--data-dir", default="/Users/skyler/workspace/stock_selection/data_cache_daily")
    ap.add_argument("--output-dir", default="/Users/skyler/workspace/stock_selection/output/strategy")
    ap.add_argument("--top", type=int, default=None, help="只取TopN板块 (默认15)")
    ap.add_argument("--min-stocks", type=int, default=3, help="板块最少股票数 (默认3)")
    ap.add_argument("--lookback", type=int, default=3, help="RSP计算周期 (默认3天，短线热度)")
    args = ap.parse_args()

    PARAMS["top_n"] = args.top or PARAMS["top_n"]
    PARAMS["min_stocks"] = args.min_stocks
    PARAMS["lookback"] = args.lookback

    print(f"╔{'═'*58}╗")
    print(f"║  🔥 RSP热门板块筛选                         ║")
    print(f"║     RSP{args.lookback} / 板块强度 / 领涨统计        ║")
    print(f"║     Top{PARAMS['top_n']}板块, 最少{args.min_stocks}只/板块              ║")
    print(f"╚{'═'*58}╝\n")

    csvs = sorted(glob.glob(os.path.join(args.data_dir, "*.csv")))
    print(f"📁 共 {len(csvs)} 只股票，开始扫描…\n")

    # 加载指数
    idx_df = _load_index(args.data_dir, PARAMS["index_code"])
    if idx_df is not None:
        print(f"📈 基准指数: {PARAMS['index_code']} ({len(idx_df)} 天)\n")
    else:
        print("⚠️  未找到指数数据，将使用绝对价格计算\n")

    _load_names()
    _load_fund()
    _load_sectors()

    # 统计行业覆盖率
    has_sector = sum(1 for t in _NAMES_CACHE if _get_sector(t))
    print(f"📊 行业映射: {has_sector}/{len(_NAMES_CACHE)} 只 ({has_sector/len(_NAMES_CACHE)*100:.1f}%)\n")

    # 逐股分析
    stock_results = []
    for fp in tqdm(csvs, desc="扫描中"):
        result = analyze_stock(fp, idx_df, PARAMS["lookback"])
        if result:
            stock_results.append(result)

    print(f"\n✅ 匹配行业: {len(stock_results)} 只股票\n")

    # 板块聚合
    sector_results = aggregate_sectors(stock_results, PARAMS["min_stocks"])

    top_n = PARAMS["top_n"]
    if len(sector_results) > top_n:
        top_sectors = sector_results[:top_n]
        print(f"⚠️  共 {len(sector_results)} 个板块满足条件 → Top {top_n}\n")
    else:
        top_sectors = sector_results

    # 打印结果
    print(f"{'='*90}")
    print(f"🟢 热门板块 Top {len(top_sectors)} — 按综合评分降序")
    print(f"{'='*90}\n")

    header = f"  {'排名':>3}  {'板块':<24}  股票数  平均RSP  平均涨幅  中位涨幅  最大涨幅  领涨股  综合评分"
    print(header)
    print(f"{'─'*90}")

    for rank, s in enumerate(top_sectors, 1):
        sec_name = _sector_cn(s['sector'])
        print(f"  {rank:>3}  {sec_name:<12}  {s['n_stocks']:>4}只  {s['avg_rsp']:>+7.3f}  "
              f"{s['avg_pct']:>+6.2f}%  {s['median_pct']:>+6.2f}%  {s['max_pct']:>+6.2f}%  "
              f"{s['n_leaders']:>3}只  ★{s['score']:>5.1f}")

    print(f"\n{'─'*90}")
    print(f"  说明: RSP=股票涨幅-指数涨幅, 正值=跑赢, 综合评分=RSP×40%+涨幅×40%+领涨比例×20%\n")

    save_json(top_sectors, stock_results, args.output_dir)
    return top_sectors

if __name__ == "__main__":
    main()
