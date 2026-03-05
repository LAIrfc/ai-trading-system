"""
个股新闻获取

主 akshare.stock_news_em；备1 东方财富搜索 API；备2 财联社（需 CLS_API_KEY）；备3 同花顺（需 10JQKA_COOKIE）。
与 docs/data/API_INTERFACES_AND_FETCHERS.md 1.3.1 一致。
"""

import json
import os
import re
import logging
import time
from typing import List, Optional
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

NEWS_REQUEST_TIMEOUT = 15
NEWS_RETRY_DELAY = 2
NEWS_MAX_RETRIES = 2


def _fetch_via_akshare(symbol: str, max_items: int = 20) -> Optional[pd.DataFrame]:
    """通过 akshare 获取个股新闻，失败返回 None。支持重试与多种 symbol 格式。"""
    import akshare as ak
    # 尝试格式：先 6 位代码，再带市场前缀（部分环境需要）
    to_try = [symbol]
    if len(symbol) == 6 and symbol.isdigit():
        if symbol.startswith(("6", "5")):
            to_try.append("sh" + symbol)
        else:
            to_try.append("sz" + symbol)
    for sym in to_try:
        for attempt in range(NEWS_MAX_RETRIES + 1):
            try:
                df = ak.stock_news_em(symbol=sym)
                if df is None or df.empty:
                    break
                col_map = {"新闻标题": "title", "新闻内容": "content", "发布时间": "date", "文章来源": "source"}
                df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
                for c in ["title", "content", "date", "source"]:
                    if c not in df.columns:
                        break
                else:
                    return df.head(max_items)
                break  # 列不全，尝试下一 symbol 格式
            except Exception as e:
                logger.debug("akshare 个股新闻 %s 第 %d 次失败: %s", sym, attempt + 1, e)
                if attempt < NEWS_MAX_RETRIES:
                    time.sleep(NEWS_RETRY_DELAY)
    return None


def _parse_eastmoney_jsonp(text: str):
    """解析东方财富 JSONP 响应，返回解析后的 dict 或 None。"""
    text = (text or "").strip()
    if not text:
        return None
    # 兼容 cb(...) 或 jQueryxxx(...)：取第一个 ( 到最后一个 ) 之间的内容
    start = text.find("(")
    end = text.rfind(")")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start + 1 : end])
    except json.JSONDecodeError:
        return None


def _eastmoney_search_to_df(rows: list, max_items: int) -> Optional[pd.DataFrame]:
    """将东方财富 cmsArticleWebOld 列表转为标准 DataFrame。"""
    if not rows:
        return None
    out = []
    for row in rows[:max_items]:
        title = (row.get("title") or "").replace("<em>", "").replace("</em>", "")
        content = (row.get("content") or "").replace("<em>", "").replace("</em>", "").replace("\u3000", " ").replace("\r\n", " ")
        out.append({
            "title": title,
            "content": content,
            "date": row.get("date"),
            "source": row.get("mediaName"),
        })
    return pd.DataFrame(out)


def _fetch_via_curl_cffi(symbol: str, max_items: int = 20) -> Optional[pd.DataFrame]:
    """通过 curl_cffi 请求东方财富搜索 API（与 akshare 一致，利于过反爬）。"""
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return None
    try:
        url = "https://search-api-web.eastmoney.com/search/jsonp"
        page_size = max(min(max_items, 50), 5)
        inner = {
            "uid": "",
            "keyword": symbol,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": page_size,
                    "preTag": "<em>",
                    "postTag": "</em>",
                }
            },
        }
        ts = int(datetime.now().timestamp() * 1000)
        params = {
            "cb": f"jQuery{ts}_{ts}",
            "param": json.dumps(inner, ensure_ascii=False),
            "_": str(ts),
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
            "Referer": "https://so.eastmoney.com/news/s?keyword=" + symbol,
            "Accept": "*/*",
        }
        r = curl_requests.get(
            url, params=params, headers=headers, timeout=NEWS_REQUEST_TIMEOUT, impersonate="chrome"
        )
        data = _parse_eastmoney_jsonp(r.text)
        if not data:
            return None
        rows = data.get("result", {}).get("cmsArticleWebOld")
        return _eastmoney_search_to_df(rows, max_items)
    except Exception as e:
        logger.debug("curl_cffi 个股新闻失败: %s", e)
        return None


