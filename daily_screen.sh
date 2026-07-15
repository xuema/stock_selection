#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/Users/skyler/workspace/stock_selection"
VENV_PYTHON="$REPO_DIR/venv/bin/python3"
UPDATE_SCRIPT="$REPO_DIR/2_update_a_stock_data.py"
RSI_SCRIPT="$REPO_DIR/strategy/screen_rsi_golden_cross.py"
SIGNALS_SCRIPT="$REPO_DIR/strategy/screen_signals.py"
MA_PULLBACK_SCRIPT="$REPO_DIR/strategy/screen_ma_pullback.py"
STB_SCRIPT="$REPO_DIR/strategy/screen_super_top_bottom.py"
RSI_STB_SCRIPT="$REPO_DIR/strategy/screen_rsi_stb_resonance.py"
OUTPUT_DIR="$REPO_DIR/output/strategy"
DATA_DIR="$REPO_DIR/data_cache_daily"
TDX_BLOCK_SCRIPT="$REPO_DIR/tools/tdx_add_blocks.py"
BRANCH="main"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'
STEP() { echo -e "\n${BLUE}▶ $1${NC}"; }
OK()   { echo -e "${GREEN}✅ $1${NC}"; }
WARN() { echo -e "${YELLOW}⚠️  $1${NC}"; }

cd "$REPO_DIR"

today=$(date +%Y-%m-%d)
echo -e "\n${GREEN}╔════════════════════════════════════════╗"
echo   "║   📈 A股每日选股流水线              ║"
echo -e "║   $today              ║"
echo   "╚════════════════════════════════════════╝${NC}"

# ─── Step 1/9: Update stock data ───
STEP "Step 1/9 — 更新股票数据 (yfinance)..."
if "$VENV_PYTHON" "$UPDATE_SCRIPT"; then
  OK "数据更新完成"
else
  WARN "数据更新有告，继续筛选..."
fi

