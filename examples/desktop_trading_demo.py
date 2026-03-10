"""
同花顺桌面客户端自动化交易演示
直接控制已安装的同花顺应用
"""

import sys
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import time
from loguru import logger

from src.api.broker.tonghuashun_desktop import TonghuashunDesktop
from src.core.strategy_document import StrategyDocument
from src.core.strategy_rule_engine import StrategyRuleEngine, StrategyRule, RuleType
from src.core.strategy_executor import StrategyExecutor
from src.core.risk.risk_manager import RiskManager


def setup_demo():
    """设置演示环境"""
    
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║       同花顺桌面客户端自动化交易演示                     ║
    ╚══════════════════════════════════════════════════════════╝
    
    特点:
    - ✅ 使用本地已安装的同花顺客户端
    - ✅ 支持已保存密码的自动登录
    - ✅ 使用键盘快捷键进行交易
    - ✅ 比网页版更稳定、更快
    
    准备工作:
    1. 确保同花顺已安装在 /opt/apps/cn.com.10jqka/files/
    2. 账户已保存密码，可以自动登录
    3. 熟悉快捷键: F1买入 F2卖出 F3撤单 F4查询
    
    """)
    
    # 配置
    broker_config = {
        'auto_start': True,           # 自动启动应用
        'screenshot_on_error': True,  # 出错时截图
        'operation_delay': 0.5,       # 操作延迟（秒）
        'confidence': 0.8,            # 图像识别置信度
    }
    
    broker = TonghuashunDesktop(broker_config)
    
    # 策略系统
    strategy_doc = StrategyDocument("desktop_demo_strategy")
    rule_engine = StrategyRuleEngine("desktop_demo_strategy")
    
    # 添加简单规则
    rule = StrategyRule(
        rule_id="price_range",
        rule_type=RuleType.ENTRY,
        name="价格范围",
        description="价格10-200元",
        condition={
            'type': 'price_range',
            'min_price': 10.0,
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
        strategy_name="desktop_demo_strategy",
        strategy_document=strategy_doc,
        rule_engine=rule_engine,
        risk_manager=risk_manager
    )
    executor.require_manual_approval = False
    executor.auto_approve = True
    
    return broker, executor


def demo_manual_trading(broker: TonghuashunDesktop):
    """手动交易演示"""
    
    print("\n" + "="*60)
    print("📊 手动交易模式")
    print("="*60)
    print("""
    程序将自动打开同花顺客户端
    你可以手动操作，也可以让程序自动执行
    
    快捷键:
    - F1: 买入
    - F2: 卖出  
    - F3: 撤单
    - F4: 查询
    """)
    
    input("\n按Enter继续...")
    
    # 启动并登录
    if not broker.login():
        print("❌ 登录失败")
        return
    
    print("\n✅ 同花顺已启动")
    print("💡 提示: 你可以手动操作，也可以让程序自动交易")
    
    while True:
        print("\n" + "="*60)
        print("主菜单")
        print("="*60)
        print("1. 自动买入（测试）")
        print("2. 自动卖出（测试）")
        print("3. 手动操作（暂停程序）")
        print("0. 退出")
        
        choice = input("\n请选择 (0-3): ")
        
        if choice == '1':
            # 买入测试
            print("\n测试买入功能...")
            print("⚠️  注意: 这会真实下单！")
            
            confirm = input("确认继续? (yes/no): ")
            if confirm.lower() != 'yes':
                print("已取消")
                continue
            
            stock_code = input("股票代码 (如600519): ")
            price = float(input("价格: "))
            quantity = int(input("数量 (必须是100的倍数): "))
            
            print(f"\n准备买入: {stock_code} @ {price} x {quantity}股")
            print("同花顺窗口将自动操作...")
            time.sleep(2)
            
            success, result = broker.buy(stock_code, price, quantity)
            
            if success:
                print(f"✅ 买入成功")
            else:
                print(f"❌ 买入失败: {result}")
                
        elif choice == '2':
            # 卖出测试
            print("\n测试卖出功能...")
            print("⚠️  注意: 这会真实下单！")
            
            confirm = input("确认继续? (yes/no): ")
            if confirm.lower() != 'yes':
                print("已取消")
                continue
            
            stock_code = input("股票代码: ")
            price = float(input("价格: "))
            quantity = int(input("数量: "))
            
            print(f"\n准备卖出: {stock_code} @ {price} x {quantity}股")
            print("同花顺窗口将自动操作...")
            time.sleep(2)
            
            success, result = broker.sell(stock_code, price, quantity)
            
            if success:
                print(f"✅ 卖出成功")
            else:
                print(f"❌ 卖出失败: {result}")
                
        elif choice == '3':
            print("\n⏸️  程序已暂停")
            print("你可以手动操作同花顺")
            print("操作完成后按Enter继续...")
            input()
            print("程序已恢复")
            
        elif choice == '0':
            print("\n退出程序...")
            break
            
        else:
            print("❌ 无效选择")


def demo_auto_trading(broker: TonghuashunDesktop, executor: StrategyExecutor):
    """自动化交易演示"""
    
    print("\n" + "="*60)
    print("🤖 自动化交易模式")
    print("="*60)
    print("""
    此模式将：
    1. 模拟策略生成交易信号
    2. 自动进行规则和风控检查
    3. 自动执行交易操作
    
    ⚠️  注意: 这是真实交易！请谨慎操作！
    """)
    
    confirm = input("\n确认进入自动交易模式? (yes/no): ")
    if confirm.lower() != 'yes':
        print("已取消")
        return
    
    # 登录
    if not broker.login():
        print("❌ 登录失败")
        return
    
    print("\n✅ 已就绪，开始自动交易...")
    
    # 模拟策略信号
    signal = {
        'stock_code': input("测试股票代码 (如600519): "),
        'action': 'buy',
        'target_position': 0.05,
        'reason': '测试信号',
    }
    
    price = float(input("目标价格: "))
    
    market_data = {
        signal['stock_code']: {
            'price': price,
            'volume': 50000000,
        }
    }
    
    # 策略执行器处理（规则+风控）
    print("\n进行规则和风控检查...")
    order = executor.process_signal(signal, market_data)
    
    if not order:
        print("❌ 信号被拒绝")
        return
    
    print(f"✅ 检查通过，准备交易")
    print(f"订单ID: {order.order_id}")
    
    # 确认执行
    confirm = input("\n确认执行交易? (yes/no): ")
    if confirm.lower() != 'yes':
        print("已取消")
        return
    
    # 执行交易
    quantity = 100  # 最小单位
    print(f"\n执行买入: {signal['stock_code']} @ {price} x {quantity}股")
    
    success, result = broker.buy(signal['stock_code'], price, quantity)
    
    if success:
        print(f"✅ 交易成功!")
        
        # 更新订单状态
        order.executed_price = price
        order.executed_quantity = quantity
        executor.executed_orders[order.order_id] = order
        
        # 显示审计日志
        print("\n审计日志:")
        logs = executor.get_audit_logs(order_id=order.order_id)
        for log in logs:
            print(f"  [{log.timestamp}] {log.event_type}")
    else:
        print(f"❌ 交易失败: {result}")


def main():
    """主函数"""
    
    broker = None
    
    try:
        # 设置环境
        broker, executor = setup_demo()
        
        print("\n选择演示模式:")
        print("1. 手动交易模式 (推荐新手)")
        print("2. 自动化交易模式")
        
        mode = input("\n请选择 (1-2): ")
        
        if mode == '1':
            demo_manual_trading(broker)
        elif mode == '2':
            demo_auto_trading(broker, executor)
        else:
            print("无效选择")
            
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
            print("✅ 已清理完成")
        
        print("\n" + "="*60)
        print("感谢使用!")
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
    ║    同花顺桌面客户端自动化交易系统                        ║
    ║                                                          ║
    ║  优势:                                                   ║
    ║  ✅ 使用本地客户端，更稳定                              ║
    ║  ✅ 支持自动登录（如已保存密码）                        ║
    ║  ✅ 键盘快捷键操作，速度快                              ║
    ║  ✅ 不依赖网页版，不怕改版                              ║
    ║                                                          ║
    ║  要求:                                                   ║
    ║  - 同花顺已安装                                          ║
    ║  - 账户密码已保存                                        ║
    ║  - 已安装pyautogui和psutil                              ║
    ║                                                          ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    main()
