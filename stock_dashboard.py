#!/usr/bin/env python3
"""A股概念板块量化仪表板 - 按核心概念标签分析"""
import os
import re
import glob
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="A股概念板块量化仪表板", layout="wide", initial_sidebar_state="expanded")

@st.cache_data(ttl=300)
def load_data():
    df = pd.read_excel("final_rankings_with_details_latest.xlsx")
    if "Unnamed: 3" in df.columns:
        df.drop(columns=["Unnamed: 3"], inplace=True)
    # 代码统一6位
    df["代码"] = df["代码"].astype(int).apply(lambda x: f"{x:06d}")

    def parse_pct(v):
        if pd.isna(v) or str(v).strip() in ["", "--", "亏损", "N/A"]:
            return np.nan
        try:
            return float(str(v).replace("%", "").replace(",", "").strip())
        except:
            return np.nan

    def parse_mkt(v):
        if pd.isna(v):
            return np.nan
        s = str(v).strip()
        m = re.search(r"([\d.]+)", s)
        if not m:
            return np.nan
        n = float(m.group(1))
        if "亿" in s:
            return n * 1e8
        if "万" in s:
            return n * 1e4
        return n

    for src, tgt in [
        ("净利同比增长", "净利增长_pct"),
        ("营收增长", "营收增长_pct"),
        ("销售毛利率", "毛利率_pct"),
        ("净资产收益率", "ROE_pct"),
        ("资产负债率", "负债率_pct"),
    ]:
        df[tgt] = df[src].apply(parse_pct)

    for src, tgt in [("市净率(PB)", "PB"), ("市盈率(静态)", "PE_STATIC"), ("市盈率(动态)", "PE_DYNAMIC")]:
        df[tgt] = df[src].apply(parse_pct)

    df["市值_元"] = df["总市值"].apply(parse_mkt)

    def parse_forecast(val):
        if pd.isna(val):
            return np.nan, np.nan, np.nan
        parts = re.findall(r"(\d{4})年:([\d.]+)(亿|万)?", str(val))
        y = {}
        for yy, v, u in parts:
            mult = 1e8 if (u == "" or u == "亿") else 1e4
            y[int(yy)] = float(v) * mult
        return y.get(2025, np.nan), y.get(2026, np.nan), y.get(2027, np.nan)

    fc = df["业绩预测"].apply(parse_forecast)
    df["预测_2025"] = fc.apply(lambda x: x[0])
    df["预测_2026"] = fc.apply(lambda x: x[1])
    df["预测_2027"] = fc.apply(lambda x: x[2])

    def calc_growth(col_a, col_b):
        va = pd.to_numeric(df[col_a], errors="coerce")
        vb = pd.to_numeric(df[col_b], errors="coerce")
        mask = va.notna() & vb.notna() & (va != 0)
        res = pd.Series(np.nan, index=df.index, dtype=float)
        res[mask] = (vb[mask] - va[mask]) / va[mask] * 100
        return res

    df["GROWTH_25_26"] = calc_growth("预测_2025", "预测_2026")
    df["GROWTH_26_27"] = calc_growth("预测_2026", "预测_2027")
    df["GROWTH_25_27"] = calc_growth("预测_2025", "预测_2027")

    def split_concepts(v):
        if pd.isna(v):
            return []
        parts = re.split(r"[+，,、]", str(v))
        return [p.strip() for p in parts if p.strip() and p.strip() not in ["未识别", "--"]]

    df["CORE_LABELS"] = df["核心概念标签"].apply(split_concepts)

    def get_all_concepts(row):
        core = row["CORE_LABELS"]
        extra = split_concepts(row["涉及概念"]) if pd.notna(row["涉及概念"]) else []
        return list(dict.fromkeys(core + extra))

    df["ALL_CONCEPTS"] = df.apply(get_all_concepts, axis=1)
    return df


df = load_data()

# ============================================================
# 行业逻辑库
# ============================================================
LOGIC = dict()

L = LOGIC
L["人形机器人"] = "人形机器人处于爆发前夜。Tesla Optimus 2025量产目标，Figure 02已进工厂。核心零部件（减速器/伺服电机/力传感器）需求将呈指数级增长。"
L["机器人概念"] = "工业机器人国产替代加速，协作机器人/AGV渗透率快速提升。"
L["机器人"] = "工业机器人国产替代加速，政策+制造业升级双轮驱动。"
L["减速器"] = "机器人核心部件占BOM 30%+，精密减速器国产替代空间大，人形机器人量产大幅拉动。"
L["低空经济"] = "低空空域管理改革推进，eVTOL商业化提速，2025年政策催化密集。"
L["无人机"] = "军用列装+民用放量，低空经济核心场景。"
L["新能源汽车"] = "2025渗透率50%+，智能化下半场开启。智能驾驶/800V/热管理核心方向。"
L["汽车芯片"] = "MCU/功率/SoC需求旺盛，国产替代空间巨大。"
L["汽车电子"] = "智能座舱+ADAS+域控制器驱动增长。"
L["汽车热管理"] = "单车价值量高于燃油车3~5倍，热泵/电子膨胀阀/液冷板受益。"
L["特斯拉概念"] = "Tesla产业链，新车+FSD+Optimus量产三重催化。"
L["芯片概念"] = "国产替代+需求共振，半导体周期触底回升。"
L["芯片"] = "国产替代持续推进，车规/AI/模拟增速突出。"
L["存储芯片"] = "AI驱动HBM爆发，存储涨价。"
L["存储"] = "AI/手机/PC反弹，价格周期上行。"
L["半导体"] = "周期触底，国产替代+AI共振。"
L["先进封装"] = "CoWoS/HBM爆发，国产替代空间巨大。"
L["第三代半导体"] = "SiC/GaN在新能源渗透率快速提升。"
L["光刻胶"] = "KrF/ArF光刻胶壁垒极高，突破后空间巨大。"
L["中芯国际概念"] = "中芯产业链，受益扩产和国产替代。"
L["AI应用"] = "大模型从训练走向推理侧应用爆发。"
L["AI智能体"] = "AI Agent是2025趋势。"
L["AIGC概念"] = "AIGC内容生成革命。"
L["AI PC"] = "AI PC是2025换机潮核心。"
L["算力"] = "训练/推理双轮驱动。"
L["东数西算(算力)"] = "算力网络建设，智算中心/液冷受益。"
L["算力租赁"] = "算力需求爆发，租赁商业跑通。"
L["数据中心"] = "智算中心+液冷趋势，2025新基建加码。"
L["创新药"] = "医保谈判优化+出海加速，ADC/GLP-1管线爆发。"
L["CRO概念"] = "CXO底部企稳，全球研发投入回升。"
L["医疗器械"] = "国产替代+出海，大型设备和IVD景气。"
L["医疗器械概念"] = "国产替代+出海。"
L["仿制药一致性评价"] = "行业出清后头部受益。"
L["重组蛋白"] = "重组蛋白药物国产替代+出海。"
L["减肥药"] = "GLP-1全球市场爆发，国产管线推进。"
L["智能医疗"] = "AI医疗商业化加速。"
L["医药电商"] = "处方外流+互联网医疗推动渗透率。"
L["流感"] = "呼吸道疾病防治需求增长。"
L["固态电池"] = "固态/半固态量产在即，电解质/硅碳负极受益。"
L["锂电池概念"] = "产能出清后格局改善，技术迭代带来机会。"
L["储能"] = "大储+工商业装机CAGR 50%+。"
L["光伏概念"] = "N型替代加速，逆变器/钙钛矿龙头。"
L["TOPCon电池"] = "TOPCon N型主流，大模替代PERC。"
L["HJT电池"] = "异质结下一代技术，效率潜力更高。"
L["BC电池"] = "背接触高效路线。"
L["风电"] = "海上风电加速，大型化降本。"
L["特高压"] = "十五五新增线路，设备商订单饱满。"
L["智能电网"] = "配网升级+数字化改造。"
L["充电桩"] = "保有量+超充网络建设加速。"
L["绿色电力"] = "绿电交易完善，运营商价值重估。"
L["商业航天"] = "卫星互联网加速部署，全产业链景气。"
L["卫星导航"] = "北斗全球服务提升，需求爆发。"
L["卫星导航 + 商业航天"] = "导航+低轨星座部署共振。"
L["可控核聚变"] = "商业化早期布局。"
L["核电"] = "审批加速，四代+小型堆。"
L["可控核聚变 + 核电"] = "清洁能源双赛道。"
L["军工"] = "装备放量，低空经济新增量。"
L["军工信息化"] = "C4ISR/电子战/数据链。"
L["航空发动机"] = "壁垒极高，长景气周期。"
L["国企改革"] = "资产重组+市值管理推动重估。"
L["央企国企改革"] = "专业化整合持续推进。"
L["一带一路"] = "海外工程/设备出口受益。"
L["信创"] = "国产替代，CPU/OS/DB/中间件。"
L["专精特新"] = "细分赛道龙头。"
L["股权转让(并购重组)"] = "资产注入/重组预期。"
L["小金属概念"] = "供需格局好，新能源拉动。"
L["煤炭概念"] = "高股息+供需紧平衡。"
L["IP经济(谷子经济)"] = "IP衍生品爆发，年轻化+国潮。"
L["网络游戏"] = "版号常态化，AI降本增效。"
L["游戏"] = "AI赋能+出海增量。"
L["手机游戏"] = "AI赋能开发运营。"
L["文化传媒"] = "AI+内容版权运营。"
L["白酒"] = "高端稳增，品牌护城河。"
L["虚拟现实"] = "Vision Pro+Quest推动MR生态。"
L["元宇宙"] = "元宇宙+AI融合。"
L["PCB概念"] = "AI服务器+汽车拉动高端PCB。"
L["氟化工"] = "新能源材料需求，壁垒高。"
L["PVDF概念"] = "锂电粘结剂+光伏背板。"
L["PEEK材料"] = "机器人+航空航天需求。"
L["一体化压铸"] = "特斯拉引领车身制造革命。"
L["数据要素"] = "数据资产入表+交易市场。"
L["数字货币"] = "数字人民币试点扩大。"
L["网络安全"] = "法规+云安全+AI安全需求。"
L["智慧城市"] = "城市大脑+智慧交通。"
L["智能交通"] = "车路协同基础设施。"
L["自动驾驶"] = "L3/L4商业化提速。"
L["车路协同"] = "V2X基础设施加速。"
L["机器视觉"] = "工业检测+AI视觉。"
L["IGBT"] = "功率半导体核心，新能源广泛使用。"
L["碳化硅"] = "SiC新能源渗透提升。"
L["激光"] = "工业/医疗应用扩展。"
L["工业母机"] = "高端机床是制造业核心。"
L["工业自动化"] = "智能制造核心装备。"
L["高端装备"] = "国产替代核心受益。"
L["鸿蒙概念"] = "鸿蒙原生生态，应用+设备拉动。"
L["消费电子"] = "AI换机潮+复苏。"
L["苹果概念"] = "苹果产业链，AI iPhone受益。"
L["华为概念"] = "华为Mate/Pura/鸿蒙/昇腾。"
L["MR(混合现实)"] = "MR/XR硬件+内容。"
L["OLED"] = "手机/电视渗透提升。"
L["MiniLED"] = "电视/车载显示渗透提升。"
L["面板"] = "价格周期回升。"
L["液冷"] = "AI算力散热升级。"
L["物联网"] = "万物互联三端受益。"
L["工业互联网"] = "制造业数字化。"
L["数字孪生"] = "工业/城市应用扩展。"
L["碳交易"] = "碳交易市场建设。"
L["碳中和"] = "减碳/节能/新能源。"
L["氢能源"] = "商业化初期，燃料电池+绿氢。"
L["燃料电池"] = "商用车推广加速。"
L["钠电池"] = "储能/低速车替代锂电。"
L["宠物"] = "宠物经济高速增长。"
L["医美"] = "医美稳健增长。"
L["横琴新区"] = "横琴合作区政策红利。"
L["粤港澳大湾区"] = "大湾区建设推进。"
L["独角兽概念"] = "被投企业上市利好。"
L["盐湖提锂"] = "碳酸锂企稳，成本优势。"
L["创投"] = "被投企业估值回升。"
L["摘帽"] = "ST摘帽预期。"
L["2025三季报预增"] = "Q3业绩改善信号。"
L["2025年报预增"] = "年报预增，业绩确定。"
L["福建自贸区"] = "自贸区红利。"
L["海峡两岸"] = "两岸融合。"
L["PPP概念"] = "基建/环保PPP。"
L["参股银行"] = "参股银行标的。"
L["动物疫苗"] = "养殖规模化+宠物疫苗。"
L["广东自贸区"] = "自贸区红利。"
L["共同富裕示范区"] = "共同富裕主题。"
L["C2M概念"] = "反向定制。"
L["Sora概念(文生视频)"] = "文生视频技术突破。"
L["DeepSeek概念"] = "国产大模型崛起。"
L["ChatGPT概念"] = "大模型产业链。"
L["AI眼镜"] = "AI硬件新形态。"
L["AI语料"] = "训练数据需求爆发。"
L["AI手机"] = "AI换机周期。"
L["MCU芯片"] = "国产替代空间大。"
L["柔性直流输电"] = "新能源并网/海风应用。"
L["高压快充"] = "800V普及。"
L["超级电容"] = "多场景驱动。"
L["光伏建筑一体化"] = "BIPV渗透提升。"
L["海工装备"] = "海风/油气拉动。"
L["黄金概念"] = "通胀+避险。"
L["煤化工概念"] = "油价高企时经济性凸显。"
L["军工电子"] = "军工信息化。"
L["柔性屏"] = "渗透提升。"
L["折叠屏"] = "渗透快速提升。"
L["消费电子概念"] = "AI换机+复苏。"
L["智能穿戴"] = "AI赋能。"
L["操作系统"] = "国产OS替代。"
L["信息安全"] = "数据安全法驱动。"
L["东数西算"] = "算力网络+智算中心。"

