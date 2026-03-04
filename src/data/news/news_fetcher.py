"""
个股新闻获取

主 akshare.stock_news_em；备1 东方财富搜索 API；备2 财联社（需 CLS_API_KEY）；备3 同花顺（需 10JQKA_COOKIE）。
与 docs/data/API_INTERFACES_AND_FETCHERS.md 1.3.1 一致。
"""

import json
import os
import re
import logging
from typing import List, Optional
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)


def _fetch_via_akshare(symbol: str, max_items: int = 20) -> Optional[pd.DataFrame]:
    """通过 akshare 获取个股新闻，失败返回 None。"""
    try:
        import akshare as ak
        df = ak.stock_news_em(symbol=symbol)
        if df is None or df.empty:
            return None
        # 统一列名
        df = df.rename(columns={
            "新闻标题": "title",
            "新闻内容": "content",
            "发布时间": "date",
            "文章来源": "source",
        })
        for c in ["title", "content", "date", "source"]:
            if c not in df.columns:
                return None
        return df.head(max_items)
    except Exception as e:
        logger.debug("akshare 个股新闻失败: %s", e)
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
        params = {
            "param": json.dumps(inner, ensure_ascii=False),
            "_": str(int(datetime.now().timestamp() * 1000)),
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://so.eastmoney.com/",
        }
        r = requests.get(url, params=params, headers=headers, timeout=10)
        text = r.text.strip()
        # 去掉 JSONP 外壳：可能为 cb(...) 或 (...)
        m = re.search(r"\((.+)\)\s*$", text, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group(1))
        rows = data.get("result", {}).get("cmsArticleWebOld")
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
    except Exception as e:
        logger.debug("requests 个股新闻失败: %s", e)
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
    df = _fetch_via_akshare(symbol, max_items)
    if df is None or df.empty:
        df = _fetch_via_requests(symbol, max_items)
    if df is None or df.empty:
        df = _fetch_via_cls(symbol, max_items)
    if df is None or df.empty:
        df = _fetch_via_10jqka(symbol, max_items)
    if df is None:
        return pd.DataFrame()
    return df
