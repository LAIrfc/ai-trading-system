"""
数据获取器模块

统一的数据获取接口：
- 基本面数据（PE、PB、ROE等）: FundamentalFetcher
- 实时行情: RealtimeDataFetcher
- K线日线（多源自动降级）: get_default_kline_provider（推荐入口）
- 市场全景: market_panorama
"""

from .realtime_data import RealtimeDataFetcher, MarketDataManager
from .fundamental_fetcher import FundamentalFetcher, create_mock_fundamental_data
from .data_prefetch import (
    fetch_stock_daily,
    get_realtime_snapshot_sina,
    get_realtime_snapshot_eastmoney,
    fetch_eastmoney_lhb,
)
from .market_panorama import (
    get_full_market_panorama,
    get_hot_concept_sectors,
    get_hot_industry_sectors,
    get_sector_fund_flow,
    get_index_quotes,
    get_market_snapshot,
    format_panorama_for_prompt,
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
    'get_full_market_panorama',
    'get_hot_concept_sectors',
    'get_hot_industry_sectors',
    'get_sector_fund_flow',
    'get_index_quotes',
    'get_market_snapshot',
    'format_panorama_for_prompt',
]
