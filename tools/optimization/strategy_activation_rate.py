#!/usr/bin/env python3
"""
策略活跃度诊断 (Strategy Activation Diagnostic)

对真实股票池跑全部子策略，统计每个策略的：
  - BUY/SELL/HOLD 占比
  - 平均置信度
  - 有效信号率（非HOLD比例）
  - 与DUAL的信号一致率

用于判断哪些策略"长期沉默"，哪些策略实际在驱动决策。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logger = logging.getLogger(__name__)

STRATEGY_NAMES = [
    'MA', 'MACD', 'RSI', 'BOLL', 'KDJ', 'DUAL',
    'PE', 'PB', 'PEPB',
    'NEWS', 'SENTIMENT', 'MONEY_FLOW',
    'EARNINGS_GROWTH',
]


def _load_stocks(pool_path: str, limit: int) -> list:
    with open(pool_path) as f:
        pool = json.load(f)
    stocks = []
    for sector, slist in pool.get('stocks', {}).items():
        for s in slist:
            s['sector'] = sector
            stocks.append(s)
    if limit and limit < len(stocks):
        import random
        random.seed(42)
        stocks = random.sample(stocks, limit)
    return stocks


def run_diagnostic(pool_path: str, limit: int = 50) -> str:
    from src.data.provider.data_provider import get_default_kline_provider
    from src.strategies.ensemble import EnsembleStrategy

    provider = get_default_kline_provider()
    stocks = _load_stocks(pool_path, limit)

    stats = {name: {'buy': 0, 'sell': 0, 'hold': 0, 'conf_sum': 0.0, 'count': 0}
             for name in STRATEGY_NAMES}
    dual_signals = {}
    stock_count = 0

    for s in stocks:
        code = s['code']
        try:
            df = provider.get_kline(symbol=code, datalen=200, min_bars=60, retries=1, timeout=8)
            if df is None or len(df) < 60:
                continue
        except Exception:
            continue

        ens = EnsembleStrategy()
        try:
            for name, strat in ens.sub_strategies.items():
                if name not in stats:
                    continue
                try:
                    sig = strat.analyze(df)
                    action = sig.action
                    stats[name]['count'] += 1
                    if action == 'BUY':
                        stats[name]['buy'] += 1
                    elif action == 'SELL':
                        stats[name]['sell'] += 1
                    else:
                        stats[name]['hold'] += 1
                    stats[name]['conf_sum'] += sig.confidence

                    if name == 'DUAL':
                        dual_signals[code] = action
                except Exception:
                    stats[name]['count'] += 1
                    stats[name]['hold'] += 1
        except Exception:
            continue

        stock_count += 1
        if stock_count % 10 == 0:
            print(f'  已分析 {stock_count}/{len(stocks)} 只...')

    lines = [f'# 策略活跃度诊断报告\n']
    lines.append(f'测试股票数: {stock_count}\n')

    lines.append('## 各策略信号分布\n')
    lines.append('| 策略 | 总数 | BUY | SELL | HOLD | BUY% | SELL% | 有效率 | 平均置信度 |')
    lines.append('|------|------|-----|------|------|------|-------|--------|----------|')

    sorted_names = sorted(STRATEGY_NAMES,
                          key=lambda n: (stats[n]['buy'] + stats[n]['sell']) / max(1, stats[n]['count']),
                          reverse=True)

    for name in sorted_names:
        s = stats[name]
        total = s['count'] or 1
        buy_pct = s['buy'] / total * 100
        sell_pct = s['sell'] / total * 100
        active_rate = (s['buy'] + s['sell']) / total * 100
        avg_conf = s['conf_sum'] / total
        lines.append(
            f"| {name:18s} | {total:4d} | {s['buy']:3d} | {s['sell']:3d} | {s['hold']:3d} | "
            f"{buy_pct:5.1f}% | {sell_pct:5.1f}% | {active_rate:5.1f}% | {avg_conf:.3f} |"
        )

    lines.append('')
    lines.append('## 诊断结论\n')

    silent = [n for n in STRATEGY_NAMES
              if stats[n]['count'] > 0
              and (stats[n]['buy'] + stats[n]['sell']) / stats[n]['count'] < 0.05]
    active = [n for n in STRATEGY_NAMES
              if stats[n]['count'] > 0
              and (stats[n]['buy'] + stats[n]['sell']) / stats[n]['count'] > 0.30]
    moderate = [n for n in STRATEGY_NAMES if n not in silent and n not in active and stats[n]['count'] > 0]

    lines.append(f'- **高活跃** (>30%有效信号): {", ".join(active) if active else "无"}')
    lines.append(f'- **中等活跃** (5-30%): {", ".join(moderate) if moderate else "无"}')
    lines.append(f'- **长期沉默** (<5%有效信号): {", ".join(silent) if silent else "无"}')
    lines.append('')

    if silent:
        lines.append('### 建议\n')
        lines.append(f'以下策略长期输出HOLD，在ensemble中占席位但不贡献信号：{", ".join(silent)}')
        lines.append('')
        lines.append('可能原因：')
        lines.append('- 阈值过严（BUY/SELL条件太苛刻）')
        lines.append('- 数据缺失（如MONEY_FLOW需要龙虎榜数据）')
        lines.append('- 适合作为修正策略而非投票策略')
        lines.append('')
        lines.append('建议：')
        lines.append('1. 放宽这些策略的信号阈值')
        lines.append('2. 或将它们从"投票策略"改为"置信度修正器"')
        lines.append('3. 或从ensemble移出，减少无效占席')

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='策略活跃度诊断')
    parser.add_argument('--pool', default='mydate/stock_pool_all.json')
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument('--output', default='output/strategy_activation_report.md')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

    print(f'开始诊断: {args.limit}只股票...\n')
    report = run_diagnostic(args.pool, args.limit)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f'\n✅ 诊断报告已保存: {args.output}')
    print('\n' + report)


if __name__ == '__main__':
    main()
