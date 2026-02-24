#!/usr/bin/env python3
"""
同花顺桌面客户端 - 完全自动化演示
不需要任何用户输入，使用预设参数进行测试
"""

import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop
from src.core.strategy.strategy_rule_engine import StrategyRuleEngine
from src.core.strategy.strategy_executor import StrategyExecutor

# ==================== 配置区 ====================
# 修改这里的参数来自定义测试

TEST_CONFIG = {
    # 测试股票（默认：贵州茅台）
    'stock_code': '600519',
    
    # 测试价格
    'price': 1000.0,
    
    # 测试数量
    'quantity': 100,
    
    # 操作类型：'buy', 'sell', 'query_only'
    'action': 'query_only',  # 默认只查询，不真实交易
    
    # 是否真实交易（True=真实下单，False=只测试不下单）
    'real_trade': False,
    
    # 是否自动启动同花顺
    'auto_start': True,
    
    # 是否自动登录（需要已保存密码）
    'auto_login': True,
}

# ================================================


def print_header():
    """打印欢迎信息"""
    print("\n" + "="*60)
    print("  同花顺桌面客户端 - 完全自动化测试")
    print("="*60)
    print("\n📋 当前配置:")
    print(f"  股票代码: {TEST_CONFIG['stock_code']}")
    print(f"  价格: {TEST_CONFIG['price']}")
    print(f"  数量: {TEST_CONFIG['quantity']}")
    print(f"  操作: {TEST_CONFIG['action']}")
    print(f"  真实交易: {'是 ⚠️' if TEST_CONFIG['real_trade'] else '否 (安全模式)'}")
    print(f"  自动启动: {'是' if TEST_CONFIG['auto_start'] else '否'}")
    print(f"  自动登录: {'是' if TEST_CONFIG['auto_login'] else '否'}")
    print("="*60 + "\n")
    
    if not TEST_CONFIG['real_trade']:
        print("✅ 安全模式：不会真实下单，只测试流程\n")
    else:
        print("⚠️  警告：真实交易模式！会实际下单！\n")
        time.sleep(2)


def test_query_only(broker):
    """只查询，不交易"""
    print("\n" + "="*60)
    print("模式：查询测试（不交易）")
    print("="*60 + "\n")
    
    # 1. 查询账户信息
    print("1️⃣ 查询账户信息...")
    try:
        account = broker.get_account_info()
        print(f"✅ 账户信息:")
        print(f"   可用资金: {account.get('available_balance', 'N/A')}")
        print(f"   总资产: {account.get('total_assets', 'N/A')}")
        print(f"   持仓市值: {account.get('market_value', 'N/A')}")
    except Exception as e:
        print(f"⚠️  查询失败: {e}")
    
    time.sleep(1)
    
    # 2. 查询持仓
    print("\n2️⃣ 查询持仓...")
    try:
        positions = broker.get_positions()
        if positions:
            print(f"✅ 当前持仓 ({len(positions)}个):")
            for pos in positions[:5]:  # 只显示前5个
                print(f"   {pos.get('code', 'N/A')} - "
                      f"{pos.get('name', 'N/A')} - "
                      f"数量: {pos.get('quantity', 'N/A')}")
        else:
            print("⚪ 暂无持仓")
    except Exception as e:
        print(f"⚠️  查询失败: {e}")
    
    time.sleep(1)
    
    # 3. 查询订单
    print("\n3️⃣ 查询今日订单...")
    try:
        orders = broker.get_orders()
        if orders:
            print(f"✅ 今日订单 ({len(orders)}个):")
            for order in orders[:5]:  # 只显示前5个
                print(f"   {order.get('code', 'N/A')} - "
                      f"{order.get('direction', 'N/A')} - "
                      f"状态: {order.get('status', 'N/A')}")
        else:
            print("⚪ 今日无订单")
    except Exception as e:
        print(f"⚠️  查询失败: {e}")


