# rps_pool — 基金+北向股票池上的 RPS 双策略每日筛选与回测

两步走:每季度用"基金持股 > 3% + 北向持股 > 3000 万 + 上市满 1 年"建一个股票池;每个交易日 13:50
在这个池里跑通达信 RPS 选股公式(SXHCG1..5),再叠加两个确认条件,输出策略1/策略2 的入选名单、
卖出提示和一个自包含看板。买入价统一取当日最后一根日线收盘(即 13:50 快照价),卖点参考 Elder
周线 RSI 死叉。

```
fetch_quarterly.py ──> data/quarter/<报告期>/ ──> build_pool.py ──> out/pool/pool_latest.csv
                                                                      │
fetch_history.py --update ──> data_cache_daily_5y/*.csv ──────────────┤
                                                                      ├─> screen_daily.py ──> out/screen/<日期>/
                                                                      │        └─ 13:50 快照 ────┐
                                                                      ├─> backtest.py ──────────┼─> dashboard.py
                                                                      └─> bt_sweep.py ──────────┘   out/dashboard.html
```

## 文件

| 文件 | 作用 |
|---|---|
| `config.py` | 所有路径与可调参数(`POOL` / `RPS` / `WK_RSI` / `BT`),脚本都从这里取,便于整体迁移 |
| `emhttp.py` | HTTP 客户端,自动在直连与环境代理之间选可用通道(东财 datacenter 走代理,新浪/推送接口必须直连) |
| `fetch_quarterly.py` | 抓三张季度表:基金持仓、前十大流通股东里的北向席位、上市日期 |
| `build_pool.py` | 第一步:按 A(基金/流通股 > 3%)+ B(北向市值 > 3000 万)+ C(上市满 1 年)+ D(本机有日线)建池 |
| `fetch_history.py` | 日线缓存:`--build` 全量回填(6 年)、`--update` 每日增量并做复权漂移检测、`--rebuild` 强制重下 |
| `indicators.py` | 指标引擎:通达信公式向量化,SXHCG1..5 + RPS + 周线 RSI 全部在这里 |
| `poolio.py` | 读池子;从基金持仓表反推流通股本 `float_shares_calc = 基金持股数 / (持股占流通股比例/100)`,供 SXHCG5 换手率用 |
| `screen_daily.py` | 第二步:每日筛选,写 `out/screen/<日期>/` 与 `dashboard.json` |
| `backtest.py` | 同一套信号逐日重放回测,写净值/交易/指标/`counts_<tag>.csv` |
| `bt_sweep.py` | 参数敏感性网格(一次载入、按参数组合缓存信号) |
| `dashboard.py` | 把筛选结果 + 回测产物合成单文件 HTML |
| `export_pipeline.py` | 适配器:把 `dashboard.json` 写成主仓 `output/strategy/` 的 `screen_*.json` 契约,接进 `daily_screen.sh` 的看板 |
| `selftest.py` | 用朴素循环实现交叉验证向量化引擎 |
| `run_daily.sh` / `run_quarterly.sh` / `run_all.sh` | 定时任务包装,日志写 `out/logs/` |

## 数据口径

- 日线来自 `data_cache_daily_5y/{code}.csv`(yfinance `auto_adjust=True` ⇒ **前复权**),6 年回填
  5255 只、成功约 5125 只、130 只退市/无数据,当前 1455 个交易日。
- 停牌/未上市:价格前向填充、成交量记 0,否则横截面 RPS 排名无法对齐。
- 毛刺清洗 `indicators.sanitize()`:单日跳变 > 35% 且次日又跳回 ⇒ 判为数据错误,当日 OHLC 用前值
  替换、成交量置 0。真实涨跌停(主板 10% / 创业科创 20% / 北交 30%)不会同时满足"次日反向跳回"。
- Open 不可靠,`fix_ohlc` 把 High/Low 按 Close 夹紧。
- 买入价 = 当日最后一根日线收盘。本机每日 13:50 抓取,所以它就是"收盘前约 1 小时"的价格。
- 与本机既有的 `data_cache_daily` 缓存交叉校验(4337 只重叠票、重叠日期对齐):最新价比中位 1.0034,
  250 日涨幅相关 0.973、逐票绝对差中位 0.85pp。