def get_logic(concepts, limit=6):
    lines = []
    seen = set()
    for c in concepts or []:
        if c in seen or c not in L:
            continue
        seen.add(c)
        lines.append(f"- **{c}**: {L[c]}")
    if not lines:
        lines.append("- 建议结合公司主营业务和行业动态进行独立分析。")
    return "\n".join(lines[:limit])


# ============================================================
# 竞争力评分
# ============================================================
def calc_score(row):
    s = 0
    rr = []
    g = row.get("毛利率_pct", np.nan)
    if not np.isnan(g):
        if g > 40: s += 3; rr.append(f"毛率极高{g:.0f}%")
        elif g > 30: s += 2; rr.append(f"毛率较高{g:.0f}%")
        elif g > 20: s += 1; rr.append(f"毛率良好{g:.0f}%")
    ro = row.get("ROE_pct", np.nan)
    if not np.isnan(ro):
        if ro > 20: s += 3; rr.append(f"ROE极佳{ro:.0f}%")
        elif ro > 15: s += 2; rr.append(f"ROE较高{ro:.0f}%")
        elif ro > 10: s += 1; rr.append(f"ROE良好{ro:.0f}%")
    pg = row.get("GROWTH_25_26", np.nan)
    if not np.isnan(pg):
        if pg > 50: s += 3; rr.append(f"预强劲{pg:.0f}%")
        elif pg > 30: s += 2; rr.append(f"预较好{pg:.0f}%")
        elif pg > 15: s += 1; rr.append(f"预稳健{pg:.0f}%")
    rv = row.get("营收增长_pct", np.nan)
    if not np.isnan(rv) and rv > 20: s += 1; rr.append(f"营收{rv:.0f}%")
    db = row.get("负债率_pct", np.nan)
    if not np.isnan(db) and db < 30: s += 1; rr.append("负债低")
    return s, "; ".join(rr)

scores = df.apply(calc_score, axis=1)
df["SCORE"] = scores.apply(lambda x: x[0])
df["REASON"] = scores.apply(lambda x: x[1])
df["IS_CORE"] = df["SCORE"] >= 7

ALL_LABELS = sorted(set(lbl for labels in df["CORE_LABELS"] for lbl in labels))


# ============================================================
# 格式化
# ============================================================
def pct1(x):
    try: return f"{float(x):.1f}%" if not pd.isna(x) else "--"
    except: return "--"

def pct2(x):
    try: return f"{float(x):.2f}%" if not pd.isna(x) else "--"
    except: return "--"

def bln(x):
    try: return f"{float(x)/1e8:.2f}亿" if not pd.isna(x) else "--"
    except: return "--"

def mkt(s):
    return s if pd.notna(s) else "--"


# ============================================================
# 展示用表（不修改原始数据）
# ============================================================
def mkdisp(sub_df):
    cols = ["名称", "代码", "核心概念标签", "SCORE", "REASON",
            "营收增长_pct", "净利增长_pct", "毛利率_pct", "ROE_pct",
            "负债率_pct", "PB", "PE_STATIC", "PE_DYNAMIC", "总市值",
            "预测_2025", "预测_2026", "GROWTH_25_26"]
    out = sub_df[[c for c in cols if c in sub_df.columns]].copy()
    out["代码"] = out["代码"].astype(str).str.zfill(6)
    for c in ["营收增长_pct", "净利增长_pct", "毛利率_pct", "ROE_pct", "负债率_pct", "GROWTH_25_26"]:
        if c in out.columns:
            out[c] = out[c].apply(pct1)
    if "预测_2025" in out.columns: out["预测_2025"] = out["预测_2025"].apply(bln)
    if "预测_2026" in out.columns: out["预测_2026"] = out["预测_2026"].apply(bln)
    if "总市值" in out.columns: out["总市值"] = out["总市值"].apply(mkt)
    return out


# ============================================================
# 渲染
# ============================================================
st.title("A股概念板块量化仪表板")
st.caption("基于核心概念标签的行业分析 | 4602只股票 | 所有代码6位格式")

st.sidebar.header("筛选")
kw = st.sidebar.text_input("搜索概念关键词", placeholder="输入关键词过滤...")
if kw:
    filt_labels = [l for l in ALL_LABELS if kw.lower() in l.lower()]
    st.sidebar.caption(f"匹配 **{len(filt_labels)}** 个概念")
    opts = ["全市场"] + filt_labels if filt_labels else ["全市场"]
else:
    opts = ["全市场"] + ALL_LABELS
csel = st.sidebar.selectbox("核心概念板块", opts, index=0)
if csel == "全市场":
    sub = df.copy()
