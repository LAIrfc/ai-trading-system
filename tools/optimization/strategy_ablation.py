#!/usr/bin/env python3
"""
策略剔除实验框架 (Strategy Ablation Study)

三层实验：
  1. 单策略剔除 — 逐个去掉1个策略，看 Sharpe/胜率变化
  2. 整组剔除   — 去掉一个信号组（趋势/超跌/估值/基本面/事件）
  3. 核心组验证 — 只保留两组看边际贡献

输出：Markdown 表格 + 每项增量贡献排名
"""

from __future__ import annotations

import argparse
import copy
import logging
import sys
import os
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.strategies.ensemble import EnsembleStrategy

logger = logging.getLogger(__name__)

SIGNAL_GROUPS = {
    'trend':       ['MA', 'MACD', 'DUAL'],
    'reversal':    ['RSI', 'KDJ', 'BOLL', 'SENTIMENT'],
    'valuation':   ['PE', 'PB', 'PEPB'],
    'fundamental': ['EARNINGS_GROWTH', 'PROFIT_QUALITY'],
    'event':       ['NEWS', 'MONEY_FLOW', 'INDUSTRY_TREND'],
}

ALL_STRATEGIES = [s for group in SIGNAL_GROUPS.values() for s in group]


def _load_test_stocks(pool_path: str, limit: int = 50) -> List[dict]:
    """加载测试股票池"""
    import json
    with open(pool_path) as f:
        pool = json.load(f)
    stocks = []
    for sector_info in pool.get('sectors', pool) if isinstance(pool, dict) else pool:
        if isinstance(sector_info, dict) and 'stocks' in sector_info:
            for s in sector_info['stocks']:
                stocks.append(s)
        elif isinstance(sector_info, dict) and 'code' in sector_info:
            stocks.append(sector_info)
    return stocks[:limit]


def _run_ensemble_on_stock(stock: dict, excluded: List[str] = None) -> Optional[dict]:
    """
    对单只股票跑 Ensemble 策略（排除指定策略），返回决策结果。
    """
    from src.data.fetchers.data_prefetch import get_default_kline_provider
    code = stock.get('code', '')
    try:
        provider = get_default_kline_provider()
        df = provider.get_kline(code, days=120)
        if df is None or len(df) < 30:
            return None
    except Exception:
        return None

    weights = EnsembleStrategy.DEFAULT_WEIGHTS.copy() if hasattr(EnsembleStrategy, 'DEFAULT_WEIGHTS') else {}
    if excluded:
        for s in excluded:
            weights.pop(s, None)

    ens = EnsembleStrategy(weights=weights if weights else None)
    try:
        signal = ens.analyze(df)
        return {
            'code': code,
            'action': signal.action,
            'confidence': signal.confidence,
        }
    except Exception as e:
        logger.debug("Ensemble failed for %s: %s", code, e)
        return None


