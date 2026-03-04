"""
政策相关新闻获取与情感聚合

主 政府官网（简单版）；备 东方财富关键词；备1 财联社；备2 同花顺。文档 1.4。
"""

import json
import os
import re
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# 搜索政策新闻用的关键词（东方财富搜索）
POLICY_SEARCH_KEYWORDS = "政策 降准 减税 央行 宏观"


def _fetch_policy_via_gov(max_items: int = 20) -> pd.DataFrame:
    """
    文档 1.4 主：政府官网政策/要闻列表（简单版）。中国政府网、发改委等，requests + BeautifulSoup。
    遵守 robots.txt、控制频率；失败返回空。
    """
    try:
        import requests
        from bs4 import BeautifulSoup
        from datetime import datetime
        out = []
        # 中国政府网 最新政策/国务院 列表页（示例）
        for url in [
            "https://www.gov.cn/pushinfo/list.htm",
            "https://www.gov.cn/xinwen/list.htm",
        ]:
            try:
                r = requests.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; PolicyBot/1.0)"},
                    timeout=12,
                )
                if r.status_code != 200 or not r.text:
                    continue
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.select("a[href*='/content/'], a[href*='gov.cn']")[:max_items]:
                    title = (a.get_text(strip=True) or "").strip()
                    if len(title) < 4 or "政策" not in title and "国务院" not in title and "宏观" not in title:
                        continue
                    href = a.get("href", "")
                    if not href.startswith("http"):
                        href = "https://www.gov.cn" + (href if href.startswith("/") else "/" + href)
                    out.append({
                        "title": title[:200],
                        "content": "",
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "source": "政府网",
                    })
                    if len(out) >= max_items:
                        break
            except Exception as e:
                logger.debug("政府网政策页 %s 解析失败: %s", url, e)
            if len(out) >= max_items:
                break
        return pd.DataFrame(out[:max_items]) if out else pd.DataFrame()
    except Exception as e:
        logger.debug("政府官网政策获取失败: %s", e)
        return pd.DataFrame()