else:
    sub = df[df["CORE_LABELS"].apply(lambda x: csel in x)].copy()

st.sidebar.info(f"共 {len(sub)} 只股票")
nfc = sub["预测_2025"].notna().sum()
st.sidebar.markdown(f"有预测: {nfc} | 无预测: {len(sub)-nfc}")

ff = st.sidebar.radio("预测范围", ["全部", "仅含预测", "仅无预测"], index=0)
if ff == "仅含预测": sub = sub[sub["预测_2025"].notna()].copy()
elif ff == "仅无预测": sub = sub[sub["预测_2025"].isna()].copy()

SO = {"SCORE降序": ("SCORE", True), "预增长25-26降序": ("GROWTH_25_26", True),
      "净利增长降序": ("净利增长_pct", True), "营收增长降序": ("营收增长_pct", True),
      "毛率降序": ("毛利率_pct", True), "ROE降序": ("ROE_pct", True),
      "市值升序": ("市值_元", False), "PE动态升序": ("PE_DYNAMIC", False),
      "PB升序": ("PB", False), "负债率升序": ("负债率_pct", False)}
sk = st.sidebar.selectbox("排序", list(SO.keys()))
sc2, sa = SO[sk]
sub = sub.sort_values(sc2, ascending=sa, na_position="last")

if st.sidebar.checkbox("仅核心标(SCORE>=7)"):
    sub = sub[sub["IS_CORE"]].copy()

mg = st.sidebar.slider("最小预增长25-26(%)", -200.0, 300.0, -200.0, 5.0)
if mg > -200.0:
    hg = sub["GROWTH_25_26"].notna()
    nofc = sub["预测_2025"].isna()
    sub = pd.concat([sub[hg & (sub["GROWTH_25_26"] >= mg)], sub[nofc]])

sfc = sub[sub["预测_2025"].notna()].copy()
snf = sub[sub["预测_2025"].isna()].copy()

# Import industry analysis module
import industry_content
import calendar_content
import hot_concept_page
import json
import review_module
import favorites_page
import favorite_manager

# Load industry data for screening
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
INDUST_FILE = os.path.join(DATA_DIR, "industry_data.json")
with open(INDUST_FILE, "r", encoding="utf-8") as f:
    _chains_data = json.load(f)["industry_chains"]

# Add tab list
tabs = st.tabs(["总览", "概念推荐", "核心标的", "盈利预测", "产业链分析", "产业筛选", "交易信号监控", "热点解析", "交易日复盘", "收藏夹", "投资日历", "投研分析", "数据明细"])

# Tab 1
with tabs[0]:
    st.subheader(f"{'核心概念: ' + csel if csel != '全市场' else '全市场总览'}")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("总数", len(sub)); c2.metric("有预测", nfc)
    c3.metric("核心标", sub["IS_CORE"].sum())
    ag = sub["GROWTH_25_26"].mean()
    c4.metric("平均预增长", f"{ag:.1f}%" if not np.isnan(ag) else "N/A")

    fh = px.histogram(sub, x="SCORE", nbins=13, color=sub["IS_CORE"], title="竞争力评分分布")
    fh.update_layout(showlegend=False)
    st.plotly_chart(fh, width="stretch")

    s2 = sub.dropna(subset=["毛利率_pct", "ROE_pct"])
    if len(s2) > 0:
        fs = px.scatter(s2, x="毛利率_pct", y="ROE_pct", size="市值_元",
            hover_data=["名称", "代码", "核心概念标签"],
            color="SCORE", labels={"毛利率_pct": "毛利率(%)", "ROE_pct": "ROE(%)"},
            title="ROE vs 毛利率")
        st.plotly_chart(fs, width="stretch")

    st.markdown("---")
    st.subheader("无预测数据分析（基于历史财务）")
    if len(snf) > 0:
        ca, cb = st.columns(2)
        ca.metric("无预测数量", len(snf))
        best = snf.nlargest(10, "SCORE")[["名称","代码","核心概念标签","SCORE","REASON",
            "净利增长_pct","毛利率_pct","ROE_pct","总市值"]].copy()
        cb.dataframe(mkdisp(best), width="stretch", hide_index=True)

        st.markdown("**高净利增长但无预测TOP10**")
        ng = snf.nlargest(10, "净利增长_pct")[["名称","代码","核心概念标签",
            "净利增长_pct","营收增长_pct","毛利率_pct","SCORE"]].copy()
        ng["代码"] = ng["代码"].astype(str).str.zfill(6)
        for c in ["净利增长_pct","营收增长_pct","毛利率_pct"]:
            ng[c] = ng[c].apply(pct1)
        ng.columns = ["股票","代码","概念","净利增长","营收增长","毛利率","SCORE"]
        st.dataframe(ng, width="stretch", hide_index=True)
    else:
        st.info("全部都有预测数据")

    st.markdown("---")
    st.subheader("预增长TOP 10")
    if len(sfc) > 0:
        tg = sfc.nlargest(10, "GROWTH_25_26")[["名称","代码","核心概念标签",
            "GROWTH_25_26","净利增长_pct","毛利率_pct","SCORE"]].copy()
        st.dataframe(mkdisp(tg), width="stretch", hide_index=True)

# Tab 2
with tabs[1]:
    st.subheader("概念推荐 List")
    if csel != "全市场":
        st.markdown(f"**{csel}** — {len(sub)}只 | 有预:{len(sfc)} | 无预:{len(snf)}")
        st.dataframe(mkdisp(sub), width="stretch", height=500)

        if len(sfc) > 0:
            st.markdown("### 有预测TOP8 - 详细分析+行业逻辑")
            for _, r in sfc.nlargest(8, "SCORE").iterrows():
                code6 = f"{r['代码']}"
                with st.expander(f"{r['名称']} ({code6}) | SCORE {r['SCORE']} | {r['核心概念标签']}"):
                    st.markdown(f"**主业**: {r['主营业务'][:400] if pd.notna(r['主营业务']) else '--'}")
                    st.markdown(f"**优势**: {r['REASON']}")
                    st.markdown(f"**三年预测**: 2025: {bln(r['预测_2025'])} -> 2026: {bln(r['预测_2026'])} ({r['GROWTH_25_26']:+.1f}%)")
                    g27 = r.get("GROWTH_26_27", np.nan)
                    if not np.isnan(g27):
                        st.markdown(f"2027: {bln(r['预测_2027'])} ({g27:+.1f}%)")
                    st.markdown("#### 行业逻辑")
                    st.markdown(get_logic(r["ALL_CONCEPTS"]))

        if len(snf) > 0:
            st.markdown("### 无预测TOP5 - 仅历史指标")
            for _, r in snf.nlargest(5, "SCORE").iterrows():
                code6 = f"{r['代码']}"
                with st.expander(f"{r['名称']} ({code6}) | SCORE {r['SCORE']} | {r['核心概念标签']}"):
                    st.markdown(f"**主业**: {r['主营业务'][:400] if pd.notna(r['主营业务']) else '--'}")
                    st.markdown(f"**历史**: 净利{r['净利增长_pct']:.1f}% 营收{r['营收增长_pct']:.1f}%")
                    st.markdown(f"**毛率** {r['毛利率_pct']:.1f}% **ROE** {r['ROE_pct']:.1f}%")
                    st.markdown(f"**优势**: {r['REASON']}")
                    st.markdown("**暂无预测数据**")
                    st.markdown(get_logic(r["ALL_CONCEPTS"]))

    else:
        cr = {}
        for c in ALL_LABELS:
            ss = df[df["CORE_LABELS"].apply(lambda x: c in x)]
            if len(ss) >= 2:
                cr[c] = ss.nlargest(3, "SCORE")
        st.info(f"{len(cr)}个板块有推荐")
        pick = st.selectbox("选择概念", sorted(cr.keys()))
        if pick in cr:
            recs = cr[pick]
            rd = recs[["名称","代码","核心概念标签","SCORE","GROWTH_25_26",
                       "净利增长_pct","毛利率_pct","ROE_pct","REASON"]].copy()
            for c in ["净利增长_pct","毛利率_pct","ROE_pct","GROWTH_25_26"]:
                rd[c] = rd[c].apply(pct1)
            rd.columns = ["股票","代码","概念","SCORE","预增%","净利%","毛率%","ROE%","优势"]
            st.dataframe(rd, width="stretch", hide_index=True)
            for _, r in recs.iterrows():
                code6 = f"{r['代码']}"
                with st.expander(f"{r['名称']} ({code6}) | {r['SCORE']}"):
                    st.markdown(f"**优势**: {r['REASON']}")
                    st.markdown(get_logic(r["ALL_CONCEPTS"]))