## 通达信公式 → 代码对应

全部在 `indicators.sxhcg()`。宽表约定:行 = 交易日(全市场统一日历),列 = 股票代码。

| 公式 | 代码 |
|---|---|
| `SXHCG1: RPSHC120+RPSHC250>185` | `RPS(ret_n(Close,120)) + RPS(ret_n(Close,250)) > sum_min`;RPS = 逐日横截面百分位 × 100(`ret.rank(axis=1, pct=True)*100`) |
| `SXHCG2: C>MA20 & COUNT(C>MA250,30)>=25 & COUNT(C>MA200,30)>=25 & (COUNT(C>MA20,10)>=9 \| (COUNT(C>MA10,4)>=3 & COUNT(C>MA20,4)>=3))` | 同形状,`COUNT` = `cond.astype(float).rolling(n).sum()` |
| `SXHCG31` 结构回撤 ≤ 25% 且区间内从未破 | `hhb=HHVBARS(H,20)`;`llb=LLVBARS(L,hhb)`(变长);`hi=REF(H,hhb)`、`lo=REF(L,llb)`;`dd=(hi-lo)/hi`;`_count_var(dd>0.25, hhb, 20)==0` |
| `SXHCG32: C/HHV(C,250)>0.8` | `newhigh` |
| 策略2 的 `C/HHV(H,250)>0.9` | `newhigh_h` |
| `SXHCG4: EVERY(MA20 上升 & MA10>=MA20, 5) \| (MA10↑ & MA20↑ & MA10>=MA20)` | `EVERY(...)` = `COUNT(...)>=n` |
| `SXHCG5: VOL/CAPITAL*100<10` | `turn = Volume / float_shares_calc * 100`;拿不到流通股本的票视为通过(否则会被误杀) |
| 变长 `REF(X,K)` / `COUNT(X,K)` / `LLVBARS(X,K)` | `_ref_var`(numpy 花式索引)、`_count_var`(累积和差分)、`LLVBARS_var`(按 K 分档) |
| `HHVBARS` 并列 | 取最靠右(最近)的一根,已验证不变量 `REF(H,HHVBARS(H,20)) == HHV(H,20)` |

周线 RSI(`indicators.weekly_rsi_daily`,《以交易为生》):

- `RSI1 = 周线 RSI(12)`、`RSI2 = MA(RSI1,5)`、`RSI3 = 50 中枢`(`three_line=True` 时改为 `MA(RSI1,24)`)。
- 平滑用递推 `SMA(X,N,1)` ⇔ `ewm(alpha=1/N, adjust=False)`,不是经典 Wilder seed。
- 关键一步:把周线状态落到**每一根日线**上 —— 本周尚未走完时,用当日收盘价充当该周的临时周收盘,
  所以 13:50 看到的状态就等于周线图"本周走到现在"的状态。
  由此 `RSI1 > RSI2` ⇔ `RSI1 > 前 4 周 RSI1 的均值`,不需要未来数据。
- 买入确认 = `RSI1 上穿 RSI2`(金叉)且 `RSI1 > RSI3`;卖出 = `RSI1 下穿 RSI2` 且 `RSI1 < RSI3`。

两个策略(都以 SXHCG 全条通过为前提):

- **策略1** = SXHCG 且 周线 `RSI1 > RSI2` 且 `RSI1 > RSI3`;排序先按"距今多少个交易日出现周线金叉"
  (越新鲜越前),再按 RPS 合计。
- **策略2** = SXHCG 且 `CLOSE/HHV(HIGH,250) > 0.90`;按距新高比例降序。

卖出提示(`sell_alerts.csv` / 看板第三张表)的口径要注意:周线死叉相对 SXHCG 是**滞后确认**。本次
43 条里,"上次入选"最近也要 29 个交易日以前 —— 因为死叉要求 `RSI1` 下穿 `RSI2`,而这时日线的
`C>MA20` 等趋势条件通常早就破了、票已经掉出策略。所以这一栏回答的是"如果你还拿着它,现在该不该走",
不是"它今天还在不在策略里"。回测的平均持有 120 日、中位收益为负,根源就是这个出场偏晚。

## 怎么跑

