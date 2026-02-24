#!/usr/bin/env python3
"""
模拟交易演示
使用模拟账户测试交易策略，完全安全，无资金风险
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import time
from datetime import datetime
from loguru import logger

from src.core.simulator.paper_trading import PaperTradingAccount
from src.core.strategy.strategy_library import strategy_library
from src.data.realtime_data import MarketDataManager


def demo_manual_trading():
    """手动交易演示"""
    print("\n" + "="*60)
    print("  模拟交易 - 手动模式")
    print("="*60 + "\n")
    
    # 创建模拟账户
    account = PaperTradingAccount(initial_capital=100000.0)
    print(f"✅ 模拟账户已创建，初始资金: 100,000元\n")
    
    # 获取实时数据
    data_manager = MarketDataManager()
    
    while True:
        print("\n" + "-"*60)
        print("操作菜单:")
        print("1. 买入")
        print("2. 卖出")
        print("3. 查看账户")
        print("4. 查看持仓")
        print("5. 查看成交")
        print("6. 更新市场价格")
        print("0. 退出")
        print("-"*60)
        
        choice = input("\n请选择 (0-6): ").strip()
        
        if choice == '1':
            # 买入
            stock_code = input("股票代码: ").strip()
            
            # 获取当前价格
            quotes = data_manager.get_realtime_data([stock_code], force_update=True)
            if stock_code not in quotes or not quotes[stock_code]:
                print("❌ 无法获取股票行情")
                continue
            
            quote = quotes[stock_code]
            print(f"\n{stock_code} - {quote['name']}")
            print(f"当前价: {quote['price']:.2f}元")
            print(f"涨跌幅: {quote['change_pct']:+.2f}%")
            
            price = float(input(f"买入价格 (默认{quote['price']:.2f}): ") or quote['price'])
            quantity = int(input("买入数量 (100的倍数): "))
            
            success, result = account.buy(stock_code, price, quantity)
            
            if success:
                print(f"\n✅ 买入成功!")
                print(f"   订单号: {result}")
                print(f"   成交价: {price:.2f}元")
                print(f"   数量: {quantity}股")
                print(f"   金额: {price * quantity:,.2f}元")
            else:
                print(f"\n❌ 买入失败: {result}")
        
        elif choice == '2':
            # 卖出
            if not account.positions:
                print("\n⚠️  当前无持仓")
                continue
            
            print("\n当前持仓:")
            for i, (code, pos) in enumerate(account.positions.items(), 1):
                print(f"{i}. {code} - {pos.quantity}股 @ {pos.cost_price:.2f}元")
            
            stock_code = input("\n股票代码: ").strip()
            
            if stock_code not in account.positions:
                print("❌ 没有该股票持仓")
                continue
            
            pos = account.positions[stock_code]
            
            # 获取当前价格
            quotes = data_manager.get_realtime_data([stock_code], force_update=True)
            if stock_code in quotes and quotes[stock_code]:
                current_price = quotes[stock_code]['price']
            else:
                current_price = pos.current_price
            
            print(f"\n持仓: {pos.quantity}股")
            print(f"成本价: {pos.cost_price:.2f}元")
            print(f"当前价: {current_price:.2f}元")
            
            price = float(input(f"卖出价格 (默认{current_price:.2f}): ") or current_price)
            quantity = int(input(f"卖出数量 (最多{pos.quantity}): "))
            
            success, result = account.sell(stock_code, price, quantity)
            
            if success:
                print(f"\n✅ 卖出成功!")
                print(f"   订单号: {result}")
                print(f"   成交价: {price:.2f}元")
                print(f"   数量: {quantity}股")
                print(f"   金额: {price * quantity:,.2f}元")
            else:
                print(f"\n❌ 卖出失败: {result}")
        
        elif choice == '3':
            # 查看账户
            account.print_summary()
        
        elif choice == '4':
            # 查看持仓
            print("\n📊 当前持仓:")
            if account.positions:
                for code, pos in account.positions.items():
                    profit_emoji = "📈" if pos.profit >= 0 else "📉"
                    print(f"\n{profit_emoji} {code}")
                    print(f"   数量: {pos.quantity}股")
                    print(f"   成本: {pos.cost_price:.2f}元")
                    print(f"   现价: {pos.current_price:.2f}元")
                    print(f"   市值: {pos.market_value:,.2f}元")
                    print(f"   盈亏: {pos.profit:+,.2f}元 ({pos.profit_pct:+.2f}%)")
            else:
                print("   暂无持仓")
        
        elif choice == '5':
            # 查看成交
            print("\n📝 成交记录:")
            trades = account.get_trades()
            if trades:
                for trade in trades[-10:]:  # 最近10条
                    side_emoji = "🟢 买入" if trade['side'] == 'buy' else "🔴 卖出"
                    print(f"\n{side_emoji}")
                    print(f"   股票: {trade['stock_code']}")
                    print(f"   价格: {trade['price']:.2f}元")
                    print(f"   数量: {trade['quantity']}股")
                    print(f"   金额: {trade['amount']:,.2f}元")
                    print(f"   手续费: {trade['commission']:.2f}元")
                    print(f"   时间: {trade['trade_time'][:19]}")
            else:
                print("   暂无成交记录")
        
        elif choice == '6':
            # 更新市场价格
            if not account.positions:
                print("\n⚠️  当前无持仓")
                continue
            
            print("\n🔄 更新市场价格...")
            codes = list(account.positions.keys())
            quotes = data_manager.get_realtime_data(codes, force_update=True)
            
            prices = {}
            for code, quote in quotes.items():
                if quote:
                    prices[code] = quote['price']
            
            account.update_market_prices(prices)
            print("✅ 价格已更新\n")
            
            # 显示持仓
            for code, pos in account.positions.items():
                profit_emoji = "📈" if pos.profit >= 0 else "📉"
                print(f"{profit_emoji} {code}: {pos.current_price:.2f}元 ({pos.profit_pct:+.2f}%)")
        
        elif choice == '0':
            # 退出
            print("\n保存账户数据...")
            filename = f"data/paper_trading_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            account.save_to_file(filename)
            print(f"✅ 已保存到: {filename}")
            
            account.print_summary()
            print("\n再见！👋\n")
            break
        
        else:
            print("\n❌ 无效选择")


def demo_strategy_trading():
    """策略自动交易演示"""
    print("\n" + "="*60)
    print("  模拟交易 - 策略自动模式")
    print("="*60 + "\n")
    
    # 创建模拟账户
    account = PaperTradingAccount(initial_capital=100000.0)
    print(f"✅ 模拟账户已创建，初始资金: 100,000元\n")
    
    # 选择策略
    print("选择策略:")
    print("1. MA (均线策略)")
    print("2. MACD策略")
    print("3. RSI策略")
    
    strategy_choice = input("\n请选择 (1-3): ").strip()
    
    strategy_map = {'1': 'MA', '2': 'MACD', '3': 'RSI'}
    strategy_name = strategy_map.get(strategy_choice, 'MA')
    
    strategy = strategy_library.get_strategy(strategy_name)
    print(f"\n✅ 策略已选择: {strategy_name}\n")
    
    # 选择股票
    stock_input = input("输入股票代码（多个用逗号分隔，如600519,000001）: ").strip()
    stock_codes = [code.strip() for code in stock_input.split(',')]
    
    print(f"\n📊 监控股票: {', '.join(stock_codes)}")
    print("🔄 策略运行中... (按Ctrl+C停止)\n")
    
    # 数据管理器
    data_manager = MarketDataManager()
    
    cycle_count = 0
    
    try:
        while True:
            cycle_count += 1
            print(f"\n--- 第{cycle_count}轮 {datetime.now().strftime('%H:%M:%S')} ---")
            
            # 获取市场数据
            market_data = data_manager.prepare_strategy_data(stock_codes, historical_days=100)
            
            # 生成信号
            signals = strategy.generate_signals(market_data)
            
            if signals:
                print(f"✅ 生成了 {len(signals)} 个信号:")
                
                for signal in signals:
                    action_emoji = "🟢 买入" if signal['action'] == 'buy' else "🔴 卖出"
                    print(f"\n{action_emoji} 信号")
                    print(f"   股票: {signal['stock_code']}")
                    print(f"   原因: {signal['reason']}")
                    print(f"   价格: {signal['price']:.2f}元")
                    print(f"   置信度: {signal['confidence']*100:.0f}%")
                    
                    # 执行交易
                    if signal['action'] == 'buy':
                        # 计算仓位
                        account_info = account.get_account_info()
                        target_position = signal.get('target_position', 0.1)
                        target_value = account_info['cash'] * target_position
                        quantity = int(target_value / signal['price'] / 100) * 100
                        quantity = max(100, quantity)
                        
                        success, result = account.buy(signal['stock_code'], signal['price'], quantity)
                        
                        if success:
                            print(f"   ✅ 买入成功: {quantity}股")
                        else:
                            print(f"   ❌ 买入失败: {result}")
                    
                    elif signal['action'] == 'sell':
                        # 检查持仓
                        if signal['stock_code'] in account.positions:
                            pos = account.positions[signal['stock_code']]
                            quantity = pos.quantity
                            
                            success, result = account.sell(signal['stock_code'], signal['price'], quantity)
                            
                            if success:
                                print(f"   ✅ 卖出成功: {quantity}股")
                            else:
                                print(f"   ❌ 卖出失败: {result}")
                        else:
                            print(f"   ⚠️  无持仓，跳过")
            else:
                print("⚪ 无交易信号")
            
            # 更新持仓价格
            if account.positions:
                codes = list(account.positions.keys())
                quotes = data_manager.get_realtime_data(codes, force_update=True)
                prices = {code: quote['price'] for code, quote in quotes.items() if quote}
                account.update_market_prices(prices)
            
            # 显示账户摘要
            info = account.get_account_info()
            print(f"\n💰 账户: 总资产{info['total_assets']:,.0f}元 | "
                  f"盈亏{info['total_profit']:+,.0f}元({info['total_profit_pct']:+.2f}%) | "
                  f"持仓{info['position_count']}只")
            
            # 等待下一轮
            print("\n等待30秒...")
            time.sleep(30)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  策略已停止")
    
    finally:
        # 保存并显示结果
        print("\n保存账户数据...")
        filename = f"data/paper_trading_strategy_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        account.save_to_file(filename)
        
        account.print_summary()
        print(f"\n✅ 数据已保存到: {filename}\n")


def main():
    """主函数"""
    
    # 设置日志
    logger.remove()
    logger.add(sys.stdout, level="WARNING")
    
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║                                                          ║")
    print("║          模拟交易系统 - 安全测试交易策略                ║")
    print("║                                                          ║")
    print("║  ✅ 完全模拟，无真实资金                                ║")
    print("║  ✅ 使用实时行情数据                                    ║")
    print("║  ✅ 真实手续费计算                                      ║")
    print("║  ✅ 可保存和回放                                        ║")
    print("║                                                          ║")
    print("╚══════════════════════════════════════════════════════════╝")
    
    print("\n选择模式:")
    print("1. 手动交易模式 (自己控制买卖)")
    print("2. 策略自动模式 (策略自动交易)")
    
    mode = input("\n请选择 (1-2): ").strip()
    
    if mode == '1':
        demo_manual_trading()
    elif mode == '2':
        demo_strategy_trading()
    else:
        print("❌ 无效选择")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
