#!/bin/bash
# 强势股回踩再启动 — 独立选股扫描器
# 用法:
#   ./run_breakout_scan.sh                    # 默认稳健模式
#   ./run_breakout_scan.sh --mode aggressive  # 激进模式（回踩低吸）
#   ./run_breakout_scan.sh --top 30           # 输出前30只

source $HOME/miniconda3/etc/profile.d/conda.sh
conda activate trading
cd /home/wangxinghan/codetree/ai-trading-system
python tools/analysis/breakout_pullback_scanner.py "$@"
