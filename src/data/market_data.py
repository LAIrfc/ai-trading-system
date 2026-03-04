"""
向后兼容：重导出 market_data

保持旧的导入路径可用：
    from src.data.market_data import MarketData, ETF_POOL
"""

from .fetchers.market_data import MarketData, ETF_POOL

__all__ = ['MarketData', 'ETF_POOL']
