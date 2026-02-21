import csv
import time
import re
import random
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- 1. 接管模式配置 ---
edge_options = Options()
# 关键：连接到你手动通过 9222 端口开启的浏览器
edge_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

# 由于是接管模式，不再需要指定驱动路径，它会自动寻找已运行的浏览器
try:
    driver = webdriver.Edge(options=edge_options)
except Exception as e:
    print(f"❌ 无法连接到浏览器！请确保你已经按步骤运行了 CMD 命令启动 Edge。错误: {e}")
    exit()

# 隐藏指纹特征（双重保险）
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
  "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
})

def check_login_and_pause():
    """检测登录拦截"""
    if "login" in driver.current_url:
        print("\n" + "!"*50)
        print("【检测到登录拦截！】")
        print("请在刚才打开的浏览器窗口中手动完成登录。")
        print("登录成功并回到数据列表后，请回来这里按回车。")
        print("!"*50 + "\n")
        input("完成登录后请按回车 [Enter] 继续抓取...")
        return True
    return False

def get_all_stocks(gn_code):
    """获取板块全量名单"""
    url = f"http://q.10jqka.com.cn/gn/detail/code/{gn_code}/"
    driver.get(url)
    
    all_stocks = []
    seen_codes = set()
    
    try:
        # 初次进入检查
        check_login_and_pause()

        # 等待页码信息加载
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CLASS_NAME, "page_info")))
        page_text = driver.find_element(By.CLASS_NAME, "page_info").text
        total_pages = int(page_text.split('/')[-1])
        print(f"✅ 检测到板块 {gn_code} 共 {total_pages} 页数据")
        
        current_p = 1
        while current_p <= total_pages:
            check_login_and_pause()
            print(f"正在读取第 {current_p}/{total_pages} 页...")
            
            try:
                # 等待数据表格
                WebDriverWait(driver, 15).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".m-table tbody tr"))
                )
                time.sleep(random.uniform(1.0, 2.0)) # 稍微快一点点
                
                rows = driver.find_elements(By.CSS_SELECTOR, ".m-table tbody tr")
                for row in rows:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) > 2:
                        code = cells[1].text.strip()
                        name = cells[2].text.strip()
                        if code and code not in seen_codes:
                            all_stocks.append({'code': code, 'name': name})
                            seen_codes.add(code)
                
                # 翻页
                if current_p < total_pages:
                    next_p = current_p + 1
                    next_btn = driver.find_element(By.XPATH, "//a[@class='changePage' and text()='下一页']")
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", next_btn)
                    
                    # 验证页码更新
                    WebDriverWait(driver, 10).until(
                        lambda d: d.find_element(By.CLASS_NAME, "page_info").text.startswith(f"{next_p}/")
                    )
                    current_p += 1
                else:
                    break
                    
            except Exception as e:
                print(f"⚠️ 第 {current_p} 页翻页受阻，尝试检测登录状态...")
                if check_login_and_pause():
                    continue
                else:
                    # 备用 JS 翻页
                    driver.execute_script(f"changePage({current_p + 1});")
                    time.sleep(3)
                    current_p += 1
                    
    except Exception as e:
        print(f"❌ 流程中断: {e}")
        
    return all_stocks

def get_stock_details(code):
    """提取详情信息"""
    biz, boss, intro, ratio = "未找到", "未找到", "未找到", "未找到"
    
    # 抓取详情时也检查一下是否跳到了登录页
    def safe_get(url):
        driver.get(url)
        if "login" in driver.current_url:
            check_login_and_pause()
            driver.get(url)

    # 1. 公司资料
    try:
        safe_get(f"http://basic.10jqka.com.cn/{code}/company.html")
        WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.CLASS_NAME, "m_table")))
        try: biz = driver.find_element(By.XPATH, "//strong[contains(text(),'主营业务')]/following-sibling::span").text.strip()
        except: pass
        try: boss = driver.find_element(By.XPATH, "//strong[contains(text(),'实际控制人')]/following-sibling::span").text.strip().replace('\n', ' ')
        except: pass
        try: intro = driver.find_element(By.CSS_SELECTOR, "p.tip.lh24").text.strip()
        except: pass
    except: pass

    # 2. 股东数据
    try:
        safe_get(f"http://basic.10jqka.com.cn/{code}/holder.html")
        WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".m_table.m_hl")))
        ratios = driver.find_elements(By.XPATH, "//caption[contains(text(),'前十大流通股东累计持有')]/em")
        if len(ratios) >= 2: ratio = ratios[1].text.strip()
    except: pass
    
    return biz, boss, intro, ratio

# --- 执行区 ---
if __name__ == "__main__":
    target_code = "309130"

    #309130 商业航天
    #309119 人形机器人
    
    try:
        stocks_list = get_all_stocks(target_code)
        
        if stocks_list:
            # 自动添加板块后缀的文件名
            csv_filename = f'stock_report_{target_code}.csv'
            print(f"\n📂 名单获取成功，准备处理 {len(stocks_list)} 只股票...")
            
            with open(csv_filename, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['代码', '名称', '十大股东占比', '实控人', '主营业务', '公司简介'])
                
                for i, s in enumerate(stocks_list):
                    print(f"[{i+1}/{len(stocks_list)}] 正在提取: {s['code']} {s['name']}")
                    b, o, intro, r = get_stock_details(s['code'])
                    writer.writerow([s['code'], s['name'], r, o, b, intro])
                    # 既然已经接管了浏览器，详情页延时可以稍微缩短
                    time.sleep(random.uniform(0.8, 1.5))
            
            print(f"\n✨ 抓取圆满完成！文件保存在: {csv_filename}")
        else:
            print("❌ 未获取到名单，请检查浏览器是否已跳转或被封禁。")
            
    finally:
        # 注意：接管模式下，建议不要 driver.quit()，否则会关掉你正在用的浏览器
        print("程序已退出，浏览器窗口保留。")