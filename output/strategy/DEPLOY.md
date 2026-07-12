# 📈 A股每日选股看板 — GitHub Pages 部署

## 目录结构

```
stock_selection/
├── daily_screen.sh              # 每日自动化运行脚本
├── output/strategy/
│   ├── index.html               # 可视化看板页面
│   ├── dates.json               # 历史日期索引（自动生成）
│   ├── screen_rsi_golden_cross_2026-07-12.json  # 每日 dated JSON
│   ├── screen_rsi_golden_cross_latest.json      # 最新 RSI 数据
│   ├── screen_signals_2026-07-12.json
│   └── screen_signals_latest.json
├── ai_quant/strategy/
│   ├── screen_rsi_golden_cross.py  # RSI策略
│   └── screen_signals.py              # 多因子策略
└── 2_update_a_stock_data.py        # 数据更新
```

## GitHub Pages 部署步骤

### 1. 配置 GitHub Pages

进入仓库 Settings → Pages:
- Source: `Deploy from a branch`
- Branch: `main`
- Folder: `/output/strategy` （注意：GitHub Pages 默认从 repo 根开始，需要用自定义路径）

**或者更简单的方式** — 创建 `docs/` 目录并指向它：

```bash
# 创建软链接或拷贝
cd /Users/skyler/workspace/stock_selection
mkdir -p docs
# 策略输出指向 docs
ln -sf ../output/strategy/* docs/
```

或者直接配置 Pages: Branch: `main`, Directory: `output/strategy`
（注意：GitHub Pages 只允许根目录、docs/ 或 .github 目录）

**推荐方案** — 创建 `docs` 目录，每日脚本自动拷贝：

```bash
mkdir -p docs
# 在 daily_screen.sh 中加一步
cp output/strategy/index.html docs/
cp output/strategy/dates.json docs/
cp output/strategy/*_latest.json docs/
cp output/strategy/screen_rsi_golden_cross_*.json docs/ 2>/dev/null || true
cp output/strategy/screen_signals_*.json docs/ 2>/dev/null || true
```

然后 Pages 设置为: Branch `main`, Directory `docs/`

### 2. 设置定时任务（cron）

```bash
# 每天下午 4:30 执行（交易日）
# macOS crontab:
30 16 * * 1-5 /Users/skyler/workspace/stock_selection/daily_screen.sh >> /tmp/daily_screen.log 2>&1

# 或用 openclaw cron job（推荐，更好管理）
```

### 3. 访问方式

部署后访问:
`https://xuema.github.io/stock_selection/`

### 4. 新增交易日数据

每天脚本运行时会自动：
1. 生成 `screen_*_YYYY-MM-DD.json` dated 文件
2. 覆盖 `screen_*_latest.json` 最新文件
3. 更新 `dates.json` 历史日期索引
4. Git commit + push

HTML 页面会自动加载最新数据，历史 tab 可切换日期。
