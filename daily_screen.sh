#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/Users/skyler/workspace/stock_selection"
VENV_PYTHON="$REPO_DIR/venv/bin/python3"
UPDATE_SCRIPT="$REPO_DIR/2_update_a_stock_data.py"
RSP_SCRIPT="$REPO_DIR/strategy/screen_rsp_trend_break.py"
RPSV2_SCRIPT="$REPO_DIR/strategy/screen_rps_trend_v2.py"
RPS_PRO_SCRIPT="$REPO_DIR/strategy/screen_rps_trend_pro.py"
RSI_SCRIPT="$REPO_DIR/strategy/screen_rsi_golden_cross.py"
SIGNALS_SCRIPT="$REPO_DIR/strategy/screen_signals.py"
MA_PULLBACK_SCRIPT="$REPO_DIR/strategy/screen_ma_pullback.py"
STB_SCRIPT="$REPO_DIR/strategy/screen_super_top_bottom_v2.py"
RSI_STB_SCRIPT="$REPO_DIR/strategy/screen_rsi_stb_resonance.py"
ACTIVE_MIDCAP_SCRIPT="$REPO_DIR/strategy/screen_active_midcap.py"
HOT_SECTORS_SCRIPT="$REPO_DIR/strategy/screen_hot_sectors.py"
OUTPUT_DIR="$REPO_DIR/output/strategy"
DATA_DIR="$REPO_DIR/data_cache_daily"
TDX_BLOCK_SCRIPT="$REPO_DIR/tools/tdx_add_blocks.py"
GEN_IMAGES_SCRIPT="$REPO_DIR/tools/gen_stock_images.py"
BRANCH="main"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'
STEP() { echo -e "\n${BLUE}▶ $1${NC}"; }
OK()   { echo -e "${GREEN}✅ $1${NC}"; }
WARN() { echo -e "${YELLOW}⚠️  $1${NC}"; }

# ─── Step 0: 更新沪深300指数数据 ───
STEP "Step 0/11 — 更新沪深300指数数据..."
cd "$REPO_DIR"
$VENV_PYTHON << 'PYEOF'
import requests, pandas as pd, os
from datetime import date, timedelta

idx_file = "data_cache_daily/000300.csv"

# 新浪财经接口（不需要代理）
url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
params = {
    "symbol": "sh000300",
    "scale": "240", "ma": "no", "datalen": "600"
}

updated = False
try:
    session = requests.Session()
    session.proxies = {'http': None, 'https': None}
    session.headers = {'User-Agent': 'Mozilla/5.0'}
    r = session.get(url, params=params, timeout=15)
    data = r.json()
    if data:
        rows = []
        for d in data:
            rows.append({
                'Date': d['day'],
                'Open': float(d['open']), 'Close': float(d['close']),
                'High': float(d['high']), 'Low': float(d['low']),
                'Volume': int(d.get('volume', 0))
            })
        df = pd.DataFrame(rows)
        df.to_csv(idx_file, index=False)
        print(f"✅ 沪深300: {len(df)}条, 最新: {df['Date'].iloc[-1]}")
        updated = True
    else:
        print("⚠️ 新浪API返回空数据")
except Exception as e:
    print(f"⚠️ 更新失败: {type(e).__name__}: {str(e)[:80]}")

# 检查数据状态
if os.path.exists(idx_file):
    latest_df = pd.read_csv(idx_file)
    latest = latest_df['Date'].iloc[-1]
    days = (date.today() - pd.to_datetime(latest).date()).days
    if not updated:
        print(f"📈 沪深300: 使用现有数据 {latest} (距今{days}天)")
        if days > 3:
            print(f"⚠️ 警告: 指数数据已{days}天未更新，RSP计算可能不准确！")
    elif days > 3:
        print(f"⚠️ 警告: 数据仅到 {latest} (距今{days}天)，可能非交易日")
else:
    print("⚠️ 警告: 无指数数据文件，RSP计算将失效！")
PYEOF


cd "$REPO_DIR"

today=$(date +%Y-%m-%d)
echo -e "\n${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "║   A股每日选股流水线              ║"
echo -e "║   $today              ║"
echo -e "╚════════════════════════════════════════╝${NC}"

# ─── Helper: count from JSON latest file ───
count_from_json() {
  local json_path="$1"
  if [ -f "$json_path" ]; then
    local cnt
    cnt=$(jq -r '.total_matched // 0' "$json_path" 2>/dev/null || true)
    echo "${cnt:-0}"
  else
    echo "0"
  fi
}

