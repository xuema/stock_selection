#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 客户端: 自动在"直连"与"环境代理"之间选可用通道。

背景: 本机在 Qoder 会话里会注入 HTTP(S)_PROXY。
  - datacenter-web.eastmoney.com 走代理可用
  - money.finance.sina.com.cn / push2his.eastmoney.com 必须直连 (代理会 000/ProxyError)
所以每个 host 第一次请求时探测一次可用通道并缓存。
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_MODE: dict[str, str] = {}   # host -> "direct" | "proxy"

def _session(mode: str) -> requests.Session:
    s = requests.Session()
    if mode == "direct":
        s.trust_env = False
        s.proxies = {"http": None, "https": None}
    else:
        s.trust_env = True
    r = Retry(total=2, backoff_factor=0.4, status_forcelist=(500, 502, 503, 504))
    s.mount("http://", HTTPAdapter(max_retries=r, pool_maxsize=32))
    s.mount("https://", HTTPAdapter(max_retries=r, pool_maxsize=32))
    return s

def headers(referer: str | None = None) -> dict:
    h = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
    if referer:
        h["Referer"] = referer
    return h

def get(url: str, params=None, referer=None, timeout=25, as_json=True):
    """返回 json (as_json=True) 或 text。失败抛异常。"""
    host = url.split("/")[2]
    order = ["direct", "proxy"] if _MODE.get(host) != "proxy" else ["proxy", "direct"]
    if _MODE.get(host) == "direct":
        order = ["direct"]
    last = None
    for mode in order:
        try:
            r = _session(mode).get(url, params=params, headers=headers(referer), timeout=timeout)
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            _MODE[host] = mode
            return r.json() if as_json else r.text
        except Exception as e:                                  # noqa: BLE001
            last = e
            continue
    raise RuntimeError(f"{host} unreachable: {last}")
