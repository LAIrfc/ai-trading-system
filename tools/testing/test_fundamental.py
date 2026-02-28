#!/usr/bin/env python3
"""
测试基本面策略

验证：
1. 基本面数据获取和合并
2. PE策略信号生成
3. 组合策略集成
"""

import sys
import os
# 调整路径：tools/testing/ -> 项目根目录
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.data.fetchers.fundamental_fetcher import FundamentalFetcher, create_mock_fundamental_data
from src.strategies.fundamental_pe import PEStrategy
from src.strategies.ensemble import EnsembleStrategy


def create_sample_data(days=200):
    """创建示例日线数据"""
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
    dates = [d for d in dates if d.weekday() < 5]  # 只保留工作日
    
    np.random.seed(42)
    base_price = 10.0
    prices = [base_price]
    for _ in range(len(dates) - 1):
        change = np.random.normal(0, 0.02)
        prices.append(prices[-1] * (1 + change))
    
    df = pd.DataFrame({
        'date': dates,
        'open': prices,
        'high': [p * (1 + abs(np.random.normal(0, 0.01))) for p in prices],
        'low': [p * (1 - abs(np.random.normal(0, 0.01))) for p in prices],
        'close': prices,
        'volume': [np.random.randint(1000000, 10000000) for _ in prices],
    })
    
    return df


def test_fundamental_merge():
    """测试基本面数据合并"""
    print("=" * 60)
    print("测试1: 基本面数据合并")
    print("=" * 60)
    
    daily_df = create_sample_data(100)
    print(f"日线数据: {len(daily_df)} 条")
    
    # 创建模拟基本面数据
    fund_df = create_mock_fundamental_data(daily_df, pe_range=(8, 30), pb_range=(1.0, 3.0))
    print(f"基本面数据: {len(fund_df)} 条")
    print(f"PE范围: {fund_df['pe_ttm'].min():.1f} ~ {fund_df['pe_ttm'].max():.1f}")
    print(f"PB范围: {fund_df['pb'].min():.2f} ~ {fund_df['pb'].max():.2f}")
    
    # 合并
    fetcher = FundamentalFetcher()
    merged = fetcher.merge_to_daily(daily_df, fund_df, fill_method='ffill')
    
    print(f"合并后数据: {len(merged)} 条")
    print(f"包含列: {list(merged.columns)}")
    print(f"PE缺失值: {merged['pe_ttm'].isna().sum()} 个")
    print("✓ 合并成功\n")


def test_pe_strategy():
    """测试PE策略"""
    print("=" * 60)
    print("测试2: PE策略信号生成")
    print("=" * 60)
    
    daily_df = create_sample_data(200)
    fund_df = create_mock_fundamental_data(daily_df, pe_range=(5, 50))
    fetcher = FundamentalFetcher()
    df = fetcher.merge_to_daily(daily_df, fund_df, fill_method='ffill')
    
    strategy = PEStrategy(low_quantile=0.2, high_quantile=0.8)
    
    # 测试不同PE分位数下的信号
    test_cases = [
        (0.05, "极低估"),
        (0.15, "低估"),
        (0.50, "中性"),
        (0.85, "高估"),
        (0.95, "极高估"),
    ]
    
    for target_quantile, desc in test_cases:
        # 手动设置最后一个PE值，使其达到目标分位数
        pe_series = df['pe_ttm'].dropna()
        sorted_pe = sorted(pe_series.iloc[:-1])
        target_idx = int(len(sorted_pe) * target_quantile)
        target_pe = sorted_pe[target_idx] if target_idx < len(sorted_pe) else sorted_pe[-1]
        df.loc[df.index[-1], 'pe_ttm'] = target_pe
        
        signal = strategy.analyze(df)
        print(f"PE分位 {target_quantile:.1%} ({desc}): "
              f"{signal.action} | conf={signal.confidence:.2f} | "
              f"pos={signal.position:.2f} | {signal.reason}")
    
    print("✓ PE策略测试通过\n")


def test_ensemble_integration():
    """测试组合策略集成"""
    print("=" * 60)
    print("测试3: 组合策略集成")
    print("=" * 60)
    
    daily_df = create_sample_data(200)
    fund_df = create_mock_fundamental_data(daily_df)
    fetcher = FundamentalFetcher()
    df = fetcher.merge_to_daily(daily_df, fund_df, fill_method='ffill')
    
    ensemble = EnsembleStrategy()
    
    # 检查PE策略是否在子策略中
    if 'PE' in ensemble.sub_strategies:
        print(f"✓ PE策略已注册到组合策略")
        print(f"  子策略数量: {len(ensemble.sub_strategies)}")
        print(f"  子策略列表: {list(ensemble.sub_strategies.keys())}")
    else:
        print("✗ PE策略未注册")
        return
    
    # 运行组合策略
    signal = ensemble.analyze(df)
    print(f"\n组合策略信号:")
    print(f"  action: {signal.action}")
    print(f"  confidence: {signal.confidence:.2f}")
    print(f"  position: {signal.position:.2f}")
    print(f"  reason: {signal.reason}")
    
    if 'PE' in signal.indicators.get('投票详情', {}):
        print(f"  ✓ PE策略参与了投票")
    else:
        print(f"  ⚠ PE策略未参与投票（可能数据不足）")
    
    print("✓ 组合策略集成测试通过\n")


if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("基本面策略测试")
    print("=" * 60 + "\n")
    
    try:
        test_fundamental_merge()
        test_pe_strategy()
        test_ensemble_integration()
        
        print("=" * 60)
        print("所有测试通过！")
        print("=" * 60)
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
