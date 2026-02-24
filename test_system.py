#!/usr/bin/env python3
"""
系统测试脚本
"""

import sys
import os

print("="*60)
print("系统测试")
print("="*60)

# 1. 测试导入
print("\n1. 测试模块导入...")
try:
    import pyautogui
    print("  ✅ pyautogui")
except ImportError as e:
    print(f"  ❌ pyautogui: {e}")

try:
    import psutil
    print("  ✅ psutil")
except ImportError as e:
    print(f"  ❌ psutil: {e}")

try:
    from loguru import logger
    print("  ✅ loguru")
except ImportError as e:
    print(f"  ❌ loguru: {e}")

try:
    import yaml
    print("  ✅ pyyaml")
except ImportError as e:
    print(f"  ❌ pyyaml: {e}")

# 2. 测试路径
print("\n2. 测试文件路径...")
from src.api.broker.tonghuashun_desktop import TonghuashunDesktop

APP_PATH = "/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp"
if os.path.exists(APP_PATH):
    print(f"  ✅ 同花顺已安装: {APP_PATH}")
else:
    print(f"  ❌ 同花顺未找到: {APP_PATH}")

# 3. 测试进程检测
print("\n3. 测试进程检测...")
broker = TonghuashunDesktop({'auto_start': False})
is_running = broker._is_app_running()
print(f"  同花顺运行状态: {'运行中' if is_running else '未运行'}")

# 4. 测试pyautogui基本功能
print("\n4. 测试pyautogui...")
try:
    screen_size = pyautogui.size()
    print(f"  ✅ 屏幕分辨率: {screen_size}")
except Exception as e:
    print(f"  ❌ pyautogui错误: {e}")

print("\n" + "="*60)
print("测试完成!")
print("="*60)
print("\n如果所有测试通过，可以运行:")
print("  python3 examples/desktop_trading_demo.py")
print()
