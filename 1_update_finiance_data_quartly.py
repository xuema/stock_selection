#!/usr/bin/env python3
"""
更新 final_rankings_with_details_latest.xlsx 中的估值/概念/股东数据为最新值
数据源: 10jqka (同花顺 basic.10jqka.com.cn)
使用内置 Chrome CDP 模拟浏览器

财务五列 (营收增长/净利同比增长/毛利率/ROE/资产负债率) 已由
update_finance_latest_quarter.py 走东财接口几秒刷完，本脚本只需跑
剩余需要页面解析的列 (PB/PE/总市值/概念/业绩预测/十大股东)。
"""

import os
import sys
import time
import random
import json
import argparse
from datetime import datetime

import openpyxl
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

# ── 断点续传 ──
CHECKPOINT_FILE = ".update_finance_checkpoint.json"

def save_checkpoint(row_num):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({"last_row": row_num, "time": datetime.now().isoformat()}, f, ensure_ascii=False)

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return None

def remove_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)

# ================= 配置 =================
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
USER_DATA_DIR = os.path.expanduser("~/sel_chrome_data")

# ── 列映射 (0-indexed, A=0) ──
COL_CODE   = 0  # A  代码
COL_NAME   = 1  # B  名称
COL_GN     = 9  # J  涉及概念
COL_PB     = 10 # K  市净率(PB)
COL_PE_S   = 11 # L  市盈率(静态)
COL_PE_D   = 12 # M  市盈率(动态)
COL_MCAP   = 13 # N  总市值
COL_PREDICT= 14 # O  业绩预测
COL_TOP10  = 15 # P  十大股东占比
COL_YYSR   = 4  # E  营收增长
COL_JLZZ   = 5  # F  净利同比增长
COL_MAOLI  = 6  # G  销售毛利率
COL_ROE    = 7  # H  净资产收益率
COL_ZHFZL  = 8  # I  资产负债率

# 需要更新的列索引列表
UPDATE_COLS = [COL_YYSR, COL_JLZZ, COL_MAOLI, COL_ROE, COL_ZHFZL,
               COL_GN, COL_PB, COL_PE_S, COL_PE_D, COL_MCAP,
               COL_PREDICT, COL_TOP10]


def get_driver():
    """启动 Chrome (使用内置 CDP，不需要 chromedriver)"""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    opts.binary_location = CHROME_PATH
    # 复用 Chrome 用户数据目录以保持登录态
    opts.add_argument(f"--user-data-dir={USER_DATA_DIR}")
    opts.add_argument("--disable-ipv6")
    opts.add_argument("--no-proxy-server")
    try:
        driver = webdriver.Chrome(options=opts)
        return driver
    except Exception as e:
        print(f"❌ 无法启动浏览器！请先关闭所有 Chrome 窗口。错误: {e}")
        return None


def kill_overlays(driver):
    """移除可能遮挡页面的弹窗或覆盖层"""
    overlay_selectors = [
        ".login-pop", ".modal-backdrop", ".fancybox-overlay",
        ".js-mask", ".confirm-pop", "div[class*='login']", "div[id*='login']"
    ]
    js = f"""
    const selectors = {json.dumps(overlay_selectors)};
    selectors.forEach(sel => {{
        document.querySelectorAll(sel).forEach(el => el.remove());
    }});
    """
    try:
        driver.execute_script(js)
    except:
        pass


def safe_get(driver, url):
    """带随机等待的安全页面访问"""
    wait_time = random.uniform(2.5, 5.5)
    time.sleep(wait_time)
    driver.get(url)
    if "login" in driver.current_url or "forbidden" in driver.page_source.lower():
        print(f"  ⚠️ 详情页探测到拦截，请手动处理后继续...")
        input("  👉 处理完成后按回车继续...")
        driver.get(url)


