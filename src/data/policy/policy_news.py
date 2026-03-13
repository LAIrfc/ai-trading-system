"""
政策相关新闻获取与情感聚合

主 政府官网（简单版）；备 东方财富关键词；备1 财联社；备2 同花顺。文档 1.4。
"""

import json
import os
import re
import logging
import time
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

POLICY_REQUEST_TIMEOUT = 15
POLICY_RETRY_DELAY = 2
POLICY_MAX_RETRIES = 2

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
            "https://www.gov.cn/yaowen/liebiao/home_5.htm",
            "https://www.gov.cn/zhengce/zuixin/home_2.htm",
        ]:
            try:
                r = requests.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; PolicyBot/1.0)"},
                    timeout=POLICY_REQUEST_TIMEOUT,
                )
                if r.status_code != 200 or not r.text:
                    continue
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.select("a[href*='/content/'], a[href*='gov.cn'], a[href*='yaowen'], a[href*='zhengce']")[:max_items * 2]:
                    title = (a.get_text(strip=True) or "").strip()
                    if len(title) < 4:
                        continue
                    if not any(k in title for k in ("政策", "国务院", "宏观", "要闻", "发布", "通知", "意见", "方案")):
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


def _parse_eastmoney_jsonp(text: str):
    """解析东方财富 JSONP 响应。"""
    text = (text or "").strip()
    if not text:
        return None
    start, end = text.find("("), text.rfind(")")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start + 1 : end])
    except json.JSONDecodeError:
        return None


def _fetch_policy_via_curl_cffi(max_items: int = 20) -> pd.DataFrame:
    """东方财富政策关键词搜索，使用 curl_cffi 过反爬。"""
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return pd.DataFrame()
    try:
        from datetime import datetime as dt
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
        ts = int(dt.now().timestamp() * 1000)
        params = {
            "cb": f"jQuery{ts}_{ts}",
            "param": json.dumps(inner, ensure_ascii=False),
            "_": str(ts),
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
            "Referer": "https://so.eastmoney.com/",
            "Accept": "*/*",
        }
        r = curl_requests.get(url, params=params, headers=headers, timeout=POLICY_REQUEST_TIMEOUT, impersonate="chrome")
        data = _parse_eastmoney_jsonp(r.text)
        if not data:
            return pd.DataFrame()
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
        logger.debug("政策新闻 curl_cffi 失败: %s", e)
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
        r = requests.get(url, params=params, headers=headers, timeout=POLICY_REQUEST_TIMEOUT)
        data = _parse_eastmoney_jsonp(r.text)
        if not data:
            return pd.DataFrame()
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
    # 优先东方财富 curl_cffi（易过反爬），再政府网、东方财富 requests、财联社、同花顺
    df = _fetch_policy_via_curl_cffi(max_items)
    if df is None or df.empty:
        df = _fetch_policy_via_gov(max_items)
        if df is None or df.empty:
            for _ in range(POLICY_MAX_RETRIES):
                time.sleep(POLICY_RETRY_DELAY)
                df = _fetch_policy_via_gov(max_items)
                if df is not None and not df.empty:
                    break
    if df is None or df.empty:
        df = _fetch_policy_news_requests(max_items)
        if df is None or df.empty:
            for _ in range(POLICY_MAX_RETRIES):
                time.sleep(POLICY_RETRY_DELAY)
                df = _fetch_policy_news_requests(max_items)
                if df is not None and not df.empty:
                    break
    if df is None or df.empty:
        df = _fetch_policy_via_cls(max_items)
    if df is None or df.empty:
        df = _fetch_policy_via_10jqka(max_items)
    if df is None or df.empty:
        logger.info(
            "政策面全部源均无数据或失败（主 政府网/东方财富，备 财联社/同花顺 需 CLS_API_KEY、10JQKA_COOKIE）"
        )
    return df if df is not None else pd.DataFrame()


def get_policy_sentiment(max_news: int = 15) -> Optional[float]:
    """
    获取近期政策面情感聚合值（-1～1）。

    取最近 max_news 条政策新闻，用关键词打分后加权平均。
    无数据返回 None。
    """
    v = get_policy_sentiment_v33(max_news)
    return v[0] if v else None


# ============================================================
# LLM 语义情感分析（升级层）
# ============================================================

_LLM_POLICY_SYSTEM = (
    "你是专业的A股政策面分析师。"
    "请基于给出的政策新闻标题列表，判断整体政策面对A股市场的影响。"
    "只输出 JSON，不要任何其他文字。"
)

