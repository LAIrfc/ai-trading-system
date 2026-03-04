#!/usr/bin/env python3
"""
策略测试工具
快速测试策略效果
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from loguru import logger
from datetime import datetime, timedelta

from src.core.strategy.strategy_library import strategy_library
from src.data.fetchers.realtime_data import MarketDataManager


def print_header():
    """打印标题"""
    print("\n" + "="*60)
    print("  交易策略测试工具")
    print("="*60 + "\n")


def list_strategies():
    """列出所有策略"""
    print("📚 可用策略：\n")
    
    strategies = strategy_library.list_strategies()
    
    for i, strategy in enumerate(strategies, 1):
        print(f"{i}. {strategy['name']}")
        print(f"   {strategy['description']}\n")


def test_strategy(strategy_name: str, stock_codes: list, params: dict = None):
    """
    测试策略
    
    Args:
        strategy_name: 策略名称
        stock_codes: 股票代码列表
        params: 策略参数
    """
    print(f"🧪 测试策略: {strategy_name}")
    print(f"📊 测试股票: {', '.join(stock_codes)}\n")
    
    try:
        # 1. 创建策略实例
        params = params or {}
        strategy = strategy_library.get_strategy(strategy_name, **params)
        print(f"✅ 策略实例已创建: {strategy.__class__.__name__}")
        
        # 2. 获取市场数据
        print(f"\n📡 获取市场数据...")
        data_manager = MarketDataManager(data_source='akshare')
        
        market_data = data_manager.prepare_strategy_data(
            stock_codes=stock_codes,
            historical_days=100
        )
        
        if not market_data:
            print("❌ 无法获取市场数据")
            return
        
        print(f"✅ 数据已准备:")
        for code, df in market_data.items():
            if df is not None and not df.empty:
                print(f"   {code}: {len(df)}个交易日数据")
        
        # 3. 生成信号
        print(f"\n🔍 生成交易信号...")
        signals = strategy.generate_signals(market_data)
        
        if not signals:
            print("⚪ 当前无交易信号")
        else:
            print(f"✅ 生成了 {len(signals)} 个信号:\n")
            
            for i, signal in enumerate(signals, 1):
                action_emoji = "🟢 买入" if signal['action'] == 'buy' else "🔴 卖出"
                print(f"{i}. {action_emoji}")
                print(f"   股票: {signal['stock_code']}")
                print(f"   信号: {signal.get('signal_type', 'N/A')}")
                print(f"   原因: {signal.get('reason', 'N/A')}")
                print(f"   价格: {signal.get('price', 'N/A'):.2f}")
                print(f"   置信度: {signal.get('confidence', 0)*100:.1f}%")
                print(f"   目标仓位: {signal.get('target_position', 0)*100:.1f}%")
                print()
        
        # 4. 显示最新行情
        print(f"\n📈 最新行情:")
        realtime = data_manager.get_realtime_data(stock_codes, force_update=True)
        
        for code, quote in realtime.items():
            if quote:
                print(f"\n{code} - {quote.get('name', 'N/A')}")
                print(f"   价格: {quote['price']:.2f}")
                print(f"   涨跌幅: {quote['change_pct']:+.2f}%")
                print(f"   今开: {quote['open']:.2f}")
                print(f"   最高: {quote['high']:.2f}")
                print(f"   最低: {quote['low']:.2f}")
                print(f"   成交量: {quote['volume']/10000:.0f}万手")
        
        print("\n" + "="*60)
        print("✅ 测试完成")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


def interactive_test():
    """交互式测试"""
    print_header()
    
    # 1. 选择策略
    list_strategies()
    
    strategies = strategy_library.list_strategies()
    strategy_names = [s['name'] for s in strategies]
    
    while True:
        strategy_input = input(f"选择策略 (1-{len(strategies)}) 或输入策略名: ").strip()
        
        if strategy_input.isdigit():
            idx = int(strategy_input) - 1
            if 0 <= idx < len(strategies):
                strategy_name = strategies[idx]['name']
                break
        elif strategy_input in strategy_names:
            strategy_name = strategy_input
            break
        
        print("❌ 无效选择，请重试")
    
    # 2. 输入股票代码
    print(f"\n输入股票代码（多个用逗号分隔，如: 600519,000001）")
    stock_input = input("股票代码: ").strip()
    stock_codes = [code.strip() for code in stock_input.split(',')]
    
    # 3. 参数配置（可选）
    params = {}
    configure = input("\n是否配置参数? (y/n, 默认n): ").strip().lower()
    
    if configure == 'y':
        if strategy_name == 'MA':
            params['short_window'] = int(input("短期均线周期 (默认5): ") or 5)
            params['long_window'] = int(input("长期均线周期 (默认20): ") or 20)
        elif strategy_name == 'MACD':
            params['fast_period'] = int(input("快速周期 (默认12): ") or 12)
            params['slow_period'] = int(input("慢速周期 (默认26): ") or 26)
            params['signal_period'] = int(input("信号周期 (默认9): ") or 9)
        elif strategy_name == 'RSI':
            params['period'] = int(input("RSI周期 (默认14): ") or 14)
            params['oversold'] = int(input("超卖阈值 (默认30): ") or 30)
            params['overbought'] = int(input("超买阈值 (默认70): ") or 70)
    
    # 4. 运行测试
    print("\n开始测试...\n")
    test_strategy(strategy_name, stock_codes, params)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='交易策略测试工具')
    
    parser.add_argument('--strategy', '-s', type=str, help='策略名称 (MA, MACD, RSI)')
    parser.add_argument('--stocks', '-t', type=str, help='股票代码，逗号分隔 (如: 600519,000001)')
    parser.add_argument('--list', '-l', action='store_true', help='列出所有可用策略')
    parser.add_argument('--interactive', '-i', action='store_true', help='交互式模式')
    
    args = parser.parse_args()
    
    # 设置日志
    logger.remove()
    logger.add(sys.stdout, level="WARNING")
    
    if args.list:
        print_header()
        list_strategies()
    
    elif args.interactive or (not args.strategy and not args.stocks):
        interactive_test()
    
    elif args.strategy and args.stocks:
        print_header()
        stock_codes = [code.strip() for code in args.stocks.split(',')]
        test_strategy(args.strategy, stock_codes)
    
    else:
        parser.print_help()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
