import akshare as ak
import pandas as pd
from fuzzywuzzy import process
import requests

# =========================
# 1. 获取行业行情（东方财富）
# =========================
def get_board_data():
    df_board = ak.stock_board_industry_name_em()
    df_board = df_board[[
        "板块名称", "涨跌幅", "领涨股票-涨跌幅", "上涨家数", "下跌家数", "换手率", "总市值"
    ]]
    df_board.dropna(subset=["板块名称"], inplace=True)
    return df_board

# =========================
# 2. 获取行业资金流（同花顺）
# =========================
def get_fund_flow():
    url = "http://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": "50",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:90+t:2,m:90+t:3",
        "fields": "f12,f14,f62"  # f12=板块名称, f14=净额, f62=主力净流入
    }
    resp = requests.get(url, params=params)
    data = resp.json()
    if "data" in data and "diff" in data["data"]:
        df = pd.DataFrame(data["data"]["diff"])
        df = df.rename(columns={"f12": "TS行业名称", "f14": "净额", "f62": "主力净流入"})
        return df
    return pd.DataFrame(columns=["TS行业名称", "净额", "主力净流入"])

# =========================
# 3. 模糊匹配行业名称（自动对齐）
# =========================
def align_industry_names(df_board, df_fund, threshold=70):
    fund_list = df_fund["TS行业名称"].tolist()
    mapping = {}
    for name in df_board["板块名称"]:
        match = process.extractOne(name, fund_list)
        if match and match[1] >= threshold:
            mapping[name] = match[0]
        else:
            mapping[name] = None
    df_board["TS行业名称"] = df_board["板块名称"].map(mapping)
    df_merge = pd.merge(df_board, df_fund, on="TS行业名称", how="left")
    return df_merge.fillna(0)

# =========================
# 4. 计算板块热度得分
# =========================
def calculate_hot_score(df_merge):
    score_cols = ["涨跌幅", "领涨股票-涨跌幅", "上涨家数", "换手率", "净额", "主力净流入"]
    for col in score_cols:
        min_val = df_merge[col].min()
        max_val = df_merge[col].max()
        df_merge[col + "_score"] = 0 if max_val - min_val == 0 else (df_merge[col] - min_val) / (max_val - min_val)

    # 综合热度得分（权重可调整）
    df_merge["热度得分"] = (
        df_merge["涨跌幅_score"] * 0.35 +
        df_merge["换手率_score"] * 0.20 +
        df_merge["净额_score"] * 0.25 +
        df_merge["上涨家数_score"] * 0.20
    )
    return df_merge.sort_values("热度得分", ascending=False)

# =========================
# 5. 获取行业成分股（模糊匹配防止 IndexError）
# =========================
def get_stocks_from_industry(industry_name, threshold=70):
    df_all = ak.stock_board_industry_name_em()
    all_names = df_all["板块名称"].tolist()

    match = process.extractOne(industry_name, all_names)
    if not match or match[1] < threshold:
        print(f"⚠ 板块 '{industry_name}' 未找到对应名称")
        return []

    matched_name = match[0]

    try:
        df = ak.stock_board_industry_cons_em(matched_name)
        return [(row["代码"], row["名称"]) for _, row in df.iterrows()]
    except Exception as e:
        print(f"⚠ 获取板块成分股失败: {e}")
        return []

# =========================
# 6. 获取行业指数最近5日涨幅
# =========================
def get_industry_return(industry_name):
    try:
        df = ak.stock_board_industry_name_ths()
        code = df[df["板块名称"] == industry_name]["代码"].iloc[0]
        kl = ak.stock_board_industry_index_ths(symbol=code)
        kl = kl.tail(5)
        start = kl.iloc[0]["收盘"]
        end = kl.iloc[-1]["收盘"]
        return round((end - start) / start * 100, 2)
    except:
        return None

# =========================
# 7. 获取个股日线行情
# =========================
def get_daily_kline(code):
    df = ak.stock_zh_a_hist(symbol=code, adjust="qfq")
    df = df[["日期", "收盘", "开盘", "最高", "最低", "成交量"]]
    df.columns = ["date", "close", "open", "high", "low", "volume"]
    df["date"] = pd.to_datetime(df["date"])
    return df

# =========================
# 8. 获取热度排名前 N 的板块
# =========================
def get_hot_industry(top_n=10):
    board_data = get_board_data()
    fund_data = get_fund_flow()
    merged_data = align_industry_names(board_data, fund_data)
    hot_board = calculate_hot_score(merged_data)

    return hot_board[["板块名称", "热度得分", "涨跌幅", "换手率", "净额", "主力净流入"]].head(top_n)
