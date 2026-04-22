"""
实时主力资金流向数据（东财接口）

通过东方财富 pushlanfu API 获取个股实时资金流向数据：
超大单/大单/中单/小单 流入流出，主力净额等。
作为龙虎榜/大宗交易策略的补充信号源。
"""

import logging
from typing import Optional, Tuple, Dict

import requests

logger = logging.getLogger(__name__)

_FLOW_CACHE: Dict[str, dict] = {}


def _code_to_secid(symbol: str) -> str:
    code = symbol[-6:] if len(symbol) >= 6 else symbol.zfill(6)
    if code.startswith("6"):
        return f"1.{code}"
    return f"0.{code}"


def fetch_realtime_fund_flow(symbol: str, timeout: int = 10) -> Optional[dict]:
    """
    获取个股实时资金流向数据。

    Returns dict with keys:
        main_net: 主力净额（元）
        super_large_net: 超大单净额
        large_net: 大单净额
        mid_net: 中单净额
        small_net: 小单净额
    """
    cached = _FLOW_CACHE.get(symbol)
    if cached is not None:
        return cached

    result = _fetch_flow_via_detail(symbol, timeout)
    if result is not None:
        return result

    return _fetch_flow_via_kline(symbol, timeout)


def _fetch_flow_via_kline(symbol: str, timeout: int = 10) -> Optional[dict]:
    """通过东财资金流向K线接口获取。格式: date,主力净额,小单净额,中单净额,大单净额,超大单净额"""
    secid = _code_to_secid(symbol)
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "lmt": "1",
        "klt": "101",
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
    }
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        if r.status_code != 200:
            logger.debug("realtime_flow_kline %s HTTP %d", symbol, r.status_code)
            return None
        data = r.json()
        klines = (data.get("data") or {}).get("klines") or []
        if not klines:
            return None
        line = klines[-1]
        parts = line.split(",")
        if len(parts) < 6:
            return None
        result = {
            "main_net": float(parts[1]),
            "small_net": float(parts[2]),
            "mid_net": float(parts[3]),
            "large_net": float(parts[4]),
            "super_large_net": float(parts[5]),
        }
        _FLOW_CACHE[symbol] = result
        return result
    except Exception as e:
        logger.debug("realtime_flow_kline %s 失败: %s", symbol, e)
        return None


def _fetch_flow_via_detail(symbol: str, timeout: int = 10) -> Optional[dict]:
    """备用接口：通过东财个股资金流向详情获取。"""
    secid = _code_to_secid(symbol)
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "fltt": "2",
        "invt": "2",
        "fields": "f12,f14,f62,f66,f69,f72,f75,f78,f81,f84,f87,f124,f164,f174,f184",
        "secids": secid,
    }
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
        diff = (data.get("data") or {}).get("diff") or []
        if not diff:
            return None
        row = diff[0]
        result = {
            "main_net": float(row.get("f62", 0) or 0),
            "super_large_net": float(row.get("f66", 0) or 0),
            "large_net": float(row.get("f72", 0) or 0),
            "mid_net": float(row.get("f78", 0) or 0),
            "small_net": float(row.get("f84", 0) or 0),
        }
        _FLOW_CACHE[symbol] = result
        return result
    except Exception as e:
        logger.debug("realtime_flow_detail %s 失败: %s", symbol, e)
        return None


def get_realtime_flow_signal(symbol: str) -> Optional[Tuple[str, float, float]]:
    """
    基于实时主力资金流向生成交易信号。

    规则：
    - 主力净流入 > 5000万且超大单净流入>0 → BUY, 置信度=min(净额/2亿, 0.7)
    - 主力净流出 < -5000万且超大单净流出<0 → SELL, 置信度=min(|净额|/2亿, 0.6)
    """
    flow = fetch_realtime_fund_flow(symbol)
    if flow is None:
        return None

    main_net = flow.get("main_net", 0)
    super_net = flow.get("super_large_net", 0)

    BUY_THRESHOLD = 5e7
    SELL_THRESHOLD = -5e7
    SCALE = 2e8

    if main_net > BUY_THRESHOLD and super_net > 0:
        conf = min(abs(main_net) / SCALE, 0.7)
        return ("BUY", round(conf, 2), 0.65)

    if main_net < SELL_THRESHOLD and super_net < 0:
        conf = min(abs(main_net) / SCALE, 0.6)
        return ("SELL", round(conf, 2), 0.3)

    return None
