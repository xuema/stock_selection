#!/usr/bin/env bash
# ====================================================================
# daily_screen.sh — 每日选股自动化流水线
#
# 流程:
#   1. 下载/更新股票数据 (2_update_a_stock_data.py)
#   2. RSI 金叉策略筛选
#   3. EXPMA+VOL+CR 多因子策略筛选
#   4. 生成 dates.json（历史日期索引，供 HTML 页面使用）
#   5. Git commit + push 到 GitHub（Pages 部署）
#
# 用法: ./daily_screen.sh
# ====================================================================
set -euo pipefail

# ─── 配置 ───
REPO_DIR="/Users/skyler/workspace/stock_selection"
VENV_PYTHON="$REPO_DIR/venv/bin/python3"
UPDATE_SCRIPT="$REPO_DIR/2_update_a_stock_data.py"
RSI_SCRIPT="$REPO_DIR/strategy/screen_rsi_golden_cross.py"
SIGNALS_SCRIPT="$REPO_DIR/strategy/screen_signals.py"
OUTPUT_DIR="$REPO_DIR/output/strategy"
DATA_DIR="$REPO_DIR/data_cache_daily"
BRANCH="main"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'
STEP() { echo -e "\n${BLUE}▶ $1${NC}"; }
OK()   { echo -e "${GREEN}✅ $1${NC}"; }
WARN() { echo -e "${YELLOW}⚠️  $1${NC}"; }
FAIL() { echo -e "${RED}❌ $1${NC}"; }

cd "$REPO_DIR"

today=$(date +%Y-%m-%d)
echo -e "\n${GREEN}╔════════════════════════════════════════╗"
echo   "║   📈 A股每日选股流水线              ║"
echo -e "║   $\today   ║"
echo   "╚════════════════════════════════════════╝${NC}"

# ─── Step 1: Update stock data ───
STEP "Step 1/4 — 更新股票数据 (yfinance)..."
if "$VENV_PYTHON" "$UPDATE_SCRIPT"; then
  OK "数据更新完成"
else
  WARN "数据更新有警告，继续筛选..."
fi

# ─── Step 2: RSI Golden Cross ───
STEP "Step 2/4 — RSI(12,56) 金叉策略..."
RSI_COUNT=$("$VENV_PYTHON" "$RSI_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 | grep -oP '共 \K[0-9]+(?= 只股票满足)' || echo "0")
OK "RSI 金叉: $RSI_COUNT 只"

# ─── Step 3: Multi-factor signals ───
STEP "Step 3/4 — EXPMA+VOL+CR 多因子策略..."
SIG_COUNT=$("$VENV_PYTHON" "$SIGNALS_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 | grep -oP '共 \K[0-9]+(?= 只股票满足)' || echo "0")
OK "多因子信号: $SIG_COUNT 只"

# ─── Step 4: Generate dates.json ───
STEP "Step 4/4 — 生成日期索引 + Git 提交..."

# Scan output directory for all dated JSON files
RSI_DATES=$(ls "$OUTPUT_DIR"/screen_rsi_golden_cross_????-??-??.json 2>/dev/null \
  | sed 's/.*screen_rsi_golden_cross_//; s/\.json$//' | sort -r | jq -R . | jq -s .)
SIG_DATES=$(ls "$OUTPUT_DIR"/screen_signals_????-??-??.json 2>/dev/null \
  | sed 's/.*screen_signals_//; s/\.json$//' | sort -r | jq -R . | jq -s .)

# Ensure arrays even if empty
if [ -z "$RSI_DATES" ] || [ "$RSI_DATES" = "[]" ]; then
  RSI_DATES="[]"
fi
if [ -z "$SIG_DATES" ] || [ "$SIG_DATES" = "[]" ]; then
  SIG_DATES="[]"
fi

# Write dates.json
jq -n --argjson rsi "$RSI_DATES" --argjson signals "$SIG_DATES" \
  '{ rsi: $rsi, signals: $signals }' > "$OUTPUT_DIR/dates.json"
OK "dates.json 已生成 (RSI: $(echo "$RSI_DATES" | jq length), SIG: $(echo "$SIG_DATES" | jq length))"

# ─── Sync docs/ for GitHub Pages ───
DOCS_DIR="$REPO_DIR/docs"
mkdir -p "$DOCS_DIR"
cp "$OUTPUT_DIR/index.html" "$DOCS_DIR/"
cp "$OUTPUT_DIR/dates.json" "$DOCS_DIR/"
cp "$OUTPUT_DIR/screen_rsi_golden_cross_latest.json" "$DOCS_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR/screen_signals_latest.json" "$DOCS_DIR/" 2>/dev/null || true
# Copy all dated files
cp "$OUTPUT_DIR"/screen_rsi_golden_cross_????-??-??.json "$DOCS_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR"/screen_signals_????-??-??.json "$DOCS_DIR/" 2>/dev/null || true
OK "docs/ 已同步 (GitHub Pages 目录)"

# ─── Git commit & push ───
git add output/strategy/ docs/

# Only commit if there are changes
if git diff --cached --quiet; then
  WARN "无变更，跳过提交"
else
  git commit -m "📈 每日选股数据更新 – $today (RSI: $RSI_COUNT, 多因子: $SIG_COUNT)"
  OK "Git 提交完成"

  if git push origin "$BRANCH" 2>&1; then
    OK "已推送到 GitHub (Pages 将自动更新)"
  else
    WARN "推送失败，请检查网络连接和凭证"
  fi
fi

echo -e "\n${GREEN}╔════════════════════════════════════════╗"
echo   "║   ✨ 流水线完成                      ║"
echo   "╚════════════════════════════════════════╝${NC}"
