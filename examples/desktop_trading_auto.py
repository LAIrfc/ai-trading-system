#!/usr/bin/env python3
"""
同花顺桌面客户端 - 模拟炒股自动化测试
不需要用户输入，自动启动同花顺并测试功能

用法：
    python3 examples/desktop_trading_auto.py                    # 默认：只查询
    python3 examples/desktop_trading_auto.py --action buy       # 测试买入
    python3 examples/desktop_trading_auto.py --action sell      # 测试卖出
    python3 examples/desktop_trading_auto.py --real             # 真实下单（慎用！）
"""

import sys
import time
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='同花顺模拟炒股自动化测试')
    parser.add_argument('--action', choices=['query', 'buy', 'sell'],
                        default='query', help='操作类型 (默认: query)')
    parser.add_argument('--code', default='600519', help='股票代码 (默认: 600519)')
    parser.add_argument('--price', type=float, default=0, help='价格 (0=使用市价)')
    parser.add_argument('--quantity', type=int, default=100, help='数量 (默认: 100)')
    parser.add_argument('--real', action='store_true', help='真实下单（不加此参数只测试流程）')
    parser.add_argument('--no-start', action='store_true', help='不自动启动同花顺')
    return parser.parse_args()


def print_banner(args):
    """打印欢迎信息"""
    print()
    print("╔" + "═" * 58 + "╗")
    print("║    同花顺模拟炒股 - 自动化测试                          ║")
    print("╚" + "═" * 58 + "╝")
    print()
    print(f"  操作:     {args.action}")
    print(f"  股票:     {args.code}")
    print(f"  数量:     {args.quantity}")
    print(f"  真实下单: {'⚠️  是' if args.real else '否 (安全模式)'}")
    print(f"  自动启动: {'否' if args.no_start else '是'}")
    print("─" * 60)
    print()


def test_query(broker):
    """测试查询功能"""
    print("=" * 60)
    print("  📊 查询测试")
    print("=" * 60)
    print()

    # 1. 检查运行状态
    print("1️⃣  检查同花顺状态...")
    is_running = broker._is_app_running()
    print(f"   {'✅ 正在运行' if is_running else '❌ 未运行'}")
    print()

    if not is_running:
        print("   ⚠️  同花顺未运行，无法执行查询")
        return False

    # 2. 查询账户信息
    print("2️⃣  查询账户信息...")
    try:
        account = broker.get_account_info()
        if account:
            print(f"   总资产:   {account.total_assets:>12,.2f} 元")
            print(f"   可用资金: {account.available_cash:>12,.2f} 元")
            print(f"   冻结资金: {account.frozen_cash:>12,.2f} 元")
            print(f"   持仓市值: {account.market_value:>12,.2f} 元")
            print(f"   总盈亏:   {account.total_profit_loss:>12,.2f} 元")
            if account.total_assets == 0 and account.available_cash == 0:
                print("   ⚠️  数据为空，可能需要先切换到模拟交易界面")
        else:
            print("   ⚠️  查询返回空")
    except Exception as e:
        print(f"   ❌ 查询失败: {e}")
    print()

    # 3. 查询持仓
    print("3️⃣  查询持仓...")
    try:
        positions = broker.get_positions()
        if positions:
            print(f"   共 {len(positions)} 个持仓:")
            print(f"   {'代码':8s} {'名称':10s} {'数量':>8s} {'成本价':>10s} {'现价':>10s} {'盈亏':>10s}")
            print("   " + "─" * 56)
            for pos in positions:
                print(f"   {pos.stock_code:8s} {pos.stock_name:10s} "
                      f"{pos.quantity:>8d} {pos.cost_price:>10.2f} "
                      f"{pos.current_price:>10.2f} {pos.profit_loss:>10.2f}")
        else:
            print("   暂无持仓（或无法读取）")
    except Exception as e:
        print(f"   ❌ 查询失败: {e}")
    print()

    # 4. 查询订单
    print("4️⃣  查询今日订单...")
    try:
        orders = broker.get_orders()
        if orders:
            print(f"   共 {len(orders)} 个订单")
        else:
            print("   暂无订单（或无法读取）")
    except Exception as e:
        print(f"   ❌ 查询失败: {e}")
    print()

    return True


