# 1_update_finiance_data_quartly

## 功能说明

批量更新 `final_rankings_with_details_latest.xlsx` 中 4604 只 A 股的最新季度财务数据。

> 财务类列（E–I，含报告期）已由 `update_finance_latest_quarter.py` 走东财 `datacenter` 接口批量刷新，
> 全市场约 10 秒；本脚本的浏览器抓取只在需要 J–P 列（概念/PB/PE/总市值/业绩预测/股东）时才用得上。

## 数据源

同花顺 basic.10jqka.com.cn，通过 Selenium + Chrome 模拟浏览器抓取。

## 更新的列

| 列名 | Excel 列 | 来源 |
|------|----------|------|
| 营收增长 | E | finance.html JSON (营业总收入同比增长) |
| 净利同比增长 | F | finance.html JSON (净利润同比增长) |
| 销售毛利率 | G | finance.html JSON |
| 净资产收益率 | H | finance.html JSON |
| 资产负债率 | I | finance.html JSON |
| 涉及概念 | J | concept.html (gnName) |
| 市净率(PB) | K | 主页 (sjl) |
| 市盈率(静态) | L | 主页 (jtsyl) |
| 市盈率(动态) | M | 主页 (dtsyl) |
| 总市值 | N | 主页 (stockzsz) |
| 业绩预测 | O | worth.html (yjycData) |
| 十大股东占比 | P | holder.html |

## 使用方法

```bash
# 测试模式：处理前 5 只股票
python3 1_update_finiance_data_quartly.py --limit 5

# 更新全部
python3 1_update_finiance_data_quartly.py

# 指定范围
python3 1_update_finiance_data_quartly.py --start 2 --end 100

# 带备份
python3 1_update_finiance_data_quartly.py --backup

# 断点续传（从第 1000 行开始）
python3 1_update_finiance_data_quartly.py --start 1000
```

## 注意事项

- **运行前请关闭 Chrome 浏览器**，否则脚本无法启动新实例
- 每只股票间随机等待 2.5~5.5 秒，防止被封锁
- 每 20 只股票自动保存一次 Excel
- 如遇登录拦截，脚本会暂停等待你手动登录

## 依赖

```bash
pip3 install selenium openpyxl setuptools
```
