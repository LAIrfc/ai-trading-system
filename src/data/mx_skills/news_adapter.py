"""
MX-Search 新闻适配器 — 将妙想资讯搜索 API 接入现有 news_fetcher 体系。

提供权威的东方财富金融资讯数据,包括:
- 个股新闻/研报/公告
- 行业板块资讯
- 宏观经济分析
"""

import logging
from typing import List, Optional

import pandas as pd

from .client import MXClient, MXQuotaExhausted, get_mx_client

logger = logging.getLogger(__name__)


class MXNewsFetcher:
    """妙想资讯搜索适配器"""

    def __init__(self, client: Optional[MXClient] = None):
        self._client = client

    @property
    def client(self) -> MXClient:
        if self._client is None:
            self._client = get_mx_client()
        return self._client

    def fetch_stock_news(
        self, symbol: str, max_items: int = 15
    ) -> pd.DataFrame:
        """
        获取个股相关资讯,返回格式与 news_fetcher.fetch_stock_news 兼容:
        columns: [title, content, date, source]
        """
        try:
            items = self.client.search_news_items(f"{symbol} 最新资讯 研报")
            if not items:
                return pd.DataFrame(columns=["title", "content", "date", "source"])
            items = items[:max_items]
            df = pd.DataFrame(items)
            for col in ["title", "content", "date", "source"]:
                if col not in df.columns:
                    df[col] = ""
            return df[["title", "content", "date", "source"]]
        except MXQuotaExhausted:
            logger.warning("MX 配额用尽，跳过新闻查询: %s", symbol)
            return pd.DataFrame(columns=["title", "content", "date", "source"])
        except Exception:
            logger.exception("MX 新闻查询失败: %s", symbol)
            return pd.DataFrame(columns=["title", "content", "date", "source"])

    def fetch_sector_news(self, sector_name: str, max_items: int = 10) -> pd.DataFrame:
        """获取板块/行业资讯"""
        try:
            items = self.client.search_news_items(f"{sector_name}板块 近期新闻")
            if not items:
                return pd.DataFrame(columns=["title", "content", "date", "source"])
            return pd.DataFrame(items[:max_items])[
                ["title", "content", "date", "source"]
            ]
        except Exception:
            logger.warning("MX 板块新闻查询失败: %s", sector_name)
            return pd.DataFrame(columns=["title", "content", "date", "source"])

    def fetch_market_analysis(self, query: str = "今日A股异动分析") -> pd.DataFrame:
        """获取市场分析资讯"""
        try:
            items = self.client.search_news_items(query)
            if not items:
                return pd.DataFrame(columns=["title", "content", "date", "source"])
            return pd.DataFrame(items)[["title", "content", "date", "source"]]
        except Exception:
            logger.warning("MX 市场分析查询失败: %s", query)
            return pd.DataFrame(columns=["title", "content", "date", "source"])