_LLM_POLICY_PROMPT_TMPL = """以下是今日最新政策/宏观新闻标题（共{n}条）：

{titles}

请分析这些新闻对A股市场的整体政策面影响，输出以下 JSON：
{{
  "score": <-1.0到1.0的浮点数，-1极度利空，0中性，1极度利好>,
  "direction": "<利好|利空|中性>",
  "major_negative": <true或false，是否存在监管加强/反垄断/集采降价/出口管制等重大利空>,
  "key_themes": ["<主题1>", "<主题2>"],
  "reason": "<50字以内的简要说明>"
}}"""


def _llm_score_policy_news(news_titles: list) -> Optional[dict]:
    """
    用 LLM 对政策新闻标题列表做语义情感分析。

    Parameters
    ----------
    news_titles : list of str
        新闻标题列表（最多 20 条）

    Returns
    -------
    dict with keys: score, direction, major_negative, key_themes, reason
    或 None（LLM 不可用或解析失败）
    """
    if not news_titles:
        return None

    try:
        from src.data.ai_analyst import call_llm
    except ImportError:
        try:
            import sys, os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
            from src.data.ai_analyst import call_llm
        except ImportError:
            logger.debug("ai_analyst 模块不可用，跳过 LLM 政策分析")
            return None

    titles_text = "\n".join(f"{i+1}. {t}" for i, t in enumerate(news_titles[:20]))
    prompt = _LLM_POLICY_PROMPT_TMPL.format(n=len(news_titles[:20]), titles=titles_text)

    try:
        result = call_llm(
            prompt=prompt,
            system_prompt=_LLM_POLICY_SYSTEM,
            max_tokens=300,
            temperature=0.1,
        )
        if not result:
            return None

        # 解析 JSON（LLM 可能在 JSON 前后加文字，用正则提取）
        import re
        m = re.search(r'\{.*\}', result, re.DOTALL)
        if not m:
            logger.debug("LLM 政策分析返回格式异常: %s", result[:200])
            return None

        data = json.loads(m.group())
        score = float(data.get("score", 0))
        score = max(-1.0, min(1.0, score))
        return {
            "score": score,
            "direction": data.get("direction", "中性"),
            "major_negative": bool(data.get("major_negative", False)),
            "key_themes": data.get("key_themes", []),
            "reason": data.get("reason", ""),
        }
    except Exception as e:
        logger.debug("LLM 政策分析解析失败: %s", e)
        return None


def get_policy_sentiment_v33(max_news: int = 15, use_llm: bool = True) -> Optional[tuple]:
    """
    V3.3+：政策情感 + 是否出现重大利空 + 加权平均影响力。

    升级：在关键词打分基础上，若 LLM 可用则融合语义分析结果。
    融合权重：关键词分 0.4 + LLM 分 0.6（LLM 不可用时退化为纯关键词）。

    Parameters
    ----------
    max_news : int
        最多获取的新闻条数
    use_llm : bool
        是否尝试调用 LLM（回测时应设为 False）

    Returns
    -------
    (agg_score, has_major_negative, avg_influence) 或 None
        agg_score 在 [-1, 1]；has_major_negative 为 True 表示出现重大利空；
        avg_influence 为影响力均值（用于置信度）。
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

    # ---- 关键词打分（原有逻辑，保留用于回测兼容）----
    scores = []
    influences = []
    major_neg = False
    titles = []

    for _, row in df.iterrows():
        title = str(row.get("title", ""))
        text = title + " " + str(row.get("content", ""))
        if title:
            titles.append(title)
        pid = policy_id_from_row(str(row.get("date", "")), title)
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
    kw_agg = sum(s * w for s, w in zip(scores, influences)) / total_w
    kw_agg = max(-1.0, min(1.0, kw_agg))
    avg_inf = sum(influences) / len(influences)

    # ---- LLM 语义分析（实盘增强层）----
    llm_result = None
    if use_llm and titles:
        llm_result = _llm_score_policy_news(titles)

    if llm_result is not None:
        # 融合：LLM 权重 0.6，关键词权重 0.4
        llm_score = llm_result["score"]
        final_agg = 0.4 * kw_agg + 0.6 * llm_score
        final_agg = max(-1.0, min(1.0, final_agg))

        # LLM 发现重大利空也触发
        if llm_result.get("major_negative"):
            major_neg = True

        logger.info(
            "政策面分析完成 [关键词%.2f × LLM%.2f → 融合%.2f] 方向:%s 主题:%s",
            kw_agg, llm_score, final_agg,
            llm_result.get("direction", ""),
            ",".join(llm_result.get("key_themes", [])),
        )
        return (final_agg, major_neg, avg_inf)

    # LLM 不可用，退化为纯关键词
    logger.debug("政策面分析：LLM 不可用，使用纯关键词分数 %.2f", kw_agg)
    return (kw_agg, major_neg, avg_inf)
