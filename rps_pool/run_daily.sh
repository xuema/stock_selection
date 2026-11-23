#!/bin/bash
# 每日 13:50 前后运行: 全市场行情更新 -> 双策略筛选 -> 看板
#   0 13 * * 1-5  /Users/skyler/workspace/stock_selection/rps_pool/run_daily.sh >> /Users/skyler/workspace/stock_selection/rps_pool/out/logs/cron.log 2>&1
#
# 说明: fetch_history 走 yfinance 批量(约 53 个请求), 全市场 5000+ 只约 15-20 分钟。
#       13:50 抓到的当日 K 线, 其 Close 就是"收盘前约 1 小时"的价格 —— 即回测/筛选的买入参考价。
cd "$(dirname "$0")" || exit 1
PY=/Users/skyler/workspace/stock_selection/venv/bin/python3
mkdir -p out/logs
LOG=out/logs/daily_$(date +%Y%m%d).log
exec >> "$LOG" 2>&1
echo "======== $(date '+%F %T') run_daily 开始 ========"

# 1) 行情增量更新(带除权漂移检测, 漂移过阈值会整段重下)
if [ "$1" != "--skip-fetch" ]; then
  $PY -u fetch_history.py --update --universe full --chunk 100 || \
    echo "!! fetch_history --update 失败, 用现有缓存继续"
fi

# 2) 每日筛选
$PY -u screen_daily.py || { echo "!! screen_daily 失败"; exit 1; }

# 3) 看板(回测产物沿用上一次的结果)
$PY -u dashboard.py --tag main || echo "!! dashboard 失败"

echo "======== $(date '+%F %T') run_daily 结束 ========"
