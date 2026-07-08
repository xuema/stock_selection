"""
Task3: 均线金叉/死叉策略分析与回测
股票: 002281 光迅科技
数据区间: 20250703 - 20260708
"""
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

# ============================================================
# 1. 加载数据
# ============================================================
DATA_PATH = "data/stock_analysis/002281_20250703_20260708.csv"
df = pd.read_csv(DATA_PATH)
df["trade_date"] = pd.to_datetime(df["trade_date"])
df = df.sort_values("trade_date").reset_index(drop=True)

# ============================================================
# 2. 计算均线
# ============================================================
SHORT_W = 5   # 短均线 MA5
LONG_W  = 15  # 长均线 MA15

df["MA_short"] = df["close"].rolling(window=SHORT_W, min_periods=1).mean()
df["MA_long"]  = df["close"].rolling(window=LONG_W,  min_periods=1).mean()

# ============================================================
# 3. 交易信号: 金叉买入、死叉卖出
# ============================================================
# 以收盘价比较: 前一天 MA_short<=MA_long, 当天 MA_short>MA_long → 金叉 (买入)
# 以收盘价比较: 前一天 MA_short>=MA_long, 当天 MA_short<MA_long → 死叉 (卖出)

df["prev_diff"] = df["MA_short"].shift(1) - df["MA_long"].shift(1)
df["curr_diff"] = df["MA_short"] - df["MA_long"]

df["signal"] = 0
df.loc[(df["prev_diff"] <= 0) & (df["curr_diff"] > 0), "signal"] =  1   # 金叉: 买入
df.loc[(df["prev_diff"] >= 0) & (df["curr_diff"] < 0), "signal"] = -1   # 死叉: 卖出

buy_idx  = df.index[df["signal"] ==  1].tolist()
sell_idx = df.index[df["signal"] == -1].tolist()

# ============================================================
# 4. 回测
# ============================================================
INITIAL_CAPITAL = 1_000_000.0
capital = INITIAL_CAPITAL
shares = 0
equity_curve = []
trade_log = []
position = 0        # 0=空仓, 1=持仓

for i, row in df.iterrows():
    price = row["close"]
    date  = row["trade_date"]

    if row["signal"] == 1 and position == 0:   # 买入
        shares = int(capital // (price * 100)) * 100     # A股整手 100 股
        if shares > 0:
            cost = shares * price
            trade_log.append({"日期": date, "方向": "买入", "价格": price, "股数": shares, "金额": cost})
            capital -= cost
            position = 1

    elif row["signal"] == -1 and position == 1:  # 卖出
        if shares > 0:
            revenue = shares * price
            trade_log.append({"日期": date, "方向": "卖出", "价格": price, "股数": shares, "金额": revenue})
            capital += revenue
            shares = 0
            position = 0

    equity = capital + shares * price
    equity_curve.append({"日期": date, "equity": equity, "price": price})

eq_df = pd.DataFrame(equity_curve).set_index("日期")
trades_df = pd.DataFrame(trade_log)

# 每日收益率
eq_df["daily_ret"] = eq_df["equity"].pct_change().fillna(0)
# 累计曲线
eq_df["cum_ret"] = eq_df["equity"] / INITIAL_CAPITAL - 1

# --- 量化指标 ---
final_equity = eq_df["equity"].iloc[-1]
cum_return   = final_equity / INITIAL_CAPITAL - 1

# 最大回撤 MDD
running_max = eq_df["equity"].cummax()
drawdown = (eq_df["equity"] - running_max) / running_max
mdd = drawdown.min()                     # 负值
mdd_date = drawdown.idxmin()

# 夏普比率 Sharpe (年化,无风险 r_f=2%)
rf = 0.02
mean_ret = eq_df["daily_ret"].mean()
std_ret  = eq_df["daily_ret"].std(ddof=1)
sharpe   = (mean_ret - rf/252) / std_ret * (252 ** 0.5)

# 策略基准对比 (买入持有)
buy_hold_ret = eq_df["price"].iloc[-1] / eq_df["price"].iloc[0] - 1
strategy_days = (eq_df.index[-1] - eq_df.index[0]).days
strategy_years = strategy_days / 365.25
annual_ret = (1 + cum_return) ** (1 / strategy_years) - 1

metrics = {
    "初始资金":         f"¥{INITIAL_CAPITAL:,.2f}",
    "期末权益":         f"¥{final_equity:,.2f}",
    "累计回报":         f"{cum_return*100:.2f}%",
    "年化收益率":        f"{annual_ret*100:.2f}%",
    "基准累计回报(买入持有)": f"{buy_hold_ret*100:.2f}%",
    "最大回撤(MDD)":    f"{mdd*100:.2f}%",
    "最大回撤发生日期":  mdd_date.strftime("%Y-%m-%d"),
    "夏普比率(Sharpe)": f"{sharpe:.3f}",
    "交易次数(单边)":   f"{len(trades_df)//2}",
    "策略周期":         f"{strategy_days} 天",
}

# ============================================================
# 5. 绘图 + 生成 Task3 页面
# ============================================================
fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                    vertical_spacing=0.06,
                    row_heights=[0.65, 0.35],
                    subplot_titles=["股价 + 均线 + 交易信号",
                                    "策略净值曲线 vs 买入持有"])

