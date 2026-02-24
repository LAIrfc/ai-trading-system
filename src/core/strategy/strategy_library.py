"""
策略库 - 收集和管理各种交易策略
每个策略都包含：买入信号、卖出信号、止损止盈规则
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from loguru import logger

from .base_strategy import BaseStrategy


class StrategyTemplate:
    """策略模板 - 用于定义新策略"""
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.parameters = {}
        
    def add_parameter(self, name: str, default_value, description: str):
        """添加策略参数"""
        self.parameters[name] = {
            'default': default_value,
            'description': description,
        }


class MAStrategy(BaseStrategy):
    """
    均线策略
    
    原理：
    - 短期均线上穿长期均线（金叉）→ 买入信号
    - 短期均线下穿长期均线（死叉）→ 卖出信号
    
    参数：
    - short_window: 短期均线周期（默认5日）
    - long_window: 长期均线周期（默认20日）
    - stop_loss: 止损比例（默认5%）
    - take_profit: 止盈比例（默认15%）
    """
    
    def __init__(self, short_window=5, long_window=20, stop_loss=0.05, take_profit=0.15):
        super().__init__()
        self.short_window = short_window
        self.long_window = long_window
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        
    def generate_signals(self, market_data: Dict) -> List[Dict]:
        """生成交易信号"""
        signals = []
        
        for stock_code, data in market_data.items():
            if not isinstance(data, pd.DataFrame) or len(data) < self.long_window:
                continue
            
            # 计算均线
            data['MA_short'] = data['close'].rolling(window=self.short_window).mean()
            data['MA_long'] = data['close'].rolling(window=self.long_window).mean()
            
            # 检测金叉/死叉
            current = data.iloc[-1]
            previous = data.iloc[-2]
            
            # 金叉：买入信号
            if (previous['MA_short'] <= previous['MA_long'] and 
                current['MA_short'] > current['MA_long']):
                
                signals.append({
                    'stock_code': stock_code,
                    'action': 'buy',
                    'signal_type': 'golden_cross',
                    'reason': f'短期MA{self.short_window}上穿长期MA{self.long_window}',
                    'confidence': 0.7,
                    'target_position': 0.1,
                    'price': current['close'],
                })
            
            # 死叉：卖出信号
            elif (previous['MA_short'] >= previous['MA_long'] and 
                  current['MA_short'] < current['MA_long']):
                
                signals.append({
                    'stock_code': stock_code,
                    'action': 'sell',
                    'signal_type': 'death_cross',
                    'reason': f'短期MA{self.short_window}下穿长期MA{self.long_window}',
                    'confidence': 0.7,
                    'price': current['close'],
                })
        
        return signals
    
    def calculate_position_size(self, signal: Dict, account_info: Dict) -> int:
        """计算仓位大小"""
        available_cash = account_info.get('available_balance', 0)
        target_position = signal.get('target_position', 0.1)
        price = signal['price']
        
        # 计算目标金额
        target_value = available_cash * target_position
        quantity = int(target_value / price / 100) * 100  # 取整到100股
        
        return max(100, quantity)  # 最小100股


class MACDStrategy(BaseStrategy):
    """
    MACD策略
    
    原理：
    - MACD线上穿信号线（金叉）且在0轴上方 → 强买入信号
    - MACD线下穿信号线（死叉）→ 卖出信号
    - MACD柱状图由负转正 → 买入信号
    
    参数：
    - fast_period: 快速EMA周期（默认12）
    - slow_period: 慢速EMA周期（默认26）
    - signal_period: 信号线周期（默认9）
    """
    
    def __init__(self, fast_period=12, slow_period=26, signal_period=9):
        super().__init__()
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
    
    def calculate_macd(self, prices: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """计算MACD指标"""
        ema_fast = prices.ewm(span=self.fast_period, adjust=False).mean()
        ema_slow = prices.ewm(span=self.slow_period, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.signal_period, adjust=False).mean()
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    def generate_signals(self, market_data: Dict) -> List[Dict]:
        """生成交易信号"""
        signals = []
        
        for stock_code, data in market_data.items():
            if not isinstance(data, pd.DataFrame) or len(data) < self.slow_period + self.signal_period:
                continue
            
            # 计算MACD
            macd, signal, histogram = self.calculate_macd(data['close'])
            
            current_macd = macd.iloc[-1]
            current_signal = signal.iloc[-1]
            current_hist = histogram.iloc[-1]
            
            prev_macd = macd.iloc[-2]
            prev_signal = signal.iloc[-2]
            prev_hist = histogram.iloc[-2]
            
            current_price = data['close'].iloc[-1]
            
            # MACD金叉 + 在0轴上方 = 强买入
            if prev_macd <= prev_signal and current_macd > current_signal:
                confidence = 0.8 if current_macd > 0 else 0.6
                
                signals.append({
                    'stock_code': stock_code,
                    'action': 'buy',
                    'signal_type': 'macd_golden_cross',
                    'reason': f'MACD金叉{"(0轴上方)" if current_macd > 0 else ""}',
                    'confidence': confidence,
                    'target_position': 0.15 if confidence > 0.7 else 0.1,
                    'price': current_price,
                })
            
            # MACD死叉 = 卖出
            elif prev_macd >= prev_signal and current_macd < current_signal:
                signals.append({
                    'stock_code': stock_code,
                    'action': 'sell',
                    'signal_type': 'macd_death_cross',
                    'reason': 'MACD死叉',
                    'confidence': 0.7,
                    'price': current_price,
                })
            
            # 柱状图由负转正 = 买入
            elif prev_hist < 0 and current_hist > 0:
                signals.append({
                    'stock_code': stock_code,
                    'action': 'buy',
                    'signal_type': 'macd_histogram_positive',
                    'reason': 'MACD柱状图转正',
                    'confidence': 0.6,
                    'target_position': 0.08,
                    'price': current_price,
                })
        
        return signals
    
    def calculate_position_size(self, signal: Dict, account_info: Dict) -> int:
        """计算仓位大小"""
        available_cash = account_info.get('available_balance', 0)
        target_position = signal.get('target_position', 0.1)
        price = signal['price']
        
        target_value = available_cash * target_position
        quantity = int(target_value / price / 100) * 100
        
        return max(100, quantity)


class RSIStrategy(BaseStrategy):
    """
    RSI策略（相对强弱指标）
    
    原理：
    - RSI < 30 → 超卖，买入信号
    - RSI > 70 → 超买，卖出信号
    - RSI从超卖区回升 → 强买入
    - RSI从超买区回落 → 强卖出
    
    参数：
    - period: RSI周期（默认14）
    - oversold: 超卖阈值（默认30）
    - overbought: 超买阈值（默认70）
    """
    
    def __init__(self, period=14, oversold=30, overbought=70):
        super().__init__()
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
    
    def calculate_rsi(self, prices: pd.Series) -> pd.Series:
        """计算RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def generate_signals(self, market_data: Dict) -> List[Dict]:
        """生成交易信号"""
        signals = []
        
        for stock_code, data in market_data.items():
            if not isinstance(data, pd.DataFrame) or len(data) < self.period + 1:
                continue
            
            # 计算RSI
            rsi = self.calculate_rsi(data['close'])
            
            current_rsi = rsi.iloc[-1]
            prev_rsi = rsi.iloc[-2]
            current_price = data['close'].iloc[-1]
            
            # 超卖区回升 = 强买入
            if prev_rsi < self.oversold and current_rsi >= self.oversold:
                signals.append({
                    'stock_code': stock_code,
                    'action': 'buy',
                    'signal_type': 'rsi_oversold_recovery',
                    'reason': f'RSI从超卖区{prev_rsi:.1f}回升至{current_rsi:.1f}',
                    'confidence': 0.75,
                    'target_position': 0.12,
                    'price': current_price,
                })
            
            # RSI < 30 = 超卖买入
            elif current_rsi < self.oversold:
                signals.append({
                    'stock_code': stock_code,
                    'action': 'buy',
                    'signal_type': 'rsi_oversold',
                    'reason': f'RSI超卖({current_rsi:.1f} < {self.oversold})',
                    'confidence': 0.65,
                    'target_position': 0.10,
                    'price': current_price,
                })
            
            # 超买区回落 = 强卖出
            elif prev_rsi > self.overbought and current_rsi <= self.overbought:
                signals.append({
                    'stock_code': stock_code,
                    'action': 'sell',
                    'signal_type': 'rsi_overbought_decline',
                    'reason': f'RSI从超买区{prev_rsi:.1f}回落至{current_rsi:.1f}',
                    'confidence': 0.75,
                    'price': current_price,
                })
            
            # RSI > 70 = 超买卖出
            elif current_rsi > self.overbought:
                signals.append({
                    'stock_code': stock_code,
                    'action': 'sell',
                    'signal_type': 'rsi_overbought',
                    'reason': f'RSI超买({current_rsi:.1f} > {self.overbought})',
                    'confidence': 0.65,
                    'price': current_price,
                })
        
        return signals
    
    def calculate_position_size(self, signal: Dict, account_info: Dict) -> int:
        """计算仓位大小"""
        available_cash = account_info.get('available_balance', 0)
        target_position = signal.get('target_position', 0.1)
        price = signal['price']
        
        target_value = available_cash * target_position
        quantity = int(target_value / price / 100) * 100
        
        return max(100, quantity)


