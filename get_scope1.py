#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import io
import subprocess

# 解决Windows控制台编码问题
if sys.platform == 'win32':
    # 尝试设置控制台输出编码为UTF-8
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        # 如果reconfigure不可用，使用TextIOWrapper
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 或者直接移除所有emoji，改用普通字符
import os
if os.name == 'nt':  # Windows系统
    # 定义替代字符映射
    emoji_map = {
        '📊': '[数据]',
        '📌': '[标记]',
        '▶️': '->',
        '✅': '[成功]',
        '❌': '[失败]',
        '⏸️': '[暂停]',
        '📁': '[文件]',
        '📂': '[文件夹]',
        '🔍': '[搜索]',
        '⚡': '[闪电]',
        '✨': '[完成]',
        '🎯': '[目标]',
        '📝': '[笔记]',
        '📈': '[上升]',
        '📉': '[下降]',
    }
    
    # 创建一个自定义的print函数
    original_print = print
    def safe_print(*args, **kwargs):
        new_args = []
        for arg in args:
            if isinstance(arg, str):
                for emoji, replacement in emoji_map.items():
                    arg = arg.replace(emoji, replacement)
            new_args.append(arg)
        original_print(*new_args, **kwargs)
    
    # 替换全局print
    __builtins__.print = safe_print

import csv
import time
import re
import random
import json
import argparse
import sys
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- 1. 接管模式配置 ---
edge_options = Options()
edge_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

try:
    driver = webdriver.Edge(options=edge_options)
except Exception as e:
    print(f"❌ 无法连接到浏览器！错误: {e}")
    exit()

driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
  "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
})

def check_login_and_pause():
    if "login" in driver.current_url:
        print("\n【检测到登录拦截！】请手动登录后按回车...")
        input()
        return True
    return False

def reset_browser_environment():
    """通过 PowerShell 强制重置 Edge 浏览器环境"""
    print("\n🔄 正在重置 Edge 浏览器环境...")
    
    # 1. 关闭占用 9222 端口的进程
    # 注意：这里使用了 r'' 前缀，确保 \s 不被解析为转义字符
    ps_close_cmd = r'netstat -ano | findstr :9222 | ForEach-Object { if ($_ -match "LISTENING\s+(\d+)$") { Stop-Process -Id $matches[1] -Force } }'
    
    # 2. 重新启动 Edge
    # 路径和参数前都加上 r 防止转义错误
    edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    edge_args = r'--remote-debugging-port=9222 --user-data-dir="C:\sel_edge_data"'
    ps_open_cmd = f'& "{edge_path}" {edge_args}'

    try:
        # 执行关闭
        subprocess.run(["powershell", "-Command", ps_close_cmd], check=False)
        time.sleep(1) 
        
        # 执行开启 (creationflags 确保在 Windows 下不会阻塞主程序)
        subprocess.Popen(["powershell", "-Command", ps_open_cmd], creationflags=subprocess.CREATE_NEW_CONSOLE)
        
        print("✅ 浏览器已重新启动，等待初始化...")
        time.sleep(5)  # 增加一点时间，确保浏览器完全加载
    except Exception as e:
        print(f"⚠️ 重置浏览器失败: {e}")

