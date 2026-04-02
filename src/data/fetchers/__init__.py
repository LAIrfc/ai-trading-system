"""
数据获取器模块

统一的数据获取接口：
- 基本面数据（PE、PB、ROE等）: FundamentalFetcher
- 实时行情: RealtimeDataFetcher
- K线日线（多源自动降级）: get_default_kline_provider（推荐入口）
"""

from .realtime_data import RealtimeDataFetcher, MarketDataManager
from .fundamental_fetcher import FundamentalFetcher, create_mock_fundamental_data
from .data_prefetch import (
    fetch_stock_daily,
    get_realtime_snapshot_sina,
    get_realtime_snapshot_eastmoney,
    fetch_eastmoney_lhb,
)

try:
    from src.data.provider import get_default_kline_provider, UnifiedDataProvider
except ImportError:
    get_default_kline_provider = None  # type: ignore
    UnifiedDataProvider = None  # type: ignore

__all__ = [
    'RealtimeDataFetcher',
    'MarketDataManager',
    'FundamentalFetcher',
    'create_mock_fundamental_data',
    'fetch_stock_daily',
    'get_realtime_snapshot_sina',
    'get_realtime_snapshot_eastmoney',
    'fetch_eastmoney_lhb',
    'get_default_kline_provider',
    'UnifiedDataProvider',
]
