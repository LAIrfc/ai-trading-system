"""
策略基类
所有交易策略都应继承此基类
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import pandas as pd
from datetime import datetime


class BaseStrategy(ABC):
    """策略基类"""
    
    def __init__(self, name: str, config: Dict):
        """
        初始化策略
        
        Args:
            name: 策略名称
            config: 策略配置
        """
        self.name = name
        self.config = config
        self.positions = {}  # 当前持仓 {stock_code: quantity}
        self.orders = []  # 订单历史
        self.signals = []  # 信号历史
        self.performance_metrics = {}  # 策略表现指标
        
    @abstractmethod
    def generate_signals(self, market_data: pd.DataFrame, 
                        current_positions: Dict) -> List[Dict]:
        """
        生成交易信号
        
        Args:
            market_data: 市场数据
            current_positions: 当前持仓
            
        Returns:
            交易信号列表，每个信号格式：
            {
                'stock_code': str,
                'action': 'buy' | 'sell' | 'hold',
                'target_position': float,  # 目标仓位比例
                'reason': str,  # 信号原因
                'confidence': float,  # 信号置信度 0-1
            }
        """
        pass
    
    @abstractmethod
    def calculate_position_size(self, signal: Dict, 
                               available_capital: float,
                               risk_metrics: Dict) -> float:
        """
        计算仓位大小
        
        Args:
            signal: 交易信号
            available_capital: 可用资金
            risk_metrics: 风险指标
            
        Returns:
            目标仓位金额
        """
        pass
    
    def on_bar(self, bar_data: pd.DataFrame):
        """
        每个bar（K线）的回调
        
        Args:
            bar_data: K线数据
        """
        pass
    
    def on_order_filled(self, order: Dict):
        """
        订单成交回调
        
        Args:
            order: 订单信息
        """
        self.orders.append(order)
        
    def on_trade(self, trade: Dict):
        """
        交易发生回调
        
        Args:
            trade: 交易信息
        """
        pass
    
    def update_positions(self, positions: Dict):
        """
        更新持仓
        
        Args:
            positions: 最新持仓信息
        """
        self.positions = positions
        
    def update_performance(self, metrics: Dict):
        """
        更新策略表现指标
        
        Args:
            metrics: 表现指标
        """
        self.performance_metrics = metrics
        
    def get_strategy_info(self) -> Dict:
        """
        获取策略信息
        
        Returns:
            策略信息字典
        """
        return {
            'name': self.name,
            'config': self.config,
            'positions': self.positions,
            'performance': self.performance_metrics,
            'total_orders': len(self.orders),
            'total_signals': len(self.signals),
        }
    
    def reset(self):
        """重置策略状态"""
        self.positions = {}
        self.orders = []
        self.signals = []
        self.performance_metrics = {}


class StrategyManager:
    """策略管理器"""
    
    def __init__(self):
        self.strategies = {}
        
    def register_strategy(self, strategy: BaseStrategy):
        """
        注册策略
        
        Args:
            strategy: 策略实例
        """
        self.strategies[strategy.name] = strategy
        
    def remove_strategy(self, strategy_name: str):
        """
        移除策略
        
        Args:
            strategy_name: 策略名称
        """
        if strategy_name in self.strategies:
            del self.strategies[strategy_name]
            
    def get_strategy(self, strategy_name: str) -> Optional[BaseStrategy]:
        """
        获取策略
        
        Args:
            strategy_name: 策略名称
            
        Returns:
            策略实例或None
        """
        return self.strategies.get(strategy_name)
    
    def get_all_strategies(self) -> Dict[str, BaseStrategy]:
        """
        获取所有策略
        
        Returns:
            策略字典
        """
        return self.strategies
    
    def run_all_strategies(self, market_data: pd.DataFrame) -> Dict[str, List[Dict]]:
        """
        运行所有策略
        
        Args:
            market_data: 市场数据
            
        Returns:
            每个策略的信号
        """
        all_signals = {}
        for name, strategy in self.strategies.items():
            signals = strategy.generate_signals(market_data, strategy.positions)
            all_signals[name] = signals
            
        return all_signals
