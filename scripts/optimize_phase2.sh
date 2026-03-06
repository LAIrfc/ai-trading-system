#!/bin/bash
# 项目优化 Phase 2: 更新导入路径
# 执行时间：2-3小时
# 风险等级：⭐⭐ 中

set -e  # 遇到错误立即退出

echo "======================================"
echo "  项目优化 Phase 2: 更新导入路径"
echo "======================================"
echo ""

# 切换到项目根目录
cd "$(dirname "$0")/.."

echo "📍 当前目录: $(pwd)"
echo ""

# 备份文件（以防万一）
echo "💾 Step 1: 备份将要修改的文件"
mkdir -p .backup_phase2
cp examples/get_kline_demo.py .backup_phase2/ 2>/dev/null || true
cp examples/paper_trading_demo.py .backup_phase2/ 2>/dev/null || true
cp examples/my_strategy_template.py .backup_phase2/ 2>/dev/null || true
cp tests/test_cross_platform.py .backup_phase2/ 2>/dev/null || true
cp tests/test_dual_momentum_quick.py .backup_phase2/ 2>/dev/null || true
cp tools/data/kline_fetcher.py .backup_phase2/ 2>/dev/null || true
cp src/core/trade_journal.py .backup_phase2/ 2>/dev/null || true
cp src/core/signal_engine.py .backup_phase2/ 2>/dev/null || true
cp run_daily.py .backup_phase2/ 2>/dev/null || true
echo "   ✅ 备份完成: .backup_phase2/"
echo ""

# 更新导入路径
echo "🔄 Step 2: 更新导入路径"

# 2.1 替换 realtime_data 导入
echo "   [1/3] 更新 realtime_data 导入..."
for file in examples/get_kline_demo.py examples/paper_trading_demo.py examples/my_strategy_template.py tests/test_cross_platform.py tools/data/kline_fetcher.py; do
    if [ -f "$file" ]; then
        sed -i 's/from src\.data\.realtime_data import/from src.data import/g' "$file"
        echo "      ✅ $file"
    fi
done

# 2.2 替换 market_data 导入
echo "   [2/3] 更新 market_data 导入..."
for file in src/core/trade_journal.py src/core/signal_engine.py run_daily.py; do
    if [ -f "$file" ]; then
        sed -i 's/from src\.data\.market_data import/from src.data import/g' "$file"
        echo "      ✅ $file"
    fi
done

# 2.3 替换 etf_data_fetcher 导入
echo "   [3/3] 更新 etf_data_fetcher 导入..."
if [ -f "tests/test_dual_momentum_quick.py" ]; then
    sed -i 's/from src\.data\.etf_data_fetcher import/from src.data import/g' tests/test_dual_momentum_quick.py
    echo "      ✅ tests/test_dual_momentum_quick.py"
fi

echo ""
echo "   ✅ 所有导入路径已更新"
echo ""

# 显示修改内容
echo "📝 Step 3: 验证修改内容"
echo "   检查修改的文件..."
git diff --stat 2>/dev/null || echo "   (git未初始化，跳过diff)"
echo ""

echo "======================================"
echo "  ✅ Phase 2 导入更新完成！"
echo "======================================"
echo ""
echo "📊 修改统计："
echo "   - 更新文件: 9个"
echo "   - realtime_data: 5个文件"
echo "   - market_data: 3个文件"
echo "   - etf_data_fetcher: 1个文件"
echo ""
echo "⚠️  重要：现在需要测试验证！"
echo ""
echo "📝 下一步："
echo "   1. 运行测试: bash scripts/test_phase2.sh"
echo "   2. 如果测试通过，删除兼容层文件"
echo "   3. 如果测试失败，恢复备份: cp .backup_phase2/* ."
echo ""
