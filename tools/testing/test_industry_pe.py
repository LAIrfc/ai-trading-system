#!/usr/bin/env python3
"""
测试行业分类和分行业PE分位数计算

功能：
1. 测试获取行业分类
2. 测试PE策略支持行业参数
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

import pandas as pd
import numpy as np
from src.data.fetchers.fundamental_fetcher import FundamentalFetcher
from src.strategies.fundamental_pe import PEStrategy

def test_industry_classification():
    """测试获取行业分类"""
    print("=" * 80)
    print("测试1: 获取行业分类")
    print("=" * 80)
    
    fetcher = FundamentalFetcher(source='tushare')
    
    # 测试几只不同行业的股票
    test_codes = ['600000', '000001', '000002', '600036']  # 浦发银行、平安银行、万科A、招商银行
    
    for code in test_codes:
        industry = fetcher.get_industry_classification(code)
        print(f"  {code}: {industry if industry else '未获取到'}")
    
    print()

def test_pe_strategy_with_industry():
    """测试PE策略支持行业参数"""
    print("=" * 80)
    print("测试2: PE策略支持行业参数")
    print("=" * 80)
    
    # 创建模拟数据
    dates = pd.date_range('2020-01-01', periods=800, freq='D')
    np.random.seed(42)
    
    # 模拟PE数据（银行股，PE通常较低）
    pe_values = np.random.normal(8, 2, 800)  # 均值8，标准差2
    pe_values = np.clip(pe_values, 3, 20)  # 限制在3-20之间
    
    df = pd.DataFrame({
        'date': dates,
        'open': np.random.randn(800) * 10 + 10,
        'high': np.random.randn(800) * 10 + 11,
        'low': np.random.randn(800) * 10 + 9,
        'close': np.random.randn(800) * 10 + 10,
        'volume': np.random.randint(1000000, 10000000, 800),
        'pe_ttm': pe_values,
    })
    
    # 测试1: 不使用行业（默认方式）
    print("\n测试2.1: 不使用行业（默认方式）")
    strategy1 = PEStrategy()
    signal1 = strategy1.analyze(df)
    print(f"  信号: {signal1.action}, 置信度: {signal1.confidence:.2f}, 仓位: {signal1.position:.2f}")
    print(f"  分位数方法: {signal1.indicators.get('quantile_method', 'N/A')}")
    print(f"  行业: {signal1.indicators.get('industry', 'N/A')}")
    
    # 测试2: 使用行业信息（但不提供行业PE数据，使用当前股票数据）
    print("\n测试2.2: 使用行业信息（但不提供行业PE数据）")
    strategy2 = PEStrategy(industry='银行')
    signal2 = strategy2.analyze(df)
    print(f"  信号: {signal2.action}, 置信度: {signal2.confidence:.2f}, 仓位: {signal2.position:.2f}")
    print(f"  分位数方法: {signal2.indicators.get('quantile_method', 'N/A')}")
    print(f"  行业: {signal2.indicators.get('industry', 'N/A')}")
    
    # 测试3: 使用行业PE数据（模拟同行业所有股票的PE数据）
    print("\n测试2.3: 使用行业PE数据（模拟同行业所有股票的PE数据）")
    # 模拟行业PE数据（银行行业，PE通常较低，范围3-15）
    industry_pe = np.random.normal(7, 1.5, 1000)  # 1000个银行股的PE数据
    industry_pe = np.clip(industry_pe, 3, 15)
    industry_pe_series = pd.Series(industry_pe)
    
    strategy3 = PEStrategy(industry='银行', industry_pe_data=industry_pe_series)
    signal3 = strategy3.analyze(df)
    print(f"  信号: {signal3.action}, 置信度: {signal3.confidence:.2f}, 仓位: {signal3.position:.2f}")
    print(f"  分位数方法: {signal3.indicators.get('quantile_method', 'N/A')}")
    print(f"  行业: {signal3.indicators.get('industry', 'N/A')}")
    print(f"  当前PE: {signal3.indicators.get('pe_ttm', 'N/A')}")
    print(f"  PE分位数: {signal3.indicators.get('pe_quantile', 'N/A'):.3f}")
    
    print()

def main():
    """主函数"""
    print("\n" + "=" * 80)
    print("行业分类和分行业PE分位数计算测试")
    print("=" * 80 + "\n")
    
    # 测试1: 获取行业分类（需要tushare token）
    try:
        test_industry_classification()
    except Exception as e:
        print(f"⚠️  行业分类测试失败（可能需要配置tushare token）: {e}\n")
    
    # 测试2: PE策略支持行业参数
    test_pe_strategy_with_industry()
    
    print("=" * 80)
    print("测试完成")
    print("=" * 80)

if __name__ == '__main__':
    main()
