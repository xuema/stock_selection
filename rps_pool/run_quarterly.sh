#!/bin/bash
# 季度运行: 抓最新季报的基金/北向/上市日期 -> 重建股票池 -> 立即重跑回测与看板
#   0 9 5 2,5,8,11 *   /Users/skyler/workspace/stock_selection/rps_pool/run_quarterly.sh >> /Users/skyler/workspace/stock_selection/rps_pool/out/logs/cron_q.log 2>&1
# 披露截止: Q1 4/30, Q2 8/31, Q3 10/31, 年报 4/30 —— 所以定在 2/5/8/11 月的 5 号,
# config.latest_report_day() 会自动挑"已经披露完"的最近一季。
cd "$(dirname "$0")" || exit 1
PY=/Users/skyler/workspace/stock_selection/venv/bin/python3
mkdir -p out/logs
exec >> out/logs/quarterly_$(date +%Y%m%d).log 2>&1
echo "======== $(date '+%F %T') run_quarterly 开始 ========"

$PY -u fetch_quarterly.py            || { echo "!! fetch_quarterly 失败"; exit 1; }
$PY -u build_pool.py                 || { echo "!! build_pool 失败"; exit 1; }
# 新入池但本地没日线的票 -> 补历史
$PY -u fetch_history.py --build --universe pool --chunk 100 || echo "!! 补历史失败(可稍后重试)"
$PY -u screen_daily.py               || echo "!! screen 失败"
$PY -u backtest.py --start 2022-01-04 --tag main --counts || echo "!! 回测失败"
$PY -u bt_sweep.py  --start 2022-01-04 || echo "!! 敏感性失败"
$PY -u dashboard.py --tag main       || echo "!! 看板失败"
echo "======== $(date '+%F %T') run_quarterly 结束 ========"
