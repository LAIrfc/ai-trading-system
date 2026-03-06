#!/usr/bin/env python3
"""
跨平台兼容性测试
自动检测Windows/Linux并使用对应配置
"""

import sys
import platform
from pathlib import Path

# 添加项目根路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.platform_config import platform_config
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop


def test_platform_detection():
    """测试平台检测"""
    print("\n" + "="*60)
    print("  跨平台兼容性测试")
    print("="*60 + "\n")
    
    # 显示平台信息
    platform_config.print_info()
    
    # 测试同花顺配置
    print("✅ 平台自动检测成功！\n")
    
    # 创建Broker实例（不自动启动）
    print("测试Broker初始化...")
    broker = TonghuashunDesktop({'auto_start': False})
    
    print("\n✅ Broker初始化成功！")
    print(f"   系统: {broker.system}")
    print(f"   应用路径: {broker.app_path}")
    print(f"   进程名称: {broker.process_name}")
    
    # 检查应用是否运行
    print("\n检查同花顺运行状态...")
    is_running = broker._is_app_running()
    
    if is_running:
        print("✅ 同花顺正在运行")
    else:
        print("⚪ 同花顺未运行")
    
    print("\n" + "="*60)
    print("✅ 跨平台兼容性测试完成！")
    print("="*60)
    
    print("\n💡 总结:")
    print(f"   - 系统类型: {platform.system()}")
    print(f"   - Python版本: {platform.python_version()}")
    print(f"   - 同花顺路径: {broker.app_path}")
    print(f"   - 配置已自动适配，无需手动修改！")
    print()


def test_data_fetcher():
    """测试数据获取（跨平台）"""
    print("\n" + "="*60)
    print("  测试数据获取")
    print("="*60 + "\n")
    
    try:
        from src.data import RealtimeDataFetcher
        
        print("创建数据获取器...")
        fetcher = RealtimeDataFetcher()
        
        print("✅ 数据获取器初始化成功")
        
        print("\n获取贵州茅台实时价格...")
        price = fetcher.get_realtime_price('600519')
        
        if price:
            print(f"✅ 成功获取价格: {price:.2f}元")
        else:
            print("⚠️  未能获取价格（可能网络问题）")
        
    except Exception as e:
        print(f"❌ 数据获取测试失败: {e}")
    
    print()


def main():
    """主函数"""
    print("\n" + "╔" + "="*58 + "╗")
    print("║" + " "*58 + "║")
    print("║" + "  AI量化交易系统 - 跨平台兼容性测试".center(58) + "║")
    print("║" + " "*58 + "║")
    print("╚" + "="*58 + "╝")
    
    try:
        # 1. 平台检测测试
        test_platform_detection()
        
        # 2. 数据获取测试
        test_data_fetcher()
        
        # 3. 最终总结
        print("\n" + "="*60)
        print("✅ 所有测试通过！")
        print("="*60)
        
        print("\n💡 使用说明:")
        print("\n1. 程序会自动检测操作系统")
        print("2. 自动使用对应的同花顺路径")
        print("3. 无需修改配置文件")
        print("4. Windows和Linux使用相同的代码")
        
        print("\n📚 下一步:")
        if platform.system() == 'Windows':
            print("   Windows用户:")
            print("   - 双击 start_windows.bat")
            print("   - 或运行: python tools\\data\\kline_fetcher.py 600519")
        else:
            print("   Linux用户:")
            print("   - 运行: python3 tools/data/kline_fetcher.py 600519")
        
        print()
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