def test_trade(broker, action, code, price, quantity, real=False):
    """测试买卖功能"""
    action_name = "买入" if action == "buy" else "卖出"
    emoji = "🟢" if action == "buy" else "🔴"

    print("=" * 60)
    print(f"  {emoji} {action_name}测试")
    print("=" * 60)
    print()
    print(f"  股票: {code}")
    print(f"  价格: {price if price > 0 else '市价'}")
    print(f"  数量: {quantity}")
    print(f"  模式: {'⚠️  真实下单' if real else '🔒 模拟测试（不实际下单）'}")
    print()

    if not broker._is_app_running():
        print("❌ 同花顺未运行，无法交易")
        return False

    if not real:
        print("🔒 安全模式：跳过实际下单")
        print("   如需真实下单，请加 --real 参数")
        print()
        print("   流程预览：")
        print(f"   1. 按 {'F1' if action == 'buy' else 'F2'} 打开{action_name}界面")
        print(f"   2. 输入股票代码: {code}")
        print(f"   3. 输入价格: {price}")
        print(f"   4. 输入数量: {quantity}")
        print(f"   5. 按 Enter 确认")
        print(f"   6. 按 Y 确认弹窗")
        return True

    # 真实下单
    print(f"⚠️  即将执行真实{action_name}...")
    print("   3秒后开始...")
    time.sleep(3)

    try:
        if action == "buy":
            success, result = broker.buy(code, price, quantity)
        else:
            success, result = broker.sell(code, price, quantity)

        if success:
            print(f"✅ {action_name}指令已发送")
            print(f"   请在同花顺查看委托状态")
        else:
            print(f"❌ {action_name}失败: {result}")

        return success
    except Exception as e:
        print(f"❌ 执行异常: {e}")
        return False


def main():
    """主函数"""
    args = parse_args()

    # 设置日志
    logger.remove()
    logger.add(sys.stdout, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level:8}</level> | {message}")

    print_banner(args)

    broker = None
    try:
        # 1. 初始化
        print("🔧 初始化...")
        config = {
            'auto_start': not args.no_start,
            'operation_delay': 0.5,
        }
        broker = TonghuashunDesktop(config)
        print("✅ Broker 初始化成功")
        print()

        # 2. 启动同花顺（如果需要）
        if not args.no_start and not broker._is_app_running():
            print("🚀 启动同花顺...")
            if broker.launch_app():
                print("✅ 同花顺已启动，等待加载...")
                time.sleep(5)
            else:
                print("❌ 启动失败")
                return

        # 3. 登录
        if broker._is_app_running():
            print("🔐 等待登录...")
            broker.is_logged_in = True  # 假设已保存密码自动登录
            time.sleep(2)
            print("✅ 就绪")
            print()

        # 4. 执行操作
        if args.action == 'query':
            test_query(broker)
        else:
            # 先查询，再交易
            test_query(broker)
            test_trade(broker, args.action, args.code,
                       args.price, args.quantity, args.real)

        # 5. 完成
        print("=" * 60)
        print("✅ 测试完成!")
        print("=" * 60)
        print()
        print("💡 提示:")
        print("   --action query   只查询账户（默认）")
        print("   --action buy     测试买入流程")
        print("   --action sell    测试卖出流程")
        print("   --real           真实下单（慎用！）")
        print("   --code 000001    指定股票代码")
        print("   --quantity 200   指定数量")
        print()

    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
    except Exception as e:
        print(f"\n❌ 出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 不自动关闭同花顺，让用户继续使用
        if broker:
            broker.auto_start = False  # 防止 close() 杀掉进程
            broker.close()


if __name__ == "__main__":
    main()
