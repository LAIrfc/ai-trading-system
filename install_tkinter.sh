#!/bin/bash

echo "=================================="
echo "安装tkinter（pyautogui需要）"
echo "=================================="
echo ""
echo "需要sudo权限安装系统包"
echo ""

# 安装tkinter
echo "正在安装 python3-tk python3-dev..."
sudo apt-get install python3-tk python3-dev -y

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ tkinter安装成功！"
    echo ""
    echo "现在可以运行："
    echo "  python3 simple_test.py"
    echo "  python3 examples/desktop_trading_demo.py"
else
    echo ""
    echo "❌ 安装失败"
    exit 1
fi
