"""
向后兼容：重导出 realtime_data

保持旧的导入路径可用：
    from src.data.realtime_data import RealtimeDataFetcher, MarketDataManager
"""

from .fetchers.realtime_data import (
    RealtimeDataFetcher,
    MarketDataManager,
)

__all__ = ['RealtimeDataFetcher', 'MarketDataManager']