# ─── Step 1: Update stock data ───
STEP "Step 1/11 — 更新股票数据 (yfinance)..."



# ─── Step 2: RSP趋势突破 ───
STEP "Step 2/11 — RSP趋势突破策略..."
"$VENV_PYTHON" "$RSP_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 || true
RSP_COUNT=$(count_from_json "$OUTPUT_DIR/screen_rsp_trend_break_latest.json")
OK "RSP趋势突破: $RSP_COUNT 只"

# ─── Step 3: RPS中长期龙头 (V2) ───
STEP "Step 3/11 — RPS中长期龙头 (V2)..."
"$VENV_PYTHON" "$RPSV2_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 || true
RPSV2_COUNT=$(count_from_json "$OUTPUT_DIR/screen_rps_trend_v2_latest.json")
OK "RPS中长期龙头: $RPSV2_COUNT 只"

# ─── Step 4: RPS超强势 (Pro) ───
STEP "Step 4/11 — RPS超强势 (Pro)..."
"$VENV_PYTHON" "$RPS_PRO_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 || true
RPS_PRO_COUNT=$(count_from_json "$OUTPUT_DIR/screen_rps_trend_pro_latest.json")
OK "RPS超强势: $RPS_PRO_COUNT 只"

# ─── Step 5: RSI金叉 ───
STEP "Step 5/11 — RSI 金叉策略..."
"$VENV_PYTHON" "$RSI_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 || true
RSI_COUNT=$(count_from_json "$OUTPUT_DIR/screen_rsi_golden_cross_latest.json")
OK "RSI 金叉: $RSI_COUNT 只"

# ─── Step 6: EXPMA+VOL+CR 多因子 ───
STEP "Step 6/11 — EXPMA+VOL+CR 多因子策略..."
"$VENV_PYTHON" "$SIGNALS_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 || true
SIG_COUNT=$(count_from_json "$OUTPUT_DIR/screen_signals_latest.json")
OK "多因子信号: $SIG_COUNT 只"

# ─── Step 7: MA回调 ───
STEP "Step 7/11 — MA 多头排列+回调策略..."
"$VENV_PYTHON" "$MA_PULLBACK_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 || true
MA_COUNT=$(count_from_json "$OUTPUT_DIR/screen_ma_pullback_latest.json")
OK "MA 回调: $MA_COUNT 只"

# ─── Step 8: 超级顶底 ───
STEP "Step 8/11 — 超级顶底趋势线策略..."
"$VENV_PYTHON" "$STB_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 || true
STB_BUY_COUNT=$(count_from_json "$OUTPUT_DIR/screen_super_top_bottom_buy_latest.json")
STB_SELL_COUNT=$(count_from_json "$OUTPUT_DIR/screen_super_top_bottom_sell_latest.json")
OK "超级顶底 — 买入: $STB_BUY_COUNT 只, 卖出: $STB_SELL_COUNT 只"

# ─── Step 9: RSI+STB 双重共振 ───
STEP "Step 9/11 — RSI+超级顶底 双重共振筛选..."
"$VENV_PYTHON" "$RSI_STB_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 || true
RES_COUNT=$(count_from_json "$OUTPUT_DIR/screen_rsi_stb_resonance_latest.json")
OK "RSI+顶底共振: $RES_COUNT 只"

# ─── Step 10: 活跃中盘股 ───
STEP "Step 10/11 — 活跃中盘股筛选..."
"$VENV_PYTHON" "$ACTIVE_MIDCAP_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 || true
MIDCAP_COUNT=$(count_from_json "$OUTPUT_DIR/screen_active_midcap_latest.json")
OK "活跃中盘股: $MIDCAP_COUNT 只"

# ─── Step 11: RSP热门板块 ───
STEP "Step 11/11 — RSP热门板块筛选..."
"$VENV_PYTHON" "$HOT_SECTORS_SCRIPT" --data-dir "$DATA_DIR" --output-dir "$OUTPUT_DIR" 2>&1 || true
SECTORS_COUNT=$(count_from_json "$OUTPUT_DIR/screen_hot_sectors_latest.json")
OK "RSP热门板块: $SECTORS_COUNT 个板块"

# ─── Generate Strategy Images (PNG) ───
STEP "生成策略图片 (PNG)..."
if "$VENV_PYTHON" "$GEN_IMAGES_SCRIPT" 2>&1; then
  OK "策略图片生成完成"
else
  WARN "策略图片生成有异常，继续后续步骤..."
fi

# ─── Generate dates.json ───
STEP "生成日期索引..."

