#!/bin/bash
# 删除兼容层文件（Phase 2 最后一步）

set -e

echo "======================================"
echo "  删除兼容层文件"
echo "======================================"
echo ""

cd "$(dirname "$0")/.."

echo "🗑️  删除4个兼容层文件..."
echo ""

# 删除兼容层文件
for file in src/data/etf_data_fetcher.py src/data/fundamental_fetcher.py src/data/realtime_data.py src/data/market_data.py; do
    if [ -f "$file" ]; then
        echo "   删除: $file"
        rm "$file"
        echo "      ✅ 已删除"
    else
        echo "   ⚠️  $file 不存在，跳过"
    fi
done

echo ""
echo "======================================"
echo "  ✅ 兼容层文件已删除！"
echo "======================================"
echo ""
echo "📊 删除统计："
echo "   - 删除文件: 4个"
echo "   - 减少代码: ~46行"
echo ""
echo "📝 下一步："
echo "   1. 运行最终验证: bash scripts/final_verification.sh"
echo "   2. Commit 所有变更"
echo ""
