"""
MX-Zixuan 自选股管理适配器

支持查询/添加/删除东方财富自选股。
"""

import logging
from typing import Optional

import pandas as pd

from .client import MXClient, MXQuotaExhausted, get_mx_client

logger = logging.getLogger(__name__)


class MXWatchlist:
    """妙想自选股管理"""

    def __init__(self, client: Optional[MXClient] = None):
        self._client = client

    @property
    def client(self) -> MXClient:
        if self._client is None:
            self._client = get_mx_client()
        return self._client

    def get_list(self) -> pd.DataFrame:
        """获取自选股列表"""
        try:
            return self.client.get_watchlist_df()
        except MXQuotaExhausted:
            logger.warning("MX 配额用尽，跳过自选股查询")
            return pd.DataFrame()
        except Exception:
            logger.exception("MX 自选股查询失败")
            return pd.DataFrame()

    def add(self, stock_name_or_code: str) -> bool:
        """添加股票到自选股"""
        try:
            result = self.client.manage_watchlist(
                f"把{stock_name_or_code}添加到我的自选股列表"
            )
            return result.get("status") == 0 or result.get("code") == 0
        except Exception:
            logger.exception("MX 添加自选失败: %s", stock_name_or_code)
            return False

    def remove(self, stock_name_or_code: str) -> bool:
        """从自选股删除"""
        try:
            result = self.client.manage_watchlist(
                f"把{stock_name_or_code}从我的自选股列表删除"
            )
            return result.get("status") == 0 or result.get("code") == 0
        except Exception:
            logger.exception("MX 删除自选失败: %s", stock_name_or_code)
            return False
