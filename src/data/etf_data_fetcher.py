"""
向后兼容：重导出 etf_data_fetcher

保持旧的导入路径可用：
    from src.data.etf_data_fetcher import ETFDataFetcher
"""

from .fetchers.etf_data_fetcher import ETFDataFetcher

__all__ = ['ETFDataFetcher']
