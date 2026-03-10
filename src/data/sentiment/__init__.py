"""
市场情绪数据模块

提供综合情绪指数（恐慌/贪婪），用于情绪因子策略。
数据源：多指标 Z-score 加权合成（V3.3），包含涨跌家数比、换手率、融资买入比、
期权 PCR、新高新低比、波动率指数。
"""

from .sentiment_index import (
    get_sentiment_series_v2,
    get_sentiment_series,   # 向后兼容接口（旧版 0~100 格式）
    composite_sentiment,
    get_s_low_s_high_latest,
)

__all__ = [
    'get_sentiment_series_v2',
    'get_sentiment_series',
    'composite_sentiment',
    'get_s_low_s_high_latest',
]