def fetch_finance_data(driver, code):
    """
    从 basic.10jqka.com.cn/{code}/finance.html 获取 JSON 财务数据
    返回 dict: {'yl_21_0': ..., 'yl_21_1': ..., ...}
    
    参考原脚本 get_stock_details() 中的财务 JSON 解析逻辑:
    - rl[2][0]  → 销售毛利率  (index 2)
    - rl[6][0]  → 净利同比增长 (index 6)
    - rl[13][0] → 营收增长     (index 13)
    - rl[14][0] → 净资产收益率  (index 14)
    - rl[24][0] → 资产负债率    (index 24)
    """
    safe_get(driver, f"https://basic.10jqka.com.cn/{code}/finance.html")
    kill_overlays(driver)
    
    raw_json_str = driver.execute_script(
        "return document.getElementById('main') ? document.getElementById('main').innerText : '';"
    )
    if not raw_json_str:
        return {}
    
    try:
        finance_dict = json.loads(raw_json_str)
    except json.JSONDecodeError:
        return {}
    
    return finance_dict


def fetch_concept(driver, code):
    """从概念页面获取涉及概念"""
    safe_get(driver, f"https://basic.10jqka.com.cn/{code}/concept.html")
    kill_overlays(driver)
    concept = driver.execute_script(
        "return Array.from(document.querySelectorAll('td.gnName'))"
        ".map(el => el.innerText.trim()).filter(t => t).join('，');"
    )
    return concept or "-"


def fetch_valuation(driver, code):
    """
    从主页获取估值数据
    返回: {'sjl': str, 'jtsyl': str, 'dtsyl': str, 'stockzsz': str}
    """
    safe_get(driver, f"https://basic.10jqka.com.cn/{code}/")
    kill_overlays(driver)
    
    result = {}
    for elem_id, key in [
        ("sjl", "PB"), ("jtsyl", "PE_static"),
        ("dtsyl", "PE_dynamic"), ("stockzsz", "market_cap")
    ]:
        try:
            el = driver.find_element(By.ID, elem_id)
            result[key] = el.text.strip()
        except:
            result[key] = "-"
    return result


def fetch_holder(driver, code):
    """从股东页面获取十大流通股东占比"""
    safe_get(driver, f"https://basic.10jqka.com.cn/{code}/holder.html")
    kill_overlays(driver)
    
    try:
        ratios = driver.find_elements(
            By.XPATH, "//caption[contains(text(),'前十大流通股东累计持有')]/em"
        )
        if len(ratios) >= 2:
            return ratios[1].text.strip()
    except:
        pass
    return "-"


def fetch_predict(driver, code):
    """从业绩预测页面获取预测数据"""
    safe_get(driver, f"https://basic.10jqka.com.cn/{code}/worth.html")
    kill_overlays(driver)
    
    try:
        raw = driver.execute_script(
            "return document.getElementById('yjycData') ? document.getElementById('yjycData').innerText : '';"
        )
        if raw:
            ds = json.loads(raw)
            items = [f"{i[0]}年:{i[1]}亿" for i in ds if i[3] == "YC"]
            if items:
                return " | ".join(items[:3])
    except:
        pass
    return "-"


def parse_finance_json_for_fields(finance_dict, page_title=""):
    """
    解析 finance JSON dict，提取需要的财务字段
    
    finance_dict 结构:
      - 'report': 二维数组，每一行是一个指标，每列是一个季度
      - 'dateList': 季度标签列表，如 ['2025-03-31', '2024-12-31', ...]
    
    报告:
      rl[2]  → 销售毛利率
      rl[6]  → 净利润同比增长
      rl[13] → 营业总收入同比增长   (营收增长)
      rl[14] → 净资产收益率(加权)(%)
      rl[24] → 资产负债率
    """
    result = {}
    
    report_list = finance_dict.get("report", [])
    date_list = finance_dict.get("dateList", [])
    
    # 判断最新季度
    latest_quarter = date_list[0] if date_list else "最新"
    
    # 指标映射: (json 数组索引, 列名)
    field_map = [
        (13, "营收增长"),       # 营业总收入同比增长(%)
        (6,  "净利同比增长"),   # 净利润同比增长(%)
        (2,  "销售毛利率"),     # 销售毛利率(%)
        (14, "净资产收益率"),   # 净资产收益率(加权)(%)
        (24, "资产负债率"),     # 资产负债率(%)
    ]
    
    for idx, field_name in field_map:
        if len(report_list) > idx:
            row = report_list[idx]
            if len(row) > 0 and row[0] is not False:
                val = row[0]  # 最新季度的值
                # 统一格式化：如果已有 % 则保留，否则添加
                val_str = str(val)
                if val_str.replace(".", "").replace("-", "").isdigit():
                    val_str = f"{val_str}%"
                result[field_name] = val_str
                result[f"{field_name}_quarter"] = latest_quarter
            else:
                result[field_name] = "-"
        else:
            result[field_name] = "-"
    
    return result


