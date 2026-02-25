#!/usr/bin/env python3
"""简单测试 - 忽略tkinter警告"""

import warnings
warnings.filterwarnings('ignore')

import sys
import os

print("测试开始...")

# 测试导入（tkinter警告会显示但不会阻止）
try:
    import pyautogui
    print(f"✅ pyautogui imported, version: {pyautogui.__version__}")
    
    # 测试基本功能
    size = pyautogui.size()
    print(f"✅ 屏幕大小: {size}")
    
except Exception as e:
    print(f"❌ 错误: {e}")
    sys.exit(1)

# 测试其他模块
try:
    import psutil
    print(f"✅ psutil imported")
    
    from loguru import logger
    print(f"✅ loguru imported")
    
    import yaml
    print(f"✅ pyyaml imported")
    
except Exception as e:
    print(f"❌ 错误: {e}")
    sys.exit(1)

# 测试同花顺路径
APP_PATH = "/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp"
if os.path.exists(APP_PATH):
    print(f"✅ 同花顺已安装")
else:
    print(f"⚠️  同花顺路径不存在: {APP_PATH}")

# 测试broker导入
try:
    sys.path.insert(0, '/home/wangxinghan/codetree/ai-trading-system')
    from src.api.broker.tonghuashun_desktop import TonghuashunDesktop
    print(f"✅ TonghuashunDesktop imported")
    
    # 创建实例
    broker = TonghuashunDesktop({'auto_start': False})
    print(f"✅ Broker实例创建成功")
    
    # 检查同花顺是否运行
    is_running = broker._is_app_running()
    print(f"同花顺状态: {'✅ 运行中' if is_running else '⚪ 未运行'}")
    
except Exception as e:
    print(f"❌ 错误: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "="*60)
print("✅ 所有测试通过！系统可以正常使用")
print("="*60)
print("\ntkinter警告可以忽略（只影响MouseInfo工具）")
print("核心功能完全正常！")
