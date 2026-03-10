"""
数据模块

统一的数据访问接口，包含：
- fetchers/   数据获取器（ETF行情、基本面、实时行情）
- provider/   统一数据提供层（主备容错、熔断机制）
- sentiment/  市场情绪指数
- news/       新闻抓取与情感分析
- money_flow/ 龙虎榜/大宗交易
- policy/     政策事件识别

推荐使用 provider 层作为主要数据入口：
    from src.data.provider.data_provider import get_default_kline_provider
"""

# 向后兼容：保持旧的导入路径可用
from .fetchers.market_data import MarketData, ETF_POOL
from .fetchers.realtime_data import RealtimeDataFetcher, MarketDataManager
from .fetchers.fundamental_fetcher import FundamentalFetcher, create_mock_fundamental_data
from .fetchers.etf_data_fetcher import ETFDataFetcher

__all__ = [
    'MarketData',
    'ETF_POOL',
    'RealtimeDataFetcher',
    'MarketDataManager',
    'FundamentalFetcher',
    'create_mock_fundamental_data',
    'ETFDataFetcher',
]
