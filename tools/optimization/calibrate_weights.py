#!/usr/bin/env python3
"""
固定权重校准工具

基于完整 12 策略全量数据，评估每个子策略的独立表现，
然后基于各策略的 Sharpe/收益/胜率 来确定最优权重配置。

步骤：
  Phase 1: 各策略独立回测（每只股票 × 12 策略）
  Phase 2: 汇总统计各策略平均表现
  Phase 3: 基于表现指标计算候选权重
  Phase 4: Ensemble 整体回测验证（对比旧权重 vs 新权重）

用法:
  python3 tools/optimization/calibrate_weights.py                # 全量
  python3 tools/optimization/calibrate_weights.py --stocks 100   # 前100只
  python3 tools/optimization/calibrate_weights.py --phase 1      # 只跑Phase1
"""

import sys
import os
import time
import json
import argparse
import logging
from collections import defaultdict

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')

BACKTEST_DIR = os.path.join(os.path.dirname(__file__), "../../mydate/backtest_kline")
RESULT_DIR = os.path.join(os.path.dirname(__file__), "../../results/calibration")
os.makedirs(RESULT_DIR, exist_ok=True)


def p(*a, **kw):
    print(*a, **kw, flush=True)


# ============================================================
# Phase 1: 各策略独立回测
# ============================================================

def run_individual_backtests(stock_files, skip_existing=True):
    """对每只股票的每个子策略单独回测"""
    from src.strategies.ma_cross import MACrossStrategy
    from src.strategies.macd_cross import MACDStrategy
    from src.strategies.rsi_signal import RSIStrategy
    from src.strategies.bollinger_band import BollingerBandStrategy
    from src.strategies.kdj_signal import KDJStrategy
    from src.strategies.dual_momentum import DualMomentumSingleStrategy
    from src.strategies.fundamental_pe import PEStrategy
    from src.strategies.fundamental_pb import PBStrategy
    from src.strategies.fundamental_pe_pb import PE_PB_CombinedStrategy
    from src.strategies.money_flow import MoneyFlowStrategy
    from src.strategies.base import Strategy

    # 只回测不需要外部API的策略（NEWS和SENTIMENT在回测中依赖外部数据，不可靠）
    strategy_factories = {
        'MA':         lambda: MACrossStrategy(),
        'MACD':       lambda: MACDStrategy(),
        'RSI':        lambda: RSIStrategy(),
        'BOLL':       lambda: BollingerBandStrategy(),
        'KDJ':        lambda: KDJStrategy(),
        'DUAL':       lambda: DualMomentumSingleStrategy(),
        'DUAL_REV':   lambda: DualMomentumSingleStrategy(),  # DUAL反向版本
        'PE':         lambda: PEStrategy(),
        'PB':         lambda: PBStrategy(),
        'PEPB':       lambda: PE_PB_CombinedStrategy(),
        'MONEY_FLOW': lambda: MoneyFlowStrategy(),
    }

    cache_file = os.path.join(RESULT_DIR, "phase1_individual_results.json")
    if skip_existing and os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                cached = json.load(f)
            if len(cached) > 0:
                p(f"  Phase 1 缓存命中: {len(cached)} 只股票的结果")
                return cached
        except Exception:
            pass

    all_results = {}
    total = len(stock_files)
    t0 = time.time()

    Strategy._BACKTEST_ACTIVE = True

    try:
        for i, fname in enumerate(stock_files):
            code = fname.replace('.parquet', '')
            path = os.path.join(BACKTEST_DIR, fname)

            try:
                df = pd.read_parquet(path)
            except Exception:
                continue

            if len(df) < 200:
                continue

            stock_results = {}

            for strat_name, factory in strategy_factories.items():
                try:
                    strat = factory()
                    if len(df) < strat.min_bars:
                        continue

                    result = strat.backtest(df)

                    # DUAL_REV: 反向信号回测
                    if strat_name == 'DUAL_REV':
                        result = _backtest_dual_reversed(strat, df)
                        if result is None:
                            continue

                    stock_results[strat_name] = {
                        'total_return': result.get('total_return', 0),
                        'trade_count': result.get('trade_count', 0),
                        'sharpe': result.get('sharpe', 0),
                        'max_drawdown': result.get('max_drawdown', 0),
                        'win_rate': result.get('win_rate', 0),
                        'annualized_return': result.get('annualized_return', 0),
                    }
                except Exception:
                    continue

            if stock_results:
                all_results[code] = stock_results

            if (i + 1) % 50 == 0 or i < 3:
                elapsed = time.time() - t0
                eta = elapsed / (i + 1) * (total - i - 1) / 60
                p(f"  [{i+1}/{total}] {code}: {len(stock_results)} 策略有效 "
                  f"(累计 {len(all_results)} 只) ETA {eta:.1f}min")
    finally:
        Strategy._BACKTEST_ACTIVE = False

    # 保存结果
    try:
        with open(cache_file, 'w') as f:
            json.dump(all_results, f, indent=2)
        p(f"  Phase 1 结果已保存: {cache_file}")
    except Exception as e:
        p(f"  ⚠️ 保存失败: {e}")

    return all_results