# Tab 3
with tabs[2]:
    st.subheader("核心力标的 (SCORE>=7)")
    core = sub[sub["IS_CORE"]].sort_values("SCORE", ascending=False)
    if len(core) > 0:
        cw = core[core["预测_2025"].notna()]
        cn = core[core["预测_2025"].isna()]
        st.success(f"共 {len(core)} 只 (有预 {len(cw)} / 无预 {len(cn)})")
        st.dataframe(mkdisp(core), width="stretch", height=500)

        # 下载核心标的 CSV
        core_csv = mkdisp(core).to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "📥 下载全部核心标的 CSV",
            data=core_csv,
            file_name="核心标的_SCORE>=7.csv",
            mime="text/csv"
        )
        core_top = core.head(10)
        if len(core_top) > 0:
            st.markdown("### 核心标的关键指标对比 (TOP 10)")
            fr = go.Figure()
            for _, r in core_top.iterrows():
                vals = [
                    min(r.get("毛利率_pct", 0) or 0, 80),
                    min(r.get("ROE_pct", 0) or 0, 50),
                    min(r.get("GROWTH_25_26", 0) or 0, 100),
                    min(r.get("净利增长_pct", 0) or 0, 200),
                    min(r.get("营收增长_pct", 0) or 0, 100),
                ]
                code6 = f"{r['代码']}"
                fr.add_trace(go.Scatterpolar(
                    r=vals, theta=["毛利率","ROE","预增长","净利增长","营收增长"],
                    fill="toself", name=f"{r['名称']}({r['SCORE']})"
                ))
            fr.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0,100])), height=500)
            st.plotly_chart(fr, width="stretch")

            st.markdown("### 核心标的行业逻辑")
            for _, r in core_top.iterrows():
                code6 = f"{r['代码']}"
                fc_tag = "有预" if not np.isnan(r.get("预测_2025", np.nan)) else "无预"
                with st.expander(f"{r['名称']} ({code6}) | {r['SCORE']} | {fc_tag}"):
                    st.markdown(f"**优势**: {r['REASON']}")
                    if not np.isnan(r.get("预测_2025", np.nan)):
                        st.markdown(f"**预测**: {r['预测_2025']/1e8:.2f}亿 -> {r['预测_2026']/1e8:.2f}亿 ({r['GROWTH_25_26']:+.1f}%)")
                    else:
                        st.markdown(f"**历史**: 净利{r['净利增长_pct']:.1f}% 毛率{r['毛利率_pct']:.1f}% ROE{r['ROE_pct']:.1f}%")
                    st.markdown(get_logic(r["ALL_CONCEPTS"]))
    else:
        st.warning("无核心标的")

# Tab 4
with tabs[3]:
    st.subheader("盈利预测深度分析")
    if len(sfc) > 0:
        ca,cb,cc,cd = st.columns(4)
        ca.metric("有预测", len(sfc))
        pos = (sfc["GROWTH_25_26"] > 0).sum()
        cb.metric("正增长", f"{pos} ({pos/len(sfc)*100:.0f}%)")
        neg = (sfc["GROWTH_25_26"] < 0).sum()
        cc.metric("负增长", f"{neg} ({neg/len(sfc)*100:.0f}%)")
        ag2 = sfc["GROWTH_25_26"].mean()
        cd.metric("平均预增长", f"{ag2:.1f}%")

        fg = px.histogram(sfc, x="GROWTH_25_26", nbins=50, title="预增长率分布")
        fg.add_vline(x=0, line_dash="dash", line_color="red")
        st.plotly_chart(fg, width="stretch")

        st.markdown("### 高增长TOP20详细逻辑")
        for _, r in sfc.nlargest(20, "GROWTH_25_26").iterrows():
            code6 = f"{r['代码']}"
            with st.expander(f"{r['名称']} ({code6}) | 预增 {r['GROWTH_25_26']:.1f}% | {r['核心概念标签']}"):
                cl1, cl2 = st.columns([2, 3])
                with cl1:
                    items = []
                    for lb, k in [("营收","营收增长_pct"),("净利","净利增长_pct"),("毛率","毛利率_pct"),("ROE","ROE_pct")]:
                        v = r.get(k, np.nan)
                        if not np.isnan(v): items.append(f"**{lb}**: {v:.1f}%")
                    st.markdown("\n".join(items))
                with cl2:
                    st.markdown(f"**优势**: {r['REASON']}")
                    st.markdown(f"**预测**: 25年 {bln(r['预测_2025'])} 26年 {bln(r['预测_2026'])} ({r['GROWTH_25_26']:+.1f}%)")
                    g27 = r.get("GROWTH_26_27", np.nan)
                    if not np.isnan(g27):
                        st.markdown(f"27年 {bln(r['预测_2027'])} ({g27:+.1f}%)")
                    st.markdown("---")
                    st.markdown("#### 行业逻辑")
                    st.markdown(get_logic(r["ALL_CONCEPTS"]))

        sf = sfc.dropna(subset=["PE_DYNAMIC", "GROWTH_25_26"])
        if len(sf) > 0:
            st.markdown("### PE vs 预增长")
            fp = px.scatter(sf, x="PE_DYNAMIC", y="GROWTH_25_26", size="市值_元",
                hover_data=["名称","代码","SCORE"], color="SCORE", title="PE/预增长")
            fp.add_shape(type="line", x0=0, y0=0, x1=100, y1=100, line=dict(dash="dash", color="gray"))
            st.plotly_chart(fp, width="stretch")

        st.markdown("### 2027加速增长标的")
        acc = sfc[sfc["GROWTH_26_27"] > sfc["GROWTH_25_26"]].nlargest(20, "GROWTH_26_27")
        if len(acc) > 0:
            ad = acc[["名称","代码","核心概念标签","GROWTH_25_26","GROWTH_26_27","SCORE"]].copy()
            ad["代码"] = ad["代码"].astype(str).str.zfill(6)
            ad["GROWTH_25_26"] = ad["GROWTH_25_26"].apply(pct1)
            ad["GROWTH_26_27"] = ad["GROWTH_26_27"].apply(pct1)
            ad.columns = ["股票","代码","概念","25-26","26-27","SCORE"]
            st.dataframe(ad, width="stretch", hide_index=True)
        else:
            st.info("无加速增长标的")
    else:
        st.warning("无预测数据")


# ══════════════ Tab 4: 产业链分析 ══════════════
with tabs[4]:
    st.markdown("### 产业链图谱 & 行业分析")
    try:
        industry_content.industry_content()
    except Exception as e:
        st.error(f"产业链模块加载失败: {e}")

# ══════════════ Tab 5: 产业链筛选 ══════════════
with tabs[5]:
    st.subheader("🎯 产业链筛选 & 标的池")

    st.markdown("### 第一步：筛选产业链范围")

    # Core level filter
    core_levels = st.multiselect(
        "核心程度",
        ["极高（国家战略）", "高（核心产业）"],
        default=["极高（国家战略）", "高（核心产业）"]
    )
    # Recommend level filter
    rec_levels = st.multiselect(
        "推荐参考",
        ["极高", "高", "中高", "中", "低"],
        default=["极高", "高"]
    )

    # Map display to actual values
    core_map = {"极高（国家战略）": "极高", "高（核心产业）": "高"}
    sel_cores = [core_map.get(x, x) for x in core_levels]
    sel_recs = rec_levels

    # Filter chains
    matching_chains = [c for c in _chains_data
                       if c["core_level"] in sel_cores and c["recommend"] in sel_recs]
    matching_chains.sort(key=lambda x: ({
                       "极高": 5, "高": 4, "中高": 3, "中": 2, "低": 1}.get(x["recommend"], 0)),
                       reverse=True)

    all_tags = sorted(set(
        t for c in matching_chains for t in c.get("tags", [])
    ))

    st.markdown(f"**{len(matching_chains)} 条产业链匹配筛选条件**")

    # Show chain cards
    cols = st.columns(3)
    for i, c in enumerate(matching_chains):
        with cols[i % 3]:
            with st.container(border=True):
                c_icon = "🔴🔴🔴" if c["core_level"] == "极高" else "🔴🔴"
                r_icon = {"极高": "⭐⭐⭐⭐⭐", "高": "⭐⭐⭐⭐",
                           "中高": "⭐⭐⭐✨", "中": "⭐⭐⭐"}.get(c["recommend"], "⭐")
                st.markdown(f"**{c['name']}**")
                st.markdown(f"核心: {c['core_level']} {c_icon} | 推荐: {c['recommend']} {r_icon}")
                st.caption(f"包含 {len(set(c.get('tags', [])))} 个概念标签")
                st.caption(" | ".join(list(c.get("tags", []))[:3]))
                if len(c.get("tags", [])) > 3:
                    st.caption(f"+{len(c.get('tags', []))-3} 个...")

    st.markdown("---")
    st.markdown("### 第二步：选择产业链")
    chain_names = [c["name"] for c in matching_chains]
    selected_chains = st.multiselect(
        "选择产业链（可多选）",
        options=chain_names,
        default=chain_names if len(chain_names) <= 5 else chain_names[:3]
    )

    # Collect all tags from selected chains
    selected_tags = sorted(set(
        t for c in matching_chains if c["name"] in selected_chains
        for t in c.get("tags", [])
    ))

    if selected_chains:
        st.markdown(f"**已选 {len(selected_chains)} 条产业链**，共 **{len(selected_tags)} 个概念标签**")

        # Show selected tags
        with st.expander("查看概念标签标签", expanded=False):
            st.markdown(", ".join(selected_tags))

        # Find stocks matching selected tags
        pool = df[df["CORE_LABELS"].apply(
            lambda x: any(t in x for t in selected_tags)
        )].copy()
        pool = pool.sort_values("SCORE", ascending=False)

        st.info(f"共匹配 **{len(pool)}** 只标的")

        # Display
        pool_disp = pool[["名称", "代码", "核心概念标签", "SCORE", "REASON",
                          "净利增长_pct", "毛利率_pct", "ROE_pct",
                          "营收增长_pct", "负债率_pct", "PB", "PE_DYNAMIC", "总市值"]].copy()
        pool_disp["代码"] = pool_disp["代码"].astype(str).str.zfill(6)
        for c in ["净利增长_pct", "毛利率_pct", "ROE_pct",
                  "营收增长_pct", "负债率_pct"]:
            pool_disp[c] = pool_disp[c].apply(pct1)

        pool_disp.columns = [
            "股票", "代码", "概念标签", "SCORE", "优势",
            "净利增长", "毛利率", "ROE", "营收增长", "负债率",
            "PB", "PE动态", "市值"
        ]

        st.dataframe(pool_disp, width="stretch", height=600, hide_index=True)

        # Download CSV
        csv_name = "_".join([c.replace("/", "_") for c in selected_chains[:3]])
        if len(selected_chains) > 3:
            csv_name += f"_等{len(selected_chains)}条产业链"
        csv_data = pool_disp.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            "📥 下载股票池CSV",
            data=csv_data,
            file_name=f"industry_pool_{csv_name}.csv",
            mime="text/csv"
        )

        # Stats
        if len(pool) > 0:
            st.markdown("### 股票池统计")
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("总数", len(pool))
            s1_core = pool["SCORE"] >= 7
            s2.metric("核心标的", s1_core.sum())
            avg_mkt = pool["市值_元"].mean()
            s3.metric("平均市值", f"{avg_mkt/1e8:.0f}亿" if not np.isnan(avg_mkt) else "--")
            avg_score = pool["SCORE"].mean()
            s4.metric("平均SCORE", f"{avg_score:.1f}")

        # Show concept breakdown
        if len(pool) > 0:
            st.markdown("### 概念标签覆盖情况")
            concept_count = {}
            for _, r in pool.iterrows():
                for label in r["CORE_LABELS"]:
                    concept_count[label] = concept_count.get(label, 0) + 1
            top_concepts = sorted(concept_count.items(), key=lambda x: x[1], reverse=True)[:15]
            c_names = [c[0] for c in top_concepts]
            c_vals = [c[1] for c in top_concepts]
            import plotly.graph_objects as go
            fig_bc = go.Figure(go.Bar(x=c_names, y=c_vals, marker_color='#4CAF50'))
            fig_bc.update_layout(
                title="概念标签覆盖股票数 TOP 15",
                xaxis_title="概念标签",
                yaxis_title="股票数",
                height=400
            )
            st.plotly_chart(fig_bc, width="stretch")
    else:
        st.info("请在上方选择至少一条产业链")


