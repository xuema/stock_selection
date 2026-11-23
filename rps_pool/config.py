#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rps_pool 全局配置: 路径与可调参数。

所有脚本都从这里取路径, 便于整体迁移。
"""
import os
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(BASE)                      # .../stock_selection
DATA = os.path.join(BASE, "data")
QUARTER_DIR = os.path.join(DATA, "quarter")
OUT = os.path.join(BASE, "out")
HIST_DIR = os.path.join(REPO, "data_cache_daily_5y")   # yfinance 前复权 6 年日线缓存(fetch_history.py 维护)

# 既有缓存( yfinance 前复权, 约 279 根 ) —— 只读, 用于交叉校验
LEGACY_DAILY = os.path.join(REPO, "data_cache_daily")
STOCK_NAMES = os.path.join(REPO, "stock_names.json")

PY = os.path.join(REPO, "venv", "bin", "python3")

# ── 股票池参数 (第一步) ─────────────────────────────────
POOL = dict(
    fund_ratio_min = 3.0,     # 基金持股 / 流通股 >= 3.0 (%)
    north_cap_min  = 3e7,     # 北向持股市值 >= 3000 万元
    min_list_days  = 365,     # 上市满 1 年
    fund_names     = ("基金",),   # zlsj type=1 即"基金"(含股票型+混合型等)
    # 北向在十大流通股东里的席位名 (2024-08 之后个股北向每日数据停发, 只能用它近似)
    # A股前十大流通股东中, 北向合计名义持有人 = "香港中央结算有限公司"
    # "香港中央结算(代理人)有限公司"/HKSCC NOMINEES 是外资代持, 不属于北向, 必须排除
    north_keys     = ("沪股通", "深股通", "香港中央结算有限公司"),
    north_excludes = ("代理人", "HKSCC", "hkscc", "登记结算"),
)

# ── RPS 选股参数 (第二步公共部分) ───────────────────────
RPS = dict(
    w_fast   = 120,           # RPS120 回看窗口
    w_slow   = 250,           # RPS250 回看窗口
    sum_min  = 185,           # RPS120 + RPS250 >= 185   (可调 180~185)
    ma20_up_days   = 5,       # SXHCG411/412: 连续上升天数 (可调 5~15)
    count250_days  = 30,      # SXHCG21/22 统计窗口
    count250_need  = 25,      # SXHCG21/22 至少站上天数 (可调 25~30)
    dd_limit = 0.25,          # SXHCG31: 回撤 <= 25%
    hhv250_ratio   = 0.80,    # SXHCG32: C/HHV(C,250) > 0.80 (策略2 用 0.90)
    turnover_max   = 10.0,    # SXHCG5: 日线换手率 < 10%
)

# ── 周线 RSI (以交易为生) ───────────────────────────────
WK_RSI = dict(
    rsi_period = 12,          # RSI1 = 周线 RSI(12)
    sig_window = 5,           # RSI2 = MA(RSI1, 5)
    mid_line   = 50.0,        # RSI3 = 50 中枢 (中期趋势分界)
    # 备选定义: three_line=True 时 RSI3 = MA(RSI1, slow_window)
    three_line    = False,
    slow_window   = 24,
    # 卖出点口径: "cross" = RSI1 下穿 RSI2 当根且 RSI1<RSI3 (字面)
    #             "state" = 处于 RSI1<RSI2 状态且 RSI1<RSI3 (更早触发, 回测里可比对)
    sell_mode     = "cross",
)

# ── 回测参数 ────────────────────────────────────────────
BT = dict(
    start          = "2022-01-04",
    end            = None,                     # None = 数据最后一天
    max_positions  = 10,                       # 同时最多持仓
    capital        = 1_000_000,                # 初始资金
    per_trade_pct  = 0.10,                     # 单笔仓位
    commission     = 0.00025,                  # 双边佣金
    stamp_tax      = 0.0005,                   # 卖出印花税
    slippage       = 0.001,                    # 滑点
    max_hold_days  = 250,                      # 兜底持有上限(交易日)
    min_bar_amount = 3e7,                      # 成交额下限(元), 过滤不可成交票
)

os.makedirs(DATA, exist_ok=True)
os.makedirs(OUT, exist_ok=True)


def latest_report_day(today: date | None = None) -> date:
    """最近一个"已经披露完毕"的报告期末: 季报披露截止 1/4/7/10 月末, 留 45 天缓冲。"""
    today = today or date.today()
    cand = [date(today.year - 1, 12, 31), date(today.year, 3, 31),
            date(today.year, 6, 30), date(today.year, 9, 30), date(today.year, 12, 31)]
    ok = []
    for c in cand:
        if c > today:
            continue
        # 披露截止日: Q4/年报 ~次年4-30, Q1~4-30, Q2~8-31, Q3~10-31
        deadline = {3: date(c.year, 4, 30), 6: date(c.year, 8, 31),
                    9: date(c.year, 10, 31), 12: date(c.year + 1, 4, 30)}[c.month]
        if today >= deadline:
            ok.append(c)
    return max(ok) if ok else date(today.year - 1, 12, 31)


def yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")