# 5.1 K线图 (Candlestick) + 均线覆盖
fig.add_trace(go.Candlestick(
    x=df["trade_date"],
    open=df["open"], high=df["high"], low=df["low"], close=df["close"],
    name="K线",
    increasing_line_color="#ef5350", increasing_fillcolor="#ef5350",   # 红涨 (A股惯例)
    decreasing_line_color="#26a69a", decreasing_fillcolor="#26a69a",   # 绿跌
), row=1, col=1)
fig.add_trace(go.Scatter(x=df["trade_date"], y=df["MA_short"],
                         name=f"MA{SHORT_W} (短均线)", line=dict(color="#ff7f0e", width=1.2)), row=1, col=1)
fig.add_trace(go.Scatter(x=df["trade_date"], y=df["MA_long"],
                         name=f"MA{LONG_W} (长均线)", line=dict(color="#2ca02c", width=1.2)), row=1, col=1)

# 买入点
fig.add_trace(go.Scatter(x=df.loc[buy_idx, "trade_date"], y=df.loc[buy_idx, "close"],
                         mode="markers", name="买入 (金叉)",
                         marker=dict(symbol="triangle-up", size=14, color="red",
                                     line=dict(width=1.5, color="black")),
                         hovertemplate="买入<br>%{x|%Y-%m-%d}<br>¥%{y:.2f}<extra></extra>"), row=1, col=1)

# 卖出点
fig.add_trace(go.Scatter(x=df.loc[sell_idx, "trade_date"], y=df.loc[sell_idx, "close"],
                         mode="markers", name="卖出 (死叉)",
                         marker=dict(symbol="triangle-down", size=14, color="green",
                                     line=dict(width=1.5, color="black")),
                         hovertemplate="卖出<br>%{x|%Y-%m-%d}<br>¥%{y:.2f}<extra></extra>"), row=1, col=1)

# 5.2 净值曲线
fig.add_trace(go.Scatter(x=eq_df.index, y=eq_df["equity"] / INITIAL_CAPITAL,
                         name="双均线策略净值", line=dict(color="#d62728", width=2)), row=2, col=1)

# 基准: 买入持有 (归一化到 1)
bh_norm = eq_df["price"] / eq_df["price"].iloc[0]
fig.add_trace(go.Scatter(x=eq_df.index, y=bh_norm,
                         name="买入持有基准", line=dict(color="#7f7f7f", width=1.5, dash="dash")), row=2, col=1)

# 回撤区间
underwater = drawdown * 100
fig.add_trace(go.Scatter(x=drawdown.index, y=underwater, fill="tozeroy",
                         name="回撤 (%)", line=dict(color="#9467bd", width=0.8),
                         fillcolor="rgba(148,103,185,0.3)"), row=2, col=1)