```bash
cd rps_pool
./run_daily.sh                 # 行情增量 -> 每日筛选 -> 看板(每日)
./run_daily.sh --skip-fetch    # 不抓行情,用现有缓存重出结果
./run_quarterly.sh             # 季度全套:季报 -> 建池 -> 补历史 -> 筛选 -> 回测 -> 敏感性 -> 看板
./run_all.sh                   # 只重跑分析部分(不动数据)

../venv/bin/python3 selftest.py                        # 引擎自检,改过 indicators.py 后必跑
../venv/bin/python3 screen_daily.py --asof 2026-11-20 --top 30 --sell-win 10
../venv/bin/python3 backtest.py --start 2022-01-04 --tag main --counts
../venv/bin/python3 backtest.py --strategy 2 --universe pool --max-pos 20 --sell-mode cross --quick
../venv/bin/python3 dashboard.py --tag main
```

`fetch_history.py --build` 全量回填约 17 分钟,只在缓存损坏或换源时用。

## 输出

- `out/pool/`:`pool_<报告期>.csv`(含 `fund_ratio_float`、`north_value`、`float_shares_calc`)、
  `pool_latest.csv`、`pool_codes_latest.txt`、`rejected_<报告期>.csv`(落选审计)。
- `out/screen/<YYYYMMDD>/`:`strategy1.csv` `strategy2.csv`(逐条 SXHCG 布尔 + RPS + 周线 RSI +
  距新高 + 换手 + 基金/北向)、`all_pool.csv`(全池明细)、`sell_alerts.csv`(卖出提示)、
  `near_miss.csv`(落选归因,`未过` 列写明是 SXHCG 第几条没过)、`summary.txt`、`dashboard.json`。
- `out/backtest/`:`nav_*.csv` `trades_*.csv` `metrics_*.json` `nav_all_main.csv` `counts_main.csv`
  (逐日入选数)`sweep.csv`(敏感性)。
- `out/dashboard.html`:单文件、无外部依赖、双击即看。策略1/策略2/卖出三张表可点表头排序,净值与
  历史入选数是内联 SVG,另有回测指标卡、敏感性表和最近 60 笔平仓交易。
- 接进主流水线后另有 `$REPO/output/strategy/`:`screen_rps_pool_dual_<日期>.json` + `_latest.json`
  (S1/S2 合并,`strat` 列标明 S1 / S2 / S1+S2)、`screen_rps_pool_sell_<日期>.json`(死叉提示)、
  两张对应的 PNG 网格(`gen_stock_images.py`)、以及 `dates.json` 里的 `rpspool` / `rpspoolSell`。

## 当前一次结果(2026-11-23,窗口 2022-01-04..2026-11-23)

股票池 598 只(有日线 597)→ 过 RPS 选股 14 只 → 策略1 11 只、策略2 13 只、卖出提示 43 只。

| | 总收益 | 年化 | 最大回撤 | 夏普 | 笔数 | 胜率 | 均持有 | 盈亏比 |
|---|---|---|---|---|---|---|---|---|
| 策略1 | +4.79% | 0.99% | −62.9% | 0.21 | 95 | 38.9% | 120 日 | 2.32 |
| 策略2 | +26.35% | 5.07% | −57.8% | 0.32 | 90 | 35.6% | 124 日 | 3.01 |
| 沪深300 | −2.96% | −0.63% | — | — | — | — | — | — |

分年:策略1 −8.3% / −13.8% / +3.8% / **+85.6%** / −31.5%;策略2 −10.3% / −8.2% / +5.2% / **+72.5%** /
−14.9%。收益几乎全部来自 2025 年,其余年份基本是亏的 —— 这不是稳健的绝对收益策略,更像"趋势
确认了才进场"的择时篮子。策略1 有 87/95 笔由周线 RSI 死叉出场(8 笔超时),最好 300476 +372%、
最差 688205 −51%。

## 已知局限

1. **北向是近似口径**。2024-08 起交易所停发个股每日北向持股,只能用季报前十大流通股东里
   "香港中央结算有限公司"席位近似(已排除 HKSCC 代理人/外资代持,它们不属于北向)。这会让池子
   偏保守且滞后一个季度。