def _fetch_via_requests(symbol: str, max_items: int = 20) -> Optional[pd.DataFrame]:
    """通过 requests 请求东方财富搜索 API，解析 JSONP。"""
    try:
        import requests
        url = "https://search-api-web.eastmoney.com/search/jsonp"
        page_size = max(min(max_items, 50), 5)
        inner = {
            "uid": "",
            "keyword": symbol,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": page_size,
                    "preTag": "<em>",
                    "postTag": "</em>",
                }
            },
        }
        ts = int(datetime.now().timestamp() * 1000)
        params = {
            "cb": f"jQuery{ts}_{ts}",
            "param": json.dumps(inner, ensure_ascii=False),
            "_": str(ts),
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://so.eastmoney.com/",
        }
        r = requests.get(url, params=params, headers=headers, timeout=NEWS_REQUEST_TIMEOUT)
        data = _parse_eastmoney_jsonp(r.text)
        if not data:
            return None
        rows = data.get("result", {}).get("cmsArticleWebOld")
        return _eastmoney_search_to_df(rows, max_items)
    except Exception as e:
        logger.debug("requests 个股新闻失败: %s", e)
        return None


def _fetch_via_push2_ulist(symbol: str, max_items: int = 20) -> Optional[pd.DataFrame]:
    """东方财富 push2 ulist.np 个股新闻，不依赖搜索反爬。"""
    try:
        import requests
        code = symbol.lstrip("shsz").strip() if isinstance(symbol, str) else str(symbol)
        secid = f"1.{code}" if code.startswith(("5", "6")) else f"0.{code}"
        url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
        params = {
            "secid": secid,
            "pn": "1",
            "pz": str(max(min(max_items, 50), 5)),
            "fields": "f1,f2,f3,f12,f13,f14,f15,f16",
        }
        r = requests.get(
            url,
            params=params,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Referer": "https://quote.eastmoney.com/"},
            timeout=NEWS_REQUEST_TIMEOUT,
        )
        data = r.json() if r.text else None
        if not data or "data" not in data:
            return None
        d = data.get("data")
        if not d or "diff" not in d:
            return None
        diff = d.get("diff") or []
        if not diff:
            return None
        out = []
        for row in diff[:max_items]:
            # f14 多为标题，f13 多为时间，f2/f3 可能为摘要/链接等
            title = str(row.get("f14") or row.get("f15") or "").strip()
            if not title:
                continue
            ts = row.get("f13")
            if ts and isinstance(ts, (int, float)):
                try:
                    date_str = datetime.fromtimestamp(ts / 1000.0).strftime("%Y-%m-%d %H:%M:%S") if ts > 1e12 else str(ts)
                except Exception:
                    date_str = str(ts)
            else:
                date_str = str(ts) if ts else ""
            out.append({
                "title": title[:500],
                "content": str(row.get("f2") or row.get("f3") or ""),
                "date": date_str,
                "source": "东方财富",
            })
        return pd.DataFrame(out) if out else None
    except Exception as e:
        logger.debug("push2 ulist 个股新闻失败: %s", e)
        return None