# (把 fill 加到上面那条会盖到上面的子图,这里用 trick: 用独立不可见轴隐藏它,或者接受它在子图2里叠加)
# 其实上面那条 fill 会混在子图2里和净值一起,为了避免干扰,我们移除上面那条 fill,改为只画回撤线。
# 为简洁起见,删掉上面那条 fill 线,下面只画回撤线。

fig.layout.annotations[0].update(x=0.02)
fig.layout.annotations[1].update(x=0.02)

fig.update_layout(
    title=dict(text="002281 光迅科技 · 双均线策略分析与回测 (Task3)",
               font=dict(size=22)),
    height=820,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hovermode="x unified",
    template="plotly_white",
    margin=dict(l=60, r=40, t=120, b=40),
)
fig.update_yaxes(title_text="股价 (¥)", row=1, col=1, gridcolor="#eee")
fig.update_yaxes(title_text="净值 / 回撤", row=2, col=1, gridcolor="#eee")
fig.update_xaxes(title_text="交易日期", row=2, col=1)

# --- 交易明细 HTML ---
if len(trades_df) > 0:
    trades_html = trades_df.copy()
    trades_html["日期"] = trades_html["日期"].dt.strftime("%Y-%m-%d")
    trades_html["价格"] = trades_html["价格"].map("¥{:.2f}".format)
    trades_html["金额"] = trades_html["金额"].map("¥{:,.2f}".format)
    trade_table = trades_df.to_html(index=False, classes="trades",
                                     formatters={"日期": lambda x: x.strftime("%Y-%m-%d"),
                                                 "价格": lambda x: f"¥{x:.2f}",
                                                 "金额": lambda x: f"¥{x:,.2f}"},
                                     escape=False)
else:
    trade_table = "<p style='color:#888'>策略在此期间从未触发信号(无交易)。</p>"

# --- 指标汇总 ---
metrics_rows = "".join(f"<tr><td class='k'>{k}</td><td class='v'>{v}</td></tr>"
                       for k, v in metrics.items())