class StrategyLibrary:
    """策略库管理器"""
    
    def __init__(self):
        self.strategies = {}
        self._register_builtin_strategies()
    
    def _register_builtin_strategies(self):
        """注册内置策略"""
        self.register_strategy('MA', MAStrategy, 
            "均线策略 - 基于短期和长期均线交叉")
        self.register_strategy('MACD', MACDStrategy, 
            "MACD策略 - 基于MACD指标的金叉死叉")
        self.register_strategy('RSI', RSIStrategy, 
            "RSI策略 - 基于相对强弱指标的超买超卖")
    
    def register_strategy(self, name: str, strategy_class, description: str):
        """注册新策略"""
        self.strategies[name] = {
            'class': strategy_class,
            'description': description,
        }
        logger.info(f"策略已注册: {name} - {description}")
    
    def get_strategy(self, name: str, **params):
        """获取策略实例"""
        if name not in self.strategies:
            raise ValueError(f"策略不存在: {name}")
        
        strategy_class = self.strategies[name]['class']
        return strategy_class(**params)
    
    def list_strategies(self) -> List[Dict]:
        """列出所有可用策略"""
        return [
            {
                'name': name,
                'description': info['description'],
            }
            for name, info in self.strategies.items()
        ]
    
    def get_strategy_info(self, name: str) -> Dict:
        """获取策略详细信息"""
        if name not in self.strategies:
            return None
        
        strategy_class = self.strategies[name]['class']
        
        # 创建临时实例以获取参数信息
        temp_instance = strategy_class()
        
        return {
            'name': name,
            'description': self.strategies[name]['description'],
            'class': strategy_class.__name__,
            'doc': strategy_class.__doc__,
        }


# 全局策略库实例
strategy_library = StrategyLibrary()
