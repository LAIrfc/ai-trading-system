"""
消息面 V3.3+：24h 同向 N、S_news、新闻源权重 + LLM 语义融合

供 NewsSentimentStrategy 调用：
- 关键词规则打分（快速、零成本、可回测）
- LLM 语义分析（实盘增强，关键词 0.4 + LLM 0.6 融合）
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import pandas as pd

from . import fetch_stock_news, score_news_sentiment, dedup_news, filter_future_time, get_source_weight

logger = logging.getLogger(__name__)

# LLM 分析的系统提示
_LLM_NEWS_SYSTEM = (
    "你是专业的A股个股消息面分析师。"
    "请基于给出的个股相关新闻标题，判断这些消息对该股票的影响。"
    "只输出 JSON，不要任何其他文字。"
)

_LLM_NEWS_PROMPT_TMPL = """以下是{name}({symbol})的最新相关新闻标题（共{n}条）：

{titles}

请分析这些新闻对该股票的影响，输出以下 JSON：
{{
  "score": <-1.0到1.0的浮点数，-1极度利空，0中性，1极度利好>,
  "direction": "<利好|利空|中性>",
  "key_events": ["<事件1>", "<事件2>"],
  "reason": "<50字以内的简要说明>"
}}"""


def _llm_score_stock_news(
    symbol: str,
    news_titles: List[str],
    stock_name: str = "",
) -> Optional[dict]:
    """
    用 LLM 对个股新闻标题列表做语义情感分析。

    Parameters
    ----------
    symbol : str
        股票代码
    news_titles : list of str
        新闻标题列表（最多 15 条）
    stock_name : str
        股票名称（可选，提升 LLM 理解准确度）

    Returns
    -------
    dict with keys: score, direction, key_events, reason
    或 None（LLM 不可用或解析失败）
    """
    if not news_titles:
        return None

    try:
        from src.data.ai_analyst import call_llm
    except ImportError:
        try:
            import sys
            import os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
            from src.data.ai_analyst import call_llm
        except ImportError:
            logger.debug("ai_analyst 模块不可用，跳过 LLM 新闻分析")
            return None

    titles = news_titles[:15]
    titles_text = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    name = stock_name or symbol
    prompt = _LLM_NEWS_PROMPT_TMPL.format(
        name=name, symbol=symbol, n=len(titles), titles=titles_text
    )

    try:
        result = call_llm(
            prompt=prompt,
            system_prompt=_LLM_NEWS_SYSTEM,
            max_tokens=200,
            temperature=0.1,
        )
        if not result:
            return None

        m = re.search(r'\{.*\}', result, re.DOTALL)
        if not m:
            logger.debug("LLM 新闻分析返回格式异常 %s: %s", symbol, result[:200])
            return None

        data = json.loads(m.group())
        score = float(data.get("score", 0))
        score = max(-1.0, min(1.0, score))
        return {
            "score": score,
            "direction": data.get("direction", "中性"),
            "key_events": data.get("key_events", []),
            "reason": data.get("reason", ""),
        }
    except Exception as e:
        logger.debug("LLM 新闻分析解析失败 %s: %s", symbol, e)
        return None


def get_news_sentiment_v33(
    symbol: str,
    ref_time: Optional[datetime] = None,
    lookback_hours: int = 24,
    max_same_direction: int = 3,
    buy_threshold: float = 0.3,
    sell_threshold: float = -0.3,
    max_items: int = 30,
    use_llm: bool = True,
    stock_name: str = "",
) -> Optional[Tuple[float, int, float]]:
    """
    24h 内同向新闻最多 N 篇的加权平均 S_news，及平均新闻源权重。

    升级：实盘时融合 LLM 语义分析（关键词 0.4 + LLM 0.6）。
    回测时设 use_llm=False 退化为纯关键词，避免未来函数和 API 费用。

    Parameters
    ----------
    symbol : str
        股票代码
    use_llm : bool
        是否启用 LLM 融合（实盘 True，回测 False）
    stock_name : str
        股票名称，提升 LLM 分析准确度

    Returns
    -------
    (S_news, N, mean_source_weight) 或 None
        S_news 为情感分 [-1, 1]；N 为同向篇数；mean_source_weight 用于置信度。
    """
    try:
        df = fetch_stock_news(symbol, max_items=max_items)
        if df is None or df.empty:
            return None

        ref = ref_time or datetime.now()
        df = filter_future_time(df, ref_time=ref)
        df = dedup_news(df, symbol=symbol, title_similarity_threshold=0.85)
        if df.empty:
            return None

        # 关键词打分
        scores = score_news_sentiment(df)
        df = df.copy()
        df["sentiment"] = scores
        df["source_weight"] = df.get("source", pd.Series(dtype=object)).map(
            lambda x: get_source_weight(str(x) if pd.notna(x) else "")
        )

        # 24h 窗口过滤
        if "date" in df.columns:
            parsed = pd.to_datetime(df["date"], errors="coerce")
            df["_pt"] = parsed
            df = df.dropna(subset=["_pt"])
            cutoff_date = (ref - timedelta(days=1)).date() if hasattr(ref, "date") else ref
            df = df[df["_pt"].dt.date >= cutoff_date].drop(columns=["_pt"], errors="ignore")
        if df.empty:
            return None

        df = df.sort_values("date", ascending=False).reset_index(drop=True)

        # 同向聚合（关键词版）
        sent = df["sentiment"].astype(float)
        pos = sent[sent >= buy_threshold]
        neg = sent[sent <= sell_threshold]
        if len(pos) >= len(neg) and len(pos) > 0:
            same = df[sent >= buy_threshold].head(max_same_direction)
        elif len(neg) > 0:
            same = df[sent <= sell_threshold].head(max_same_direction)
        else:
            same = pd.DataFrame()

        # 关键词加权平均分
        if not same.empty:
            w = same["source_weight"].astype(float)
            s = same["sentiment"].astype(float)
            total_w = w.sum()
            kw_score = float((s * w).sum() / total_w) if total_w > 0 else float(s.mean())
            kw_score = max(-1.0, min(1.0, kw_score))
            N = len(same)
            mean_weight = float(w.mean()) if len(w) else 1.0
        else:
            kw_score = 0.0
            N = 0
            mean_weight = 1.0

        # LLM 语义分析（实盘增强层）
        llm_result = None
        if use_llm:
            titles = df["title"].dropna().tolist()[:15]
            if titles:
                llm_result = _llm_score_stock_news(symbol, titles, stock_name)

        if llm_result is not None:
            llm_score = llm_result["score"]
            final_score = 0.4 * kw_score + 0.6 * llm_score
            final_score = max(-1.0, min(1.0, final_score))
            logger.info(
                "[%s] 新闻情感 [关键词%.2f × LLM%.2f → 融合%.2f] %s 主要事件:%s",
                symbol, kw_score, llm_score, final_score,
                llm_result.get("direction", ""),
                ",".join(llm_result.get("key_events", [])),
            )
            # N 用关键词同向篇数，mean_weight 保持不变
            return (final_score, max(N, 1), mean_weight)

        # LLM 不可用，退化为纯关键词
        if N == 0:
            return None
        logger.debug("[%s] 新闻情感：LLM 不可用，使用纯关键词分数 %.2f (N=%d)", symbol, kw_score, N)
        return (kw_score, N, mean_weight)

    except Exception as e:
        logger.debug("get_news_sentiment_v33 失败 %s: %s", symbol, e)
        return None
