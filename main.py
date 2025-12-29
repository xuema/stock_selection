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

    print("🔍 获取热门行业...")
    industries = get_hot_industry(HOT_INDUSTRY_TOPN)

    for ind in industries:
        print(f"\n📌 行业：{ind}")
        
        # 获取行业涨幅（5 日）
        industry_ret_5d = get_industry_return(ind)

        stocks = get_stocks_from_industry(ind)  # (code, name)

        for code, name in stocks:
            try:
                code_6 = str(code).zfill(6)
                df = get_daily_kline(code_6)
                df = indicators(df)

                score = score_strategy(df)
                last = df.iloc[-1]

                # ---- 新增：单日涨跌幅 ----
                pct_chg = last["pct_chg"] if "pct_chg" in last else None

                # ---- 新增：成交额（turnover / amount） ----
                amount = last["amount"] if "amount" in last else None

                # ---- 新增：5 日涨幅 ----
                if len(df) >= 5:
                    price_5d = df.iloc[-5]["close"]
                    price_last = last["close"]
                    ret_5d = round((price_last - price_5d) / price_5d * 100, 2)
                else:
                    ret_5d = None

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

                    stock_num = stock_num + 1

                    print(f"  ✔ {code_6} {name} 得分={score:.2f}")

            except Exception as e:
                print(f"  ✖ {code} 失败: {e}")

    # 输出
    result_df = pd.DataFrame(all_results)
    result_df.to_excel(OUTPUT_EXCEL, index=False)
    print(f"\n📁 结果已输出到：{OUTPUT_EXCEL}")

    # 生成邮件正文内容
    if all_results:  # 确保有结果
        codes_names = [f"{item['代码']}" for item in all_results]
        codes_names_str = ", ".join(codes_names)
        email_content = f"今日符合策略的股票见附件。总共筛选出{stock_num}支股票。\n\n股票列表:\n{codes_names_str}"
    else:
        email_content = "今日没有符合策略的股票。"

    # 邮件发送
    send_email(
        subject="A股强势延续策略选股结果",
        content=email_content,
        attachments=[OUTPUT_EXCEL],
    )

if __name__ == "__main__":
    main()
