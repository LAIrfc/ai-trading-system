"""
网页自动化交易演示
展示如何使用同花顺模拟炒股进行自动化交易
"""

import sys
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import time
from datetime import datetime
from loguru import logger

from src.api.broker.tonghuashun_simulator import TonghuashunSimulator
from src.core.strategy_document import StrategyDocument
from src.core.strategy_rule_engine import StrategyRuleEngine, StrategyRule, RuleType
from src.core.strategy_executor import StrategyExecutor
from src.core.risk.risk_manager import RiskManager


def setup_demo_environment():
    """设置演示环境"""
    
    print("\n" + "="*60)
    print("🌐 网页自动化交易演示")
    print("="*60)
    print("\n使用同花顺模拟炒股进行策略验证和调试")
    
    # 1. 配置同花顺模拟炒股
    print("\n📝 Step 1: 配置同花顺模拟炒股")
    
    broker_config = {
        'username': input("请输入同花顺用户名: "),
        'password': input("请输入密码: "),
        'headless': False,  # 可以看到浏览器操作
        'implicit_wait': 10,
    }
    
    broker = TonghuashunSimulator(broker_config)
    
    # 2. 设置策略组件
    print("\n🔧 Step 2: 初始化策略系统")
    
    strategy_doc = StrategyDocument("web_demo_strategy")
    rule_engine = StrategyRuleEngine("web_demo_strategy")
    
    # 添加简单规则
    rule = StrategyRule(
        rule_id="price_range",
        rule_type=RuleType.ENTRY,
        name="价格范围",
        description="价格5-200元",
        condition={
            'type': 'price_range',
            'min_price': 5.0,
            'max_price': 200.0,
        },
        action="reject",
        priority=10,
        mandatory=True
    )
    rule_engine.add_rule(rule)
    
    risk_manager = RiskManager({
        'account_risk': {'max_drawdown': 0.20},
        'stock_risk': {'stop_loss': -0.08},
    })
    
    executor = StrategyExecutor(
        strategy_name="web_demo_strategy",
        strategy_document=strategy_doc,
        rule_engine=rule_engine,
        risk_manager=risk_manager
    )
    executor.require_manual_approval = False
    executor.auto_approve = True
    
    print("✅ 策略系统已初始化")
    
    return broker, executor


def demo_account_info(broker: TonghuashunSimulator):
    """演示账户信息查询"""
    
    print("\n" + "="*60)
    print("💰 查询账户信息")
    print("="*60)
    
    account = broker.get_account_info()
    
    if account:
        print(f"\n总资产: {account.total_assets:,.2f}元")
        print(f"可用资金: {account.available_cash:,.2f}元")
        print(f"持仓市值: {account.market_value:,.2f}元")
        print(f"总盈亏: {account.total_profit_loss:+,.2f}元")
        
        if account.positions:
            print(f"\n持仓明细 ({len(account.positions)}只):")
            print("-" * 60)
            for pos in account.positions:
                print(f"{pos.stock_name}({pos.stock_code})")
                print(f"  数量: {pos.quantity}股 (可用: {pos.available}股)")
                print(f"  成本: {pos.cost_price:.2f}元 | 现价: {pos.current_price:.2f}元")
                print(f"  市值: {pos.market_value:,.2f}元")
                print(f"  盈亏: {pos.profit_loss:+,.2f}元 ({pos.profit_loss_ratio:+.2%})")
                print()
        else:
            print("\n暂无持仓")
    else:
        print("❌ 获取账户信息失败")


