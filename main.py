from data_source import (
    get_hot_industry,
    get_stocks_from_industry,
    get_daily_kline,
    get_industry_return,
)
from indicators import indicators
from strategy import score_strategy
from utils import send_email
from config import *
import pandas as pd

def main():
    all_results = []
    stock_num = 0

    # 保存每个行业中股票的当日涨幅 & 5日涨幅（用于 Top5）
    industry_stock_perf = {}

    print("🔍 获取热门行业...")
    top_hot_df = get_hot_industry(HOT_INDUSTRY_TOPN)
    industries = top_hot_df["板块名称"].tolist()

    for ind in industries:
        print(f"\n📌 行业：{ind}")
        industry_stock_perf[ind] = []

        # 行业 5 日涨幅
        industry_ret_5d = get_industry_return(ind)

        # 成分股
        stocks = get_stocks_from_industry(ind)
        if not stocks:
            continue

        for code, name in stocks:
            try:
                code_6 = str(code).zfill(6)
                df = get_daily_kline(code_6)
                df = indicators(df)

                score = score_strategy(df)
                last = df.iloc[-1]

                # 当日涨跌幅                
                if len(df) >= 2:
                    prev_close = df.iloc[-2]["close"]
                    today_close = last["close"]
                    pct_chg = round((today_close - prev_close) / prev_close * 100, 2)
                else:
                    pct_chg = None

                # 成交额
                amount = last["amount"] if "amount" in last else None

                # 5 日累计涨幅
                if len(df) >= 5:
                    price_5d = df.iloc[-5]["close"]
                    price_last = last["close"]
                    ret_5d = round((price_last - price_5d) / price_5d * 100, 2)
                else:
                    ret_5d = None

                # =========================
                # 行业 Top5（按当日涨幅）
                # =========================
                if pct_chg is not None and ret_5d is not None:
                    industry_stock_perf[ind].append({
                        "代码": code_6,
                        "名称": name,
                        "当日涨幅%": round(pct_chg, 2),
                        "5日累计涨幅%": ret_5d
                    })

                # =========================
                # 原有强势策略（不变）
                # =========================
                if score >= SCORE_THRESHOLD:
                    all_results.append({
                        "代码": code_6,
                        "名称": name,
                        "行业": ind,
                        "行业5日涨幅%": industry_ret_5d,
                        "收盘价": last["close"],
                        "涨跌幅%": pct_chg,
                        "成交额(亿)": round(amount / 1e8, 2) if amount else None,
                        "股票5日涨幅%": ret_5d,
                        "得分": round(score, 3)
                    })

                    stock_num += 1
                    print(f"  ✔ {code_6} {name} 得分={score:.2f}")

            except Exception as e:
                print(f"  ✖ {code} 失败: {e}")

    # =========================
    # 输出 Excel（原功能）
    # =========================
    result_df = pd.DataFrame(all_results)
    result_df.to_excel(OUTPUT_EXCEL, index=False)
    print(f"\n📁 结果已输出到：{OUTPUT_EXCEL}")
    
    
    # =========================
    # 当日策略入选股票代码（一行）
    # =========================
    selected_codes_str = ""
    if all_results:
        selected_codes_str = "、".join([item["代码"] for item in all_results])


    # =========================
    # 生成行业「当日涨幅 Top5」
    # =========================
    industry_top5_map = {}
    for ind, stocks in industry_stock_perf.items():
        if not stocks:
            continue
        top5 = sorted(
            stocks,
            key=lambda x: x["当日涨幅%"],
            reverse=True
        )[:6]
        industry_top5_map[ind] = top5

    # =========================
    # 邮件正文
    # =========================
    email_lines = []

    email_lines.append(f"本次共选取 {len(industries)} 个热门行业：")
    email_lines.append(",".join(industries))
    email_lines.append("\n")

    if all_results:
        email_lines.append(f"📈 强势延续策略共筛选出 {stock_num} 支股票：")
        email_lines.append(selected_codes_str + "\n")
    else:
        email_lines.append("📉 今日没有符合强势延续策略的股票。\n")


    email_lines.append("🔥 各热门行业【当日涨幅 Top5 股票】（含 5 日累计涨幅）：")

    for ind, top5 in industry_top5_map.items():
        email_lines.append(f"\n【{ind}】")
        for item in top5:
            email_lines.append(
                f"- {item['代码']} {item['名称']}："
                f"当日 {item['当日涨幅%']}%，"
                f"5日 {item['5日累计涨幅%']}%"
            )

    email_content = "\n".join(email_lines)

    send_email(
        subject="A股强势延续策略选股结果",
        content=email_content,
        attachments=[OUTPUT_EXCEL],
    )


if __name__ == "__main__":
    main()
