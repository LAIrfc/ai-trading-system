"""
向后兼容：重导出 fundamental_fetcher

保持旧的导入路径可用：
    from src.data.fundamental_fetcher import FundamentalFetcher
"""

from .fetchers.fundamental_fetcher import (
    FundamentalFetcher,
    create_mock_fundamental_data,
)

__all__ = ['FundamentalFetcher', 'create_mock_fundamental_data']
