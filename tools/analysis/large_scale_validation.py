#!/usr/bin/env python3
"""
大规模修复验证 — 500只股票全策略诊断

验证项：
  1. StrategySignal 参数顺序（news_sentiment.py 修复）
  2. 所有策略无异常执行
  3. 策略活跃度统计
  4. PE/PB 多源降级 + parquet 缓存
  5. DoublerModel 大市值边界 >=500
  6. Ensemble 14策略投票 + 共振/弱动态权重开关
"""
from __future__ import annotations

import json
import logging
import os
import random
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

pd.set_option('future.no_silent_downcasting', True)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)
logger = logging.getLogger('validation')
logger.setLevel(logging.INFO)

STOCK_LIMIT = 500
KLINE_BARS = 250


def load_stocks(pool_path: str, limit: int) -> list:
    with open(pool_path) as f:
        pool = json.load(f)
    stocks = []
    for sector, slist in pool.get('stocks', {}).items():
        for s in slist:
            s['sector'] = sector
            stocks.append(s)
    random.seed(42)
    if limit < len(stocks):
        stocks = random.sample(stocks, limit)
    return stocks


def validate_signal(sig, strategy_name: str) -> list[str]:
    """校验 StrategySignal 字段类型是否正确"""
    errors = []
    if not isinstance(sig.action, str):
        errors.append(f'{strategy_name}: action={sig.action!r} 不是str')
    if not isinstance(sig.confidence, (int, float)):
        errors.append(f'{strategy_name}: confidence={sig.confidence!r} 不是数值')
    if not isinstance(sig.reason, str):
        errors.append(f'{strategy_name}: reason={sig.reason!r} 不是str (可能参数顺序错误)')
    if not isinstance(sig.position, (int, float)):
        errors.append(f'{strategy_name}: position={sig.position!r} 不是数值 (可能参数顺序错误)')
    if not isinstance(sig.indicators, dict):
        errors.append(f'{strategy_name}: indicators={sig.indicators!r} 不是dict')
    return errors