def fetch_all(driver, code):
    """获取一只股票的所有需要更新的数据"""
    results = {}
    
    # ── 1. 财务数据 (JSON) ──
    print(f"  📊 获取财务数据...", end="", flush=True)
    finance = fetch_finance_data(driver, code)
    if finance:
        page_title_raw = driver.execute_script("return document.title;")
        fdata = parse_finance_json_for_fields(finance, page_title_raw)
        results.update(fdata)
        quarter_tag = fdata.get("营收增长_quarter", "")
        print(f" ✅ (季度: {quarter_tag})")
    else:
        for k in ["营收增长", "净利同比增长", "销售毛利率", "净资产收益率", "资产负债率"]:
            results[k] = "-"
        print(" ❌ (未获取到)")
    
    # ── 2. 概念 ──
    print(f"  🏷️  获取概念...", end="", flush=True)
    results["涉及概念"] = fetch_concept(driver, code)
    print(" ✅")
    
    # ── 3. 估值 ──
    print(f"  💰 获取估值...", end="", flush=True)
    val = fetch_valuation(driver, code)
    results["市净率(PB)"] = val.get("PB", "-")
    results["市盈率(静态)"] = val.get("PE_static", "-")
    results["市盈率(动态)"] = val.get("PE_dynamic", "-")
    results["总市值"] = val.get("market_cap", "-")
    print(" ✅")
    
    # ── 4. 十大股东 ──
    print(f"  👥 获取股东占比...", end="", flush=True)
    results["十大股东占比"] = fetch_holder(driver, code)
    print(" ✅")
    
    # ── 5. 业绩预测 ──
    print(f"  🔮 获取业绩预测...", end="", flush=True)
    results["业绩预测"] = fetch_predict(driver, code)
    print(" ✅")
    
    return results


def format_col_name(col_idx):
    """列索引 → 列名"""
    mapping = {
        COL_YYSR: "营收增长", COL_JLZZ: "净利同比增长",
        COL_MAOLI: "销售毛利率", COL_ROE: "净资产收益率",
        COL_ZHFZL: "资产负债率", COL_GN: "涉及概念",
        COL_PB: "市净率(PB)", COL_PE_S: "市盈率(静态)",
        COL_PE_D: "市盈率(动态)", COL_MCAP: "总市值",
        COL_PREDICT: "业绩预测", COL_TOP10: "十大股东占比",
    }
    return mapping.get(col_idx, f"Col{col_idx}")


