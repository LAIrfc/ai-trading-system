#!/usr/bin/env python3
"""
策略测试工具
快速测试策略效果
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
from loguru import logger
from datetime import datetime, timedelta

from src.strategies import STRATEGY_REGISTRY, list_strategies as _list_strategies
from src.data.provider.data_provider import get_default_kline_provider


def print_header():
    """打印标题"""
    print("\n" + "="*60)
    print("  交易策略测试工具")
    print("="*60 + "\n")


def list_strategies():
    """列出所有策略"""
    print("可用策略：\n")
    for i, strategy in enumerate(_list_strategies(), 1):
        print(f"{i:2d}. [{strategy['name']:12s}] {strategy['description']}")
        print(f"      最少K线: {strategy['min_bars']} 根")
    print()


def test_strategy(strategy_name: str, stock_codes: list, params: dict = None):
    """
    测试策略

    Args:
        strategy_name: 策略名称（STRATEGY_REGISTRY 中的 key）
        stock_codes: 股票代码列表
        params: 策略参数
    """
    if strategy_name not in STRATEGY_REGISTRY:
        print(f"未知策略: {strategy_name}，可用策略: {list(STRATEGY_REGISTRY.keys())}")
        return

    print(f"测试策略: {strategy_name}")
    print(f"测试股票: {', '.join(stock_codes)}\n")

    params = params or {}
    strategy = STRATEGY_REGISTRY[strategy_name](**params)
    print(f"策略实例已创建: {strategy.__class__.__name__}")

    provider = get_default_kline_provider()
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=400)).strftime('%Y%m%d')

    for code in stock_codes:
        print(f"\n{'='*50}")
        print(f"股票: {code}")
        print(f"{'='*50}")

        try:
            df = provider.fetch_kline(code, start_date, end_date)
            if df is None or df.empty:
                print(f"  无法获取 {code} 的数据，跳过")
                continue

            print(f"  数据: {len(df)} 个交易日 ({df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')})")

            signal = strategy.safe_analyze(df)

            action_map = {'BUY': '买入', 'SELL': '卖出', 'HOLD': '持有'}
            print(f"  信号: {action_map.get(signal.action, signal.action)}")
            print(f"  置信度: {signal.confidence:.1%}")
            print(f"  建议仓位: {signal.position:.1%}")
            print(f"  理由: {signal.reason}")

            if signal.indicators:
                print("  指标快照:")
                for k, v in list(signal.indicators.items())[:6]:
                    print(f"    {k}: {v}")

        except Exception as e:
            print(f"  测试 {code} 失败: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print("测试完成")
    print(f"{'='*60}")


def interactive_test():
    """交互式测试"""
    print_header()

    list_strategies()
    strategy_keys = list(STRATEGY_REGISTRY.keys())

    while True:
        strategy_input = input(f"选择策略 (1-{len(strategy_keys)}) 或输入策略名: ").strip()
        if strategy_input.isdigit():
            idx = int(strategy_input) - 1
            if 0 <= idx < len(strategy_keys):
                strategy_name = strategy_keys[idx]
                break
        elif strategy_input in strategy_keys:
            strategy_name = strategy_input
            break
        print("无效选择，请重试")

    stock_input = input("\n输入股票代码（多个用逗号分隔，如: 600519,000001）: ").strip()
    stock_codes = [code.strip() for code in stock_input.split(',')]

    print("\n开始测试...\n")
    test_strategy(strategy_name, stock_codes)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='交易策略测试工具')
    parser.add_argument('--strategy', '-s', type=str, help='策略名称')
    parser.add_argument('--stocks', '-t', type=str, help='股票代码，逗号分隔 (如: 600519,000001)')
    parser.add_argument('--list', '-l', action='store_true', help='列出所有可用策略')
    parser.add_argument('--interactive', '-i', action='store_true', help='交互式模式')

    args = parser.parse_args()

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
        print("\n\n用户中断")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