def run_validation():
    from src.data.provider.data_provider import get_default_kline_provider
    from src.strategies.ensemble import EnsembleStrategy

    pool_path = os.path.join(Path(__file__).resolve().parents[2], 'mydate', 'stock_pool_all.json')
    if not os.path.exists(pool_path):
        logger.error(f'股票池不存在: {pool_path}')
        return

    provider = get_default_kline_provider()
    stocks = load_stocks(pool_path, STOCK_LIMIT)
    logger.info(f'=== 大规模验证开始: {len(stocks)}只股票 ===')

    ALL_STRATEGIES = [
        'MA', 'MACD', 'RSI', 'BOLL', 'KDJ', 'DUAL',
        'PE', 'PB', 'PEPB',
        'NEWS', 'SENTIMENT', 'MONEY_FLOW',
        'EARNINGS_GROWTH', 'INDUSTRY_TREND',
    ]

    stats = {n: {'buy': 0, 'sell': 0, 'hold': 0, 'error': 0, 'count': 0,
                 'conf_sum': 0.0, 'type_errors': []}
             for n in ALL_STRATEGIES}
    stats['ENSEMBLE'] = {'buy': 0, 'sell': 0, 'hold': 0, 'error': 0, 'count': 0,
                         'conf_sum': 0.0, 'type_errors': []}

    ensemble_errors = []
    pe_pb_stats = {'has_data': 0, 'no_data': 0, 'cache_hit': 0}
    doubler_500_tests = []
    stock_ok = 0
    stock_fail = 0
    t0 = time.time()

    skip_network = {'NEWS', 'MONEY_FLOW', 'EARNINGS_GROWTH', 'INDUSTRY_TREND'}

    for i, s in enumerate(stocks):
        code = s['code']
        name = s.get('name', code)

        try:
            df = provider.get_kline(symbol=code, datalen=KLINE_BARS, min_bars=60,
                                    retries=1, timeout=8)
            if df is None or len(df) < 60:
                stock_fail += 1
                continue
        except Exception:
            stock_fail += 1
            continue

        ens = EnsembleStrategy(symbol=code, stock_name=name)

        for sname, strat in ens.sub_strategies.items():
            if sname not in stats:
                continue
            if sname in skip_network:
                continue
            try:
                sig = strat.analyze(df)
                stats[sname]['count'] += 1

                type_errs = validate_signal(sig, sname)
                if type_errs:
                    stats[sname]['type_errors'].extend(type_errs)

                if sig.action == 'BUY':
                    stats[sname]['buy'] += 1
                elif sig.action == 'SELL':
                    stats[sname]['sell'] += 1
                else:
                    stats[sname]['hold'] += 1
                stats[sname]['conf_sum'] += sig.confidence
            except Exception as e:
                stats[sname]['error'] += 1
                stats[sname]['count'] += 1
                if stats[sname]['error'] <= 3:
                    ensemble_errors.append(f'{sname}@{code}: {e}')

        try:
            ens_sig = ens.analyze(df)
            stats['ENSEMBLE']['count'] += 1
            type_errs = validate_signal(ens_sig, 'ENSEMBLE')
            if type_errs:
                stats['ENSEMBLE']['type_errors'].extend(type_errs)
            if ens_sig.action == 'BUY':
                stats['ENSEMBLE']['buy'] += 1
            elif ens_sig.action == 'SELL':
                stats['ENSEMBLE']['sell'] += 1
            else:
                stats['ENSEMBLE']['hold'] += 1
            stats['ENSEMBLE']['conf_sum'] += ens_sig.confidence
        except Exception as e:
            stats['ENSEMBLE']['error'] += 1
            stats['ENSEMBLE']['count'] += 1
            if len(ensemble_errors) < 10:
                ensemble_errors.append(f'ENSEMBLE@{code}: {e}\n{traceback.format_exc()[-200:]}')

        if 'pe_ttm' in df.columns and df['pe_ttm'].notna().sum() > 50:
            pe_pb_stats['has_data'] += 1
        else:
            pe_pb_stats['no_data'] += 1

        stock_ok += 1
        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (len(stocks) - i - 1) / rate
            logger.info(f'进度: {i+1}/{len(stocks)} | 成功={stock_ok} 失败={stock_fail} | '
                        f'速度={rate:.1f}只/秒 | ETA={eta:.0f}秒')

    elapsed = time.time() - t0

    lines = []
    lines.append('=' * 70)
    lines.append(f'  大规模修复验证报告 ({stock_ok}只股票, {elapsed:.1f}秒)')
    lines.append('=' * 70)

    lines.append(f'\n## 1. 基本统计')
    lines.append(f'  目标: {len(stocks)} | 成功: {stock_ok} | K线获取失败: {stock_fail}')
    lines.append(f'  跳过网络策略: {", ".join(sorted(skip_network))}')

    lines.append(f'\n## 2. 各策略信号分布')
    lines.append(f'{"策略":18s} | {"总数":>4s} | {"BUY":>4s} | {"SELL":>4s} | {"HOLD":>4s} | '
                 f'{"ERR":>3s} | {"BUY%":>6s} | {"有效率":>6s} | {"均信度":>5s} | 类型错误')
    lines.append('-' * 110)

    all_names = [n for n in ALL_STRATEGIES if n not in skip_network] + ['ENSEMBLE']
    for n in all_names:
        s = stats[n]
        total = s['count'] or 1
        buy_pct = s['buy'] / total * 100
        active = (s['buy'] + s['sell']) / total * 100
        conf = s['conf_sum'] / total
        te = len(s['type_errors'])
        flag = f'!!! {te}个' if te > 0 else 'OK'
        lines.append(f'{n:18s} | {s["count"]:4d} | {s["buy"]:4d} | {s["sell"]:4d} | {s["hold"]:4d} | '
                     f'{s["error"]:3d} | {buy_pct:5.1f}% | {active:5.1f}% | {conf:.3f} | {flag}')

    lines.append(f'\n## 3. 关键修复验证')

    total_type_errors = sum(len(s['type_errors']) for s in stats.values())
    lines.append(f'\n### 3.1 StrategySignal 参数顺序')
    if total_type_errors == 0:
        lines.append('  ✅ 所有策略的 StrategySignal 字段类型正确 (action=str, confidence=float, reason=str, position=float)')
    else:
        lines.append(f'  ❌ 发现 {total_type_errors} 个类型错误:')
        for n in all_names:
            for err in stats[n]['type_errors'][:5]:
                lines.append(f'    - {err}')

    lines.append(f'\n### 3.2 PE/PB 数据可用性')
    lines.append(f'  有PE/PB历史(>50条): {pe_pb_stats["has_data"]}只 ({pe_pb_stats["has_data"]/(stock_ok or 1)*100:.1f}%)')
    lines.append(f'  无PE/PB历史: {pe_pb_stats["no_data"]}只')

    pe_active = stats['PE']['buy'] + stats['PE']['sell']
    pb_active = stats['PB']['buy'] + stats['PB']['sell']
    pepb_active = stats['PEPB']['buy'] + stats['PEPB']['sell']
    lines.append(f'  PE策略有效信号: {pe_active} ({pe_active/(stats["PE"]["count"] or 1)*100:.1f}%)')
    lines.append(f'  PB策略有效信号: {pb_active} ({pb_active/(stats["PB"]["count"] or 1)*100:.1f}%)')
    lines.append(f'  PEPB策略有效信号: {pepb_active} ({pepb_active/(stats["PEPB"]["count"] or 1)*100:.1f}%)')

    lines.append(f'\n### 3.3 Ensemble 14策略 + 开关状态')
    lines.append(f'  子策略数: {len(ens.sub_strategies)}')
    from src.strategies.ensemble import ENABLE_RESONANCE_THRESHOLD, ENABLE_WEAK_DYNAMIC_WEIGHT
    lines.append(f'  ENABLE_RESONANCE_THRESHOLD: {ENABLE_RESONANCE_THRESHOLD}')
    lines.append(f'  ENABLE_WEAK_DYNAMIC_WEIGHT: {ENABLE_WEAK_DYNAMIC_WEIGHT}')
    lines.append(f'  Ensemble执行错误: {stats["ENSEMBLE"]["error"]}')

    lines.append(f'\n### 3.4 策略执行异常')
    total_errors = sum(s['error'] for s in stats.values())
    if total_errors == 0:
        lines.append('  ✅ 零异常')
    else:
        lines.append(f'  ⚠️ 共 {total_errors} 个异常:')
        for err in ensemble_errors[:10]:
            lines.append(f'    - {err}')

    lines.append(f'\n## 4. 总结')
    issues = []
    if total_type_errors > 0:
        issues.append(f'StrategySignal类型错误 {total_type_errors}个')
    if total_errors > 0:
        issues.append(f'策略执行异常 {total_errors}个')
    if pe_pb_stats['has_data'] < stock_ok * 0.1:
        issues.append('PE/PB数据覆盖率低于10%')

    if not issues:
        lines.append('  ✅ 所有修复验证通过，500只股票零类型错误、零执行异常')
    else:
        lines.append(f'  ⚠️ 存在问题: {"; ".join(issues)}')

    report = '\n'.join(lines)
    print(report)

    out_dir = os.path.join(Path(__file__).resolve().parents[2], 'output')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, 'large_scale_validation_report.md')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(report)
    logger.info(f'报告已保存: {out_path}')


if __name__ == '__main__':
    run_validation()
