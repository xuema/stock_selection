import pandas as pd
import numpy as np

# =========================
# 工具函数
# =========================

def parse_percent(value):
    if pd.isna(value):
        return 0.0
    value = str(value).replace('%', '').strip()
    try:
        return float(value)
    except:
        return 0.0

def parse_float(value):
    if pd.isna(value):
        return None
    value = str(value).strip()
    if value in ['亏损', '--', '']:
        return None
    try:
        return float(value)
    except:
        return None


# =========================
# 第一步：计算板块合理PE / PB
# =========================

def calculate_sector_thresholds(df):

    pe_list = []
    pb_list = []

    for _, row in df.iterrows():

        pe = parse_float(row['市盈率(动态)'])
        pb = parse_float(row['市净率(PB)'])

        # 剔除极端值
        if pe is not None and pe <= 500:
            pe_list.append(pe)

        if pb is not None and pb <= 50:
            pb_list.append(pb)

    pe_median = np.median(pe_list)
    pb_median = np.median(pb_list)

    pe_limit = pe_median * 1.2
    pb_limit = pb_median * 1.2

    print("======== 板块估值分析 ========")
    print("PE中位数:", round(pe_median, 2))
    print("合理PE门限:", round(pe_limit, 2))
    print("PB中位数:", round(pb_median, 2))
    print("合理PB门限:", round(pb_limit, 2))
    print("==============================\n")

    return pe_limit, pb_limit


# =========================
# 第二步：公司评分
# =========================

def calculate_score(row, pe_limit, pb_limit):

    score = 0

    # ===== 成长性 =====
    revenue_growth = parse_percent(row['营收增长'])
    profit_growth = parse_percent(row['净利同比增长'])

    if revenue_growth > 20:
        score += 15

    if profit_growth > 20:
        score += 15
    elif profit_growth < 0:
        score -= 10

    # ===== 盈利能力 =====
    gross_margin = parse_percent(row['销售毛利率'])

    if gross_margin > 40:
        score += 15
    elif 25 <= gross_margin <= 40:
        score += 10
    else:
        score += 5

    if profit_growth > 0:
        score += 10

    # ===== 财务安全 =====
    debt_ratio = parse_percent(row['资产负债率'])

    if debt_ratio < 40:
        score += 15
    elif 40 <= debt_ratio <= 60:
        score += 10
    else:
        score += 5

    # ===== 估值（板块自适应）=====
    pe = parse_float(row['市盈率(动态)'])
    pb = parse_float(row['市净率(PB)'])

    # PE评分
    if pe is None:
        pe_score = 0
        pe_label = "亏损"
    elif pe <= pe_limit:
        pe_score = 10
        pe_label = "合理"
    elif pe <= pe_limit * 1.5:
        pe_score = 6
        pe_label = "偏高"
    else:
        pe_score = 2
        pe_label = "高估"

    # PB评分
    if pb is None:
        pb_score = 0
        pb_label = "异常"
    elif pb <= pb_limit:
        pb_score = 10
        pb_label = "合理"
    elif pb <= pb_limit * 1.5:
        pb_score = 6
        pb_label = "偏高"
    else:
        pb_score = 2
        pb_label = "高估"

    score += pe_score + pb_score

    return score, pe_label, pb_label


# =========================
# 主程序
# =========================

def safe_read_csv(file_path):
    try:
        return pd.read_csv(file_path, encoding='utf-8')
    except:
        try:
            return pd.read_csv(file_path, encoding='gbk')
        except:
            return pd.read_csv(file_path, encoding='gb2312')

def main():

    input_file = "D:\\stock\\stock_308491_2026-03-04.csv"
    output_file = "D:\\stock\\scored\\氢能源.csv"

    df = safe_read_csv(input_file)

    # 计算板块门限
    pe_limit, pb_limit = calculate_sector_thresholds(df)

    scores = []
    pe_labels = []
    pb_labels = []

    for _, row in df.iterrows():
        score, pe_label, pb_label = calculate_score(row, pe_limit, pb_limit)
        scores.append(score)
        pe_labels.append(pe_label)
        pb_labels.append(pb_label)

    df['总评分'] = scores
    df['PE估值判断'] = pe_labels
    df['PB估值判断'] = pb_labels

    # 按评分排序
    df = df.sort_values(by='总评分', ascending=False)

    df.to_csv(output_file, index=False, encoding='utf-8-sig')

    print("评分完成，已输出文件:", output_file)


if __name__ == "__main__":
    main()