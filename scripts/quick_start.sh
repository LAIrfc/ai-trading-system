#!/bin/bash

# AI量化交易系统快速启动脚本

echo "=================================="
echo "AI量化交易系统 - 快速启动"
echo "=================================="

# 检查Python版本
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python版本: $PYTHON_VERSION"

# 创建虚拟环境
if [ ! -d "venv" ]; then
    echo ""
    echo "1. 创建虚拟环境..."
    python3 -m venv venv
    echo "✓ 虚拟环境创建成功"
else
    echo ""
    echo "虚拟环境已存在，跳过创建"
fi

# 激活虚拟环境
echo ""
echo "2. 激活虚拟环境..."
source venv/bin/activate
echo "✓ 虚拟环境已激活"

# 安装依赖
echo ""
echo "3. 安装依赖包（这可能需要几分钟）..."
pip install --upgrade pip
pip install -r requirements.txt
echo "✓ 依赖安装完成"

# 复制配置文件
echo ""
echo "4. 设置配置文件..."

if [ ! -f "config/trading_config.yaml" ]; then
    cp config/trading_config.yaml.example config/trading_config.yaml
    echo "✓ trading_config.yaml 已创建"
else
    echo "trading_config.yaml 已存在，跳过"
fi

if [ ! -f "config/risk_config.yaml" ]; then
    cp config/risk_config.yaml.example config/risk_config.yaml
    echo "✓ risk_config.yaml 已创建"
else
    echo "risk_config.yaml 已存在，跳过"
fi

# 创建必要的目录
echo ""
echo "5. 创建数据目录..."
mkdir -p data/market_data
mkdir -p data/factor_data
mkdir -p data/models
mkdir -p logs
mkdir -p cache
echo "✓ 目录创建完成"

echo ""
echo "=================================="
echo "✓ 环境配置完成！"
echo "=================================="
echo ""
echo "接下来您可以："
echo ""
echo "1. 编辑配置文件："
echo "   config/trading_config.yaml"
echo "   config/risk_config.yaml"
echo ""
echo "2. 下载历史数据："
echo "   python src/main.py --mode download --start 20200101 --end 20231231"
echo ""
echo "3. 运行回测："
echo "   python src/main.py --mode backtest --strategy your_strategy --start 20230101 --end 20231231"
echo ""
echo "4. 启动实盘（需充分测试后）："
echo "   python src/main.py --mode live --strategy your_strategy --confirm"
echo ""
echo "⚠️  注意：实盘交易前请务必："
echo "   - 充分回测和模拟测试"
echo "   - 配置严格的风控参数"
echo "   - 使用独立的测试账户"
echo "   - 设置合理的止损"
echo ""
echo "投资有风险，入市需谨慎！"
echo "=================================="
