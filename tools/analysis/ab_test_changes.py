"""
A/B 回测验证：对比策略改动前后的表现差异。

测试项：
1. 相关性折扣（NEWS+MONEY_FLOW 同方向时折扣 vs 不折扣）
2. L2 波动率自适应权重 vs 固定权重
3. 综合改动 vs 原始

方法：在 30 只代表性股票上跑 EnsembleStrategy.backtest()，
比较 Sharpe、年化收益、最大回撤。
"""

import sys
import os
import json
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
from pathlib import Path


def load_sample_stocks(cache_dir: str, n: int = 30) -> list:
    """从缓存中加载 n 只有足够历史数据的股票。"""
    cache_path = Path(cache_dir)
    if not cache_path.exists():
        return []
    parquets = sorted(cache_path.glob('*.parquet'))
    result = []
    for p in parquets:
        if len(result) >= n:
            break
        try:
            df = pd.read_parquet(p)
            if len(df) >= 200:
                code = p.stem
                result.append((code, df))
        except Exception:
            continue
    return result


def run_single_backtest(strategy, df: pd.DataFrame) -> dict:
    """对单只股票跑回测，返回指标。"""
    try:
        return strategy.backtest(df)
    except Exception as e:
        return {
            'total_return': 0.0, 'annualized_return': 0.0,
            'max_drawdown': 0.0, 'sharpe': 0.0, 'win_rate': 0.0,
            'trade_count': 0,
        }


def aggregate_metrics(results: list) -> dict:
    """聚合多只股票的回测结果。"""
    if not results:
        return {}
    sharpes = [r['sharpe'] for r in results if r.get('trade_count', 0) > 0]
    returns = [r['annualized_return'] for r in results if r.get('trade_count', 0) > 0]
    drawdowns = [r['max_drawdown'] for r in results if r.get('trade_count', 0) > 0]
    win_rates = [r['win_rate'] for r in results if r.get('trade_count', 0) > 0]
    
    n = len(sharpes)
    if n == 0:
        return {'n': 0}
    return {
        'n': n,
        'avg_sharpe': round(np.mean(sharpes), 4),
        'med_sharpe': round(np.median(sharpes), 4),
        'avg_ann_ret': round(np.mean(returns), 4),
        'avg_max_dd': round(np.mean(drawdowns), 4),
        'avg_win_rate': round(np.mean(win_rates), 2),
    }


def main():
    cache_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'mydate', 'backtest_kline')
    print("=" * 70)
    print("A/B 回测验证：策略改动前后对比")
    print("=" * 70)

    print("\n📂 加载样本股票...")
    stocks = load_sample_stocks(cache_dir, n=30)
    if len(stocks) < 10:
        print(f"❌ 仅加载到 {len(stocks)} 只股票，数据不足，请先运行 backtest_prefetch.py")
        return
    print(f"✅ 加载 {len(stocks)} 只股票用于回测")

    from src.strategies.base import _BACKTEST_ACTIVE
    import src.strategies.base as base_mod
    base_mod._BACKTEST_ACTIVE = True

    # ── 测试 A: 原始固定权重（无相关性折扣，无L2） ──
    print("\n" + "─" * 50)
    print("🔵 配置A: 原始固定权重（无相关性折扣，无L2波动率自适应）")
    print("─" * 50)

    from src.strategies.ensemble import EnsembleStrategy

    results_a = []
    for i, (code, df) in enumerate(stocks):
        strat_a = EnsembleStrategy(symbol=code, dual_reverse=True)
        strat_a._CORRELATED_PAIRS = {}
        
        old_method = strat_a._compute_volatility_adjusted_weights
        strat_a._compute_volatility_adjusted_weights = lambda df: None
        
        r = run_single_backtest(strat_a, df)
        results_a.append(r)
        if (i + 1) % 10 == 0:
            print(f"  进度: {i+1}/{len(stocks)}")

    agg_a = aggregate_metrics(results_a)
    print(f"  结果: {agg_a}")

    # ── 测试 B: 新版（含相关性折扣 + L2 波动率自适应） ──
    print("\n" + "─" * 50)
    print("🟢 配置B: 新版（含相关性折扣 + L2波动率自适应）")
    print("─" * 50)

    results_b = []
    for i, (code, df) in enumerate(stocks):
        strat_b = EnsembleStrategy(symbol=code, dual_reverse=True)
        r = run_single_backtest(strat_b, df)
        results_b.append(r)
        if (i + 1) % 10 == 0:
            print(f"  进度: {i+1}/{len(stocks)}")

    agg_b = aggregate_metrics(results_b)
    print(f"  结果: {agg_b}")

    # ── 对比 ──
    print("\n" + "=" * 70)
    print("📊 A/B 对比结果")
    print("=" * 70)
    print(f"{'指标':<20} {'A(原始)':<15} {'B(新版)':<15} {'差值':<15} {'结论':<10}")
    print("-" * 70)

    if agg_a.get('n', 0) > 0 and agg_b.get('n', 0) > 0:
        for metric, label in [
            ('avg_sharpe', 'Sharpe'),
            ('avg_ann_ret', '年化收益%'),
            ('avg_max_dd', '最大回撤%'),
            ('avg_win_rate', '胜率%'),
        ]:
            va = agg_a.get(metric, 0)
            vb = agg_b.get(metric, 0)
            diff = vb - va
            if metric == 'avg_max_dd':
                better = "✅改善" if diff > 0 else ("⚠️恶化" if diff < 0 else "持平")
            else:
                better = "✅改善" if diff > 0 else ("⚠️恶化" if diff < 0 else "持平")
            print(f"{label:<20} {va:<15.4f} {vb:<15.4f} {diff:<+15.4f} {better}")

        sharpe_a = agg_a.get('avg_sharpe', 0)
        sharpe_b = agg_b.get('avg_sharpe', 0)
        if sharpe_b > sharpe_a:
            pct_improve = (sharpe_b - sharpe_a) / (abs(sharpe_a) + 1e-8) * 100
            print(f"\n✅ 结论: Sharpe 提升 {pct_improve:.1f}%，改动为正向优化")
        elif sharpe_b == sharpe_a:
            print(f"\n⚪ 结论: Sharpe 不变，改动无正面/负面影响")
        else:
            print(f"\n⚠️ 结论: Sharpe 下降，需要回滚或调整参数")
    else:
        print("数据不足，无法对比")

    base_mod._BACKTEST_ACTIVE = False
    print("\n回测完成。")


if __name__ == '__main__':
    main()
