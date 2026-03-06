#!/bin/bash
# 项目优化 Phase 1: 立即清理
# 执行时间：1-2小时
# 风险等级：⭐ 低

set -e  # 遇到错误立即退出

echo "======================================"
echo "  项目优化 Phase 1: 立即清理"
echo "======================================"
echo ""

# 切换到项目根目录
cd "$(dirname "$0")/.."

echo "📍 当前目录: $(pwd)"
echo ""

# 1. 删除占位文件
echo "🗑️  Step 1: 删除占位文件"
if [ -f "src/data/industry.py" ]; then
    echo "   删除: src/data/industry.py"
    rm src/data/industry.py
    echo "   ✅ 已删除"
else
    echo "   ⚠️  文件不存在，跳过"
fi
echo ""

# 2. 合并文档
echo "📄 Step 2: 合并文档"

# 2.1 合并 TROUBLESHOOTING_TKINTER.md
if [ -f "docs/setup/TROUBLESHOOTING_TKINTER.md" ]; then
    echo "   合并: TROUBLESHOOTING_TKINTER.md -> TROUBLESHOOTING.md"
    echo "" >> docs/setup/TROUBLESHOOTING.md
    echo "---" >> docs/setup/TROUBLESHOOTING.md
    echo "" >> docs/setup/TROUBLESHOOTING.md
    echo "## Tkinter 相关问题" >> docs/setup/TROUBLESHOOTING.md
    echo "" >> docs/setup/TROUBLESHOOTING.md
    cat docs/setup/TROUBLESHOOTING_TKINTER.md >> docs/setup/TROUBLESHOOTING.md
    rm docs/setup/TROUBLESHOOTING_TKINTER.md
    echo "   ✅ 已合并并删除"
else
    echo "   ⚠️  TROUBLESHOOTING_TKINTER.md 不存在，跳过"
fi

# 2.2 删除 GIT_GUIDE.md
if [ -f "docs/setup/GIT_GUIDE.md" ]; then
    echo "   删除: docs/setup/GIT_GUIDE.md（通用知识，不需要项目专门文档）"
    rm docs/setup/GIT_GUIDE.md
    echo "   ✅ 已删除"
else
    echo "   ⚠️  GIT_GUIDE.md 不存在，跳过"
fi

# 2.3 合并 V33 文档
if [ -f "docs/strategy/V33_落地与状态.md" ]; then
    echo "   合并: V33_落地与状态.md -> V33_DESIGN_SPEC.md"
    echo "" >> docs/strategy/V33_DESIGN_SPEC.md
    echo "---" >> docs/strategy/V33_DESIGN_SPEC.md
    echo "" >> docs/strategy/V33_DESIGN_SPEC.md
    echo "## 落地状态" >> docs/strategy/V33_DESIGN_SPEC.md
    echo "" >> docs/strategy/V33_DESIGN_SPEC.md
    cat "docs/strategy/V33_落地与状态.md" >> docs/strategy/V33_DESIGN_SPEC.md
    rm "docs/strategy/V33_落地与状态.md"
    echo "   ✅ 已合并并删除"
else
    echo "   ⚠️  V33_落地与状态.md 不存在，跳过"
fi
echo ""

# 3. 更新 .gitignore
echo "📝 Step 3: 更新 .gitignore"
if ! grep -q "mycache/\*\*/\*.csv" .gitignore; then
    echo "" >> .gitignore
    echo "# 缓存和临时文件（自动生成）" >> .gitignore
    echo "mycache/**/*.csv" >> .gitignore
    echo "mycache/**/*.parquet" >> .gitignore
    echo "mydate/temp_*.json" >> .gitignore
    echo "mylog/*.log" >> .gitignore
    echo "*.pyc" >> .gitignore
    echo "__pycache__/" >> .gitignore
    echo "   ✅ 已添加缓存忽略规则"
else
    echo "   ⚠️  规则已存在，跳过"
fi
echo ""

# 4. 统计结果
echo "======================================"
echo "  ✅ Phase 1 完成！"
echo "======================================"
echo ""
echo "📊 优化结果："
echo "   - 删除文件: 1个占位文件 + 3个重复文档 = 4个"
echo "   - 合并文档: 3个"
echo "   - 更新配置: .gitignore"
echo ""
echo "📝 下一步："
echo "   1. 查看优化报告: docs/architecture/OPTIMIZATION_SUMMARY.md"
echo "   2. 执行 Phase 2: bash scripts/optimize_phase2.sh（需要测试）"
echo "   3. 创建缓存清理工具: 见 OPTIMIZATION_EXECUTION_PLAN.md"
echo ""
echo "💡 提示："
echo "   - 可以运行 git status 查看变更"
echo "   - 建议先 commit 这些变更，再继续下一步"
echo ""