def _fetch_policy_news_requests(max_items: int = 20) -> pd.DataFrame:
    """请求东方财富搜索 API，keyword 为政策相关。"""
    try:
        import requests
        from datetime import datetime
        url = "https://search-api-web.eastmoney.com/search/jsonp"
        page_size = max(min(max_items, 50), 5)
        inner = {
            "uid": "",
            "keyword": POLICY_SEARCH_KEYWORDS,
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
        m = re.search(r"\((.+)\)\s*$", text, re.DOTALL)
        if not m:
            return pd.DataFrame()
        data = json.loads(m.group(1))
        rows = data.get("result", {}).get("cmsArticleWebOld")
        if not rows:
            return pd.DataFrame()
        out = []
        for row in rows[:max_items]:
            title = (row.get("title") or "").replace("<em>", "").replace("</em>", "")
            content = (row.get("content") or "").replace("<em>", "").replace("</em>", "").replace("\u3000", " ").replace("\r\n", " ")
            out.append({"title": title, "content": content, "date": row.get("date"), "source": row.get("mediaName")})
        return pd.DataFrame(out)
    except Exception as e:
        logger.debug("政策新闻请求失败: %s", e)
        return pd.DataFrame()


def _fetch_policy_via_cls(max_items: int = 20) -> pd.DataFrame:
    """文档 1.4 备1：财联社 policy 分类，需 CLS_API_KEY。"""
    api_key = os.environ.get("CLS_API_KEY", "").strip()
    if not api_key:
        return pd.DataFrame()
    try:
        import requests
        url = "https://api.cls.cn/v1/information/list"
        payload = {"category": "policy", "page": 1, "page_size": min(max_items, 50)}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        if r.status_code != 200:
            return pd.DataFrame()
        data = r.json()
        items = data.get("data", {}).get("list", []) or data.get("list", [])
        if not items:
            return pd.DataFrame()
        out = [{"title": row.get("title", ""), "content": row.get("content", row.get("summary", "")), "date": row.get("date", row.get("publish_time", "")), "source": row.get("source", "财联社")} for row in items[:max_items]]
        return pd.DataFrame(out)
    except Exception as e:
        logger.debug("财联社政策新闻失败: %s", e)
        return pd.DataFrame()


def _fetch_policy_via_10jqka(max_items: int = 20) -> pd.DataFrame:
    """文档 1.4 备2：同花顺政策，GET，type=1/2/3 国家/部委/地方，需 10JQKA_COOKIE。"""
    cookie = os.environ.get("10JQKA_COOKIE", "").strip()
    if not cookie:
        return pd.DataFrame()
    try:
        import requests
        from bs4 import BeautifulSoup
        url = "https://data.10jqka.com.cn/policy/"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Cookie": cookie}
        r = requests.get(url, params={"type": "1"}, headers=headers, timeout=15)
        if r.status_code != 200:
            return pd.DataFrame()
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for node in soup.select("a[href*='policy'], .list-item, .news-item")[:max_items]:
            title = node.get_text(strip=True) if hasattr(node, "get_text") else (node.text or "").strip()
            if not title or len(title) < 2:
                continue
            out.append({"title": title, "content": "", "date": "", "source": "同花顺"})
        return pd.DataFrame(out) if out else pd.DataFrame()
    except Exception as e:
        logger.debug("同花顺政策新闻失败: %s", e)
        return pd.DataFrame()


def fetch_policy_news(max_items: int = 20) -> pd.DataFrame:
    """
    获取近期政策相关新闻。回测时若 BACKTEST_PREFETCH_DIR 且存在 {DIR}/policy.parquet 则读本地（文档 2.3）。
    """
    prefetch_dir = os.environ.get("BACKTEST_PREFETCH_DIR", "").strip()
    if prefetch_dir:
        path = os.path.join(prefetch_dir, "policy.parquet")
        if os.path.isfile(path):
            try:
                return pd.read_parquet(path).head(max_items)
            except Exception as e:
                logger.debug("回测预取政策读本地失败: %s", e)
    df = _fetch_policy_via_gov(max_items)
    if df is None or df.empty:
        df = _fetch_policy_news_requests(max_items)
    if df is None or df.empty:
        df = _fetch_policy_via_cls(max_items)
    if df is None or df.empty:
        df = _fetch_policy_via_10jqka(max_items)
    return df if df is not None else pd.DataFrame()


def get_policy_sentiment(max_news: int = 15) -> Optional[float]:
    """
    获取近期政策面情感聚合值（-1～1）。

    取最近 max_news 条政策新闻，用关键词打分后加权平均。
    无数据返回 None。
    """
    v = get_policy_sentiment_v33(max_news)
    return v[0] if v else None


def get_policy_sentiment_v33(max_news: int = 15) -> Optional[tuple]:
    """
    V3.3：政策情感 + 是否出现重大利空 + 加权平均影响力。

    Returns
    -------
    (agg_score, has_major_negative, avg_influence) 或 None
        agg_score 在 [-1, 1]；has_major_negative 为 True 表示某条新闻影响力≥1.0 且命中重大利空关键词；
        avg_influence 为用于置信度计算的影响力均值。
    """
    try:
        from .policy_keywords import score_policy_text, has_major_negative
        from .policy_overrides import get_policy_override, policy_id_from_row, score_from_override, influence_from_override
    except ImportError:
        from src.data.policy.policy_keywords import score_policy_text, has_major_negative
        from src.data.policy.policy_overrides import get_policy_override, policy_id_from_row, score_from_override, influence_from_override
    df = fetch_policy_news(max_items=max_news)
    if df is None or df.empty:
        return None
    scores = []
    influences = []
    major_neg = False
    for _, row in df.iterrows():
        text = str(row.get("title", "")) + " " + str(row.get("content", ""))
        pid = policy_id_from_row(str(row.get("date", "")), str(row.get("title", "")))
        ov = get_policy_override(pid)
        if ov is not None:
            s = score_from_override(ov)
            inf = influence_from_override(ov)
        else:
            s, inf = score_policy_text(text)
        scores.append(s)
        influences.append(inf)
        if inf >= 1.0:
            if ov is not None and "利空" in str(ov.get("direction", "")):
                major_neg = True
            elif ov is None and has_major_negative(text):
                major_neg = True
    if not scores:
        return None
    total_w = sum(influences)
    if total_w <= 0:
        total_w = 1.0
    agg = sum(s * w for s, w in zip(scores, influences)) / total_w
    agg = max(-1.0, min(1.0, agg))
    avg_inf = sum(influences) / len(influences)
    return (agg, major_neg, avg_inf)