# ══════════════ Tab 6: 交易信号监控 ══════════════
SIGNAL_DIR = "/Users/skyler/workspace/投资框架/筛选股票/可视化"

with tabs[6]:
    import glob, time as _time

    st.subheader("📡 交易信号监控")
    st.caption(f"监控路径: {SIGNAL_DIR}")

    # 扫描 csv 文件
    csv_files = sorted(
        [f for f in os.listdir(SIGNAL_DIR) if f.endswith(".csv")],
        reverse=True
    )

    if not csv_files:
        st.warning(f"路径下暂无 CSV 文件，等待交易信号脚本生成...")
        st.info("运行脚本: `python3 /Users/skyler/workspace/stock_selection/trade_signal.py`")
    else:
        # 提取日期并分组
        date_groups = {}
        for fn in csv_files:
            # 提取日期：trade_signal_YYYYMMDD.csv → YYYYMMDD
            m = re.search(r'(\d{8})', fn)
            if m:
                dt = m.group(1)
                date_groups[dt] = date_groups.get(dt, [])
                date_groups[dt].append(fn)

        # 选择日期
        dates = sorted(date_groups.keys(), reverse=True)
        sel_date = st.selectbox("选择日期", dates, index=0)
        available = date_groups.get(sel_date, [])

        st.info(f"{sel_date} 共 **{len(available)}** 个信号文件")

        for fn in available:
            try:
                fp = os.path.join(SIGNAL_DIR, fn)
                sig = pd.read_csv(fp, encoding="utf-8-sig")
                st.markdown(f"### 📄 `{fn}`")

                # 基本信息
                total = len(sig)
                buy_c = len(sig[sig["信号"]=="买入"])
                sell_c = len(sig[sig["信号"]=="卖出"])
                wait_c = len(sig[sig["信号"]=="观望"])
                c1,c2,c3,c4 = st.columns(4)
                c1.metric("总数", total)
                c2.metric("🟢 买入", buy_c)
                c3.metric("🔴 卖出", sell_c)
                c4.metric("⚪ 观望", wait_c)

                # ── 多级筛选：先信号 → 概念 → 搜索 → 指标 ──
                st.markdown("##### 🏷️ 第一步：信号筛选")
                sig_filter = st.radio("", ["全部", "🟢 买入", "🔴 卖出", "⚪ 观望"],
                    index=0, key=f"sig_{fn}_filter", label_visibility="collapsed",
                    horizontal=True)
                if sig_filter == "🟢 买入":
                    sig_d = sig[sig["信号"]=="买入"].copy()
                elif sig_filter == "🔴 卖出":
                    sig_d = sig[sig["信号"]=="卖出"].copy()
                elif sig_filter == "⚪ 观望":
                    sig_d = sig[sig["信号"]=="观望"].copy()
                else:
                    sig_d = sig.copy()

                st.markdown("##### 🏷️ 第二步：概念筛选")
                # 概念池 = 当前已筛选数据中的概念
                all_concepts_sorted = sorted(sig_d["概念"].dropna().astype(str).unique().tolist())
                cc1, cc2 = st.columns([2, 1])
                with cc1:
                    # 多选概念标签
                    selected_concepts = st.multiselect(
                        "从列表选择（可多选）", all_concepts_sorted, default=[],
                        key=f"sig_{fn}_concept")
                with cc2:
                    # 自定义概念关键词输入
                    custom_concept = st.text_input("或输入自定义关键词", value="", key=f"sig_{fn}_custom_concept")

                # 合并筛选条件
                concept_filters = []
                if selected_concepts:
                    concept_filters.append("|".join([re.escape(c) for c in selected_concepts]))
                if custom_concept.strip():
                    concept_filters.append(re.escape(custom_concept.strip()))

                if concept_filters:
                    pattern = "|".join(concept_filters)
                    sig_d = sig_d[sig_d["概念"].astype(str).str.contains(pattern, na=False)]

                st.markdown("##### 🔍 第三步：股票搜索")
                search_input = st.text_input("输入股票名称或代码关键词", value="", key=f"sig_{fn}_search")
                sig_d["代码6"] = sig_d["代码"].astype(str).str.zfill(6)
                if search_input.strip():
                    kw = search_input.strip().lower()
                    sig_d = sig_d[
                        sig_d["股票"].str.contains(kw, case=False, na=False) |
                        sig_d["代码6"].str.contains(kw, na=False) |
                        sig_d["代码"].astype(str).str.contains(kw, na=False)
                    ]

                st.markdown("##### 📊 第四步：指标范围筛选")
                ind1, ind2, ind3 = st.columns(3)
                with ind1:
                    score_range = st.slider("SCORE 范围", 0, 10, (0, 10), key=f"sig_{fn}_score")
                    if score_range != (0, 10):
                        sig_d["SCORE_num"] = pd.to_numeric(sig_d["SCORE"], errors="coerce")
                        sig_d = sig_d[(sig_d["SCORE_num"] >= score_range[0]) & (sig_d["SCORE_num"] <= score_range[1])]
                    # 额外：买入信号可以按买入理由关键词筛选
                    if "买入" in sig_filter:
                        reason_kw = st.text_input("买入理由关键词（选填）", value="", key=f"sig_{fn}_reason")
                        if reason_kw.strip():
                            sig_d = sig_d[sig_d["理由"].str.contains(reason_kw, case=False, na=False)]

                with ind2:
                    rsi_min = st.number_input("RSI(14) 最低", value=None, step=5, min_value=0, max_value=100, key=f"sig_{fn}_rsi_min")
                    rsi_max = st.number_input("RSI(14) 最高", value=None, step=5, min_value=0, max_value=100, key=f"sig_{fn}_rsi_max")
                    if rsi_min is not None or rsi_max is not None:
                        sig_d["RSI_num"] = pd.to_numeric(sig_d["RSI(14)"], errors="coerce")
                        if rsi_min is not None:
                            sig_d = sig_d[sig_d["RSI_num"] >= rsi_min]
                        if rsi_max is not None:
                            sig_d = sig_d[sig_d["RSI_num"] <= rsi_max]

                with ind3:
                    price_min = st.number_input("最新价 最低", value=None, step=1.0, min_value=0.0, key=f"sig_{fn}_prc_min")
                    price_max = st.number_input("最新价 最高", value=None, step=1.0, min_value=0.0, key=f"sig_{fn}_prc_max")
                    if price_min is not None or price_max is not None:
                        sig_d["price_num"] = pd.to_numeric(sig_d["最新价"], errors="coerce")
                        if price_min is not None:
                            sig_d = sig_d[sig_d["price_num"] >= price_min]
                        if price_max is not None:
                            sig_d = sig_d[sig_d["price_num"] <= price_max]

                # 筛选计数
                active_filters = []
                if sig_filter != "全部": active_filters.append(f"信号={sig_filter}")
                if selected_concepts: active_filters.append(f"概念={len(selected_concepts)}个")
                if search_input.strip(): active_filters.append(f"搜索={search_input}")
                if score_range != (0,10): active_filters.append(f"SCORE={score_range}")
                if rsi_min is not None or rsi_max is not None: active_filters.append(f"RSI≈[{rsi_min}-{rsi_max}]")
                if price_min is not None or price_max is not None: active_filters.append(f"价格≈[{price_min}-{price_max}]")

                if active_filters:
                    st.info(f"🔍 条件: {' | '.join(active_filters)} → 匹配 {len(sig_d)} 条")
                else:
                    st.info(f"显示 {len(sig_d)} 条记录（无额外筛选）")

                # 格式化显示
                sig_d["代码"] = sig_d["代码"].astype(str).str.zfill(6)
                for c in ["最新价","EMA20","EMA60","ATR","压力位","支撑位"]:
                    if c in sig_d.columns:
                        sig_d[c] = sig_d[c].apply(lambda x: f"{x:.2f}" if isinstance(x,(int,float)) and not pd.isna(x) else "--")
                if "RSI(14)" in sig_d.columns:
                    sig_d["RSI(14)"] = sig_d["RSI(14)"].apply(lambda x: f"{x:.1f}%" if isinstance(x,(int,float)) and not pd.isna(x) else "--")
                if "乖离60" in sig_d.columns:
                    pass  # already string

                # 排序
                if sig_filter == "🟢 买入":
                    sig_d = sig_d.sort_values("SCORE", ascending=False)
                elif sig_filter == "🔴 卖出":
                    sig_d = sig_d.sort_values("SCORE", ascending=False)
                else:
                    sig_d = sig_d.sort_values("SCORE", ascending=False)

                # ── 自定义表格 + 收藏按钮 ──
                st.markdown("##### 📊 信号明细（点击 ⭐ 收藏）")
                # 表头
                st_cols = ["#","股票","代码","概念","SCORE","信号","最新价","压力位","支撑位","EMA20","EMA60","RSI(14)","OBV>EMA","ATR","乖离60","⭐"]
                widths = [0.4, 1.2, 0.9, 1.8, 0.5, 0.8, 0.8, 0.9, 0.9, 0.8, 0.8, 0.9, 0.7, 0.7, 0.8, 0.4]
                hdr = st.columns(widths)
                for j, c in enumerate(st_cols):
                    hdr[j].markdown(f"**{c}**")

                sig_d["代码6"] = sig_d["代码"].astype(str).str.zfill(6)
                for ri, (_, row) in enumerate(sig_d.iterrows()):
                    cols = st.columns(widths)
                    with cols[0]:
                        st.text(str(ri+1))
                    with cols[1]:
                        st.text(str(row.get("股票","")))
                    with cols[2]:
                        st.text(str(row.get("代码6","")))
                    with cols[3]:
                        st.text(str(row.get("概念","")))
                    with cols[4]:
                        s_val = row.get("SCORE", "--")
                        s_color = "🟢" if isinstance(s_val, (int, float)) and s_val >= 7 else ("🟡" if isinstance(s_val, (int, float)) and s_val >= 4 else "")
                        st.text(f"{s_color} {s_val}")
                    with cols[5]:
                        sig = str(row.get("信号",""))
                        if "买入" in sig: st.text("🟢买入")
                        elif "卖出" in sig: st.text("🔴卖出")
                        elif "观望" in sig: st.text("⚪观望")
                        else: st.text(sig)
                    with cols[6]: st.text(f"{row.get('最新价','--')}")
                    with cols[7]: st.text(f"{row.get('压力位','--')}")
                    with cols[8]: st.text(f"{row.get('支撑位','--')}")
                    with cols[9]: st.text(f"{row.get('EMA20','--')}")
                    with cols[10]: st.text(f"{row.get('EMA60','--')}")
                    with cols[11]: st.text(f"{row.get('RSI(14)','--')}")
                    with cols[12]: st.text(f"{row.get('OBV>EMA','--')}")
                    with cols[13]: st.text(f"{row.get('ATR','--')}")
                    with cols[14]: st.text(f"{row.get('乖离60','--')}")

                    # ⭐ 收藏按钮
                    with cols[15]:
                        code6 = str(row.get("代码6",""))
                        name = str(row.get("股票",""))
                        is_fav = favorite_manager.is_favorite(code6)
                        btn_text = "⭐" if is_fav else "☆"
                        btn_type = "primary" if is_fav else "secondary"
                        if st.button(btn_text, key=f"sig_fav_{fn}_{ri}_{code6}", type=btn_type,
                                    help=f"收藏: {name}({code6})" if not is_fav else f"取消收藏: {name}({code6})"):
                            if is_fav:
                                favorite_manager.remove_favorite(code6)
                                st.toast(f"❌ 已取消收藏 {name}", icon="❌")
                            else:
                                # 保存时关联df基本面
                                favorite_manager.add_favorite(code6, name=name, source=f"信号({sig})",
                                                               sector=str(row.get("概念","")), df=df)
                                st.toast(f"⭐ 已收藏 {name}", icon="⭐")
                            st.rerun()
            except Exception as e:
                st.error(f"读取 {fn} 失败: {e}")


