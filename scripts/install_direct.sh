#!/bin/bash

echo "=================================="
echo "直接安装（不使用虚拟环境）"
echo "=================================="
echo ""
echo "⚠️  这将直接在系统Python中安装依赖"
echo ""
read -p "确认继续? (y/n): " confirm

if [ "$confirm" != "y" ]; then
    echo "已取消"
    exit 0
fi

# 1. 确保pip3可用
echo ""
echo "Step 1: 检查pip3..."
which pip3
if [ $? -ne 0 ]; then
    echo "安装pip3..."
    sudo apt install python3-pip -y
fi

# 2. 升级pip
echo ""
echo "Step 2: 升级pip..."
pip3 install --upgrade pip --user

# 3. 安装核心依赖（桌面自动化所需）
echo ""
echo "Step 3: 安装核心依赖..."
pip3 install --user pyautogui==0.9.54
pip3 install --user psutil==5.9.5
pip3 install --user pillow==10.0.0
pip3 install --user loguru==0.7.0
pip3 install --user pyyaml==6.0.1

echo ""
echo "=================================="
echo "✓ 安装完成！"
echo "=================================="
echo ""
echo "现在可以直接运行（不需要激活虚拟环境）："
echo "  python3 examples/desktop_trading_demo.py"
echo ""
