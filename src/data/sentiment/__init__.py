"""
市场情绪数据模块

提供综合情绪指数（恐慌/贪婪），用于情绪因子策略。
数据源：指数日线（涨跌幅、波动率等代理指标），后续可扩展两融、涨跌家数等。
"""

from .market_sentiment import get_sentiment_series

__all__ = ['get_sentiment_series']