# ══════════════ Tab 8: 交易日复盘 ══════════════
REVIEW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review_data")
if not os.path.exists(REVIEW_DIR):
    os.makedirs(REVIEW_DIR, exist_ok=True)

def save_review(trade_date, data):
    fname = os.path.join(REVIEW_DIR, f"review_{trade_date}.json")
    data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return fname

def load_review(trade_date):
    fname = os.path.join(REVIEW_DIR, f"review_{trade_date}.json")
    if not os.path.exists(fname):
        return None
    with open(fname, "r", encoding="utf-8") as f:
        return json.load(f)

def list_reviews():
    files = glob.glob(os.path.join(REVIEW_DIR, "review_*.json"))
    dates = []
    for fn in files:
        bn = os.path.basename(fn)
        m = bn.replace("review_", "").replace(".json", "")
        dates.append(m)
    return sorted(set(dates), reverse=True)


def _render_stock_table(stocks, prefix, df, trade_date):
    """在复盘页面中渲染涨停股表格 + 收藏按钮"""
    cols_w = [0.4, 0.8, 1.4, 0.8, 1.2, 0.8, 0.8, 0.6, 0.8, 1.8, 0.4]
    headers = ["#", "代码", "名称", "涨跌幅%", "收盘价", "成交额", "换手率", "连板", "涨停统计", "涨停原因", "⭐"]
    hdr = st.columns(cols_w)
    for j, h in enumerate(headers):
        hdr[j].markdown(f"**{h}**")

    for ri, sk in enumerate(stocks):
        cols = st.columns(cols_w)
        with cols[0]: st.text(str(ri + 1))
        with cols[1]: st.text(sk.get("code", "--"))
        with cols[2]: st.markdown(f"**{sk.get('name', '--')}**")
        with cols[3]:
            pct = sk.get("change_pct", "--")
            if isinstance(pct, (int, float)):
                st.markdown(f"**🟢 +{pct}%**" if pct > 0 else f"{pct}%")
            else:
                st.text(str(pct))
        with cols[4]: st.text(str(sk.get("close", "--")))
        with cols[5]: st.text(str(sk.get("turnover", "--")))
        with cols[6]: st.text(str(sk.get("turnover_rate", "--")))
        with cols[7]:
            lb = sk.get("连板数", 1)
            if isinstance(lb, (int, float)) and lb > 1:
                st.markdown(f"**{int(lb)}板**")
            else:
                st.text("1")
        with cols[8]:
            ts = sk.get("涨停统计", "")
            st.text(str(ts) if ts else "--")
        with cols[9]: st.text(str(sk.get("reason", "--")[:50]))
        with cols[10]:
            code = str(sk.get("code", "")).zfill(6)
            name = sk.get("name", "")
            is_fav = favorite_manager.is_favorite(code)
            btn_t = "⭐" if is_fav else "☆"
            btn_tp = "primary" if is_fav else "secondary"
            if st.button(btn_t, key=f"fav_{prefix}_{ri}_{code}", type=btn_tp,
                        help=f"收藏: {name}" if not is_fav else f"取消收藏: {name}"):
                if is_fav:
                    favorite_manager.remove_favorite(code)
                    st.toast(f"❌ 已取消收藏 {name}")
                else:
                    favorite_manager.add_favorite(code, name=name, source=f"复盘({trade_date})",
                                                   sector=sk.get("所属板块", ""), df=df)
                    st.toast(f"⭐ 已收藏 {name}")
                st.rerun()


# ══════════════ Tab 7: 热点解析 ══════════════
with tabs[7]:
    try:
        hot_concept_page.render_hot_concept_page()
    except Exception as e:
        st.error(f"热点解析模块加载失败: {e}")


