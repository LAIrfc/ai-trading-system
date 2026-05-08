#!/bin/bash

# AI量化交易系统快速启动脚本

echo "=================================="
echo "AI量化交易系统 - 快速启动"
echo "=================================="

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python版本: $PYTHON_VERSION"

if [ ! -d "venv" ]; then
    echo ""
    echo "1. 创建虚拟环境..."
    python3 -m venv venv
    echo "✓ 虚拟环境创建成功"
else
    echo ""
    echo "虚拟环境已存在，跳过创建"
fi

echo ""
echo "2. 激活虚拟环境..."
source venv/bin/activate
echo "✓ 虚拟环境已激活"

echo ""
echo "3. 安装依赖包..."
pip install --upgrade pip
pip install -r requirements.txt
echo "✓ 依赖安装完成"

echo ""
echo "4. 创建数据目录..."
mkdir -p mydate/daily_reports
mkdir -p mydate/backtest_kline
mkdir -p mydate/news_cache
mkdir -p mycache/fundamental
mkdir -p mylog
mkdir -p output
mkdir -p results
echo "✓ 目录创建完成"

echo ""
echo "5. 配置环境变量..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "✓ .env 已从模板创建，请编辑填入API密钥"
else
    echo ".env 已存在，跳过"
fi

echo ""
echo "=================================="
echo "✓ 环境配置完成！"
echo "=================================="
echo ""
echo "接下来您可以："
echo ""
echo "1. 编辑 .env 文件填入 API 密钥"
echo ""
echo "2. 预取K线数据："
echo "   python3 tools/data/backtest_prefetch.py"
echo ""
echo "3. 运行每日推荐："
echo "   python3 tools/analysis/recommend_today.py"
echo ""
echo "4. 查看所有可用命令："
echo "   python3 src/main.py --help"
echo ""
echo "⚠️  投资有风险，入市需谨慎！"
echo "=================================="
