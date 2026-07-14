import pandas as pd
import json

print('Loading Excel...')
df = pd.read_excel('final_rankings_with_details_Q1.xlsx')
print(f'Total rows: {len(df)}')

cache = {}
for _, row in df.iterrows():
    code = str(row.get('代码','')).zfill(6)
    if not code or len(code) != 6:
        continue
    
    entry = {}
    
    # 净利同比增长
    jl = row.get('净利同比增长')
    if pd.notna(jl) and str(jl) != '-':
        try:
            entry['jl_growth_pct'] = round(float(str(jl).replace('%','')), 2)
        except:
            pass
    
    # 总市值
    mcap = row.get('总市值')
    if pd.notna(mcap) and str(mcap) != '-':
        try:
            s = str(mcap).lower()
            if '亿' in s:
                entry['mcap_yi'] = float(s.replace('亿','').strip())
            elif '万' in s:
                entry['mcap_yi'] = float(s.replace('万','').strip()) / 10000
        except:
            pass
    
    if entry:
        cache[code] = entry

with open('stock_fundamentals_cache.json', 'w', encoding='utf-8') as f:
    json.dump(cache, f, ensure_ascii=False, indent=2)

print('Cached:', len(cache), 'stocks')
jl_vals = [v['jl_growth_pct'] for v in cache.values() if 'jl_growth_pct' in v]
mc_vals = [v['mcap_yi'] for v in cache.values() if 'mcap_yi' in v]
if jl_vals:
    pos = sum(1 for v in jl_vals if v > 0)
    print(f'  Jil: pos={pos}/{len(jl_vals)} ({pos/len(jl_vals)*100:.1f}%)')
if mc_vals:
    mc_sorted = sorted(mc_vals)
    print(f'  Mkap: median={mc_sorted[len(mc_sorted)//2]:.1f} yi')