date_list_from_pattern() {
  ls "$OUTPUT_DIR"/${1}_????-??-??.json 2>/dev/null \
    | sed "s/.*${1}_//; s/\.json$//" | sort -r | jq -R . | jq -s . || echo "[]"
}

RSI_DATES=$(date_list_from_pattern "screen_rsi_golden_cross")
SIG_DATES=$(date_list_from_pattern "screen_signals")
MA_DATES=$(date_list_from_pattern "screen_ma_pullback")
STB_DATES=$(date_list_from_pattern "screen_super_top_bottom_buy")
RES_DATES=$(date_list_from_pattern "screen_rsi_stb_resonance")
RSP_DATES=$(date_list_from_pattern "screen_rsp_trend_break")
RPSV2_DATES=$(date_list_from_pattern "screen_rps_trend_v2")
RPS_PRO_DATES=$(date_list_from_pattern "screen_rps_trend_pro")
MIDCAP_DATES=$(date_list_from_pattern "screen_active_midcap")
SECTORS_DATES=$(date_list_from_pattern "screen_hot_sectors")

jq -n \
  --argjson rsi "$RSI_DATES" \
  --argjson signals "$SIG_DATES" \
  --argjson ma "$MA_DATES" \
  --argjson stb "$STB_DATES" \
  --argjson resonance "$RES_DATES" \
  --argjson rsp "$RSP_DATES" \
  --argjson rpsv2 "$RPSV2_DATES" \
  --argjson pro "$RPS_PRO_DATES" \
  --argjson midcap "$MIDCAP_DATES" \
  --argjson sectors "$SECTORS_DATES" \
  '{
    rsi: $rsi,
    signals: $signals,
    ma: $ma,
    stb: $stb,
    resonance: $resonance,
    rsp: $rsp,
    rpsv2: $rpsv2,
    pro: $pro,
    midcap: $midcap,
    sectors: $sectors
  }' > "$OUTPUT_DIR/dates.json"

OK "dates.json 已生成"

# ─── Sync to docs/ for GitHub Pages ───
STEP "同步 GitHub Pages..."

DOCS_DIR="$REPO_DIR/docs"
mkdir -p "$DOCS_DIR"
cp "$OUTPUT_DIR/index.html" "$DOCS_DIR/"
cp "$OUTPUT_DIR/dates.json" "$DOCS_DIR/"
cp "$REPO_DIR/stock_names.json" "$DOCS_DIR/" 2>/dev/null || true

# Copy all strategy JSON files
cp "$OUTPUT_DIR"/screen_*_latest.json "$DOCS_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR"/screen_*_????-??-??.json "$DOCS_DIR/" 2>/dev/null || true
cp "$OUTPUT_DIR"/*.png "$DOCS_DIR/" 2>/dev/null || true
OK "docs/ 已同步"

# ─── Git commit & push ───
git add output/strategy/ docs/

COMMIT_MSG="A股每日选股更新 $today (RSP:$RSP_COUNT V2:$RPSV2_COUNT Pro:$RPS_PRO_COUNT RSI:$RSI_COUNT SIG:$SIG_COUNT MA:$MA_COUNT STB:${STB_BUY_COUNT}x${STB_SELL_COUNT} Res:$RES_COUNT Mid:$MIDCAP_COUNT Sec:$SECTORS_COUNT)"
git commit -m "$COMMIT_MSG"
OK "Git 提交完成"

if git push origin "$BRANCH" 2>&1; then
  OK "已推送到 GitHub (Pages 将自动更新)"
else
  WARN "推送失败，请检查网络连接和凭证"
fi

# ─── Summary ───
echo ""
echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "║   每日选股结果汇总               ║"
echo -e "╚════════════════════════════════════════╝${NC}"
printf "  RSP趋势突破:     %s 只\n" "$RSP_COUNT"
printf "  RPS中长期龙头:   %s 只\n" "$RPSV2_COUNT"
printf "  RPS超强势:       %s 只\n" "$RPS_PRO_COUNT"
printf "  RSI 金叉:        %s 只\n" "$RSI_COUNT"
printf "  多因子:          %s 只\n" "$SIG_COUNT"
printf "  MA 回调:         %s 只\n" "$MA_COUNT"
printf "  超级顶底买入:    %s 只\n" "$STB_BUY_COUNT"
printf "  超级顶底卖出:    %s 只\n" "$STB_SELL_COUNT"
printf "  RSI+共振:        %s 只\n" "$RES_COUNT"
printf "  活跃中盘股:      %s 只\n" "$MIDCAP_COUNT"
printf "  RSP热门板块:     %s 个板块\n" "$SECTORS_COUNT"
echo ""
