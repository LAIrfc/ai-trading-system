#!/usr/bin/env python3
"""
测试PB策略和PE+PB双因子策略

功能：
1. 测试PB策略信号生成
2. 测试PE+PB双因子策略信号生成
3. 测试ROE过滤（待ROE数据获取实现后）
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

import pandas as pd
import numpy as np
from src.strategies.fundamental_pb import PBStrategy
from src.strategies.fundamental_pe_pb import PE_PB_CombinedStrategy

def test_pb_strategy():
    """测试PB策略"""
    print("=" * 80)
    print("测试1: PB策略")
    print("=" * 80)
    
    # 创建模拟数据
    dates = pd.date_range('2020-01-01', periods=800, freq='D')
    np.random.seed(42)
    
    # 模拟PB数据（银行股，PB通常较低）
    pb_values = np.random.normal(1.0, 0.3, 800)  # 均值1.0，标准差0.3
    pb_values = np.clip(pb_values, 0.3, 3.0)  # 限制在0.3-3.0之间
    
    df = pd.DataFrame({
        'date': dates,
        'open': np.random.randn(800) * 10 + 10,
        'high': np.random.randn(800) * 10 + 11,
        'low': np.random.randn(800) * 10 + 9,
        'close': np.random.randn(800) * 10 + 10,
        'volume': np.random.randint(1000000, 10000000, 800),
        'pb': pb_values,
    })
    
    # 测试1: 不使用行业（默认方式）
    print("\n测试1.1: 不使用行业（默认方式）")
    strategy1 = PBStrategy()
    signal1 = strategy1.analyze(df)
    print(f"  信号: {signal1.action}, 置信度: {signal1.confidence:.2f}, 仓位: {signal1.position:.2f}")
    print(f"  原因: {signal1.reason}")
    print(f"  PB分位数: {signal1.indicators.get('pb_quantile', 'N/A')}")
    print(f"  当前PB: {signal1.indicators.get('pb', 'N/A')}")
    print(f"  ROE过滤: {signal1.indicators.get('roe_filter', 'N/A')}")
    
    # 测试2: 使用行业信息
    print("\n测试1.2: 使用行业信息（银行）")
    strategy2 = PBStrategy(industry='银行')
    signal2 = strategy2.analyze(df)
    print(f"  信号: {signal2.action}, 置信度: {signal2.confidence:.2f}, 仓位: {signal2.position:.2f}")
    print(f"  原因: {signal2.reason}")
    print(f"  行业: {signal2.indicators.get('industry', 'N/A')}")
    
    # 测试3: 模拟ROE数据（测试ROE过滤）
    print("\n测试1.3: 模拟ROE数据（测试ROE过滤）")
    df3 = df.copy()
    # 添加ROE数据（最近3年都>8%）
    roe_values = np.random.normal(12.0, 2.0, 800)  # 均值12%，标准差2%
    roe_values = np.clip(roe_values, 8.0, 20.0)  # 限制在8-20%之间
    df3['roe'] = roe_values
    
    strategy3 = PBStrategy(industry='银行', min_roe=8.0)
    signal3 = strategy3.analyze(df3)
    print(f"  信号: {signal3.action}, 置信度: {signal3.confidence:.2f}, 仓位: {signal3.position:.2f}")
    print(f"  原因: {signal3.reason}")
    print(f"  ROE过滤: {signal3.indicators.get('roe_filter', 'N/A')}")
    print(f"  ROE原因: {signal3.indicators.get('roe_reason', 'N/A')}")
    
    print()

def test_pe_pb_combined_strategy():
    """测试PE+PB双因子策略"""
    print("=" * 80)
    print("测试2: PE+PB双因子策略")
    print("=" * 80)
    
    # 创建模拟数据（包含PE和PB）
    dates = pd.date_range('2020-01-01', periods=800, freq='D')
    np.random.seed(42)
    
    # 模拟PE数据
    pe_values = np.random.normal(10, 3, 800)
    pe_values = np.clip(pe_values, 5, 30)
    
    # 模拟PB数据
    pb_values = np.random.normal(1.5, 0.4, 800)
    pb_values = np.clip(pb_values, 0.5, 3.0)
    
    df = pd.DataFrame({
        'date': dates,
        'open': np.random.randn(800) * 10 + 10,
        'high': np.random.randn(800) * 10 + 11,
        'low': np.random.randn(800) * 10 + 9,
        'close': np.random.randn(800) * 10 + 10,
        'volume': np.random.randint(1000000, 10000000, 800),
        'pe_ttm': pe_values,
        'pb': pb_values,
    })
    
    # 测试1: 双低估（PE和PB都低估）
    print("\n测试2.1: 双低估（PE和PB都低估）")
    # 调整最后一天的PE和PB，使其都低估
    df1 = df.copy()
    df1.loc[df1.index[-1], 'pe_ttm'] = df1['pe_ttm'].quantile(0.1)  # 10%分位
    df1.loc[df1.index[-1], 'pb'] = df1['pb'].quantile(0.1)  # 10%分位
    
    strategy1 = PE_PB_CombinedStrategy()
    signal1 = strategy1.analyze(df1)
    print(f"  信号: {signal1.action}, 置信度: {signal1.confidence:.2f}, 仓位: {signal1.position:.2f}")
    print(f"  原因: {signal1.reason}")
    print(f"  PE分位数: {signal1.indicators.get('pe_quantile', 'N/A'):.3f}")
    print(f"  PB分位数: {signal1.indicators.get('pb_quantile', 'N/A'):.3f}")
    
    # 测试2: 双高估（PE和PB都高估）
    print("\n测试2.2: 双高估（PE和PB都高估）")
    df2 = df.copy()
    df2.loc[df2.index[-1], 'pe_ttm'] = df2['pe_ttm'].quantile(0.9)  # 90%分位
    df2.loc[df2.index[-1], 'pb'] = df2['pb'].quantile(0.9)  # 90%分位
    
    strategy2 = PE_PB_CombinedStrategy()
    signal2 = strategy2.analyze(df2)
    print(f"  信号: {signal2.action}, 置信度: {signal2.confidence:.2f}, 仓位: {signal2.position:.2f}")
    print(f"  原因: {signal2.reason}")
    
    # 测试3: PE高估但PB不高估（"或"逻辑，应该卖出）
    print("\n测试2.3: PE高估但PB不高估（\"或\"逻辑，应该卖出）")
    df3 = df.copy()
    df3.loc[df3.index[-1], 'pe_ttm'] = df3['pe_ttm'].quantile(0.9)  # PE高估
    df3.loc[df3.index[-1], 'pb'] = df3['pb'].quantile(0.5)  # PB中性
    
    strategy3 = PE_PB_CombinedStrategy()
    signal3 = strategy3.analyze(df3)
    print(f"  信号: {signal3.action}, 置信度: {signal3.confidence:.2f}, 仓位: {signal3.position:.2f}")
    print(f"  原因: {signal3.reason}")
    print(f"  PE分位数: {signal3.indicators.get('pe_quantile', 'N/A'):.3f}")
    print(f"  PB分位数: {signal3.indicators.get('pb_quantile', 'N/A'):.3f}")
    
    # 测试4: PE低估但PB不低估（"与"逻辑，不应该买入）
    print("\n测试2.4: PE低估但PB不低估（\"与\"逻辑，不应该买入）")
    df4 = df.copy()
    df4.loc[df4.index[-1], 'pe_ttm'] = df4['pe_ttm'].quantile(0.1)  # PE低估
    df4.loc[df4.index[-1], 'pb'] = df4['pb'].quantile(0.5)  # PB中性
    
    strategy4 = PE_PB_CombinedStrategy()
    signal4 = strategy4.analyze(df4)
    print(f"  信号: {signal4.action}, 置信度: {signal4.confidence:.2f}, 仓位: {signal4.position:.2f}")
    print(f"  原因: {signal4.reason}")
    print(f"  PE分位数: {signal4.indicators.get('pe_quantile', 'N/A'):.3f}")
    print(f"  PB分位数: {signal4.indicators.get('pb_quantile', 'N/A'):.3f}")
    
    print()

def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("PB策略和PE+PB双因子策略测试")
    print("=" * 80 + "\n")
    
    test_pb_strategy()
    test_pe_pb_combined_strategy()
    
    print("=" * 80)
    print("测试完成")
    print("=" * 80)

if __name__ == '__main__':
    main()
