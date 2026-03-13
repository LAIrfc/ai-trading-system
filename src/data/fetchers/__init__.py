"""
数据获取器模块

统一的数据获取接口，支持多种数据源：
- 市场数据（日线、实时行情）
- 基本面数据（PE、PB、ROE等）
- ETF数据
- 日线：统一 DataProvider（config 配置主备顺序），见 docs/data/API_INTERFACES_AND_FETCHERS.md
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
