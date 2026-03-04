"""
个股新闻与情感数据模块（V3.3）

- 从东方财富等源获取个股相关新闻
- 情感打分（-1~1）、去重、新闻源权重
"""

from .news_fetcher import fetch_stock_news
from .sentiment import score_news_sentiment, aggregate_sentiment
from .clean import dedup_news, filter_future_time
from .source_weights import get_source_weight
from .news_v33 import get_news_sentiment_v33

__all__ = [
    "fetch_stock_news",
    "score_news_sentiment",
    "aggregate_sentiment",
    "dedup_news",
    "filter_future_time",
    "get_source_weight",
    "get_news_sentiment_v33",
]
