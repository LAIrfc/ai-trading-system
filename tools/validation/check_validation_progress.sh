#!/bin/bash
# 检查换手率验证脚本的进度

LOG_FILE="turnover_validation_150.log"
RESULT_FILE="turnover_validation_results.json"

echo "检查验证进度..."
echo "=================="

if [ -f "$LOG_FILE" ]; then
    echo "日志文件: $LOG_FILE"
    echo "最后10行:"
    tail -10 "$LOG_FILE"
    echo ""
else
    echo "日志文件不存在"
fi

if [ -f "$RESULT_FILE" ]; then
    echo "结果文件: $RESULT_FILE"
    python3 << EOF
import json
try:
    with open('$RESULT_FILE', 'r', encoding='utf-8') as f:
        data = json.load(f)
    count = len(data.get('detailed_results', []))
    print(f"已完成股票数量: {count}")
    if 'summary' in data:
        print("\n当前汇总结果:")
        summary = data['summary']
        if 'total_return' in summary:
            tr = summary['total_return']
            print(f"  总收益: 有换手率={tr['with_avg']}%, 无换手率={tr['without_avg']}%, 改进={tr['improvement']}%")
        if 'sharpe' in summary:
            sh = summary['sharpe']
            print(f"  夏普比率: 有换手率={sh['with_avg']}, 无换手率={sh['without_avg']}, 改进={sh['improvement']}")
except Exception as e:
    print(f"读取结果文件失败: {e}")
EOF
else
    echo "结果文件不存在（脚本可能还在运行）"
fi

echo ""
echo "检查进程..."
ps aux | grep validate_turnover_effect | grep -v grep || echo "进程未运行"
