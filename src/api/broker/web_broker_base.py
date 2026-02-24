"""
网页端券商接口基类
通过浏览器自动化实现交易操作
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from loguru import logger


@dataclass
class Position:
    """持仓信息"""
    stock_code: str
    stock_name: str
    quantity: int  # 持仓数量
    available: int  # 可用数量
    cost_price: float  # 成本价
    current_price: float  # 现价
    market_value: float  # 市值
    profit_loss: float  # 盈亏
    profit_loss_ratio: float  # 盈亏比例


@dataclass
class AccountInfo:
    """账户信息"""
    total_assets: float  # 总资产
    available_cash: float  # 可用资金
    frozen_cash: float  # 冻结资金
    market_value: float  # 持仓市值
    total_profit_loss: float  # 总盈亏
    positions: List[Position]  # 持仓列表


@dataclass
class OrderInfo:
    """订单信息"""
    order_id: str
    stock_code: str
    stock_name: str
    action: str  # buy / sell
    price: float
    quantity: int
    filled_quantity: int
    status: str  # pending / filled / cancelled / failed
    submit_time: str
    filled_time: Optional[str] = None


class WebBrokerBase(ABC):
    """网页端券商接口基类"""
    
    def __init__(self, config: Dict):
        """
        初始化
        
        Args:
            config: 配置信息
        """
        self.config = config
        self.driver = None
        self.is_logged_in = False
        
    @abstractmethod
    def login(self) -> bool:
        """
        登录
        
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    def logout(self):
        """登出"""
        pass
    
    @abstractmethod
    def get_account_info(self) -> Optional[AccountInfo]:
        """
        获取账户信息
        
        Returns:
            账户信息
        """
        pass
    
    @abstractmethod
    def get_positions(self) -> List[Position]:
        """
        获取持仓列表
        
        Returns:
            持仓列表
        """
        pass
    
    @abstractmethod
    def buy(self, stock_code: str, price: float, quantity: int) -> Tuple[bool, str]:
        """
        买入
        
        Args:
            stock_code: 股票代码
            price: 价格
            quantity: 数量
            
        Returns:
            (是否成功, 订单ID或错误信息)
        """
        pass
    
    @abstractmethod
    def sell(self, stock_code: str, price: float, quantity: int) -> Tuple[bool, str]:
        """
        卖出
        
        Args:
            stock_code: 股票代码
            price: 价格
            quantity: 数量
            
        Returns:
            (是否成功, 订单ID或错误信息)
        """
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        撤单
        
        Args:
            order_id: 订单ID
            
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    def get_orders(self, status: Optional[str] = None) -> List[OrderInfo]:
        """
        获取订单列表
        
        Args:
            status: 订单状态过滤
            
        Returns:
            订单列表
        """
        pass
    
    @abstractmethod
    def get_current_price(self, stock_code: str) -> Optional[float]:
        """
        获取当前价格
        
        Args:
            stock_code: 股票代码
            
        Returns:
            当前价格
        """
        pass
    
    def check_login_status(self) -> bool:
        """检查登录状态"""
        return self.is_logged_in
    
    def ensure_logged_in(self) -> bool:
        """确保已登录"""
        if not self.check_login_status():
            logger.warning("未登录，尝试登录...")
            return self.login()
        return True
    
    def close(self):
        """关闭浏览器"""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("浏览器已关闭")
            except Exception as e:
                logger.error(f"关闭浏览器失败: {e}")