def get_all_stocks(gn_code):
    """
    全量名单抓取方案：从第 1 页抓到最后一页，剔除科创板
    """
    url = f"http://q.10jqka.com.cn/gn/detail/code/{gn_code}/"

    #url = f"https://q.10jqka.com.cn/thshy/detail/code/{thshy_code}/"

    driver.get(url)
    all_stocks = []
    seen_codes = set()
    
    try:
        check_login_and_pause()
        
        # 1. 自动解析总页数
        try:
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CLASS_NAME, "page_info")))
            page_info_text = driver.find_element(By.CLASS_NAME, "page_info").text
            total_pages = int(page_info_text.split('/')[-1])
            print(f"✅ 系统检测到共有 {total_pages} 页数据，准备开始全量抓取...")
        except:
            print("ℹ️ 未发现页码信息，按单页处理")
            total_pages = 1

        # 2. 循环遍历所有页面 (从 1 到 total_pages)
        for current_p in range(1, total_pages + 1):
            check_login_and_pause()
            print(f"🚀 正在处理第 {current_p}/{total_pages} 页...")
            
            # --- 核心：确保本页数据真实加载 ---
            page_rows = []
            for retry in range(5):  # 增加重试次数到 5 次
                try:
                    # 等待表格的行出现
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".m-table tbody tr"))
                    )
                    time.sleep(0.5) # 基础缓冲
                    temp_rows = driver.find_elements(By.CSS_SELECTOR, ".m-table tbody tr")
                    
                    # 检查是否真的拿到了数据行（排除“暂无数据”或“加载中”等占位符）
                    if len(temp_rows) > 0 and temp_rows[0].text.strip() != "":
                        page_rows = temp_rows
                        break
                except:
                    print(f"   ⏳ 正在等待第 {current_p} 页数据渲染 (第 {retry+1} 次尝试)...")
                    time.sleep(2)

            if not page_rows:
                print(f"   ❌ 无法获取第 {current_p} 页内容，可能触发了反爬或网络波动。")
                continue

            # --- 提取并过滤数据 ---
            page_added_count = 0
            for row in page_rows:
                try:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) > 2:
                        code = cells[1].text.strip()
                        name = cells[2].text.strip()
                        
                        # 核心过滤逻辑：剔除 688 科创板
                        if code.startswith('688'):
                            continue
                            
                        if code and code not in seen_codes:
                            all_stocks.append({'code': code, 'name': name})
                            seen_codes.add(code)
                            page_added_count += 1
                except:
                    continue
            
            print(f"   ✅ 本页新增 {page_added_count} 只有效股票 (剔除科创板后)")

            # --- 翻页操作 ---
            if current_p < total_pages:
                try:
                    # 优先寻找“下一页”按钮
                    next_btn = driver.find_element(By.XPATH, "//a[@class='changePage' and text()='下一页']")
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", next_btn)
                except:
                    # 备选方案：通过页码数字或 changePage JS 翻页
                    print(f"   🔄 尝试备选翻页方案跳转至第 {current_p + 1} 页")
                    driver.execute_script(f"changePage({current_p + 1});")
                
                # 必须验证翻页是否成功：检查页码文本是否更新
                try:
                    next_page_str = f"{current_p + 1}/"
                    WebDriverWait(driver, 10).until(
                        lambda d: d.find_element(By.CLASS_NAME, "page_info").text.startswith(next_page_str)
                    )
                except:
                    print(f"   ⚠️ 翻页验证超时，尝试刷新当前状态...")
                    time.sleep(3)

    except Exception as e:
        print(f"❌ 流程意外中断: {e}")
        
    print(f"\n📊 抓取汇总：全量页面已扫描完毕")
    print(f"🔹 最终获得非科创板股票总数: {len(all_stocks)} 只")
    return all_stocks

def get_stock_concepts(code):
    """
    从 concept.html 页面提取所有涉及概念
    """
    try:
        driver.get(f"https://basic.10jqka.com.cn/{code}/concept.html")
        # 增加显式等待，确保表格已加载
        time.sleep(1)
        
        # 使用 JS 直接在浏览器内存中完成文本清洗和合并
        js_code = """
        return Array.from(document.querySelectorAll('td.gnName'))
                    .map(el => el.innerText.trim())
                    .filter(text => text.length > 0)
                    .join('，');
        """
        concepts = driver.execute_script(js_code)
        return concepts if concepts else "-"
    except Exception as e:
        print(f"   ⚠️ 概念提取异常 [{code}]: {e}")
        return "-"

