#!/bin/bash
# 一次性重跑: 每日筛选 -> 回测 -> 敏感性 -> 看板
cd "$(dirname "$0")"
PY=/Users/skyler/workspace/stock_selection/venv/bin/python3
set -e
echo "== screen_daily =="; $PY -u screen_daily.py
echo "== backtest ==";     $PY -u backtest.py --start 2022-01-04 --tag main --counts
echo "== sweep ==";        $PY -u bt_sweep.py --start 2022-01-04
echo "== dashboard ==";    $PY -u dashboard.py --tag main
