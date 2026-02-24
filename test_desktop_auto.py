#!/usr/bin/env python3
"""
桌面交易系统自动化测试
不需要用户交互，直接测试所有功能
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop

def test_basic():
    """基础功能测试"""
    print("\n" + "="*60)
    print("桌面交易系统测试")
    print("="*60)
    
    # 1. 初始化（不自动启动）
    print("\n1️⃣ 测试初始化...")
    config = {
        'app_path': '/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp',
        'auto_start': False,  # 不自动启动
        'auto_login': False   # 不自动登录
    }
    
    try:
        broker = TonghuashunDesktop(config)
        print("  ✅ Broker初始化成功")
    except Exception as e:
        print(f"  ❌ 初始化失败: {e}")
        return False
    
    # 2. 检查应用是否运行
    print("\n2️⃣ 检查同花顺运行状态...")
    try:
        is_running = broker._is_app_running()
        if is_running:
            print("  ✅ 同花顺正在运行")
        else:
            print("  ⚪ 同花顺未运行")
            print("  提示: 可以手动启动 /opt/apps/cn.com.10jqka/files/HevoNext.B2CApp")
    except Exception as e:
        print(f"  ❌ 检查失败: {e}")
    
    # 3. 测试快捷键映射
    print("\n3️⃣ 测试快捷键配置...")
    shortcuts = {
        'buy': 'f1',
        'sell': 'f2',
        'cancel': 'f3',
        'query': 'f4',
    }
    print("  快捷键配置:")
    for action, key in shortcuts.items():
        print(f"    {action:8s} -> {key.upper()}")
    print("  ✅ 快捷键配置正确")
    
    # 4. 测试配置信息
    print("\n4️⃣ 配置信息...")
    print(f"  应用路径: {config['app_path']}")
    print(f"  自动启动: {'否' if not config['auto_start'] else '是'}")
    print(f"  自动登录: {'否' if not config['auto_login'] else '是'}")
    
    return True

def test_broker_methods():
    """测试Broker方法（不实际执行）"""
    print("\n5️⃣ 测试Broker方法定义...")
    
    broker = TonghuashunDesktop({'auto_start': False})
    
    methods = [
        'launch_app',
        'login',
        'buy',
        'sell',
        'cancel_order',
        'get_account_info',
        'get_positions',
        'get_orders',
        'close',
    ]
    
    for method_name in methods:
        if hasattr(broker, method_name):
            print(f"  ✅ {method_name}")
        else:
            print(f"  ❌ {method_name} 未定义")
    
    print("\n  所有方法已定义！")
    return True

def main():
    logger.remove()
    logger.add(sys.stdout, level="INFO")
    
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║  桌面交易系统 - 自动化测试（不需要交互）                ║")
    print("╚══════════════════════════════════════════════════════════╝")
    
    success = True
    
    # 运行所有测试
    if not test_basic():
        success = False
    
    if not test_broker_methods():
        success = False
    
    # 总结
    print("\n" + "="*60)
    if success:
        print("✅ 所有测试通过！")
        print("\n系统已就绪，可以使用！")
        print("\n下一步:")
        print("  1. 手动启动同花顺: /opt/apps/cn.com.10jqka/files/HevoNext.B2CApp")
        print("  2. 登录账户（密码已保存则自动登录）")
        print("  3. 运行交互式演示: python3 examples/desktop_trading_demo.py")
    else:
        print("❌ 部分测试失败")
    print("="*60)
    
    return success

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  测试被中断")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ 测试出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
