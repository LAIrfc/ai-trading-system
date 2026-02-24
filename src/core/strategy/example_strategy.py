"""
示例策略：简单的动量策略
演示如何继承BaseStrategy并实现自己的交易策略
"""

from typing import Dict, List
import pandas as pd
import numpy as np
from loguru import logger

from .base_strategy import BaseStrategy


class SimpleMomentumStrategy(BaseStrategy):
    """
    简单动量策略
    
    策略逻辑：
    1. 计算过去N天的价格动量
    2. 选择动量最强的K只股票
    3. 等权重配置
    4. 定期调仓
    """
    
    def __init__(self, name: str, config: Dict):
        """
        初始化策略
        
        配置参数：
        - lookback_period: 回看周期（天）
        - top_n: 选择股票数量
        - rebalance_frequency: 调仓频率（daily/weekly/monthly）
        - min_momentum: 最小动量阈值
        """
        super().__init__(name, config)
        
        self.lookback_period = config.get('lookback_period', 20)
        self.top_n = config.get('top_n', 10)
        self.rebalance_frequency = config.get('rebalance_frequency', 'weekly')
        self.min_momentum = config.get('min_momentum', 0.0)
        
        self.last_rebalance_date = None
        
        logger.info(f"策略初始化: {name}")
        logger.info(f"回看周期: {self.lookback_period}天")
        logger.info(f"选股数量: {self.top_n}")
        logger.info(f"调仓频率: {self.rebalance_frequency}")
    
    def calculate_momentum(self, price_data: pd.DataFrame) -> pd.Series:
        """
        计算动量指标
        
        Args:
            price_data: 价格数据，索引为日期，列为股票代码
            
        Returns:
            动量序列
        """
        if len(price_data) < self.lookback_period:
            return pd.Series()
        
        # 计算收益率动量
        momentum = (price_data.iloc[-1] / price_data.iloc[-self.lookback_period] - 1)
        
        return momentum
    
    def should_rebalance(self, current_date: pd.Timestamp) -> bool:
        """
        判断是否应该调仓
        
        Args:
            current_date: 当前日期
            
        Returns:
            是否调仓
        """
        if self.last_rebalance_date is None:
            return True
        
        if self.rebalance_frequency == 'daily':
            return True
        elif self.rebalance_frequency == 'weekly':
            return (current_date - self.last_rebalance_date).days >= 5
        elif self.rebalance_frequency == 'monthly':
            return (current_date - self.last_rebalance_date).days >= 20
        
        return False
    
    def generate_signals(self, market_data: pd.DataFrame, 
                        current_positions: Dict) -> List[Dict]:
        """
        生成交易信号
        
        Args:
            market_data: 市场数据，包含所有股票的历史价格
            current_positions: 当前持仓 {stock_code: shares}
            
        Returns:
            交易信号列表
        """
        signals = []
        
        if len(market_data) < self.lookback_period:
            logger.warning("数据不足，无法生成信号")
            return signals
        
        current_date = market_data.index[-1]
        
        # 判断是否需要调仓
        if not self.should_rebalance(current_date):
            logger.debug(f"未到调仓时间，保持当前持仓")
            return signals
        
        # 计算动量
        momentum = self.calculate_momentum(market_data)
        
        # 过滤掉动量过低的股票
        momentum = momentum[momentum >= self.min_momentum]
        
        if len(momentum) == 0:
            logger.warning("没有符合条件的股票")
            return signals
        
        # 选择动量最强的top_n只股票
        top_stocks = momentum.nlargest(self.top_n)
        target_stocks = set(top_stocks.index)
        current_stocks = set(current_positions.keys())
        
        # 计算目标仓位（等权重）
        target_position = 1.0 / len(target_stocks) if len(target_stocks) > 0 else 0.0
        
        # 生成卖出信号（不在目标股票中的持仓）
        for stock in current_stocks - target_stocks:
            signals.append({
                'stock_code': stock,
                'action': 'sell',
                'target_position': 0.0,
                'reason': f'退出持仓（动量不足）',
                'confidence': 0.8,
            })
        
        # 生成买入/调仓信号
        for stock in target_stocks:
            if stock in current_stocks:
                # 已持仓，调整仓位
                signals.append({
                    'stock_code': stock,
                    'action': 'rebalance',
                    'target_position': target_position,
                    'reason': f'调整仓位（动量排名: {list(top_stocks.index).index(stock) + 1}）',
                    'confidence': 0.8,
                    'momentum': top_stocks[stock],
                })
            else:
                # 新建仓位
                signals.append({
                    'stock_code': stock,
                    'action': 'buy',
                    'target_position': target_position,
                    'reason': f'买入（动量: {top_stocks[stock]:.2%}）',
                    'confidence': 0.8,
                    'momentum': top_stocks[stock],
                })
        
        self.last_rebalance_date = current_date
        self.signals.extend(signals)
        
        logger.info(f"生成{len(signals)}个交易信号")
        return signals
    
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
        # 基础仓位
        base_position = available_capital * signal['target_position']
        
        # 根据动量强度调整（可选）
        momentum = signal.get('momentum', 0.0)
        if momentum > 0:
            # 动量越强，仓位可以适当增加（但不超过目标的120%）
            adjustment = min(1.2, 1.0 + momentum * 0.5)
            adjusted_position = base_position * adjustment
        else:
            adjusted_position = base_position
        
        # 风控检查
        max_single_position = available_capital * 0.15  # 单股最大15%
        final_position = min(adjusted_position, max_single_position)
        
        return final_position


