#!/usr/bin/env python3
"""
同花顺模拟交易 + 策略自动执行
使用同花顺软件内置的模拟交易功能
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import time
from datetime import datetime
from loguru import logger

from src.api.broker.tonghuashun_desktop import TonghuashunDesktop
from src.core.strategy.strategy_library import strategy_library
from src.data.realtime_data import MarketDataManager


# ==================== 配置区 ====================
CONFIG = {
    # 监控的股票代码
    'stocks': ['600519', '000001', '600036'],
    
    # 使用的策略 ('MA', 'MACD', 'RSI')
    'strategy': 'MA',
    
    # 检查间隔（秒）
    'check_interval': 60,
    
    # 是否自动确认交易（False=每次询问，True=自动执行）
    'auto_confirm': False,
    
    # 单笔交易股数
    'trade_quantity': 100,
}
# ================================================


def print_banner():
    """打印欢迎信息"""
    print("\n" + "="*60)
    print("  同花顺模拟交易 + 策略自动执行")
    print("="*60)
    print("\n📋 配置:")
    print(f"   策略: {CONFIG['strategy']}")
    print(f"   股票: {', '.join(CONFIG['stocks'])}")
    print(f"   间隔: {CONFIG['check_interval']}秒")
    print(f"   自动: {'是' if CONFIG['auto_confirm'] else '否（需确认）'}")
    print("="*60 + "\n")


def check_tonghuashun():
    """检查同花顺状态"""
    print("🔍 检查同花顺...")
    
    broker = TonghuashunDesktop({'auto_start': False})
    
    if broker._is_app_running():
        print("✅ 同花顺正在运行\n")
        return broker
    else:
        print("⚠️  同花顺未运行")
        
        start = input("是否启动同花顺? (y/n): ").strip().lower()
        if start in ['y', 'yes']:
            print("🚀 启动同花顺...")
            if broker.launch_app():
                print("✅ 同花顺已启动")
                print("⏰ 等待5秒...")
                time.sleep(5)
                return broker
        
        print("❌ 无法继续，请先打开同花顺")
        return None


def confirm_simulator_account():
    """确认是否使用模拟账户"""
    print("\n⚠️  重要提醒:")
    print("="*60)
    print("1. 请确保您已登录【模拟交易账户】，而非实盘账户")
    print("2. 确认界面显示'模拟'或虚拟资金")
    print("3. 如果不确定，请先退出，切换到模拟账户")
    print("="*60)
    
    confirm = input("\n✅ 已确认使用模拟账户? (yes/no): ").strip().lower()
    
    if confirm != 'yes':
        print("\n❌ 用户取消，请先切换到模拟账户")
        return False
    
    print("\n✅ 确认使用模拟账户\n")
    return True


def run_strategy_loop(broker, strategy, data_manager):
    """策略循环"""
    
    cycle = 0
    
    try:
        while True:
            cycle += 1
            
            print("\n" + "="*60)
            print(f"第{cycle}轮 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("="*60 + "\n")
            
            # 1. 获取市场数据
            print("📊 获取市场数据...")
            try:
                market_data = data_manager.prepare_strategy_data(
                    CONFIG['stocks'], 
                    historical_days=100
                )
                
                if not market_data:
                    print("❌ 数据获取失败，跳过本轮")
                    time.sleep(CONFIG['check_interval'])
                    continue
                
                print(f"✅ 获取了 {len(market_data)} 只股票的数据")
                
            except Exception as e:
                print(f"❌ 数据获取异常: {e}")
                time.sleep(CONFIG['check_interval'])
                continue
            
            # 2. 生成信号
            print("\n🔍 策略分析...")
            try:
                signals = strategy.generate_signals(market_data)
                
                if not signals:
                    print("⚪ 无交易信号")
                else:
                    print(f"✅ 发现 {len(signals)} 个信号\n")
                    
                    # 3. 处理每个信号
                    for i, signal in enumerate(signals, 1):
                        process_signal(broker, signal, i, len(signals))
                
            except Exception as e:
                print(f"❌ 策略分析异常: {e}")
                import traceback
                traceback.print_exc()
            
            # 4. 查询账户（可选）
            try:
                print("\n💰 查询账户...")
                account = broker.get_account_info()
                if account:
                    print(f"   可用资金: {account.get('available_balance', 'N/A')}")
                else:
                    print("   ⚠️  查询失败（可能需要手动操作）")
                
                positions = broker.get_positions()
                print(f"   当前持仓: {len(positions)}只")
                
            except Exception as e:
                print(f"   ⚠️  查询异常: {e}")
            
            # 5. 等待下一轮
            print(f"\n⏰ 等待{CONFIG['check_interval']}秒...")
            time.sleep(CONFIG['check_interval'])
    
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断策略")
    
    finally:
        print("\n" + "="*60)
        print("策略已停止")
        print("="*60)
        print("\n💡 提示: 请在同花顺查看:")
        print("   - 持仓情况")
        print("   - 历史成交")
        print("   - 资金变化")
        print()


def process_signal(broker, signal, index, total):
    """处理单个交易信号"""
    
    code = signal['stock_code']
    action = signal['action']
    price = signal['price']
    reason = signal['reason']
    confidence = signal.get('confidence', 0.5)
    
    emoji = "🟢 买入" if action == 'buy' else "🔴 卖出"
    
    print(f"信号 #{index}/{total}: {emoji}")
    print(f"   股票: {code}")
    print(f"   价格: {price:.2f}元")
    print(f"   原因: {reason}")
    print(f"   置信度: {confidence*100:.0f}%")
    
    # 决定是否执行
    should_execute = False
    
    if CONFIG['auto_confirm']:
        should_execute = True
        print(f"   🤖 自动执行模式")
    else:
        confirm = input("\n   执行此交易? (y/n, 默认n): ").strip().lower()
        should_execute = confirm in ['y', 'yes']
    
    if not should_execute:
        print("   ⏭️  跳过")
        return
    
    # 执行交易
    try:
        quantity = CONFIG['trade_quantity']
        
        if action == 'buy':
            print(f"   🔄 执行买入: {code} {quantity}股 @ {price:.2f}元")
            success, result = broker.buy(code, price, quantity)
        else:
            print(f"   🔄 执行卖出: {code} {quantity}股 @ {price:.2f}元")
            success, result = broker.sell(code, price, quantity)
        
        if success:
            print(f"   ✅ 交易执行成功!")
            print(f"   提示: 请在同花顺查看委托状态")
        else:
            print(f"   ❌ 交易失败: {result}")
    
    except Exception as e:
        print(f"   ❌ 执行异常: {e}")


def main():
    """主函数"""
    
    # 设置日志
    logger.remove()
    logger.add(sys.stdout, level="WARNING")
    
    # 打印欢迎信息
    print_banner()
    
    # 检查同花顺
    broker = check_tonghuashun()
    if not broker:
        return
    
    # 确认模拟账户
    if not confirm_simulator_account():
        return
    
    # 初始化策略和数据
    print("🔧 初始化...")
    try:
        strategy = strategy_library.get_strategy(CONFIG['strategy'])
        print(f"✅ 策略: {CONFIG['strategy']}")
        
        data_manager = MarketDataManager()
        print(f"✅ 数据管理器已就绪")
        
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        return
    
    # 最后确认
    print("\n" + "="*60)
    print("准备开始自动交易")
    print("="*60)
    print(f"策略: {CONFIG['strategy']}")
    print(f"股票: {', '.join(CONFIG['stocks'])}")
    print(f"间隔: {CONFIG['check_interval']}秒")
    print("="*60)
    
    start = input("\n✅ 确认开始? (yes/no): ").strip().lower()
    if start != 'yes':
        print("\n❌ 用户取消")
        return
    
    # 运行策略
    print("\n🚀 策略开始运行...\n")
    run_strategy_loop(broker, strategy, data_manager)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  程序中断")
    except Exception as e:
        print(f"\n❌ 程序错误: {e}")
        import traceback
        traceback.print_exc()