def _backtest_dual_reversed(strat, df):
    """DUAL 反向回测：手动反转信号后执行"""
    from src.strategies.base import StrategySignal

    original_analyze = strat.analyze

    def reversed_analyze(df_arg):
        sig = original_analyze(df_arg)
        if sig.action == 'BUY':
            return StrategySignal(
                action='SELL', confidence=sig.confidence,
                position=1.0 - sig.position,
                reason=f'[REV] {sig.reason}', indicators=sig.indicators)
        elif sig.action == 'SELL':
            return StrategySignal(
                action='BUY', confidence=sig.confidence,
                position=1.0 - sig.position,
                reason=f'[REV] {sig.reason}', indicators=sig.indicators)
        return sig

    strat.analyze = reversed_analyze
    try:
        result = strat.backtest(df)
        return result
    except Exception:
        return None
    finally:
        strat.analyze = original_analyze


# ============================================================
# Phase 2: 汇总统计
# ============================================================

def summarize_results(all_results):
    """汇总各策略的平均表现"""
    strategy_stats = defaultdict(lambda: {
        'returns': [], 'sharpes': [], 'drawdowns': [],
        'win_rates': [], 'trade_counts': [], 'annual_returns': [],
    })

    for code, stock_results in all_results.items():
        for strat_name, metrics in stock_results.items():
            s = strategy_stats[strat_name]
            s['returns'].append(metrics.get('total_return', 0))
            s['sharpes'].append(metrics.get('sharpe', 0))
            s['drawdowns'].append(metrics.get('max_drawdown', 0))
            s['win_rates'].append(metrics.get('win_rate', 0))
            s['trade_counts'].append(metrics.get('trade_count', 0))
            s['annual_returns'].append(metrics.get('annualized_return', 0))

    summary = {}
    for strat_name, s in strategy_stats.items():
        n = len(s['returns'])
        if n == 0:
            continue

        returns_arr = np.array(s['returns'])
        sharpes_arr = np.array(s['sharpes'])
        win_rates_arr = np.array(s['win_rates'])
        drawdowns_arr = np.array(s['drawdowns'])
        annual_arr = np.array(s['annual_returns'])
        trades_arr = np.array(s['trade_counts'])

        summary[strat_name] = {
            'stock_count': n,
            'avg_return': float(np.mean(returns_arr)),
            'median_return': float(np.median(returns_arr)),
            'avg_sharpe': float(np.mean(sharpes_arr)),
            'median_sharpe': float(np.median(sharpes_arr)),
            'avg_win_rate': float(np.mean(win_rates_arr)),
            'avg_max_drawdown': float(np.mean(drawdowns_arr)),
            'avg_annual_return': float(np.mean(annual_arr)),
            'avg_trades': float(np.mean(trades_arr)),
            'positive_return_pct': float((returns_arr > 0).mean()),
            'positive_sharpe_pct': float((sharpes_arr > 0).mean()),
        }

    return summary


