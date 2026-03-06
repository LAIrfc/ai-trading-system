#!/usr/bin/env python3
"""
双核动量策略 - 快速测试脚本

快速验证策略是否能正常运行（使用较短的数据周期）
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.etf_data_fetcher import ETFDataFetcher
from src.core.strategy.dual_momentum_strategy import DualMomentumStrategy
from loguru import logger
from datetime import datetime

logger.remove()
logger.add(sys.stderr, level="INFO")

print("="*60)
print("双核动量策略 - 快速测试")
print("="*60)

# 1. 获取数据（只获取1年，快速测试）
print("\n[1/3] 获取ETF数据...")
etf_codes = ['510300', '159949', '513100', '518880', '511520']

fetcher = ETFDataFetcher()
data = fetcher.get_etf_pool_data(
    codes=etf_codes,
    start_date='20230101',  # 1年数据足够测试
    end_date=datetime.now().strftime('%Y%m%d')
)

if data.empty:
    print("❌ 数据获取失败")
    sys.exit(1)

print(f"✅ 数据获取成功: {data.shape[0]} 个交易日")

# 2. 初始化策略
print("\n[2/3] 初始化策略...")
strategy_config = {
    'absolute_period': 200,
    'relative_period': 60,
    'rebalance_days': 20,
    'top_k': 1,
    'etf_pool': etf_codes,
}

strategy = DualMomentumStrategy(strategy_config)
print(f"✅ 策略初始化完成")

# 3. 生成信号
print("\n[3/3] 生成交易信号...")
signals = strategy.generate_signals(data)

print("\n" + "="*60)
print("交易信号")
print("="*60)

if signals.empty:
    print("当前无交易信号")
else:
    print(signals.to_string(index=False))

print("\n" + "="*60)
print("策略状态")
print("="*60)
info = strategy.get_strategy_info()
print(f"策略名称: {info['name']}")
print(f"版本: {info['version']}")
print(f"当前持仓: {info['current_holdings'] if info['current_holdings'] else '空仓'}")
print(f"黑名单: {info['blacklist'] if info['blacklist'] else '无'}")
print(f"熔断模式: {'是' if info['emergency_mode'] else '否'}")

print("\n✅ 测试完成！")
print("\n💡 运行完整回测:")
print("   python tools/backtest_dual_momentum.py")