def run_ablation(pool_path: str, limit: int = 50) -> str:
    """
    执行完整剔除实验，返回 Markdown 报告。
    """
    stocks = _load_test_stocks(pool_path, limit)
    if not stocks:
        return "❌ 无法加载测试股票池"

    lines = ["# 策略剔除实验报告\n"]
    lines.append(f"测试股票数: {len(stocks)}\n")

    # Baseline: 全策略
    print(f"[Ablation] Running baseline with all strategies on {len(stocks)} stocks...")
    baseline = []
    for s in stocks:
        r = _run_ensemble_on_stock(s, excluded=[])
        if r:
            baseline.append(r)
    base_buy_rate = sum(1 for r in baseline if r['action'] == 'BUY') / max(1, len(baseline))
    base_avg_conf = np.mean([r['confidence'] for r in baseline]) if baseline else 0

    lines.append(f"**基准**: BUY率={base_buy_rate:.1%}, 平均置信度={base_avg_conf:.3f}, 有效股={len(baseline)}\n")

    # === 1. 单策略剔除 ===
    lines.append("## 1. 单策略剔除\n")
    lines.append("| 被剔除策略 | BUY率 | 平均置信度 | BUY率变化 | 置信度变化 | 判定 |")
    lines.append("|-----------|-------|----------|----------|----------|------|")

    single_results = {}
    for strat in ALL_STRATEGIES:
        print(f"  [Single] Excluding {strat}...")
        results = []
        for s in stocks:
            r = _run_ensemble_on_stock(s, excluded=[strat])
            if r:
                results.append(r)
        if results:
            buy_rate = sum(1 for r in results if r['action'] == 'BUY') / max(1, len(results))
            avg_conf = np.mean([r['confidence'] for r in results])
            delta_buy = buy_rate - base_buy_rate
            delta_conf = avg_conf - base_avg_conf
            verdict = "✅有贡献" if abs(delta_buy) > 0.02 or abs(delta_conf) > 0.01 else "⚠可能冗余"
            single_results[strat] = {'delta_buy': delta_buy, 'delta_conf': delta_conf}
            lines.append(
                f"| {strat} | {buy_rate:.1%} | {avg_conf:.3f} | "
                f"{delta_buy:+.1%} | {delta_conf:+.3f} | {verdict} |"
            )
    lines.append("")

    # === 2. 整组剔除 ===
    lines.append("## 2. 整组剔除\n")
    lines.append("| 被剔除组 | 包含策略 | BUY率 | 平均置信度 | BUY率变化 | 置信度变化 |")
    lines.append("|---------|---------|-------|----------|----------|----------|")

    for gname, members in SIGNAL_GROUPS.items():
        print(f"  [Group] Excluding {gname}: {members}...")
        results = []
        for s in stocks:
            r = _run_ensemble_on_stock(s, excluded=members)
            if r:
                results.append(r)
        if results:
            buy_rate = sum(1 for r in results if r['action'] == 'BUY') / max(1, len(results))
            avg_conf = np.mean([r['confidence'] for r in results])
            delta_buy = buy_rate - base_buy_rate
            delta_conf = avg_conf - base_avg_conf
            lines.append(
                f"| {gname} | {', '.join(members)} | {buy_rate:.1%} | "
                f"{avg_conf:.3f} | {delta_buy:+.1%} | {delta_conf:+.3f} |"
            )
    lines.append("")

    # === 3. 核心组验证 ===
    lines.append("## 3. 核心组验证（只保留两组）\n")
    lines.append("| 保留组 | BUY率 | 平均置信度 |")
    lines.append("|-------|-------|----------|")

    combos = [
        ('fundamental+valuation', SIGNAL_GROUPS['fundamental'] + SIGNAL_GROUPS['valuation']),
        ('reversal+trend',        SIGNAL_GROUPS['reversal'] + SIGNAL_GROUPS['trend']),
        ('fundamental+event',     SIGNAL_GROUPS['fundamental'] + SIGNAL_GROUPS['event']),
        ('trend+event',           SIGNAL_GROUPS['trend'] + SIGNAL_GROUPS['event']),
    ]
    for combo_name, keep_list in combos:
        exclude = [s for s in ALL_STRATEGIES if s not in keep_list]
        print(f"  [Core] Keeping only {combo_name}...")
        results = []
        for s in stocks:
            r = _run_ensemble_on_stock(s, excluded=exclude)
            if r:
                results.append(r)
        if results:
            buy_rate = sum(1 for r in results if r['action'] == 'BUY') / max(1, len(results))
            avg_conf = np.mean([r['confidence'] for r in results])
            lines.append(f"| {combo_name} | {buy_rate:.1%} | {avg_conf:.3f} |")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="策略剔除实验")
    parser.add_argument('--pool', default='mydate/stock_pool_all.json', help='股票池路径')
    parser.add_argument('--limit', type=int, default=30, help='测试股票数量')
    parser.add_argument('--output', default='output/ablation_report.md', help='输出路径')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

    report = run_ablation(args.pool, args.limit)
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n✅ 剔除实验报告已保存: {args.output}")


if __name__ == '__main__':
    main()
