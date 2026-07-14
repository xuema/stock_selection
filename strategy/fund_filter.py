"""
基本面过滤工具 — 供 strategy/ 下所有选股脚本共用。

从 stock_fundamentals_cache.json (Q1 数据) 读取：
  - mcap_yi: 总市值（亿元）
  - jl_growth_pct: 净利同比增长（%）

用法:
    from fund_filter import _check_fund, _load_fundamentals

    # 过滤: 流通市值>=50亿 且 净利同比增长>0
    if not _check_fund(ticker, min_mcap_yi=50, min_jl_growth=0):
        return ticker, False, {}

命令行:
    python fund_filter.py 000155 300502 601600
    python fund_filter.py --stats
"""
import os, sys, json

_FUND_CACHE = {}

def _cache_path():
    """定位 stock_fundamentals_cache.json"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     os.pardir, "stock_fundamentals_cache.json")
    return os.path.normpath(p)

def _load_fundamentals():
    global _FUND_CACHE
    if _FUND_CACHE:
        return _FUND_CACHE
    cp = _cache_path()
    if os.path.exists(cp):
        try:
            with open(cp) as f:
                _FUND_CACHE = json.load(f)
            print(f"  [fund] 加载 {_cache_path()} ({len(_FUND_CACHE)}只)", file=sys.stderr)
        except Exception as e:
            print(f"  [fund] 加载失败: {e}", file=sys.stderr)
    return _FUND_CACHE

def _check_fund(ticker, min_mcap_yi=50, min_jl_growth=0):
    """
    基本面过滤。
    返回 True=通过, False=不通过。
    缓存不存在或股票不在缓存中时，返回 True（不拦住）。
    """
    if not _FUND_CACHE:
        _load_fundamentals()
    if not _FUND_CACHE:
        return True
    d = _FUND_CACHE.get(ticker)
    if not d:
        return True  # 无缓存数据不拦
    if min_mcap_yi is not None and d.get("mcap_yi") is not None and d["mcap_yi"] < min_mcap_yi:
        return False
    if min_jl_growth is not None and d.get("jl_growth_pct") is not None and d["jl_growth_pct"] <= min_jl_growth:
        return False
    return True

def _fund_info(ticker):
    """返回某股票的基本面信息"""
    if not _FUND_CACHE:
        _load_fundamentals()
    return _FUND_CACHE.get(ticker)

if __name__ == "__main__":
    if "--stats" in sys.argv:
        _load_fundamentals()
        mc = [v["mcap_yi"] for v in _FUND_CACHE.values() if "mcap_yi" in v]
        jl = [v["jl_growth_pct"] for v in _FUND_CACHE.values() if "jl_growth_pct" in v]
        pos = sum(1 for v in jl if v > 0)
        print(f"总计: {len(_FUND_CACHE)} 只")
        print(f"净利正增长: {pos}/{len(jl)} ({pos/len(jl)*100:.1f}%)")
        if mc:
            ms = sorted(mc)
            print(f"市值中位: {ms[len(ms)//2]:.1f}亿")
    elif len(sys.argv) > 1:
        for code in sys.argv[1:]:
            d = _fund_info(code)
            if d:
                print(f"{code}: 市值={d.get('mcap_yi','N/A')}亿 净利增长={d.get('jl_growth_pct','N/A')}%")
            else:
                print(f"{code}: 无数据")
    else:
        print("用法: python fund_filter.py <code1> <code2>... 或 --stats")