def print_summary(summary):
    """打印策略表现汇总表"""
    p("\n" + "=" * 100)
    p("  Phase 2: 各策略独立表现汇总")
    p("=" * 100)
    p(f"{'策略':<12} {'股票数':>6} {'平均收益':>10} {'中位收益':>10} "
      f"{'平均Sharpe':>10} {'平均胜率':>8} {'平均回撤':>8} "
      f"{'正收益%':>8} {'平均交易':>8}")
    p("-" * 100)

    sorted_strats = sorted(summary.items(),
                           key=lambda x: x[1]['avg_sharpe'], reverse=True)

    for name, s in sorted_strats:
        p(f"{name:<12} {s['stock_count']:>6} "
          f"{s['avg_return']:>9.2%} {s['median_return']:>9.2%} "
          f"{s['avg_sharpe']:>10.4f} {s['avg_win_rate']:>7.1%} "
          f"{s['avg_max_drawdown']:>7.1%} "
          f"{s['positive_return_pct']:>7.1%} {s['avg_trades']:>8.1f}")

    p("=" * 100)


# ============================================================
# Phase 3: 基于表现计算候选权重
# ============================================================

def compute_candidate_weights(summary):
    """
    基于各策略表现指标计算候选权重配置

    方法：
    1. Sharpe-based: 权重 ∝ max(avg_sharpe, 0)
    2. Composite score: 综合 Sharpe + 正收益率 + 胜率
    3. Rank-based: 基于排名的等差权重
    """
    # 映射 DUAL_REV -> DUAL（ensemble 中用的是 DUAL + reverse）
    strat_names_in_ensemble = ['BOLL', 'MACD', 'KDJ', 'MA', 'DUAL', 'RSI',
                                'PE', 'PB', 'PEPB', 'NEWS', 'MONEY_FLOW', 'SENTIMENT']

    def _normalize_weights(raw, min_w=0.3, max_w=2.0):
        """归一化权重到 [min_w, max_w] 范围"""
        if not raw:
            return {}
        vals = list(raw.values())
        v_min, v_max = min(vals), max(vals)
        if v_max - v_min < 1e-9:
            return {k: 1.0 for k in raw}
        result = {}
        for k, v in raw.items():
            normalized = min_w + (v - v_min) / (v_max - v_min) * (max_w - min_w)
            result[k] = round(normalized, 2)
        return result

    candidates = {}

    # 方法1: Sharpe-based
    raw = {}
    for name in strat_names_in_ensemble:
        lookup = 'DUAL_REV' if name == 'DUAL' else name
        if lookup in summary:
            raw[name] = max(summary[lookup]['avg_sharpe'], 0.001)
        else:
            raw[name] = 0.5  # 无数据的策略给中等权重
    candidates['sharpe_based'] = _normalize_weights(raw)

    # 方法2: Composite score (Sharpe 40% + 正收益率 30% + 胜率 30%)
    raw = {}
    for name in strat_names_in_ensemble:
        lookup = 'DUAL_REV' if name == 'DUAL' else name
        if lookup in summary:
            s = summary[lookup]
            score = (0.4 * max(s['avg_sharpe'], 0) +
                     0.3 * s['positive_return_pct'] +
                     0.3 * s['avg_win_rate'])
            raw[name] = max(score, 0.01)
        else:
            raw[name] = 0.3
    candidates['composite'] = _normalize_weights(raw)

    # 方法3: Rank-based (按 Sharpe 排名)
    ranked = []
    for name in strat_names_in_ensemble:
        lookup = 'DUAL_REV' if name == 'DUAL' else name
        if lookup in summary:
            ranked.append((name, summary[lookup]['avg_sharpe']))
        else:
            ranked.append((name, 0))
    ranked.sort(key=lambda x: x[1], reverse=True)
    raw = {}
    n = len(ranked)
    for i, (name, _) in enumerate(ranked):
        raw[name] = 2.0 - (i / max(n - 1, 1)) * 1.5  # 2.0 -> 0.5
    candidates['rank_based'] = {k: round(v, 2) for k, v in raw.items()}

    # 当前权重（baseline）
    candidates['current'] = {
        'BOLL': 1.5, 'MACD': 1.3, 'KDJ': 1.1, 'MA': 1.0,
        'DUAL': 0.9, 'RSI': 0.8, 'PEPB': 0.8, 'PE': 0.6,
        'PB': 0.6, 'NEWS': 0.5, 'SENTIMENT': 0.5, 'MONEY_FLOW': 0.4,
    }

    return candidates


