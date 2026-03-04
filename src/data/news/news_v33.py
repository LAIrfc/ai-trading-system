"""
消息面 V3.3：24h 同向 N、S_news、新闻源权重

供 NewsSentimentStrategy 调用：取 24h 内同向最多 3 篇，加权平均得 S_news，并返回 N 与平均新闻源权重。
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pandas as pd

from . import fetch_stock_news, score_news_sentiment, dedup_news, filter_future_time, get_source_weight

logger = logging.getLogger(__name__)


def get_news_sentiment_v33(
    symbol: str,
    ref_time: Optional[datetime] = None,
    lookback_hours: int = 24,
    max_same_direction: int = 3,
    buy_threshold: float = 0.3,
    sell_threshold: float = -0.3,
    max_items: int = 30,
) -> Optional[Tuple[float, int, float]]:
    """
    24h 内同向新闻最多 N 篇的加权平均 S_news，及平均新闻源权重。

    Returns
    -------
    (S_news, N, mean_source_weight) 或 None
        S_news 为同向情感加权平均 [-1, 1]；N 为同向篇数（最多 max_same_direction）；mean_source_weight 用于置信度。
        无有效新闻时返回 None。
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
        scores = score_news_sentiment(df)
        df = df.copy()
        df["sentiment"] = scores
        df["source_weight"] = df.get("source", pd.Series(dtype=object)).map(
            lambda x: get_source_weight(str(x) if pd.notna(x) else "")
        )
        # 24h 窗口：无精确时分时按自然日，取 ref 当日及前一日
        if "date" in df.columns:
            parsed = pd.to_datetime(df["date"], errors="coerce")
            df["_pt"] = parsed
            df = df.dropna(subset=["_pt"])
            cutoff_date = (ref - timedelta(days=1)).date() if hasattr(ref, "date") else ref
            df = df[df["_pt"].dt.date >= cutoff_date].drop(columns=["_pt"], errors="ignore")
        if df.empty:
            return None
        df = df.sort_values("date", ascending=False).reset_index(drop=True)
        # 同向：先判断整体倾向
        sent = df["sentiment"].astype(float)
        pos = sent[sent >= buy_threshold]
        neg = sent[sent <= sell_threshold]
        if len(pos) >= len(neg) and len(pos) > 0:
            same = df[sent >= buy_threshold].head(max_same_direction)
            direction = 1
        elif len(neg) > 0:
            same = df[sent <= sell_threshold].head(max_same_direction)
            direction = -1
        else:
            return None
        if same.empty:
            return None
        w = same["source_weight"].astype(float)
        s = same["sentiment"].astype(float)
        # 加权平均（按 source_weight 加权情感）
        total_w = w.sum()
        if total_w <= 0:
            S_news = float(s.mean())
        else:
            S_news = float((s * w).sum() / total_w)
        S_news = max(-1.0, min(1.0, S_news))
        N = len(same)
        mean_weight = float(w.mean()) if len(w) else 1.0
        return (S_news, N, mean_weight)
    except Exception as e:
        logger.debug("get_news_sentiment_v33 失败 %s: %s", symbol, e)
        return None