def test_strategy_execution(executor):
    """测试策略执行流程（不实际交易）"""
    print("\n" + "="*60)
    print("模式：策略执行测试（规则+风控检查）")
    print("="*60 + "\n")
    
    # 构造测试信号
    signal = {
        'stock_code': TEST_CONFIG['stock_code'],
        'action': 'buy',
        'target_position': 0.05,
        'reason': '自动化测试信号',
        'confidence': 0.85,
    }
    
    market_data = {
        TEST_CONFIG['stock_code']: {
            'price': TEST_CONFIG['price'],
            'volume': 50000000,
            'change_pct': 0.02,
        }
    }
    
    print("📊 测试信号:")
    print(f"   股票: {signal['stock_code']}")
    print(f"   操作: {signal['action']}")
    print(f"   价格: {market_data[signal['stock_code']]['price']}")
    print(f"   目标仓位: {signal['target_position']*100}%")
    print(f"   信号置信度: {signal['confidence']}")
    
    print("\n🔍 进行规则和风控检查...")
    time.sleep(1)
    
    # 处理信号
    order = executor.process_signal(signal, market_data)
    
    if order:
        print(f"\n✅ 检查通过!")
        print(f"   订单ID: {order.order_id}")
        print(f"   状态: {order.status.value}")
        print(f"   目标价格: {order.target_price}")
        print(f"   目标数量: {order.target_quantity}")
        
        # 显示审计日志
        print("\n📝 审计日志:")
        logs = executor.get_audit_logs(order_id=order.order_id)
        for log in logs[-3:]:  # 只显示最近3条
            print(f"   [{log.timestamp.strftime('%H:%M:%S')}] {log.event_type}")
            if log.details:
                for key, value in log.details.items():
                    if key != 'signal' and key != 'market_data':
                        print(f"      {key}: {value}")
    else:
        print("\n❌ 信号被拒绝（未通过规则或风控检查）")
        
        # 查看拒绝原因
        recent_logs = executor.get_audit_logs()
        if recent_logs:
            last_log = recent_logs[-1]
            print(f"   原因: {last_log.details.get('reason', '未知')}")


def test_real_trade(broker):
    """真实交易测试（需要确认）"""
    print("\n" + "="*60)
    print("模式：真实交易")
    print("="*60 + "\n")
    
    print("⚠️⚠️⚠️  警告：这会进行真实交易！ ⚠️⚠️⚠️\n")
    
    action = TEST_CONFIG['action']
    stock_code = TEST_CONFIG['stock_code']
    price = TEST_CONFIG['price']
    quantity = TEST_CONFIG['quantity']
    
    print(f"准备{action}: {stock_code}")
    print(f"价格: {price}")
    print(f"数量: {quantity}股")
    
    print("\n开始执行...")
    time.sleep(1)
    
    if action == 'buy':
        success, result = broker.buy(stock_code, price, quantity)
    elif action == 'sell':
        success, result = broker.sell(stock_code, price, quantity)
    else:
        print(f"❌ 不支持的操作: {action}")
        return
    
    if success:
        print(f"\n✅ 交易成功!")
        print(f"   结果: {result}")
    else:
        print(f"\n❌ 交易失败!")
        print(f"   错误: {result}")


def main():
    """主函数"""
    
    # 设置日志
    logger.remove()
    logger.add(sys.stdout, level="INFO", 
               format="<green>{time:HH:mm:ss}</green> | <level>{level:8}</level> | <level>{message}</level>")
    
    print_header()
    
    broker = None
    
    try:
        # 1. 初始化Broker
        print("🚀 初始化同花顺客户端...")
        config = {
            'app_path': '/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp',
            'auto_start': TEST_CONFIG['auto_start'],
            'auto_login': TEST_CONFIG['auto_login'],
        }
        broker = TonghuashunDesktop(config)
        print("✅ 初始化成功\n")
        time.sleep(1)
        
        # 2. 检查/启动同花顺
        if TEST_CONFIG['auto_start']:
            print("🚀 启动同花顺...")
            if broker.launch_app():
                print("✅ 同花顺已启动")
                time.sleep(3)  # 等待启动完成
            else:
                print("⚠️  同花顺启动失败或已在运行")
        
        # 3. 登录
        if TEST_CONFIG['auto_login']:
            print("\n🔐 自动登录...")
            if broker.login():
                print("✅ 登录成功")
                time.sleep(2)  # 等待登录完成
            else:
                print("⚠️  自动登录失败，请手动登录")
        
        # 4. 初始化策略执行器
        print("\n📋 初始化策略执行器...")
        rule_engine = StrategyRuleEngine()
        
        # 添加示例规则
        rule_engine.add_rule(
            rule_id='price_range',
            name='价格范围检查',
            rule_type='entry',
            condition=lambda signal, market_data: 10 <= market_data[signal['stock_code']]['price'] <= 5000,
            priority=1
        )
        
        executor = StrategyExecutor(
            strategy_name='auto_test_strategy',
            rule_engine=rule_engine,
            broker=broker,
        )
        print("✅ 策略执行器已就绪\n")
        time.sleep(1)
        
        # 5. 根据配置执行测试
        if TEST_CONFIG['action'] == 'query_only':
            test_query_only(broker)
        else:
            # 先测试策略执行流程
            test_strategy_execution(executor)
            
            # 如果启用真实交易
            if TEST_CONFIG['real_trade']:
                print("\n" + "="*60)
                input("⚠️  按Enter继续真实交易，或Ctrl+C取消...")
                test_real_trade(broker)
        
        # 6. 完成
        print("\n" + "="*60)
        print("✅ 测试完成!")
        print("="*60 + "\n")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
    except Exception as e:
        print(f"\n❌ 出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if broker:
            print("\n🔚 关闭连接...")
            broker.close()


if __name__ == "__main__":
    main()