def get_stock_valuation(code):
    """
    获取股票 市盈率（静态）、市盈率（动态）、市净率
    """

    try:
        url = f"https://basic.10jqka.com.cn/{code}/"
        driver.get(url)

        wait = WebDriverWait(driver, 10)

        pb = wait.until(
            EC.presence_of_element_located((By.ID, "sjl"))
        ).text.strip()

        pe_static = wait.until(
            EC.presence_of_element_located((By.ID, "jtsyl"))
        ).text.strip()

        pe_dynamic = wait.until(
            EC.presence_of_element_located((By.ID, "dtsyl"))
        ).text.strip()

        market_value = wait.until(
            EC.presence_of_element_located((By.ID, "stockzsz"))
        ).text.strip()

        return {
            "市净率(PB)": pb,
            "市盈率(静态)": pe_static,
            "市盈率(动态)": pe_dynamic,
            "总市值": market_value
        }

    except Exception as e:
        return {
            "股票代码": code,
            "error": str(e)
        }
        
def get_stock_details(code):
    """精准提取：仅保留增长变动指标和基础资料"""
    """提取：涉及概念、增长指标（基于JSON解析）、基础资料"""
    biz, boss, intro, ratio, concepts = "未找到", "未找到", "未找到", "未找到", "未找到"
    # 新增/修改的指标
    net_profit_growth = "-"  # 净利润同比增长率
    gross_margin = "-"      # 销售毛利率
    debt_ratio = "-"        # 资产负债率
    roe = "-"               # 净资产收益率
    pb, pe_static, pe_dynamic, market_value = "-", "-", "-", "-" # 估值指标
    
    rev_growth, eps_growth = "-", "-" # 保留原有的其他财务指标
    yjyc = "无数据"

    def safe_get(target_url):
        driver.get(target_url)
        time.sleep(0.5)
        if "login" in driver.current_url:
            check_login_and_pause()
            driver.get(target_url)

    concepts = get_stock_concepts(code)
    pb, pe_static, pe_dynamic, market_value = get_stock_valuation(code).get("市净率(PB)", "-"), get_stock_valuation(code).get("市盈率(静态)", "-"), get_stock_valuation(code).get("市盈率(动态)", "-"), get_stock_valuation(code).get("总市值", "-")
    # 1. 基础资料 & 涉及概念 (company.html)
    try:
        safe_get(f"http://basic.10jqka.com.cn/{code}/company.html")
        # --- 核心修改：提取完整概念字符串 ---
        try: biz = driver.find_element(By.XPATH, "//strong[contains(text(),'主营业务')]/following-sibling::span").text.strip()
        except: pass
        try: boss = driver.find_element(By.XPATH, "//strong[contains(text(),'实际控制人')]/following-sibling::span").text.strip().replace('\n', ' ')
        except: pass
        try: intro = driver.find_element(By.CSS_SELECTOR, "p.tip.lh24").text.strip()
        except: pass
    except: pass

    # 2. 股东数据 (holder.html)
    try:
        safe_get(f"http://basic.10jqka.com.cn/{code}/holder.html")
        ratios = driver.find_elements(By.XPATH, "//caption[contains(text(),'前十大流通股东累计持有')]/em")
        if len(ratios) >= 2: ratio = ratios[1].text.strip()
    except: pass

    # 3. 核心财务指标 (finance.html) - 采用 JSON 解析方案
    try:
        safe_get(f"http://basic.10jqka.com.cn/{code}/finance.html")
        # 获取隐藏在页面 p#main 标签中的 JSON 数据
        raw_json_str = driver.execute_script("return document.getElementById('main') ? document.getElementById('main').innerText : '';")
        
        if raw_json_str:
            finance_data = json.loads(raw_json_str)
            report_list = finance_data.get('report', [])
            
            # 同花顺固定索引位：
            # index 2: 净利润同比增长率
            # index 6: 营业总收入同比增长率 (即营收增长)
            # index 13: 销售毛利率
            # index 14: 净资产收益率 (ROE) - 根据数据推断
            # index 24: 资产负债率
            
            if len(report_list) > 24:
                # [0] 代表获取最新一期的数据
                net_profit_growth = report_list[2][0] if report_list[2][0] else "-"
                rev_growth = report_list[6][0] if report_list[6][0] else "-"
                gross_margin = report_list[13][0] if report_list[13][0] else "-"
                roe = report_list[14][0] if report_list[14][0] else "-"
                debt_ratio = report_list[24][0] if report_list[24][0] else "-"
                
                # 处理可能存在的 False 值（同花顺 JSON 中无效数据常为 false）
                net_profit_growth = "-" if net_profit_growth is False else net_profit_growth
                rev_growth = "-" if rev_growth is False else rev_growth
                gross_margin = "-" if gross_margin is False else gross_margin
                roe = "-" if roe is False else roe
                debt_ratio = "-" if debt_ratio is False else debt_ratio
    except Exception as e:
        print(f"   ⚠️ 财务 JSON 解析失败: {e}")

    # 4. 业绩预测 (worth.html)
    try:
        safe_get(f"https://basic.10jqka.com.cn/{code}/worth.html")
        raw = driver.execute_script("return document.getElementById('yjycData') ? document.getElementById('yjycData').innerText : '';")
        if raw:
            ds = json.loads(raw)
            items = [f"{i[0]}年:{i[1]}亿" for i in ds if i[3] == "YC"]
            if items: yjyc = " | ".join(items[:3])
    except: pass
    
    return biz, boss, intro, ratio, yjyc, rev_growth, net_profit_growth, eps_growth, concepts, gross_margin, roe, debt_ratio, pb, pe_static, pe_dynamic, market_value

