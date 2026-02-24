#!/bin/bash

echo "=================================="
echo "修复环境问题"
echo "=================================="

# 1. 安装python3-venv
echo ""
echo "Step 1: 安装 python3-venv"
echo "请执行以下命令（需要sudo权限）："
echo ""
echo "    sudo apt install python3.8-venv python3-pip -y"
echo ""
read -p "安装完成后按Enter继续..."

# 2. 清理旧的虚拟环境
if [ -d "venv" ]; then
    echo ""
    echo "Step 2: 清理旧的虚拟环境..."
    rm -rf venv
    echo "✓ 已清理"
fi

# 3. 创建新的虚拟环境
echo ""
echo "Step 3: 创建虚拟环境..."
python3 -m venv venv
if [ $? -eq 0 ]; then
    echo "✓ 虚拟环境创建成功"
else
    echo "❌ 虚拟环境创建失败"
    exit 1
fi

# 4. 激活虚拟环境
echo ""
echo "Step 4: 激活虚拟环境..."
source venv/bin/activate

# 5. 升级pip
echo ""
echo "Step 5: 升级pip..."
pip install --upgrade pip

# 6. 安装依赖
echo ""
echo "Step 6: 安装依赖（这可能需要几分钟）..."
pip install -r requirements.txt

echo ""
echo "=================================="
echo "✓ 环境修复完成！"
echo "=================================="
echo ""
echo "现在可以运行："
echo "  ./scripts/run_desktop_trading.sh"
echo ""
