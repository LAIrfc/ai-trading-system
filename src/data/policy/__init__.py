"""
政策面数据模块

- 政策关键词库（利好/利空/影响力）
- 政策相关新闻获取与情感打分
"""

from .policy_keywords import (
    score_policy_text,
    has_major_negative,
    POLICY_POSITIVE,
    POLICY_NEGATIVE,
    MAJOR_NEGATIVE_KEYWORDS,
)
from .policy_news import fetch_policy_news, get_policy_sentiment, get_policy_sentiment_v33
from .policy_overrides import get_policy_override, policy_id_from_row

__all__ = [
    "score_policy_text",
    "has_major_negative",
    "fetch_policy_news",
    "get_policy_sentiment",
    "get_policy_sentiment_v33",
    "get_policy_override",
    "policy_id_from_row",
    "POLICY_POSITIVE",
    "POLICY_NEGATIVE",
    "MAJOR_NEGATIVE_KEYWORDS",
]