# ─── Step 2/9: RSI Golden Cross ───
STEP "Step 2/9 — RSI 金叉策略..."
RSI_COUNT=$("$VENV_PYTHON" "$RSI_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 | grep -o '共 [0-9]* 只股票满足' | grep -o '[0-9]*' || echo "0")
OK "RSI 金叉: $RSI_COUNT 只"

# ─── Step 3/9: Multi-factor signals ───
STEP "Step 3/9 — EXPMA+VOL+CR 多因子策略..."
SIG_COUNT=$("$VENV_PYTHON" "$SIGNALS_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 | grep -o '共 [0-9]* 只股票满足' | grep -o '[0-9]*' || echo "0")
OK "多因子信号: $SIG_COUNT 只"

# ─── Step 4/9: MA Pullback ───
STEP "Step 4/9 — MA 多头排列+回调策略..."
MA_COUNT=$("$VENV_PYTHON" "$MA_PULLBACK_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 | grep -o '共 [0-9]* 只股票满足' | grep -o '[0-9]*' || echo "0")
OK "MA 回调: $MA_COUNT 只"

# ─── Step 5/9: Super Top Bottom ───
STEP "Step 5/9 — 超级顶底趋势线策略..."
STB_OUTPUT=$("$VENV_PYTHON" "$STB_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 || true)
STB_BUY_COUNT=$(echo "$STB_OUTPUT" | grep '买入信号' | grep -o '[0-9]* 只' | grep -o '[0-9]*' || echo "0")
STB_SELL_COUNT=$(echo "$STB_OUTPUT" | grep '卖出信号' | grep -o '[0-9]* 只' | grep -o '[0-9]*' || echo "0")
OK "超级顶底 — 买入: $STB_BUY_COUNT 只, 卖出: $STB_SELL_COUNT 只"

# ─── Step 6/9: RSI + STB Resonance ───
STEP "Step 6/9 — RSI 金叉 + 超级顶底 双重共振筛选..."
RES_COUNT=$("$VENV_PYTHON" "$RSI_STB_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 | grep -o '[0-9]* 只' | head -1 | grep -o '[0-9]*' || echo "0")
OK "RSI+顶底共振: $RES_COUNT 只"

# ─── Step 7/9: 同步通达信板块 ───
STEP "Step 7/9 — 同步通达信自选股板块..."
if [ -f "$TDX_BLOCK_SCRIPT" ]; then
  if "$VENV_PYTHON" "$TDX_BLOCK_SCRIPT" 2>&1 | tail -20; then
    OK "通达信板块同步完成"
  else
    WARN "通达信板块同步有告，不影响选股结果"
  fi
else
  WARN "通达信同步脚本不存在，跳过"
fi

# ─── Step 8a/9: 生成策略图片 ───
STEP "Step 8a/9 — 生成策略图片..."
IMG_SCRIPT="$REPO_DIR/tools/gen_stock_images.py"
if [ -f "$IMG_SCRIPT" ]; then
  if "$VENV_PYTHON" "$IMG_SCRIPT" 2>&1; then
    OK "策略图片生成完成"
  else
    WARN "策略图片生成有告"
  fi
else
  WARN "图片生成脚本不存在，跳过"
fi

# ─── Step 8b/9: 生成日期索引 ───
STEP "Step 8b/9 — 生成日期索引..."

RSI_DATES=$(ls "$OUTPUT_DIR"/screen_rsi_golden_cross_????-??-??.json 2>/dev/null \
  | sed 's/.*screen_rsi_golden_cross_//; s/\.json$//' | sort -r | jq -R . | jq -s . || echo "[]")
SIG_DATES=$(ls "$OUTPUT_DIR"/screen_signals_????-??-??.json 2>/dev/null \
  | sed 's/.*screen_signals_//; s/\.json$//' | sort -r | jq -R . | jq -s . || echo "[]")
MA_DATES=$(ls "$OUTPUT_DIR"/screen_ma_pullback_????-??-??.json 2>/dev/null \
  | sed 's/.*screen_ma_pullback_//; s/\.json$//' | sort -r | jq -R . | jq -s . || echo "[]")
STB_DATES=$(ls "$OUTPUT_DIR"/screen_super_top_bottom_buy_????-??-??.json 2>/dev/null \
  | sed 's/.*screen_super_top_bottom_buy_//; s/\.json$//' | sort -r | jq -R . | jq -s . || echo "[]")
RES_DATES=$(ls "$OUTPUT_DIR"/screen_rsi_stb_resonance_????-??-??.json 2>/dev/null \
  | sed 's/.*screen_rsi_stb_resonance_//; s/\.json$//' | sort -r | jq -R . | jq -s . || echo "[]")

for var in RSI_DATES SIG_DATES MA_DATES STB_DATES RES_DATES; do
  if [ -z "${!var}" ] || [ "${!var}" = "[]" ]; then
    eval "$var='[]'"
  fi
done

jq -n --argjson rsi "$RSI_DATES" --argjson signals "$SIG_DATES" --argjson ma "$MA_DATES" --argjson stb "$STB_DATES" --argjson resonance "$RES_DATES" \
  '{ rsi: $rsi, signals: $signals, ma: $ma, stb: $stb, resonance: $resonance }' > "$OUTPUT_DIR/dates.json"
OK "dates.json 已生成 (RSI: $(echo "$RSI_DATES" | jq length), SIG: $(echo "$SIG_DATES" | jq length), MA: $(echo "$MA_DATES" | jq length), STB: $(echo "$STB_DATES" | jq length), 共振: $(echo "$RES_DATES" | jq length))"

# ─── Step 9/9: Sync docs/ for GitHub Pages + Git 提交 ───
STEP "Step 9/9 — 同步 GitHub Pages 并提交..."

DOCS_DIR="$REPO_DIR/docs"
mkdir -p "$DOCS_DIR"
cp "$OUTPUT_DIR/index.html" "$DOCS_DIR/"
cp "$OUTPUT_DIR/dates.json" "$DOCS_DIR/"
cp "$REPO_DIR/stock_names.json" "$DOCS_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR/screen_rsi_golden_cross_latest.json" "$DOCS_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR/screen_signals_latest.json" "$DOCS_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR/screen_ma_pullback_latest.json" "$DOCS_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR/screen_super_top_bottom_buy_latest.json" "$DOCS_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR/screen_super_top_bottom_sell_latest.json" "$DOCS_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR/screen_rsi_stb_resonance_latest.json" "$DOCS_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR"/screen_rsi_golden_cross_????-??-??.json "$DOCS_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR"/screen_signals_????-??-??.json "$DOCS_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR"/screen_ma_pullback_????-??-??.json "$DOCS_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR"/screen_super_top_bottom_buy_????-??-??.json "$DOCS_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR"/screen_super_top_bottom_sell_????-??-??.json "$DOCS_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR"/screen_rsi_stb_resonance_????-??-??.json "$DOCS_DIR/" 2>/dev/null || true
# Copy strategy PNG images too
cp "$OUTPUT_DIR"/*.png "$DOCS_DIR/" 2>/dev/null || true
OK "docs/ 已同步 (GitHub Pages 目录)"

# ─── Git commit & push ───
git add output/strategy/ docs/

if git diff --cached --quiet; then
  WARN "无变更，跳过提交"
else
  git commit -m "📈 每日选股数据更新 – $today (RSI: $RSI_COUNT, 多因子: $SIG_COUNT, MA: $MA_COUNT, STB买: $STB_BUY_COUNT, STB卖: $STB_SELL_COUNT, 共振: $RES_COUNT)"
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
