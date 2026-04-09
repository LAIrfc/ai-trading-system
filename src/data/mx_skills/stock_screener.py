"""
MX-Xuangu 智能选股适配器

支持基于自然语言条件筛选股票,可作为策略的预筛选层。
"""

import logging
from typing import Dict, List, Optional

import pandas as pd

from .client import MXClient, MXQuotaExhausted, get_mx_client

logger = logging.getLogger(__name__)


class MXStockScreener:
    """妙想智能选股"""

    def __init__(self, client: Optional[MXClient] = None):
        self._client = client

    @property
    def client(self) -> MXClient:
        if self._client is None:
            self._client = get_mx_client()
        return self._client

    def screen(self, condition: str) -> pd.DataFrame:
        """
        按自然语言条件筛选股票。

        Examples:
            screen("市盈率小于20 净利润增长率大于30%")
            screen("今日涨幅大于3%的A股")
            screen("新能源板块市盈率小于30的股票")

        返回 DataFrame 包含筛选结果,列名已映射为中文。
        """
        try:
            return self.client.screen_stocks_df(condition)
        except MXQuotaExhausted:
            logger.warning("MX 配额用尽，跳过选股: %s", condition)
            return pd.DataFrame()
        except Exception:
            logger.exception("MX 选股失败: %s", condition)
            return pd.DataFrame()

    def screen_value_stocks(
        self,
        max_pe: float = 20,
        min_roe: float = 10,
        min_dividend: float = 2,
    ) -> pd.DataFrame:
        """预置: 价值股筛选"""
        cond = f"市盈率小于{max_pe} ROE大于{min_roe}% 股息率大于{min_dividend}%"
        return self.screen(cond)

    def screen_growth_stocks(
        self,
        min_revenue_growth: float = 20,
        min_profit_growth: float = 30,
    ) -> pd.DataFrame:
        """预置: 成长股筛选"""
        cond = (
            f"营业收入增长率大于{min_revenue_growth}% "
            f"净利润增长率大于{min_profit_growth}%"
        )
        return self.screen(cond)

    def screen_momentum_stocks(
        self,
        min_change: float = 2,
        max_pe: float = 50,
    ) -> pd.DataFrame:
        """预置: 动量股筛选"""
        cond = f"今日涨幅大于{min_change}% 市盈率小于{max_pe}"
        return self.screen(cond)

    def get_sector_stocks(self, sector: str) -> pd.DataFrame:
        """获取板块/行业成分股"""
        return self.screen(f"{sector}板块成分股")
