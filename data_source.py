import akshare as ak
import pandas as pd

def get_hot_industry(top_n=10):
    df = ak.stock_board_industry_name_em()
    df = df.sort_values("涨跌幅", ascending=False).head(top_n)

    #df["板块热度"] = df["涨跌幅"] * 0.5 + df["换手率"] * 0.3 + (df["上涨家数"] / (df["上涨家数"] + df["下跌家数"])) * 0.2
    top_hot = df.sort_values("涨跌幅", ascending=False).head(top_n)

    return df["板块名称"].tolist()

def get_stocks_from_industry(industry):
    df = ak.stock_board_industry_cons_em(industry)
    return [(row["代码"], row["名称"]) for _, row in df.iterrows()]

def get_industry_return(industry):
    """获取行业指数 5 日涨幅（%）"""
    try:
        df = ak.stock_board_industry_name_ths()
        code = df[df["板块名称"] == industry]["代码"].iloc[0]

        kl = ak.stock_board_industry_index_ths(symbol=code)
        kl = kl.tail(5)

        start = kl.iloc[0]["收盘"]
        end = kl.iloc[-1]["收盘"]

        return round((end - start) / start * 100, 2)
    except:
        return None

def get_daily_kline(code):
    df = ak.stock_zh_a_hist(symbol=code, adjust="qfq")
    df = df[["日期", "收盘", "开盘", "最高", "最低", "成交量"]]
    df.columns = ["date", "close", "open", "high", "low", "volume"]
    df["date"] = pd.to_datetime(df["date"])
    return df