def print_candidates(candidates):
    """打印候选权重配置"""
    p("\n" + "=" * 100)
    p("  Phase 3: 候选权重配置")
    p("=" * 100)

    strat_names = ['BOLL', 'MACD', 'KDJ', 'MA', 'DUAL', 'RSI',
                   'PE', 'PB', 'PEPB', 'NEWS', 'SENTIMENT', 'MONEY_FLOW']

    header = f"{'策略':<12}"
    for method in candidates:
        header += f" {method:>14}"
    p(header)
    p("-" * 100)

    for name in strat_names:
        row = f"{name:<12}"
        for method, weights in candidates.items():
            row += f" {weights.get(name, 0):>14.2f}"
        p(row)

    p("=" * 100)


# ============================================================
# Phase 4: Ensemble 整体回测验证
# ============================================================

def run_ensemble_backtests(stock_files, candidates, max_stocks=200):
    """用不同权重配置做 Ensemble 整体回测"""
    from src.strategies.ensemble import EnsembleStrategy
    from src.strategies.base import Strategy

    Strategy._BACKTEST_ACTIVE = True

    files_to_test = stock_files[:max_stocks]
    total = len(files_to_test)

    p(f"\n  Phase 4: Ensemble 整体回测 ({total} 只股票 × {len(candidates)} 配置)")

    ensemble_results = {}

    for method_name, weights in candidates.items():
        p(f"\n  --- 配置: {method_name} ---")
        returns = []
        sharpes = []
        trade_counts = []
        t0 = time.time()

        for i, fname in enumerate(files_to_test):
            code = fname.replace('.parquet', '')
            path = os.path.join(BACKTEST_DIR, fname)

            try:
                df = pd.read_parquet(path)
                if len(df) < 200:
                    continue

                ens = EnsembleStrategy(mode='weighted', weights=weights.copy())
                result = ens.backtest(df)

                returns.append(result.get('total_return', 0))
                sharpes.append(result.get('sharpe', 0))
                trade_counts.append(result.get('trade_count', 0))

            except Exception:
                continue

            if (i + 1) % 100 == 0:
                elapsed = time.time() - t0
                p(f"    [{i+1}/{total}] 已完成 {len(returns)} 只")

        elapsed = time.time() - t0

        if returns:
            returns_arr = np.array(returns)
            sharpes_arr = np.array(sharpes)
            ensemble_results[method_name] = {
                'stock_count': len(returns),
                'avg_return': float(np.mean(returns_arr)),
                'median_return': float(np.median(returns_arr)),
                'avg_sharpe': float(np.mean(sharpes_arr)),
                'median_sharpe': float(np.median(sharpes_arr)),
                'positive_return_pct': float((returns_arr > 0).mean()),
                'avg_trades': float(np.mean(trade_counts)),
                'elapsed_sec': round(elapsed, 1),
            }
            p(f"    完成: 平均收益={np.mean(returns_arr):.2%}, "
              f"平均Sharpe={np.mean(sharpes_arr):.4f}, "
              f"正收益率={float((returns_arr > 0).mean()):.1%}, "
              f"耗时 {elapsed:.0f}s")

    Strategy._BACKTEST_ACTIVE = False

    return ensemble_results