def _fetch_via_cls(symbol: str, max_items: int = 20) -> Optional[pd.DataFrame]:
    """
    文档 1.3.1 主：财联社 api.cls.cn，POST，需 APIKey。
    环境变量 CLS_API_KEY 存在时启用；返回 title, content, date, source。
    """
    api_key = os.environ.get("CLS_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        import requests
        url = "https://api.cls.cn/v1/information/list"
        payload = {"keyword": symbol, "type": "news", "page": 1, "page_size": min(max_items, 50)}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        items = data.get("data", {}).get("list", []) or data.get("list", [])
        if not items:
            return None
        out = []
        for row in items[:max_items]:
            out.append({
                "title": row.get("title", ""),
                "content": row.get("content", row.get("summary", "")),
                "date": row.get("date", row.get("publish_time", "")),
                "source": row.get("source", "财联社"),
            })
        return pd.DataFrame(out)
    except Exception as e:
        logger.debug("财联社个股新闻失败: %s", e)
        return None


def _fetch_via_10jqka(symbol: str, max_items: int = 20) -> Optional[pd.DataFrame]:
    """
    文档 1.3.1 备1：同花顺 get_news_list，GET，需 cookie。
    环境变量 10JQKA_COOKIE 存在时启用；code 为 6 位股票代码。
    """
    cookie = os.environ.get("10JQKA_COOKIE", "").strip()
    if not cookie:
        return None
    try:
        import requests
        code = symbol[-6:] if len(symbol) >= 6 else symbol.zfill(6)
        url = "https://news.10jqka.com.cn/tapp/news/get_news_list"
        params = {"code": code, "page": 1, "size": min(max_items, 50), "type": "0"}
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Cookie": cookie}
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        items = data.get("data", {}).get("list", []) or data.get("list", [])
        if not items:
            return None
        out = []
        for row in items[:max_items]:
            out.append({
                "title": row.get("title", row.get("name", "")),
                "content": row.get("content", row.get("digest", "")),
                "date": row.get("date", row.get("time", "")),
                "source": row.get("source", "同花顺"),
            })
        return pd.DataFrame(out)
    except Exception as e:
        logger.debug("同花顺个股新闻失败: %s", e)
        return None


def fetch_stock_news(symbol: str, max_items: int = 20) -> pd.DataFrame:
    """
    获取个股最近新闻。回测时若设置 BACKTEST_PREFETCH_DIR 且存在 {DIR}/news/{symbol}.parquet 则直接读本地（文档 2.3）。

    Parameters
    ----------
    symbol : str
        股票代码，如 "000001", "600519"
    max_items : int
        最多返回条数

    Returns
    -------
    pd.DataFrame
        列: title, content, date, source；无数据时返回空 DataFrame。
    """
    prefetch_dir = os.environ.get("BACKTEST_PREFETCH_DIR", "").strip()
    if prefetch_dir:
        path = os.path.join(prefetch_dir, "news", f"{symbol}.parquet")
        if os.path.isfile(path):
            try:
                return pd.read_parquet(path).head(max_items)
            except Exception as e:
                logger.debug("回测预取新闻 %s 读本地失败: %s", symbol, e)
    # 优先 curl_cffi（与 akshare 一致，易过反爬），再 akshare、requests、push2、财联社、同花顺
    df = _fetch_via_curl_cffi(symbol, max_items)
    if df is None or df.empty:
        df = _fetch_via_akshare(symbol, max_items)
    if df is None or df.empty:
        df = _fetch_via_requests(symbol, max_items)
        if df is None or df.empty:
            for _ in range(NEWS_MAX_RETRIES):
                time.sleep(NEWS_RETRY_DELAY)
                df = _fetch_via_requests(symbol, max_items)
                if df is not None and not df.empty:
                    break
    if df is None or df.empty:
        df = _fetch_via_push2_ulist(symbol, max_items)
    if df is None or df.empty:
        df = _fetch_via_cls(symbol, max_items)
    if df is None or df.empty:
        df = _fetch_via_10jqka(symbol, max_items)
    if df is None or df.empty:
        logger.info(
            "个股新闻全部源均无数据或失败（主 akshare/东方财富，备 财联社/同花顺 需 CLS_API_KEY、10JQKA_COOKIE）symbol=%s",
            symbol,
        )
        return pd.DataFrame()
    return df
