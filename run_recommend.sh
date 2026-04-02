#!/bin/bash
# 使用修复后的 Conda 环境运行每日推荐

source $HOME/miniconda3/etc/profile.d/conda.sh
conda activate trading
cd /home/wangxinghan/codetree/ai-trading-system
python tools/analysis/recommend_today.py "$@"