def main():
    parser = argparse.ArgumentParser(description="更新 Excel 中股票的财务/估值数据为最新季度")
    parser.add_argument("--start", type=int, default=None, help="起始行号 (默认自动检测断点→2)")
    parser.add_argument("--end", type=int, default=None, help="结束行号 (默认最后一行)")
    parser.add_argument("--backup", action="store_true", help="在更新前备份原始文件")
    parser.add_argument("--limit", type=int, help="限制处理的股票数量 (用于测试)")
    parser.add_argument("--no-resume", action="store_true", help="忽略断点记录，从头开始")
    parser.add_argument("--clear-checkpoint", action="store_true", help="清除断点记录并退出")
    args = parser.parse_args()

    # ── 清除断点 ──
    if args.clear_checkpoint:
        remove_checkpoint()
        print("🗑️ 断点记录已清除")
        sys.exit(0)

    filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "final_rankings_with_details_latest.xlsx")
    if not os.path.exists(filepath):
        print(f"❌ 文件不存在: {filepath}")
        sys.exit(1)

    wb = openpyxl.load_workbook(filepath)
    ws = wb.active
    rows = ws.max_row

    # ── 自动断点续传 ──
    resume_row = None
    if not args.no_resume and args.start is None:
        cp = load_checkpoint()
        if cp:
            resume_row = cp["last_row"] + 1
            print(f"🔁 检测到上次中断于第 {cp['last_row']} 行 ({cp.get('time','?')})，将从第 {resume_row} 行继续")

    if args.start is not None:
        start_row = args.start
    elif resume_row is not None:
        start_row = resume_row
    else:
        start_row = 2

    # ── 备份 ──
    if args.backup:
        bk = filepath.replace(".xlsx", f"_backup_{datetime.today().strftime('%Y%m%d')}.xlsx")
        import shutil
        shutil.copy2(filepath, bk)
        print(f"📦 已备份: {bk}")

    end_row = args.end if args.end else rows
    if args.limit:
        end_row = min(end_row, start_row + args.limit - 1)

    print(f"📂 文件: {filepath}")
    print(f"📊 总行数: {rows}, 处理范围: 第 {start_row} → {end_row} 行, 共 {end_row - start_row + 1} 只股票")
    print()

    driver = get_driver()
    if not driver:
        sys.exit(1)

    success_count = 0
    fail_count = 0

    try:
        for row_num in range(start_row, end_row + 1):
            code_cell = ws.cell(row=row_num, column=COL_CODE + 1)
            name_cell = ws.cell(row=row_num, column=COL_NAME + 1)
            code = str(code_cell.value).strip() if code_cell.value else ""
            name = name_cell.value or ""

            if not code:
                print(f"\n⏭️  第 {row_num} 行: 代码为空，跳过")
                continue

            total = end_row - start_row + 1
            print(f"\n{'='*60}")
            print(f"[{row_num - start_row + 1}/{total}] {code} {name}")
            print(f"{'='*60}")

            try:
                data = fetch_all(driver, code)

                # 写回 Excel
                col_name_to_idx = {
                    "营收增长": COL_YYSR, "净利同比增长": COL_JLZZ,
                    "销售毛利率": COL_MAOLI, "净资产收益率": COL_ROE,
                    "资产负债率": COL_ZHFZL, "涉及概念": COL_GN,
                    "市净率(PB)": COL_PB, "市盈率(静态)": COL_PE_S,
                    "市盈率(动态)": COL_PE_D, "总市值": COL_MCAP,
                    "业绩预测": COL_PREDICT, "十大股东占比": COL_TOP10,
                }
                for col_name, col_idx in col_name_to_idx.items():
                    if col_name in data:
                        ws.cell(row=row_num, column=col_idx + 1, value=data[col_name])

                success_count += 1
                print(f"✅ 第 {row_num} 行更新完成")

            except Exception as e:
                fail_count += 1
                print(f"❌ 第 {row_num} 行 {code} 处理失败: {e}")

            # 保存断点 (每行都记，方便随时恢复)
            save_checkpoint(row_num)

            # 每 20 只股票保存一次 Excel
            if (row_num - start_row + 1) % 20 == 0:
                wb.save(filepath)
                print(f"💾 中间保存 (进度: {row_num - start_row + 1})")

    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断，正在保存当前进度...")
        wb.save(filepath)
        print(f"🏁 下次直接运行将自动从断点恢复")
    finally:
        wb.save(filepath)
        driver.quit()

    remove_checkpoint()  # 全部完成，清除断点
    print(f"\n{'='*40}")
    print(f"🏁 全部完成!")
    print(f"  成功: {success_count}")
    print(f"  失败: {fail_count}")
    print(f"  文件已保存: {filepath}")


if __name__ == "__main__":
    main()
