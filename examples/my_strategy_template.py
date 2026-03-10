#!/usr/bin/env python3
"""
策略模板 - 复制此文件开始开发你的策略

使用方法:
1. 复制此文件: cp my_strategy_template.py my_awesome_strategy.py
2. 修改策略名称和逻辑
3. 运行测试: python3 my_awesome_strategy.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import Dict, List
import pandas as pd
from src.core.base_strategy import BaseStrategy


class MyStrategy(BaseStrategy):
    """
    策略名称: [在这里填写你的策略名称]
    
    策略说明:
    - 买入条件: [说明买入的条件]
    - 卖出条件: [说明卖出的条件]
    - 止损: [说明止损规则]
    - 止盈: [说明止盈规则]
    
    策略参数:
    - param1: [参数说明]
    - param2: [参数说明]
    """
    
    def __init__(self, param1=10, param2=20, name: str = "MyStrategy", config: Dict = None):
        """
        初始化策略
        
        Args:
            param1: 参数1的说明
            param2: 参数2的说明
            name: 策略名称（供 BaseStrategy 使用）
            config: 策略配置（供 BaseStrategy 使用，默认含 param1/param2）
        """
        config = config or {}
        config = {**{"param1": param1, "param2": param2}, **config}
        super().__init__(name=name, config=config)
        self.param1 = self.config.get("param1", param1)
        self.param2 = self.config.get("param2", param2)
    
    def generate_signals(self, market_data: Dict) -> List[Dict]:
        """
        生成交易信号
        
        这是策略的核心函数，根据市场数据生成买入/卖出信号
        
        Args:
            market_data: 市场数据字典
                {
                    '600519': DataFrame(包含open, high, low, close, volume列),
                    '000001': DataFrame(...),
                    ...
                }
        
        Returns:
            信号列表，每个信号是一个字典:
            {
                'stock_code': '600519',          # 股票代码
                'action': 'buy' or 'sell',       # 操作类型
                'signal_type': 'my_signal',      # 信号类型标识
                'reason': '触发买入条件',         # 信号原因
                'confidence': 0.8,               # 信号置信度 (0-1)
                'target_position': 0.1,          # 目标仓位 (0-1, 即10%)
                'price': 1000.0,                 # 当前价格
            }
        """
        signals = []
        
        for stock_code, data in market_data.items():
            # 1. 数据验证
            if not isinstance(data, pd.DataFrame):
                continue
            
            if len(data) < self.param2:  # 确保有足够的数据
                continue
            
            # 2. 计算你需要的指标
            # 例如：计算移动平均线
            data['MA_short'] = data['close'].rolling(window=self.param1).mean()
            data['MA_long'] = data['close'].rolling(window=self.param2).mean()
            
            # 3. 获取最新数据
            latest = data.iloc[-1]
            previous = data.iloc[-2]
            
            current_price = latest['close']
            ma_short_current = latest['MA_short']
            ma_long_current = latest['MA_long']
            ma_short_prev = previous['MA_short']
            ma_long_prev = previous['MA_long']
            
            # 4. 判断买入条件
            if self._check_buy_condition(latest, previous):
                signals.append({
                    'stock_code': stock_code,
                    'action': 'buy',
                    'signal_type': 'my_buy_signal',
                    'reason': f'满足买入条件: ...',  # 详细说明原因
                    'confidence': 0.75,  # 你对这个信号的信心
                    'target_position': 0.1,  # 目标仓位10%
                    'price': current_price,
                })
            
            # 5. 判断卖出条件
            elif self._check_sell_condition(latest, previous):
                signals.append({
                    'stock_code': stock_code,
                    'action': 'sell',
                    'signal_type': 'my_sell_signal',
                    'reason': f'满足卖出条件: ...',
                    'confidence': 0.70,
                    'price': current_price,
                })
        
        return signals
    
    def _check_buy_condition(self, latest: pd.Series, previous: pd.Series) -> bool:
        """
        检查买入条件
        
        在这里实现你的买入逻辑
        
        Args:
            latest: 最新一条数据
            previous: 前一条数据
            
        Returns:
            True表示满足买入条件，False表示不满足
        """
        # 示例：金叉买入
        ma_short_current = latest['MA_short']
        ma_long_current = latest['MA_long']
        ma_short_prev = previous['MA_short']
        ma_long_prev = previous['MA_long']
        
        # 检测金叉：短期均线上穿长期均线
        if ma_short_prev <= ma_long_prev and ma_short_current > ma_long_current:
            return True
        
        # TODO: 在这里添加你的买入条件
        # 例如:
        # - RSI < 30 (超卖)
        # - MACD金叉
        # - 成交量放大
        # - 突破关键价位
        # ...
        
        return False
    
    def _check_sell_condition(self, latest: pd.Series, previous: pd.Series) -> bool:
        """
        检查卖出条件
        
        在这里实现你的卖出逻辑
        
        Args:
            latest: 最新一条数据
            previous: 前一条数据
            
        Returns:
            True表示满足卖出条件，False表示不满足
        """
        # 示例：死叉卖出
        ma_short_current = latest['MA_short']
        ma_long_current = latest['MA_long']
        ma_short_prev = previous['MA_short']
        ma_long_prev = previous['MA_long']
        
        # 检测死叉：短期均线下穿长期均线
        if ma_short_prev >= ma_long_prev and ma_short_current < ma_long_current:
            return True
        
        # TODO: 在这里添加你的卖出条件
        # 例如:
        # - RSI > 70 (超买)
        # - MACD死叉
        # - 跌破止损线
        # - 达到止盈目标
        # ...
        
        return False
    
    def calculate_position_size(self, signal: Dict, account_info: Dict) -> int:
        """
        计算仓位大小
        
        根据信号和账户情况计算应该买入的股数
        
        Args:
            signal: 交易信号
            account_info: 账户信息 {'available_balance': 可用资金}
            
        Returns:
            购买股数（必须是100的整数倍）
        """
        available_cash = account_info.get('available_balance', 0)
        target_position = signal.get('target_position', 0.1)
        price = signal['price']
        
        # 计算目标金额
        target_value = available_cash * target_position
        
        # 计算股数（向下取整到100的倍数）
        quantity = int(target_value / price / 100) * 100
        
        # 最小100股
        return max(100, quantity)


def test_strategy():
    """测试策略"""
    from src.data import MarketDataManager
    from loguru import logger
    
    print("\n" + "="*60)
    print("  策略测试")
    print("="*60 + "\n")
    
    # 1. 创建策略实例
    print("1. 创建策略...")
    strategy = MyStrategy(param1=5, param2=20)
    print(f"✅ 策略已创建: {strategy.__class__.__name__}\n")
    
    # 2. 获取市场数据
    print("2. 获取市场数据...")
    data_manager = MarketDataManager(data_source='akshare')
    
    # 测试股票（可以修改）
    test_stocks = ['600519', '000001']
    print(f"   测试股票: {', '.join(test_stocks)}")
    
    market_data = data_manager.prepare_strategy_data(
        stock_codes=test_stocks,
        historical_days=100
    )
    
    if not market_data:
        print("❌ 无法获取市场数据")
        return
    
    print(f"✅ 数据已准备:")
    for code, df in market_data.items():
        if df is not None:
            print(f"   {code}: {len(df)}天数据")
    print()
    
    # 3. 生成信号
    print("3. 生成交易信号...")
    signals = strategy.generate_signals(market_data)
    
    if not signals:
        print("⚪ 当前无交易信号\n")
        print("💡 提示:")
        print("   - 这可能是正常的，说明当前不满足策略条件")
        print("   - 尝试调整参数或测试其他股票")
        print("   - 检查数据是否正常")
    else:
        print(f"✅ 生成了 {len(signals)} 个信号:\n")
        
        for i, signal in enumerate(signals, 1):
            action_emoji = "🟢 买入" if signal['action'] == 'buy' else "🔴 卖出"
            
            print(f"信号 #{i}: {action_emoji}")
            print(f"   股票: {signal['stock_code']}")
            print(f"   价格: {signal['price']:.2f}")
            print(f"   原因: {signal['reason']}")
            print(f"   置信度: {signal['confidence']*100:.1f}%")
            print(f"   目标仓位: {signal['target_position']*100:.1f}%")
            print()
    
    print("="*60)
    print("✅ 测试完成")
    print("="*60 + "\n")


if __name__ == "__main__":
    """
    运行此文件即可测试策略:
    python3 my_strategy_template.py
    """
    try:
        test_strategy()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
