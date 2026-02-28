#!/usr/bin/env python3
"""
测试换手率辅助功能

功能：
1. 测试相对换手率计算
2. 测试流动性过滤
3. 测试信号增强
4. 测试MA策略集成换手率辅助
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

import pandas as pd
import numpy as np
from src.strategies.turnover_helper import (
    calc_relative_turnover_rate,
    check_turnover_liquidity,
    enhance_signal_with_turnover
)
from src.strategies.ma_cross import MACrossStrategy

def test_relative_turnover_rate():
    """测试相对换手率计算"""
    print("=" * 80)
    print("测试1: 相对换手率计算")
    print("=" * 80)
    
    # 创建模拟数据
    dates = pd.date_range('2020-01-01', periods=100, freq='D')
    np.random.seed(42)
    
    # 模拟换手率数据（单位：%）
    # 前80天：平均2%，最后20天：平均3%（放量）
    turnover_base = np.random.normal(2.0, 0.3, 80)
    turnover_recent = np.random.normal(3.0, 0.3, 20)
    turnover_values = np.concatenate([turnover_base, turnover_recent])
    turnover_values = np.clip(turnover_values, 0.1, 10.0)  # 限制在合理范围
    
    df = pd.DataFrame({
        'date': dates,
        'open': np.random.randn(100) * 10 + 10,
        'high': np.random.randn(100) * 10 + 11,
        'low': np.random.randn(100) * 10 + 9,
        'close': np.random.randn(100) * 10 + 10,
        'volume': np.random.randint(1000000, 10000000, 100),
        'turnover_rate': turnover_values,
    })
    
    relative_turnover = calc_relative_turnover_rate(df, ma_period=20)
    print(f"  相对换手率: {relative_turnover:.2f}倍")
    print(f"  当前换手率: {df['turnover_rate'].iloc[-1]:.2f}%")
    print(f"  20日均换手率: {df['turnover_rate'].iloc[-21:-1].mean():.2f}%")
    print(f"  预期相对换手率: {df['turnover_rate'].iloc[-1] / df['turnover_rate'].iloc[-21:-1].mean():.2f}倍")
    print()

def test_liquidity_filter():
    """测试流动性过滤"""
    print("=" * 80)
    print("测试2: 流动性过滤")
    print("=" * 80)
    
    test_cases = [
        (0.3, False, "流动性差"),
        (0.5, True, "边界值"),
        (1.0, True, "正常"),
        (2.0, True, "放量"),
        (3.0, True, "边界值"),
        (4.0, False, "异常放量"),
        (None, True, "无数据"),
    ]
    
    for relative_turnover, expected_valid, desc in test_cases:
        is_valid, reason = check_turnover_liquidity(relative_turnover)
        status = "✅" if is_valid == expected_valid else "❌"
        print(f"  {status} {desc}: 相对换手率={relative_turnover}, "
              f"结果={is_valid}, 原因={reason}")
    print()

def test_signal_enhancement():
    """测试信号增强"""
    print("=" * 80)
    print("测试3: 信号增强")
    print("=" * 80)
    
    base_conf = 0.7
    base_pos = 0.8
    
    # 测试突破信号
    print("\n  突破信号:")
    for rel_turnover in [0.5, 1.0, 1.5, 2.0]:
        conf, pos, reason = enhance_signal_with_turnover(
            'breakout', rel_turnover, base_conf, base_pos
        )
        print(f"    相对换手率={rel_turnover:.2f}: "
              f"置信度 {base_conf:.2f}→{conf:.2f}, {reason}")
    
    # 测试回调信号
    print("\n  回调信号:")
    for rel_turnover in [0.5, 0.8, 1.0, 2.0]:
        conf, pos, reason = enhance_signal_with_turnover(
            'pullback', rel_turnover, base_conf, base_pos
        )
        print(f"    相对换手率={rel_turnover:.2f}: "
              f"置信度 {base_conf:.2f}→{conf:.2f}, {reason}")
    print()

def test_ma_strategy_with_turnover():
    """测试MA策略集成换手率辅助"""
    print("=" * 80)
    print("测试4: MA策略集成换手率辅助")
    print("=" * 80)
    
    # 创建模拟数据（包含换手率）
    dates = pd.date_range('2020-01-01', periods=200, freq='D')
    np.random.seed(42)
    
    # 模拟价格数据（形成金叉）
    prices = 10 + np.cumsum(np.random.randn(200) * 0.5)
    
    # 模拟换手率数据
    turnover_values = np.random.normal(2.0, 0.5, 200)
    turnover_values = np.clip(turnover_values, 0.1, 10.0)
    
    df = pd.DataFrame({
        'date': dates,
        'open': prices + np.random.randn(200) * 0.1,
        'high': prices + abs(np.random.randn(200) * 0.2),
        'low': prices - abs(np.random.randn(200) * 0.2),
        'close': prices,
        'volume': np.random.randint(1000000, 10000000, 200),
        'turnover_rate': turnover_values,
    })
    
    strategy = MACrossStrategy(short_window=5, long_window=20)
    
    # 测试1: 正常换手率
    print("\n  测试4.1: 正常换手率（相对换手率≈1.0）")
    signal1 = strategy.analyze(df)
    print(f"    信号: {signal1.action}, 置信度: {signal1.confidence:.2f}, "
          f"仓位: {signal1.position:.2f}")
    print(f"    原因: {signal1.reason}")
    print(f"    相对换手率: {signal1.indicators.get('relative_turnover', 'N/A')}")
    
    # 测试2: 放量突破（相对换手率>1.2）
    print("\n  测试4.2: 放量突破（相对换手率>1.2）")
    df2 = df.copy()
    # 最后一天放量
    df2.loc[df2.index[-1], 'turnover_rate'] = df2['turnover_rate'].iloc[-21:-1].mean() * 1.5
    signal2 = strategy.analyze(df2)
    print(f"    信号: {signal2.action}, 置信度: {signal2.confidence:.2f}, "
          f"仓位: {signal2.position:.2f}")
    print(f"    原因: {signal2.reason}")
    print(f"    相对换手率: {signal2.indicators.get('relative_turnover', 'N/A')}")
    
    # 测试3: 流动性差（相对换手率<0.5）
    print("\n  测试4.3: 流动性差（相对换手率<0.5）")
    df3 = df.copy()
    # 最后一天缩量严重
    df3.loc[df3.index[-1], 'turnover_rate'] = df3['turnover_rate'].iloc[-21:-1].mean() * 0.3
    signal3 = strategy.analyze(df3)
    print(f"    信号: {signal3.action}, 置信度: {signal3.confidence:.2f}, "
          f"仓位: {signal3.position:.2f}")
    print(f"    原因: {signal3.reason}")
    print(f"    相对换手率: {signal3.indicators.get('relative_turnover', 'N/A')}")
    
    print()

def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("换手率辅助功能测试")
    print("=" * 80 + "\n")
    
    test_relative_turnover_rate()
    test_liquidity_filter()
    test_signal_enhancement()
    test_ma_strategy_with_turnover()
    
    print("=" * 80)
    print("测试完成")
    print("=" * 80)

if __name__ == '__main__':
    main()