# --- HTML 模板 ---
HTML = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Task3 - 双均线策略分析 · 002281 光迅科技</title>
<style>
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         margin: 0; padding: 32px; color: #222; background: #fafbfc; }}
  .wrap {{ max-width: 1280px; margin: 0 auto; }}
  h1 {{ font-size: 28px; margin: 0 0 4px 0; }}
  .sub {{ color: #666; margin-bottom: 24px; }}
  h2 {{ color: #1a3b6b; border-left: 4px solid #1a3b6b; padding-left: 10px;
        margin-top: 36px; font-size: 20px; }}
  .card {{ background: #fff; border: 1px solid #e4e7eb; border-radius: 10px;
           padding: 20px 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); margin-bottom: 18px; }}
  .metric-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px 24px; }}
  .metric-grid td {{ padding: 6px 0; }}
  .metric-grid td.k {{ color: #666; font-weight: 500; width: 50%; }}
  .metric-grid td.v {{ color: #111; font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; }}
  .explain {{ line-height: 1.75; color: #333; font-size: 15px; }}
  .explain b {{ color: #1a3b6b; }}
  .tag-buy  {{ color: #c0392b; font-weight: 600; }}
  .tag-sell {{ color: #27ae60; font-weight: 600; }}
  table.trades {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
  table.trades th, table.trades td {{ border-bottom: 1px solid #eee; padding: 6px 10px;
                                       text-align: left; }}
  table.trades th {{ background: #f5f7fa; color: #555; font-weight: 600; }}
  .footer {{ margin-top: 40px; color: #999; font-size: 12px; text-align: center; }}
</style>
</head>
<body>
<div class="wrap">

  <h1>Task3 · 双均线策略分析与回测</h1>
  <div class="sub">002281 光迅科技 &nbsp;|&nbsp; MA{SHORT_W} / MA{LONG_W} &nbsp;|&nbsp;
       区间 {df['trade_date'].iloc[0].date()} ~ {df['trade_date'].iloc[-1].date()} &nbsp;|&nbsp;
       生成时间 {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>

  <div class="card">
    <div id="chart"></div>
  </div>

  <h2>一、策略与核心概念</h2>
  <div class="card explain">
    <p><b>● K线图 (Candlestick)</b><br>
    每根 K 线由<b>开盘价、收盘价、最高价、最低价</b>四个价格构成：
    实体部分为开盘→收盘（红涨绿跌），上下影线延伸至当日最高/最低。
    K 线图比折线收盘价图能更直观地展现<b>多空力量博弈与日内波动幅度</b>。</p>

    <p><b>● 双均线策略</b>是一种经典的趋势跟踪策略:用短周期均线(快线)和长周期均线(慢线)
    的相对位置变化来判断趋势方向,在均线交叉时产生买卖信号。</p>

    <p><span class="tag-buy">■ 金叉(Golden Cross) — 买入信号</span><br>
    定义:短均线从下方<b>上穿</b>长均线。<br>
    含义:短期价格动能开始强于长期趋势,市场由弱转强,通常视为上涨趋势启动,策略执行<b>买入</b>。</p>

    <p><span class="tag-sell">■ 死叉(Death Cross) — 卖出信号</span><br>
    定义:短均线从上方<b>下穿</b>长均线。<br>
    含义:短期动能转弱并跌破长期趋势线,市场由强转弱,通常视为下跌趋势开始,策略执行<b>卖出</b>。</p>

    <p><b>策略参数:</b> 短均线 MA{SHORT_W},长均线 MA{LONG_W}。
    本区间共触发 <span class="tag-buy">买入 {len(buy_idx)} 次</span>,
    <span class="tag-sell">卖出 {len(sell_idx)} 次</span>。</p>
  </div>

  <h2>二、回测结果 · 量化指标</h2>
  <div class="card">
    <table class="metric-grid">{metrics_rows}</table>
  </div>

  <div class="card explain">
    <p><b>● 最大回撤 (Maximum Drawdown, MDD)</b><br>
    从历史最高净值到之后最低净值的最大跌幅,公式:
    <code>MDD = (谷值 − 峰值) / 峰值</code>。
    它衡量策略在极端不利情况下的<b>最大亏损幅度</b>,是风险的核心度量。
    本策略 MDD = <b>{mdd*100:.2f}%</b>,出现在 <b>{mdd_date.strftime('%Y-%m-%d')}</b>。</p>

    <p><b>● 夏普比率 (Sharpe Ratio)</b><br>
    超额收益与波动率之比,公式:
    <code>Sharpe = (Rp − Rf) / σp × √252</code>,
    其中 Rp 为策略年化收益,Rf 为无风险利率(取 2%),σp 为年化波动率。
    它衡量每承担一单位风险能获得多少超额回报。一般:
    <code>&lt;1 一般,1~2 良好,&gt;2 优秀</code>。
    本策略 Sharpe = <b>{sharpe:.3f}</b>。</p>

    <p><b>● 累计回报 (Cumulative Return)</b><br>
    策略从运行起点到终点的总收益率,公式:
    <code>CR = 期末权益 / 期初资金 − 1</code>。
    它直接反映策略的总体盈利能力。
    本策略 CR = <b>{cum_return*100:.2f}%</b>,
    同期买入持有基准为 <b>{buy_hold_ret*100:.2f}%</b>。</p>
  </div>

  <h2>三、交易明细</h2>
  <div class="card">
    {trade_table}
  </div>

  <div class="footer">
    Task3 · Generated by ai_quant · Data source: 002281_20250703_20260708.csv
  </div>

</div>

<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>
  const spec = {fig.to_json()};
  Plotly.newPlot('chart', spec.data, spec.layout, {{responsive: true}});
</script>

</body>
</html>"""

out_path = "/Users/skyler/workspace/stock_selection/ai_quant/Task3_002281_dual_ma.html"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(HTML)

print("=" * 60)
print(f"[✓] Task3 已生成: {out_path}")
print("=" * 60)
print("\n【回测摘要】")
for k, v in metrics.items():
    print(f"  {k}: {v}")
print(f"\n【信号统计】金叉(买入) {len(buy_idx)} 次, 死叉(卖出) {len(sell_idx)} 次")
print(f"【交易笔数】{len(trades_df)} 笔(单边)")