2. **前视/幸存者偏差**。回测用"当前"股票池回溯 2022 年,等于用了未来才知道的持仓信息;真实
   每季度重选会更早剔除走坏票、也更晚纳入新入围票。所以上表的收益偏乐观,横向比较参数才有意义。
3. **换手率用当前流通股本**近似历史(`float_shares_calc` 来自最新季报反推),对期间有解禁/增发的
   票会失真。
4. **变长 `HHVBARS/LLVBARS` 并列极值取最靠右一根**,通达信某些版本取最左,个别票的高点天数会差
   1 根,进而影响 `SXHCG31` 的判定。
5. 13:50 快照价与真实收盘价有差异,周末/停牌周的金叉判定按"当周临时周收盘"处理,回测里也一样。

## 参数怎么调(实测,见 `out/backtest/sweep.csv`)

| 改动 | 结果 |
|---|---|
| `RPS.sum_min` 185 → 180 | 年化完全不变。信号格确实多了 7.76%,但补仓位按 RPS 合计降序排,多出来的边际带永远排不进 |
| `WK_RSI.sell_mode` `cross` → `state` | 明显变差:策略1 0.99% → −11.25%,策略2 5.07% → −17.14%。字面"下穿当根"比"处于下方"更好 |
| `BT.max_positions` 5 / 10 / 20 | 策略1 −0.37% / 0.99% / 4.79%;策略2 5.90% / 5.07% / 9.10% ⇒ 这两个策略集中度高,分散才有肉 |
| `WK_RSI.three_line=True`(RSI3 用 MA24) | 敏感性里最好的一档:策略1 年化 13.49%、策略2 8.97%;均持有从 120 日缩到 40 日,笔数升到 271/285 |
| `--universe all`(全市场,不加池) | 崩:策略1 −21.0%、策略2 −29.4%,回撤 −72%/−84% ⇒ 基金+北向这个池本身是最大的正贡献 |

想改阈值直接编辑 `config.py`,改完跑一次 `selftest.py` 再跑 `run_all.sh`。

## 定时任务(已接进主仓 daily_screen.sh)

本机 crontab 本来就有一行 `50 13 * * * .../daily_screen.sh`,rps_pool 现在是它的一部分,不需要新装 cron:

- **Step 1a**(后台启动,与 Step 1..12 并行):`fetch_history.py --update --universe full --chunk 100`,
  日志 `rps_pool/logs/fetch_daily.log`。全市场约 5000 只,实测 6~20 分钟;因为并行,基本不拖慢整条流水线。
- **Step 1b**:`wait` 上一步 → `screen_daily.py` → `export_pipeline.py --output-dir $OUTPUT_DIR`,之后按
  其它策略的老规矩统计 `total_matched`、写进 `dates.json`、生成 PNG、随主仓一起 commit + push。
- 任一环节失败只打 `WARN` 并继续,不会把后面的策略带崩。
- 盘中反复调参想跳过行情:`RPSPOOL_SKIP_FETCH=1 ./daily_screen.sh`。
- 池子季报期落后时 `summary.txt` 会多打一行 `⚠ 已落后于应有的 <报告期>, 请跑 ./run_quarterly.sh`;
  季度那一套(季报→建池→回测→敏感性)仍然手动/按需跑,不塞进每日任务。

想彻底独立于主仓(或不想要主仓那条 cron)时,也可以单独挂:

```cron
# 交易日 13:00 起跑:抓取+筛选约 15 分钟,赶在 13:50 拿到当日快照(与 daily_screen.sh 重复,二选一)
0 13 * * 1-5        cd /Users/skyler/workspace/stock_selection/rps_pool && ./run_daily.sh      >> out/logs/cron_daily.log     2>&1

# 季报披露截止为 4-30 / 8-31 / 10-31,定在 2/5/8/11 月 5 号,config.latest_report_day() 会自动挑"已披露完"的最近一季
0 9 5 2,5,8,11 *   cd /Users/skyler/workspace/stock_selection/rps_pool && ./run_quarterly.sh >> out/logs/cron_quarterly.log 2>&1
```

日志在 `out/logs/daily_YYYYMMDD.log`、`out/logs/quarterly_YYYYMMDD.log`;脚本内部会失败即退出并打
`!!` 前缀,便于 `grep '!!'` 排查。