class AIMultiFactorStrategy(BaseStrategy):
    """
    AI多因子策略（示例框架）
    
    实际使用时需要：
    1. 训练AI模型
    2. 计算多个因子
    3. 集成模型预测
    """
    
    def __init__(self, name: str, config: Dict):
        super().__init__(name, config)
        
        self.model = None  # AI模型
        self.factors = config.get('factors', [])
        
        logger.info(f"AI多因子策略初始化: {name}")
        logger.info(f"因子列表: {self.factors}")
    
    def load_model(self, model_path: str):
        """加载训练好的AI模型"""
        # TODO: 实现模型加载
        logger.info(f"加载模型: {model_path}")
        pass
    
    def calculate_factors(self, market_data: pd.DataFrame) -> pd.DataFrame:
        """
        计算因子值
        
        Args:
            market_data: 市场数据
            
        Returns:
            因子DataFrame
        """
        factors_df = pd.DataFrame()
        
        # 示例：计算一些简单因子
        if 'momentum' in self.factors:
            factors_df['momentum'] = market_data['close'].pct_change(20)
        
        if 'volatility' in self.factors:
            factors_df['volatility'] = market_data['close'].pct_change().rolling(20).std()
        
        if 'volume' in self.factors:
            factors_df['volume_ratio'] = market_data['volume'] / market_data['volume'].rolling(20).mean()
        
        # TODO: 添加更多因子
        
        return factors_df
    
    def generate_signals(self, market_data: pd.DataFrame, 
                        current_positions: Dict) -> List[Dict]:
        """生成交易信号"""
        signals = []
        
        # 计算因子
        factors = self.calculate_factors(market_data)
        
        # 使用AI模型预测
        if self.model:
            # predictions = self.model.predict(factors)
            # TODO: 根据预测生成信号
            pass
        
        return signals
    
    def calculate_position_size(self, signal: Dict, 
                               available_capital: float,
                               risk_metrics: Dict) -> float:
        """计算仓位大小"""
        # 根据AI模型的置信度调整仓位
        confidence = signal.get('confidence', 0.5)
        base_position = available_capital * signal['target_position']
        
        # 置信度越高，仓位越大
        adjusted_position = base_position * confidence
        
        return adjusted_position


# 策略工厂
class StrategyFactory:
    """策略工厂"""
    
    _strategies = {
        'momentum': SimpleMomentumStrategy,
        'ai_multi_factor': AIMultiFactorStrategy,
    }
    
    @classmethod
    def create_strategy(cls, strategy_type: str, name: str, config: Dict) -> BaseStrategy:
        """
        创建策略实例
        
        Args:
            strategy_type: 策略类型
            name: 策略名称
            config: 策略配置
            
        Returns:
            策略实例
        """
        if strategy_type not in cls._strategies:
            raise ValueError(f"不支持的策略类型: {strategy_type}")
        
        strategy_class = cls._strategies[strategy_type]
        return strategy_class(name, config)
    
    @classmethod
    def register_strategy(cls, strategy_type: str, strategy_class: type):
        """
        注册新策略
        
        Args:
            strategy_type: 策略类型
            strategy_class: 策略类
        """
        cls._strategies[strategy_type] = strategy_class
        logger.info(f"策略已注册: {strategy_type}")


# 使用示例
if __name__ == '__main__':
    # 创建策略
    config = {
        'lookback_period': 20,
        'top_n': 10,
        'rebalance_frequency': 'weekly',
        'min_momentum': 0.05,
    }
    
    strategy = StrategyFactory.create_strategy('momentum', 'test_momentum', config)
    
    # 模拟市场数据
    dates = pd.date_range('2023-01-01', '2023-12-31', freq='D')
    stocks = ['000001', '000002', '600000', '600519']
    
    # 随机生成价格数据（实际应该从数据源获取）
    np.random.seed(42)
    data = {}
    for stock in stocks:
        base_price = 100
        returns = np.random.randn(len(dates)) * 0.02
        prices = base_price * (1 + returns).cumprod()
        data[stock] = prices
    
    market_data = pd.DataFrame(data, index=dates)
    
    # 生成信号
    signals = strategy.generate_signals(market_data, {})
    
    print(f"生成了{len(signals)}个交易信号")
    for signal in signals:
        print(signal)