with tabs[8]:
    st.subheader("📋 交易日复盘")
    st.caption("市场温度 | 热点板块 TOP10 | 涨停股总览（自动获取）| 收藏")

    dates = list_reviews()
    today = datetime.now().strftime("%Y-%m-%d")

    col_date, col_exist, col_auto = st.columns([2, 2, 2])
    with col_date:
        trade_date = st.text_input("交易日期 (YYYY-MM-DD)", value=today)
    with col_exist:
        existing = load_review(trade_date)
        if existing:
            src_tag = existing.get("source", "手动")
            st.success(f"✅ 已从{src_tag}获取 (更新于 {existing.get('updated_at', 'N/A')})")
        else:
            st.info(f"📝 {trade_date} 暂无复盘数据")
    with col_auto:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 一键自动获取", width="stretch", type="primary", key="auto_fetch_btn"):
            fetch_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fetch_daily_review.py")
            if os.path.exists(fetch_script):
                with st.spinner("正在从东方财富获取数据..."):
                    import subprocess
                    try:
                        result = subprocess.run(
                            ["python3", fetch_script, trade_date],
                            capture_output=True, text=True, timeout=120
                        )
                        if result.returncode == 0:
                            st.success("✅ 自动获取成功！数据已更新")
                            existing = load_review(trade_date)
                            st.rerun()
                        else:
                            st.error(f"获取失败:\n{result.stderr}")
                            st.text(result.stdout)
                    except subprocess.TimeoutExpired:
                        st.error("获取超时，请重试")
                    except Exception as e:
                        st.error(f"执行脚本异常: {e}")
            else:
                st.error(f"未找到脚本: {fetch_script}")

    # 1. Market Temperature
    if existing:
        st.markdown("### 🌡️ 市场温度")
        temp_val = existing["temperature"]
        temp_icon = "🥶" if temp_val < 20 else ("❄️" if temp_val < 40 else ("😐" if temp_val < 60 else ("🔥" if temp_val < 80 else "🔥🔥🔥")))
        temp_label = "冰点" if temp_val < 20 else ("偏冷" if temp_val < 40 else "中性" if temp_val < 60 else "偏热" if temp_val < 80 else "过热")
        if existing.get("source") == "akshare/东方财富":
            zt_c = existing.get("zt_count", "--")
            dt_c = existing.get("dt_count", "--")
            st.info(f"🤖 涨停 **{zt_c}** 只 | 跌停 **{dt_c}** 只 | {existing.get('updated_at','')}")
        st.markdown(f"**{temp_val}°C {temp_icon}** — {temp_label}")

        # 2. Hot Sectors
        st.markdown("### 🔥 热点板块 TOP 10")
        existing_sectors = existing.get("hot_sectors", existing.get("sectors", []))
        if existing_sectors:
            sec_cols_w = [0.4, 2.5, 1.2, 1.5, 2.5]
            sec_hdr = st.columns(sec_cols_w)
            for j, h in enumerate(["#", "板块", "均涨跌%", "封板", "涨停龙头股"]):
                sec_hdr[j].markdown(f"**{h}**")
            for sec in existing_sectors[:10]:
                sec_row = st.columns(sec_cols_w)
                with sec_row[0]: st.text(str(sec.get("rank", "--")))
                with sec_row[1]: st.markdown(f"**{sec.get('name', '--')}**")
                with sec_row[2]: st.text(str(sec.get("change_pct", "--")))
                with sec_row[3]: st.text(str(sec.get("turnover", "--")))
                # 显示该板块前3只涨停股
                sec_stocks = sec.get("stocks", [])
                with sec_row[4]:
                    if sec_stocks:
                        names = [s.get("name", "") for s in sec_stocks[:3]]
                        st.text("、".join(names))
                    else:
                        st.text("--")

        # 3. 涨停股 — 全部按板块分组 + 收藏
        if existing.get("hot_sectors"):
            st.markdown("### 🏷️ 涨停股 — 按板块分组 (点击 ⭐ 收藏)")
            if st.checkbox("仅显示收藏相关股票（已收藏的）", key="fav_filter_review"):
                fav_codes = set(favorite_manager.load_favorites().keys())
            else:
                fav_codes = None

            for sec in existing.get("hot_sectors", []):
                sec_name = sec.get("name", "")
                sec_stocks = sec.get("stocks", [])
                if fav_codes:
                    sec_stocks = [s for s in sec_stocks if str(s.get("code", "")).zfill(6) in fav_codes]
                    if not sec_stocks:
                        continue
                sec_count = len(sec_stocks)
                with st.expander(f"📌 {sec_name} — {sec_count}只 | 均涨跌: {sec.get('change_pct','')}% | 封板: {sec.get('turnover','')}", expanded=True):
                    if sec_stocks:
                        _render_stock_table(sec_stocks, f"ztf_{sec_name}", df, trade_date)
        elif existing.get("hot_stocks"):
            st.markdown("### 🔥 涨停股总览")
            _render_stock_table(existing["hot_stocks"], "all", df, trade_date)

        # 备注
        if existing.get("notes"):
            st.markdown(f"**备注**: {existing['notes']}")

    # ── 历史复盘 & 温度曲线 ──
    st.markdown("---")
    st.subheader("📅 历史复盘 & 温度曲线")
    if dates:
        temp_data = []
        for d in dates:
            rv = load_review(d)
            if rv:
                temp_data.append({"日期": d, "温度": rv.get("temperature", 0)})
        if len(temp_data) >= 2:
            temp_df = pd.DataFrame(temp_data).sort_values("日期")
            st.line_chart(temp_df.set_index("日期"), width="stretch")

        # Tab 切换：历史复盘回顾 vs 板块轮动分析
        review_tab, rotation_tab = st.tabs(["📊 历史复盘回顾", "🔄 板块轮动对比"])

        with review_tab:
            for d in dates[:10]:
                rv = load_review(d)
                if rv:
                    tv = rv.get("temperature", 0)
                    tic = "🥶" if tv < 20 else ("❄️" if tv < 40 else ("😐" if tv < 60 else ("🔥" if tv < 80 else "🔥🔥🔥")))
                    secs = rv.get("hot_sectors", rv.get("sectors", []))
                    top3 = [f"{s['rank']}.{s.get('name','')}" for s in secs[:3]]
                    hs = rv.get("hot_stocks", rv.get("stocks", []))
                    zt_n = rv.get("zt_count", len(hs))
                    with st.expander(f"{d} — {tv}°C {tic} | 涨停:{zt_n}只 | TOP3: {', '.join(top3)}"):
                        st.markdown(f"**温度**: {tv}°C {tic}")
                        if secs:
                            st.markdown("**热点板块**:")
                            for s in secs[:10]:
                                ss = s.get("stocks", [])
                                names = [x.get("name","") for x in ss[:3]]
                                st.markdown(f"  {s.get('rank','')}. **{s.get('name','')}** ({s.get('turnover','')}) → {', '.join(names)}")
                        if rv.get("notes"):
                            st.markdown(f"**备注**: {rv['notes']}")

        with rotation_tab:
            st.markdown("### 🔄 历史热门板块轮动对比")
            st.caption("对比各交易日 Top10 热门板块，追踪板块资金流向")

            # 选择对比日期
            max_dates = min(len(dates), 7)
            sel_dates = st.multiselect("选择对比日期", dates, default=dates[:min(3, len(dates))])

            if len(sel_dates) >= 2:
                # 构建对比矩阵
                rotation_rows = []
                for d in sel_dates:
                    rv = load_review(d)
                    if rv:
                        secs = rv.get("hot_sectors", rv.get("sectors", []))
                        for rank in range(1, 11):
                            sec = next((s for s in secs if s.get("rank") == rank), None)
                            rotation_rows.append({
                                "日期": d,
                                "排名": rank,
                                "板块": sec.get("name", "--") if sec else "--",
                                "涨停数": sec.get("turnover", "--").split("只")[0] if sec and "只" in str(sec.get("turnover", "")) else "--",
                                "均涨跌%": sec.get("change_pct", "--") if sec else "--",
                            })

                if rotation_rows:
                    rot_df = pd.DataFrame(rotation_rows)
                    # 按排名透视：日期为行，板块名列
                    pivot = rot_df.pivot_table(
                        index="日期", columns="排名", values="板块",
                        aggfunc="first", fill_value="--"
                    )
                    pivot = pivot[[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]]
                    pivot.columns = [f"第{_}名" for _ in range(1, 11)]
                    st.dataframe(pivot, width="stretch", height=min(50 * len(sel_dates) + 50, 300))

                    # 板块出现频次统计
                    st.markdown("#### 📊 板块出现频次 (选中日期)")
                    all_sectors = []
                    for d in sel_dates:
                        rv = load_review(d)
                        if rv:
                            secs = rv.get("hot_sectors", rv.get("sectors", []))
                            for s in secs:
                                sname = s.get("name", "")
                                if sname:
                                    all_sectors.append(sname)

                    if all_sectors:
                        from collections import Counter
                        freq = Counter(all_sectors)
                        freq_df = pd.DataFrame([
                            {"板块": k, "出现天数": v, "占比": f"{v/len(sel_dates)*100:.0f}%"}
                            for k, v in freq.most_common()
                        ])
                        st.dataframe(freq_df, width="stretch", hide_index=True, height=300)

                        # 连续出现板块高亮
                        always_in = [f"{k} ({v}/{len(sel_dates)})" for k, v in freq.most_common() if v == len(sel_dates)]
                        if always_in:
                            st.success(f"🔥 所有选中日期均上榜的板块: {' | '.join(always_in)}")

                else:
                    st.info("选中日期暂无板块数据")
            else:
                st.info("请至少选择 2 个日期进行对比")
with tabs[9]:
    favorites_page.render_favorites_page(df)

