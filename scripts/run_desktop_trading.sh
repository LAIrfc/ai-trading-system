#!/bin/bash

# 同花顺桌面客户端自动化交易 - 一键启动脚本

echo "=================================="
echo "同花顺桌面客户端自动化交易"
echo "=================================="

# 检查同花顺是否安装
TONGHUASHUN_PATH="/opt/apps/cn.com.10jqka/files/HevoNext.B2CApp"

if [ ! -f "$TONGHUASHUN_PATH" ]; then
    echo "❌ 错误: 同花顺未安装"
    echo "   路径: $TONGHUASHUN_PATH"
    echo ""
    echo "请先安装同花顺客户端"
    exit 1
fi

echo "✅ 同花顺已安装: $TONGHUASHUN_PATH"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo ""
    echo "❌ 错误: 虚拟环境不存在"
    echo "请先运行: ./scripts/quick_start.sh"
    exit 1
fi

# 激活虚拟环境
source venv/bin/activate

# 检查依赖
echo ""
echo "检查依赖..."

python -c "import pyautogui" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "⚠️  缺少依赖: pyautogui"
    echo "正在安装..."
    pip install pyautogui psutil pillow
fi

# 运行程序
echo ""
echo "=================================="
echo "启动交易程序..."
echo "=================================="
echo ""

python examples/desktop_trading_demo.py

echo ""
echo "=================================="
echo "程序已退出"
echo "=================================="
