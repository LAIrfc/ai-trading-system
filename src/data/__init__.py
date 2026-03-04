"""
数据模块

统一的数据访问接口，包含：
- fetchers/: 数据获取器（市场数据、基本面数据等）
- collectors/: 数据采集器
- processors/: 数据处理器
"""

# 向后兼容：保持旧的导入路径可用
from .fetchers.market_data import MarketData
from .fetchers.realtime_data import RealtimeDataFetcher, MarketDataManager
from .fetchers.fundamental_fetcher import FundamentalFetcher, create_mock_fundamental_data
from .fetchers.etf_data_fetcher import ETFDataFetcher

__all__ = [
    'MarketData',
    'RealtimeDataFetcher',
    'MarketDataManager',
    'FundamentalFetcher',
    'create_mock_fundamental_data',
    'ETFDataFetcher',
]
