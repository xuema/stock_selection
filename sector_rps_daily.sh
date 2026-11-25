#!/usr/bin/env bash
# 次日 08:30 板块 RPS 定版任务
# 与 13:50 的 daily_screen.sh 分工：
#   13:50 daily_screen.sh   → 盘中快照(session=intraday)，当日K线未定版，跑完整12步选股
#   08:30 本脚本            → 上一交易日定版(session=final)，只跑板块RPS+通达信对照，轻量
set -uo pipefail

REPO_DIR="/Users/skyler/workspace/stock_selection"
VENV_PY="$REPO_DIR/venv/bin/python3"
SECTOR_DIR="$REPO_DIR/sector_rps"
DOCS_DIR="$REPO_DIR/docs"
BRANCH="main"

cd "$REPO_DIR"

# 周末直接退出；节假日在这里跑也只会用同一个 latest_date 覆盖同名快照，无副作用
if [ "$(date +%u)" -gt 5 ]; then
  echo "周末，跳过板块RPS定版任务"
  exit 0
fi

echo "════════ 板块RPS定版 $(date '+%Y-%m-%d %H:%M') ════════"

SNAP="$SECTOR_DIR/data/sector_rps.json"
PREV_DATE=$([ -f "$SNAP" ] && jq -r '.date // "none"' "$SNAP" 2>/dev/null || echo none)
echo "  覆盖前快照日期: ${PREV_DATE:-none}"

# ─── 东财概念板块（主源，定版口径）───
RPS_OK=0
if "$VENV_PY" "$SECTOR_DIR/sector_rps_concept.py" --session final; then
  RPS_OK=1
  echo "✅ 东财概念板块RPS 完成"
else
  echo "❌ 东财概念板块RPS 失败 → 不刷新 docs/，线上保持上一版页面"
fi

# ─── 通达信板块指数（对照表，失败不影响主流程）───
if "$VENV_PY" "$SECTOR_DIR/sector_rps_tdx.py" --session final; then
  echo "✅ 通达信对照表 完成"
else
  echo "⚠️  通达信对照表 失败/不可用，跳过"
fi

NEW_DATE=$(jq -r '.date // "none"' "$SNAP" 2>/dev/null || echo none)

# ─── 刷新 HTML 面板（只在东财源本轮成功时执行）───
mkdir -p "$DOCS_DIR"
if [ "$RPS_OK" -eq 1 ]; then
  "$VENV_PY" "$SECTOR_DIR/gen_html.py" || echo "⚠️  HTML 生成失败"
  cp -f "$SECTOR_DIR/data/sector_rps.json" "$DOCS_DIR/" 2>/dev/null
  cp -f "$SECTOR_DIR/data/tdx_rps.json" "$DOCS_DIR/" 2>/dev/null
  echo "✅ docs/ 已同步 (RPS 数据日期 $NEW_DATE)"
  [ "$NEW_DATE" = "$PREV_DATE" ] && echo "⚠️  数据日期未前进，仍是 $NEW_DATE"
fi

# ─── 提交（无变更则跳过，避免空提交）───
# 只提交看板要读的快照与历史；K线缓存和 matplotlib 产物留在本地，不进版本库
git add sector_rps/data/sector_rps.json sector_rps/data/concept_rps_full.csv sector_rps/data/history docs/ 2>/dev/null
if [ -n "$(git status --porcelain -- sector_rps/data docs/)" ]; then
  git commit -m "板块RPS定版更新 $(date +%Y-%m-%d) (数据日期 $NEW_DATE)" >/dev/null && echo "✅ 已提交"
  git push origin "$BRANCH" 2>&1 | tail -2 || echo "⚠️  推送失败"
else
  echo "— 无数据变更，跳过提交"
fi

echo "════════ 完成 $(date '+%H:%M') ════════"