def print_ensemble_results(ensemble_results):
    """打印 Ensemble 回测对比"""
    p("\n" + "=" * 100)
    p("  Phase 4: Ensemble 整体回测对比")
    p("=" * 100)
    p(f"{'配置':<16} {'股票数':>6} {'平均收益':>10} {'中位收益':>10} "
      f"{'平均Sharpe':>10} {'中位Sharpe':>10} {'正收益%':>8} {'平均交易':>8}")
    p("-" * 100)

    sorted_results = sorted(ensemble_results.items(),
                            key=lambda x: x[1]['avg_sharpe'], reverse=True)

    for name, r in sorted_results:
        marker = " ★" if name != 'current' and r['avg_sharpe'] > ensemble_results.get('current', {}).get('avg_sharpe', -999) else ""
        p(f"{name:<16} {r['stock_count']:>6} "
          f"{r['avg_return']:>9.2%} {r['median_return']:>9.2%} "
          f"{r['avg_sharpe']:>10.4f} {r['median_sharpe']:>10.4f} "
          f"{r['positive_return_pct']:>7.1%} {r['avg_trades']:>8.1f}{marker}")

    p("=" * 100)

    # 找最优配置
    best = max(sorted_results, key=lambda x: x[1]['avg_sharpe'])
    current = ensemble_results.get('current', {})
    if best[0] != 'current' and current:
        improvement = best[1]['avg_sharpe'] - current['avg_sharpe']
        p(f"\n  最优配置: {best[0]}")
        p(f"  相对 current 的 Sharpe 提升: {improvement:+.4f}")
    elif best[0] == 'current':
        p(f"\n  当前权重已是最优配置")


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="权重校准工具")
    parser.add_argument("--stocks", type=int, default=0, help="股票数量（0=全部）")
    parser.add_argument("--phase", type=int, default=0, help="只运行指定phase（0=全部）")
    parser.add_argument("--no-cache", action="store_true", help="不使用Phase1缓存")
    parser.add_argument("--ensemble-stocks", type=int, default=200,
                        help="Phase4 Ensemble回测股票数（默认200）")
    args = parser.parse_args()

    files = sorted([f for f in os.listdir(BACKTEST_DIR) if f.endswith('.parquet')])
    if args.stocks > 0:
        files = files[:args.stocks]

    p(f"\n{'='*60}")
    p(f"  权重校准工具")
    p(f"  股票数: {len(files)}")
    p(f"{'='*60}")

    # Phase 1
    if args.phase == 0 or args.phase == 1:
        p(f"\n📊 Phase 1: 各策略独立回测 ({len(files)} 只股票)")
        t0 = time.time()
        all_results = run_individual_backtests(files, skip_existing=not args.no_cache)
        p(f"  Phase 1 完成: {len(all_results)} 只有效股票, 耗时 {(time.time()-t0)/60:.1f}min")

        if args.phase == 1:
            summary = summarize_results(all_results)
            print_summary(summary)
            return

    # Phase 2
    if args.phase == 0 or args.phase == 2:
        if args.phase == 2:
            cache_file = os.path.join(RESULT_DIR, "phase1_individual_results.json")
            with open(cache_file, 'r') as f:
                all_results = json.load(f)

        p(f"\n📊 Phase 2: 汇总统计")
        summary = summarize_results(all_results)
        print_summary(summary)

        # 保存汇总
        summary_file = os.path.join(RESULT_DIR, "phase2_summary.json")
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        if args.phase == 2:
            return

    # Phase 3
    if args.phase == 0 or args.phase == 3:
        if args.phase == 3:
            summary_file = os.path.join(RESULT_DIR, "phase2_summary.json")
            with open(summary_file, 'r') as f:
                summary = json.load(f)

        p(f"\n📊 Phase 3: 计算候选权重")
        candidates = compute_candidate_weights(summary)
        print_candidates(candidates)

        # 保存候选权重
        cand_file = os.path.join(RESULT_DIR, "phase3_candidates.json")
        with open(cand_file, 'w') as f:
            json.dump(candidates, f, indent=2, ensure_ascii=False)

        if args.phase == 3:
            return

    # Phase 4
    if args.phase == 0 or args.phase == 4:
        if args.phase == 4:
            cand_file = os.path.join(RESULT_DIR, "phase3_candidates.json")
            with open(cand_file, 'r') as f:
                candidates = json.load(f)

        p(f"\n📊 Phase 4: Ensemble 整体回测验证")
        ensemble_results = run_ensemble_backtests(
            files, candidates, max_stocks=args.ensemble_stocks)
        print_ensemble_results(ensemble_results)

        # 保存最终结果
        final_file = os.path.join(RESULT_DIR, "phase4_ensemble_results.json")
        with open(final_file, 'w') as f:
            json.dump(ensemble_results, f, indent=2, ensure_ascii=False)

        # 保存最优权重
        if ensemble_results:
            best_method = max(ensemble_results.items(), key=lambda x: x[1]['avg_sharpe'])[0]
            best_weights = candidates[best_method]
            best_file = os.path.join(RESULT_DIR, "best_weights.json")
            with open(best_file, 'w') as f:
                json.dump({
                    'method': best_method,
                    'weights': best_weights,
                    'performance': ensemble_results[best_method],
                }, f, indent=2, ensure_ascii=False)
            p(f"\n  最优权重已保存: {best_file}")

    p(f"\n✅ 全部完成")


if __name__ == '__main__':
    main()
