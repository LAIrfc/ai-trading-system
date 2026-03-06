"""
统一数据接入层：抽象接口定义

策略/回测/采集器只依赖本接口请求数据，底层数据源通过适配器注入，由配置决定主备顺序。
"""

from abc import ABC, abstractmethod
from typing import List, Optional

import pandas as pd


# 日线标准列名，各适配器输出必须统一为此 schema
KLINE_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


class KlineAdapter(ABC):
    """日线 K 线数据源适配器抽象：屏蔽 Sina/东方财富/腾讯/tushare 等接口差异。"""

    @property
    @abstractmethod
    def source_id(self) -> str:
        """数据源标识，用于日志、熔断、缓存键。如 sina / eastmoney / tencent / tushare。"""
        pass

    @abstractmethod
    def get_kline(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        datalen: Optional[int] = None,
        **kwargs,
    ) -> pd.DataFrame:
        """
        获取个股日线 K 线，返回统一 schema：date, open, high, low, close, volume。

        Args:
            symbol: 股票代码，如 600519、000001（不含市场前缀）。
            start_date: 开始日期 YYYYMMDD，与 end_date 成对使用。
            end_date: 结束日期 YYYYMMDD。
            datalen: 最近 N 条（与 start_date/end_date 二选一；若都传则 datalen 优先）。
            **kwargs: 如 adjust（复权）、timeout 等，由具体适配器决定。

        Returns:
            标准化 DataFrame，列含 KLINE_COLUMNS；失败或无数据返回空 DataFrame。
        """
        pass