def demo_strategy_trading(broker: TonghuashunSimulator, executor: StrategyExecutor):
    """演示策略交易"""
    
    print("\n" + "="*60)
    print("📊 策略交易演示")
    print("="*60)
    
    # 模拟策略生成信号
    print("\n策略生成买入信号...")
    
    signal = {
        'stock_code': '600519',  # 贵州茅台
        'action': 'buy',
        'target_position': 0.05,
        'reason': '策略信号',
    }
    
    # 获取当前价格
    current_price = broker.get_current_price(signal['stock_code'])
    
    if not current_price:
        print("❌ 无法获取价格")
        return
    
    print(f"股票: {signal['stock_code']}")
    print(f"当前价: {current_price:.2f}元")
    
    # 构造市场数据
    market_data = {
        signal['stock_code']: {
            'price': current_price,
            'volume': 50000000,
            'volatility': 0.02,
        }
    }
    
    # 处理信号（规则检查 + 风控）
    print("\n进行规则和风控检查...")
    order = executor.process_signal(signal, market_data)
    
    if not order:
        print("❌ 信号被拒绝，未生成订单")
        return
    
    print(f"✅ 订单已创建: {order.order_id}")
    print(f"状态: {order.status.value}")
    
    # 确认是否执行
    user_input = input("\n是否执行交易? (y/n): ")
    
    if user_input.lower() == 'y':
        # 计算交易数量
        account = broker.get_account_info()
        if not account:
            print("❌ 无法获取账户信息")
            return
        
        # 按目标仓位计算
        target_value = account.total_assets * signal['target_position']
        quantity = int(target_value / current_price / 100) * 100  # 整百股
        
        if quantity < 100:
            print("❌ 资金不足，无法买入100股")
            return
        
        print(f"\n准备买入: {quantity}股 @ {current_price:.2f}元")
        print(f"预计金额: {quantity * current_price:,.2f}元")
        
        # 执行交易
        success, result = broker.buy(
            stock_code=signal['stock_code'],
            price=current_price,
            quantity=quantity
        )
        
        if success:
            print(f"✅ 交易成功! 订单号: {result}")
            
            # 更新执行器的订单状态（实际应该从券商获取订单状态）
            order.executed_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            order.executed_price = current_price
            order.executed_quantity = quantity
            
            # 记录到审计日志
            executor.executed_orders[order.order_id] = order
            
        else:
            print(f"❌ 交易失败: {result}")
    else:
        print("⏸️  用户取消交易")


def demo_order_query(broker: TonghuashunSimulator):
    """演示订单查询"""
    
    print("\n" + "="*60)
    print("📋 查询订单")
    print("="*60)
    
    orders = broker.get_orders()
    
    if orders:
        print(f"\n共{len(orders)}个订单:")
        print("-" * 60)
        
        for order in orders[:10]:  # 只显示最近10个
            print(f"订单号: {order.order_id}")
            print(f"股票: {order.stock_name}({order.stock_code})")
            print(f"操作: {order.action} | 价格: {order.price:.2f}元 | 数量: {order.quantity}股")
            print(f"成交: {order.filled_quantity}股 | 状态: {order.status}")
            print(f"时间: {order.submit_time}")
            print()
    else:
        print("暂无订单")


def main():
    """主函数"""
    
    broker = None
    
    try:
        # 设置环境
        broker, executor = setup_demo_environment()
        
        # 登录
        print("\n" + "="*60)
        print("🔐 登录同花顺模拟炒股")
        print("="*60)
        
        if not broker.login():
            print("\n❌ 登录失败，请检查用户名和密码")
            return
        
        print("\n✅ 登录成功!")
        
        # 主菜单循环
        while True:
            print("\n" + "="*60)
            print("📱 主菜单")
            print("="*60)
            print("1. 查看账户信息")
            print("2. 查看持仓")
            print("3. 策略交易（买入）")
            print("4. 查看订单")
            print("5. 生成执行报告")
            print("0. 退出")
            
            choice = input("\n请选择 (0-5): ")
            
            if choice == '1':
                demo_account_info(broker)
                
            elif choice == '2':
                positions = broker.get_positions()
                if positions:
                    print(f"\n持仓数量: {len(positions)}")
                    for pos in positions:
                        print(f"{pos.stock_name}({pos.stock_code}): {pos.quantity}股, "
                              f"盈亏: {pos.profit_loss:+.2f}元")
                else:
                    print("\n暂无持仓")
                    
            elif choice == '3':
                demo_strategy_trading(broker, executor)
                
            elif choice == '4':
                demo_order_query(broker)
                
            elif choice == '5':
                report = executor.generate_execution_report()
                print("\n" + report)
                
            elif choice == '0':
                print("\n退出程序...")
                break
                
            else:
                print("❌ 无效选择")
        
    except KeyboardInterrupt:
        print("\n\n用户中断程序")
        
    except Exception as e:
        logger.exception(f"程序运行出错: {e}")
        
    finally:
        # 清理
        if broker:
            print("\n正在清理...")
            broker.logout()
            broker.close()
            print("✅ 浏览器已关闭")
        
        print("\n" + "="*60)
        print("👋 感谢使用!")
        print("="*60)


if __name__ == '__main__':
    # 配置日志
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO"
    )
    
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║                                                          ║
    ║       网页自动化交易系统 - 同花顺模拟炒股演示            ║
    ║                                                          ║
    ║  注意事项:                                               ║
    ║  1. 首次运行需要安装Chrome浏览器和ChromeDriver          ║
    ║  2. 建议先用headless=False模式观察操作流程              ║
    ║  3. 网页元素选择器需要根据实际页面调整                  ║
    ║  4. 本演示仅供学习和测试，请勿用于实盘                  ║
    ║                                                          ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    main()