def parse_args():
    """解析命令行参数 - 极简版"""
    parser = argparse.ArgumentParser(
        description='股票数据抓取工具 - 按行业抓取股票数据',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python script.py 数字水印                    # 基本用法
  python script.py MiniLED                      # 其他行业
  python script.py 氢能源 -o mydata.csv         # 指定输出文件
  python script.py -i 智能电网                   # 使用参数名
        """
    )
    
    # 位置参数 - industry (可以直接输入，不需要 -i)
    parser.add_argument(
        'industry',
        type=str,
        nargs='?',  # 可选，为了兼容 -i 参数
        help='行业名称 (例如: 数字水印, MiniLED, 氢能源, 智能电网)'
    )
    
    # 可选参数
    parser.add_argument(
        '-i', '--industry',
        type=str,
        dest='industry_alt',
        help='行业名称（替代位置参数）'
    )
    
    parser.add_argument(
        '-o', '--output',
        type=str,
        default=None,
        help='输出文件名（可选），不指定则自动生成: {行业}_{日期}.csv'
    )
    
    # 如果没有参数，显示帮助
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)
    
    return parser.parse_args()


def get_target_code_by_industry(industry):
    """
    根据行业名称返回对应的 target_code
    您可以根据需要在这里配置各个行业的 target_code
    """
    industry_target_codes = {
        # ========== 人形机器人 & 高端制造 ==========
        "人形机器人": "309119",      # 人形机器人 380
        "机器人概念": "300816",      # 机器人概念
        "BC电池": "309084",        # BC电池
        "3D打印": "300127",         # 3D打印
        "PEEK材料": "309105",        # PEEK材料 Y
        "减速器": "309000",          # 减速器
        
        # ========== 新能源 & 电力 ==========
        "储能": "306380",            # 储能 809
        "风电": "300200",            # 风电 413
        "光伏概念": "301079",         # 光伏概念 578 Y
        "BC电池": "309084",           # BC电池 49 Y
        "钙钛矿电池": "308991",       # 钙钛矿电池 Y
        "HJT电池": "308991",          # HJT电池（与钙钛矿电池共用）
        "TOPCON电池": "308992",       # TOPCON电池（与钙钛矿电池共用）
        "固态电池": "308294",         # 固态电池
        "钠离子电池": "301096",       # 钠离子电池（与固态电池共用）
        "锂电池": "300733",           # 锂电池（与光伏概念共用）
        "氢能源": "308491",           # 氢能源 Y
        "燃料电池": "300316",         # 燃料电池（与氢能源共用）
        "可燃冰": "300277",           # 可燃冰 Y
        "天然气": "300358",           # 天然气
        "页岩气": "300402",           # 页岩气（与可燃冰共用）
        "绿色电力": "308760",          # 绿色电力 372 Y
        "智能电网": "300037",          # 智能电网 Y
        "特高压": "300353",            # 特高压 Y
        "柔性直流输电": "308810",       # 柔性直流输电 Y
        "虚拟电厂": "308761",           # 虚拟电厂 Y
        "电力物联网": "308477",          # 电力物联网 Y
        "风电": "300200",               # 风电
        "核电": "300238",               # 核电（与风电共用）
        "抽水蓄能": "308753",           # 抽水蓄能（与绿色电力共用）
        "生物质能发电": "308989",       # 生物质能发电（与绿色电力共用）
        "超超临界发电": "308969",       # 超超临界发电（与绿色电力共用）
        
        # ========== 半导体 & 芯片 ==========
        "第三代半导体": "308700",        # 第三代半导体 159
        "芯片概念": "301085",            # 芯片概念（与第三代半导体共用）
        "存储芯片": "307940",            # 存储芯片 172 Y
        "先进封装": "309004",             # 先进封装 Y
        "共封装光学": "309049",           # 共封装光学（CPO）150 Y
        "光刻胶": "308582",               # 光刻胶
        "光刻机": "309085",               # 光刻机（与光刻胶共用）
        "PCB概念": "308832",              # PCB概念 Y
        "MiniLED": "308628",              # MiniLED Y
        "MicroLED": "308628",             # MicroLED（与MiniLED共用）
        "OLED": "301154",                 # OLED Y
        "电子纸": "301135",               # 电子纸 Y
        "柔性屏": "308467",                # 柔性屏 Y
        
        # ========== AI & 数字经济 ==========
        "Sora概念": "309118",              # Sora概念
        "AI应用": "309264",                 # AI 应用 Y
        "AI智能体": "309264",               # AI智能体（与AI应用共用）
        "多模态AI": "309264",               # 多模态AI（与AI应用共用）
        "ChatGPT概念": "309264",            # ChatGPT概念（与AI应用共用）
        "AIGC概念": "309264",               # AIGC概念（与AI应用共用）
        "数据安全": "308801",               # 数据安全 Y
        "网络安全": "300756",               # 网络安全（与数据安全共用）
        "信创": "309020",                   # 信创（与数据安全共用）
        "数据要素": "309060",                # 数据要素（与数据安全共用）
        "数据中心": "308642",                # 数据中心 576
        "算力租赁": "309068",                 # 算力租赁 Y
        "东数西算": "308828",                 # 东数西算 358 Y
        "液冷服务器": "309061",                # 液冷服务器 Y 172
        "铜缆高速连接": "309125",              # 铜缆高速连接 Y
        "数字水印": "309050",                  # 数字水印 Y
        "数字货币": "301997",                  # 数字货币 Y
        "跨境支付": "301997",                  # 跨境支付（与数字货币共用）
        "区块链": "302045",                    # 区块链（与数字货币共用）
        "华为昇腾": "309090",                   # 华为昇腾 Y
        "华为鲲鹏": "308883",                   # 华为鲲鹏（与华为昇腾共用）
        "华为鸿蒙": "309090",                   # 华为鸿蒙（与华为昇腾共用）
        "华为概念": "301459",                   # 华为概念（与华为昇腾共用）
        "英伟达概念": "309065",                  # 英伟达概念 Y
        "AI手机": "309120",                     # AI手机
        "AI PC": "309121",                      # AI PC（与AI手机共用）
        "消费电子": "308384",                    # 消费电子 Y
        
        # ========== 商业航天 & 军工 ==========
        "商业航天": "309130",           # 商业航天 386 Y
        "卫星导航": "300722",           # 卫星导航（与商业航天共用）
        "低空经济": "309115",           # 低空经济（与商业航天共用）
        "飞行汽车": "309113",           # 飞行汽车（与商业航天共用）
        "中船系": "301713",             # 中船系 10 Y
        "军工": "300082",                # 军工 597 Y
        "军民融合": "301786",            # 军民融合（与军工共用）
        "军工信息化": "309128",          # 军工信息化 Y
        "兵装重组": "309185",            # 兵装重组 Y
        "大飞机": "300013",              # 大飞机（与商业航天共用）
        "航空发动机": "301470",           # 航空发动机（与商业航天共用）
        "海工装备": "300105",             # 海工装备 Y
        "国产航母": "300236",             # 航母概念（与中船系共用）
        "可控核聚变": "309108",             # 可控核聚变 Y 100
        
        # ========== 有色金属 & 资源 ==========
        "黄金概念": "300248",             # 黄金概念 Y
        "金属铜": "301577",                # 金属铜 Y
        "铜": "301577",                    # 铜
        "小金属概念": "300809",            # 小金属概念 Y
        "稀土永磁": "300382",               # 稀土永磁 63 Y
        "金属钴": "302174",                 # 金属钴 Y
        "钴": "302174",                     # 钴
        "金属镍": "301511",                 # 金属镍（与小金属概念共用）
        "盐湖提锂": "307904",                # 盐湖提锂
        "磷化工": "300098",                  # 磷化工 62 Y
        "氟化工概念": "300085",               # 氟化工概念 Y
        "煤化工概念": "300084",                # 煤化工概念 Y
        "煤炭概念": "308716",                  # 煤炭概念 Y
        "可燃冰": "300277",                    # 可燃冰 Y
        "天然气": "300358",                    # 天然气
        "页岩气": "300402",                    # 页岩气（与可燃冰共用）
        "钻石培育": "308774",                   # 钻石培育 Y
        
        # ========== 通信 & 5G/6G ==========
        "F5G概念": "308977",                  # 5G概念 Y
        "6G概念": "309055",                  # 6G概念（与5G共用）
        "光纤概念": "309151",                 # 光纤概念 Y
        
        # ========== 量子 & 超导 ==========
        "量子科技": "300830",                  # 量子科技 Y
        "超导概念": "309056",                  # 超导概念
        
        # ========== 医疗 & 健康 ==========
        "创新药": "308014",                    # 创新药 270 Y
        "医疗器械概念": "301505",               # 医疗器械概念
        "智能医疗": "300682",                   # 智能医疗
        "养老概念": "301494",                   # 养老概念
        "医药电商": "301565",                    # 医药电商
        "乳业": "300983",                        # 乳业 Y
        "医美概念": "308712",                    # 医美概念（与创新药共用）
        
        # ========== 农业 & 机械 ==========
        "农机": "301306",                        # 农机
        "乡村振兴": "300836",                    # 乡村振兴（与农机共用）
        
        # ========== 其他概念 ==========
        "脑机接口": "308535",                    # 脑机接口 70 Y
        "俄乌冲突概念": "308850",                 # 俄乌冲突概念 Y 100
        "一带一路": "301365",                     # 一带一路（与俄乌冲突共用）
        "中俄贸易": "308854",                     # 中俄贸易（与俄乌冲突共用）
        "海峡两岸": "300066",                     # 海峡两岸
        "福建自贸区": "301236",                   # 福建自贸区（与海峡两岸共用）
        "足球概念": "301100",                     # 足球概念 Y
        "体育产业": "301605",                     # 体育产业（与足球概念共用）
        "染料": "301292",                         # 染料
        "文化传媒": "300806",                      # 文化传媒
        "抖音概念": "308366",                      # 抖音概念（与文化传媒共用）
        "网红经济": "308630",                      # 网红经济（与文化传媒共用）
        "短剧游戏": "309093",                      # 短剧游戏（与文化传媒共用）
        "虚拟现实": "301699",                      # 虚拟现实（与柔性屏共用）
        "元宇宙": "308752",                        # 元宇宙（与柔性屏共用）
    }
    
    # 返回对应行业的 target_code，如果没有找到则返回 None
    return industry_target_codes.get(industry)

if __name__ == "__main__":
    import time
    import random
    import csv
    import sys
    from datetime import datetime

    # --- 前置参数解析与配置省略 (保持你之前的逻辑) ---
    args = parse_args()

    # ================= 核心修改点 1：定义重试配置 =================
    max_retries = 3  
    retry_count = 0
    stocks_list = []

    industry_name = args.industry or args.industry_alt
    if not industry_name: sys.exit(1)
    target_code = get_target_code_by_industry(industry_name)
    #stocks_list = get_all_stocks(target_code)
    csv_filename = args.output if args.output else f'{industry_name}_{datetime.today().strftime("%Y-%m-%d")}.csv'
    # ----------------------------------------------
    
    while retry_count < max_retries:
        print(f"🔍 正在尝试获取 {industry_name} 的股票列表 (第 {retry_count + 1} 次)...")
        stocks_list = get_all_stocks(target_code)
        
        if stocks_list and len(stocks_list) > 0:
            print(f"✅ 成功获取到 {len(stocks_list)} 只股票")
            break
        else:
            print(f"⚠️ 警告：本页新增 0 只有效股票，触发环境重置...")
            reset_browser_environment()  # 执行你之前定义的 PowerShell 重置命令
            retry_count += 1
            time.sleep(5) # 给浏览器预留更多的启动时间

    if not stocks_list:
        print(f"❌ 错误：连续 {max_retries} 次尝试均未获取到有效股票，脚本退出。")
        sys.exit(1)

    try:
        with open(csv_filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['代码', '名称', '营收增长', '净利同比增长', '销售毛利率', '净资产收益率', '资产负债率', '涉及概念', '市净率(PB)', '市盈率(静态)', '市盈率(动态)', '总市值', '业绩预测', '十大股东占比', '实控人', '主营业务', '简介'])

            consecutive_failures = 0  # 计数器：记录连续失败次数

            for i, s in enumerate(stocks_list, 1):
                print(f"[{i}/{len(stocks_list)}] 正在提取: {s['code']} {s['name']}...", end='', flush=True)
                
                try:
                    res = get_stock_details(s['code'])
                    
                    # 如果抓取成功，重置连续失败计数
                    consecutive_failures = 0
                    
                    writer.writerow([
                        s['code'],           # 代码
                        s['name'],           # 名称
                        res[5],               # 营收增长
                        res[6],               # 净利同比增长
                        res[9],               # 销售毛利率
                        res[10],              # 净资产收益率
                        res[11],              # 资产负债率
                        res[8],               # 涉及概念
                        res[12],              # 市净率(PB)
                        res[13],              # 市盈率(静态)
                        res[14],              # 市盈率(动态)
                        res[15],              # 总市值
                        res[4],               # 业绩预测
                        res[3],               # 十大股东占比
                        res[1],               # 实控人
                        res[0],               # 主营业务
                        res[2]                # 简介
                    ])
                    
                    print(f" ✅ 完成")
                    
                    # 随机延时，避免请求过快
                    time.sleep(random.uniform(0.5, 1.0))
                    
                except Exception as e:
                    print(f" ❌ 失败: {e}")
                    consecutive_failures += 1
                    
                    # --- 核心逻辑：如果连续失败 2 次，尝试重置浏览器 ---
                    if consecutive_failures >= 2:
                        reset_browser_environment()
                        consecutive_failures = 0 # 重置计数，给新环境机会
                    continue

    except KeyboardInterrupt:
        print("\n⚠️ 用户中断")
    finally:
        print("\n" + "-" * 40)
        if 'driver' in locals():
            try:
                driver.quit()
                print("✅ 资源已回收")
            except:
                pass
        print(f"📁 最终数据保存至: {csv_filename}")