# ══════════════ Tab 9: 投资日历 ══════════════
with tabs[10]:
    try:
        calendar_content.render_calendar()
    except Exception as e:
        st.error(f"投资日历模块加载失败: {e}")

import pypinyin

# ─── 拼音转换 ───
def name2pinyin_first(name: str) -> str:
    """将中文名转为拼音首字母缩写，如 '方正电机' → 'fzdj'"""
    return ''.join(pypinyin.lazy_pinyin(name, style=pypinyin.FIRST_LETTER)).lower()


# ============================================================
# Tab 10: 投研分析
# ============================================================
RESEARCH_DIR = "/Users/skyler/workspace/投资框架/筛选股票/投研分析"

with tabs[11]:
    st.subheader("📊 券商研报投研分析")
    
    # 扫描 CSV 文件
    if os.path.isdir(RESEARCH_DIR):
        csv_files = sorted(glob.glob(os.path.join(RESEARCH_DIR, "*.csv")))
    else:
        csv_files = []
    
    if csv_files:
        file_choices = [os.path.basename(f) for f in csv_files]
        selected_file = st.selectbox("选择分析文件", file_choices, key="research_file")
        
        selected_path = os.path.join(RESEARCH_DIR, selected_file)
        
        @st.cache_data(ttl=600)
        def load_research(path):
            return pd.read_csv(path, dtype={"code": str})
        
        rdf = load_research(selected_path)
        
        # 清理列名和 NaN
        rdf["score"].fillna(0, inplace=True)
        
        # 统计卡片
        total = len(rdf)
        buys = rdf[rdf["score"] >= 2].shape[0]
        holds = rdf[(rdf["score"] >= 0) & (rdf["score"] < 2)].shape[0]
        sells = rdf[rdf["score"] < 0].shape[0]
        avg_score = round(rdf["score"].mean(), 2)
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("📋 总研报数", total)
        c2.metric("🟢 买入/强烈买入", f"{buys} ({buys/total*100:.0f}%)")
        c3.metric("⚪ 增持/持有", f"{holds} ({holds/total*100:.0f}%)")
        c4.metric("🔴 减持/卖出", f"{sells} ({sells/total*100:.0f}%)")
        
        # 评分分布图
        c5, c6 = st.columns(2)
        with c5:
            import plotly.graph_objects as go
            fig = go.Figure(data=[go.Bar(
                x=["强烈买入(3)", "买入(2)", "增持(1)", "持有(0)", "减持(-1)", "卖出(<0)"],
                y=[
                    len(rdf[rdf["score"] == 3]),
                    len(rdf[(rdf["score"] >= 1.5) & (rdf["score"] < 2.5)]),
                    len(rdf[(rdf["score"] >= 0.5) & (rdf["score"] < 1.5)]),
                    len(rdf[(rdf["score"] >= -0.5) & (rdf["score"] < 0.5)]),
                    len(rdf[(rdf["score"] >= -1.5) & (rdf["score"] < -0.5)]),
                    len(rdf[rdf["score"] < -1.5])
                ],
                marker_color=["#00cc96", "#1f77b4", "#ff7f0e", "#9467bd", "#d62728", "darkred"]
            )])
            fig.update_layout(title="评级分布", height=300, margin=dict(l=30,r=30,t=40,b=30))
            st.plotly_chart(fig, width="stretch")
        
        with c6:
            # 机构覆盖统计
            import plotly.express as px
            if "orgName" in rdf.columns:
                org_counts = rdf["orgName"].value_counts().head(15)
                fig2 = go.Figure(data=[go.Bar(
                    x=org_counts.values,
                    y=org_counts.index,
                    orientation="h",
                    marker_color="skyblue"
                )])
                fig2.update_layout(title="机构研报Top 15", height=300, margin=dict(l=30,r=30,t=40,b=30))
                st.plotly_chart(fig2, width="stretch")
            else:
                st.info("无机构信息")
        
        # 买入推荐详细列表
        st.markdown("### 🟢 强烈买入 / 买入推荐")
        buy_df = rdf[rdf["score"] >= 2].copy()
        if len(buy_df) > 0:
            buy_df = buy_df.sort_values("score", ascending=False).reset_index(drop=True)
            
            for i, (_, r) in enumerate(buy_df.iterrows()):
                code = str(r.get("code", "")).zfill(6)
                name = r.get("name", "")
                score = r.get("score", 0)
                rating = r.get("rating", "")
                logic = r.get("core_logic", "")
                org = r.get("orgName", "")
                report = r.get("reportTitle", "")
                ind = r.get("industry", "")
                pe = r.get("pe", "")
                cats = r.get("catalysts", "")
                risks = r.get("risks", "")
                
                with st.expander(
                    f"{'🟢' if score >= 2.5 else '🔵'} **{name}（{code}）** | SCORE={score:.1f} | {rating} | PE:{pe if not pd.isna(pe) else 'N/A'}",
                    expanded=(i < 5)
                ):
                    st.markdown(f"**机构**: {org}  |  **行业**: {ind}")
                    st.markdown(f"**研报**: {report}")
                    st.markdown(f"**核心逻辑**: {logic}")
                    
                    if cats and str(cats) != "nan" and str(cats) != "[]":
                        st.markdown(f"**催化剂**: {cats}")
                    else:
                        st.markdown("**催化剂**: 无")
                    if risks and str(risks) != "nan" and str(risks) != "[]":
                        st.markdown(f"**风险**: {risks}")
    
        # 增持 / 持有
        st.markdown("### ⚪ 增持 / 持有")
        hold_df = rdf[(rdf["score"] >= 0) & (rdf["score"] < 2)].copy()
        if len(hold_df) > 0:
            hold_df = hold_df.sort_values("score", ascending=False).reset_index(drop=True)
            for i, (_, r) in enumerate(hold_df.iterrows()):
                code = str(r.get("code", "")).zfill(6)
                name = r.get("name", "")
                score = r.get("score", 0)
                rating = r.get("rating", "")
                logic = r.get("core_logic", "")
                org = r.get("orgName", "")
                with st.expander(
                    f"⚪ **{name}（{code}）** | SCORE={score:.1f} | {rating} | **{org}**",
                    expanded=False
                ):
                    st.markdown(f"**逻辑**: {logic}")
    
        # 减持/卖出
        if sells > 0:
            st.markdown("### 🔴 减持 / 卖出")
            sell_df = rdf[rdf["score"] < 0].copy().sort_values("score", ascending=True).reset_index(drop=True)
            for i, (_, r) in enumerate(sell_df.iterrows()):
                code = str(r.get("code", "")).zfill(6)
                name = r.get("name", "")
                score = r.get("score", 0)
                rating = r.get("rating", "")
                logic = r.get("core_logic", "")
                org = r.get("orgName", "")
                with st.expander(
                    f"🔴 **{name}（{code}）** | SCORE={score:.1f} | {rating} | **{org}**",
                    expanded=False
                ):
                    st.markdown(f"**逻辑**: {logic}")
        
        # 全部明细表格
        st.markdown("---")
        st.markdown("### 📋 全部明细")
        display_cols = ["code", "name", "score", "rating", "industry", "orgName", "core_logic"]
        display_cols = [c for c in display_cols if c in rdf.columns]
        rdf_display = rdf[display_cols].copy()
        rdf_display["code"] = rdf_display["code"].str.zfill(6)
        st.dataframe(rdf_display.sort_values("score", ascending=False), width="stretch", height=400)
        
    else:
        st.info("投研分析目录下暂无 CSV 文件。请先运行 research_analyzer.py 生成分析结果。")
        st.code(f"dirc: {RESEARCH_DIR}", language="text")


# ══════════════ Tab 11: 数据明细 ══════════════
with tabs[12]:
    st.subheader(f"📋 完整数据表 ({len(sub)} 只)")

    # 搜索过滤
    search_kw = st.text_input(
        "🔍 搜索",
        placeholder="输入代码、名称或拼音首字母（如 fzdj → 方正电机）...",
        key="search_kw_detail"
    )

    if search_kw:
        kw = search_kw.strip().lower()
        # 预计算拼音首字母
        sub_pinyin = sub.copy()
        sub_pinyin["名称拼音"] = sub_pinyin["名称"].apply(
            lambda x: name2pinyin_first(x) if pd.notna(x) else ""
        )
        
        code_mask = sub_pinyin["代码"].astype(str).str.contains(kw, case=False, na=False)
        name_mask = sub_pinyin["名称"].str.contains(kw, case=False, na=False)
        
        # 纯字母输入时匹配拼音首字母
        if kw.isalpha():
            pinyin_mask = sub_pinyin["名称拼音"].str.contains(kw, case=False, na=False)
            filtered = sub_pinyin[code_mask | name_mask | pinyin_mask]
        else:
            filtered = sub_pinyin[code_mask | name_mask]
        
        st.info(f"找到 {len(filtered)} 只股票")
    else:
        filtered = sub

    dd = mkdisp(filtered)
    dd["代码"] = dd["代码"].astype(str).str.zfill(6)
    st.dataframe(dd, width="stretch", height=700)
    fn = f"stock_detail_{csel if csel != '全市场' else 'all'}.csv"
    st.download_button("📥 下载CSV", dd.to_csv(index=False, encoding="utf-8-sig"), fn, "text/csv")
