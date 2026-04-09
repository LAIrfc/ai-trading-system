"""
MX-Moni 模拟组合管理适配器

支持模拟交易操作：持仓查询、买入/卖出、撤单、资金查询。
"""

import logging
from typing import Optional

import pandas as pd

from .client import MXClient, MXQuotaExhausted, get_mx_client

logger = logging.getLogger(__name__)


class MXMockTrading:
    """妙想模拟交易"""

    def __init__(self, client: Optional[MXClient] = None):
        self._client = client

    @property
    def client(self) -> MXClient:
        if self._client is None:
            self._client = get_mx_client()
        return self._client

    def positions(self) -> dict:
        """查询当前持仓"""
        try:
            return self.client.moni_positions()
        except Exception:
            logger.exception("MX 持仓查询失败")
            return {}

    def balance(self) -> dict:
        """查询资金"""
        try:
            return self.client.moni_balance()
        except Exception:
            logger.exception("MX 资金查询失败")
            return {}

    def orders(self) -> dict:
        """查询委托"""
        try:
            return self.client.moni_orders()
        except Exception:
            logger.exception("MX 委托查询失败")
            return {}

    def buy(
        self,
        stock_code: str,
        quantity: int,
        price: Optional[float] = None,
        market_price: bool = False,
    ) -> dict:
        """买入"""
        if quantity % 100 != 0:
            return {"error": "数量必须为100的整数倍"}
        try:
            return self.client.moni_buy(stock_code, quantity, price, market_price)
        except Exception as e:
            logger.exception("MX 买入失败: %s", stock_code)
            return {"error": str(e)}

    def sell(
        self,
        stock_code: str,
        quantity: int,
        price: Optional[float] = None,
        market_price: bool = False,
    ) -> dict:
        """卖出"""
        if quantity % 100 != 0:
            return {"error": "数量必须为100的整数倍"}
        try:
            return self.client.moni_sell(stock_code, quantity, price, market_price)
        except Exception as e:
            logger.exception("MX 卖出失败: %s", stock_code)
            return {"error": str(e)}

    def cancel(self, order_id: Optional[str] = None) -> dict:
        """撤单（传 order_id 撤单只, 不传则一键撤单）"""
        try:
            return self.client.moni_cancel(order_id)
        except Exception as e:
            logger.exception("MX 撤单失败")
            return {"error": str(e)}
