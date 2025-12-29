import streamlit as st
import pandas as pd

st.set_page_config(page_title="A股量化策略 Dashboard", layout="wide")

# -------------------------------
# 读取 Excel
# -------------------------------
EXCEL_FILE = "strategy_result.xlsx"

try:
    df = pd.read_excel(EXCEL_FILE)
except Exception as e:
    st.error(f"读取 Excel 文件失败: {e}")
    st.stop()

# -------------------------------
# 列处理
# -------------------------------
# 如果有代码列，保证6位格式
if "代码" in df.columns:
    df["代码"] = df["代码"].astype(str).str.zfill(6)

# 创建展示名列（代码 + 名称，如果有名称列）
if "名称" in df.columns:
    df["展示名"] = df["代码"] + "_" + df["名称"]
else:
    df["展示名"] = df["代码"]

# -------------------------------
# Streamlit Tab1：选股结果
# -------------------------------
st.title("📊 A股选股结果 Dashboard")
st.subheader("今日策略选股结果")

# 显示 DataFrame
st.dataframe(df)

# 排序 Top10
score_col = "得分" if "得分" in df.columns else df.columns[-1]  # 默认用最后一列当得分
top10 = df.sort_values(score_col, ascending=False).head(10)

st.subheader("🔝 得分最高 TOP10")
st.bar_chart(top10.set_index("展示名")[score_col])
