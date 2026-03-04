"""
数据获取器模块

统一的数据获取接口，支持多种数据源：
- 市场数据（日线、实时行情）
- 基本面数据（PE、PB、ROE等）
- ETF数据
- 日线主备容错：data_prefetch（Sina → 东方财富 → 腾讯），见 docs/data/API_INTERFACES_AND_FETCHERS.md
"""

from .market_data import MarketData
from .realtime_data import RealtimeDataFetcher, MarketDataManager
from .fundamental_fetcher import FundamentalFetcher, create_mock_fundamental_data
from .etf_data_fetcher import ETFDataFetcher
from .data_prefetch import (
    fetch_stock_daily,
    get_realtime_snapshot_sina,
    get_realtime_snapshot_eastmoney,
    fetch_eastmoney_lhb,
    fetch_eastmoney_stock_news,
)

__all__ = [
    'MarketData',
    'RealtimeDataFetcher',
    'MarketDataManager',
    'FundamentalFetcher',
    'create_mock_fundamental_data',
    'ETFDataFetcher',
    'fetch_stock_daily',
    'get_realtime_snapshot_sina',
    'get_realtime_snapshot_eastmoney',
    'fetch_eastmoney_lhb',
    'fetch_eastmoney_stock_news',
]
