#!/usr/bin/env python3
"""
MACD 短线参数优化器

对 fast / slow / signal 三个参数做网格扫描，
找出5个月短线最优参数组合。

用法:
    python3 tools/optimize_macd.py
    python3 tools/optimize_macd.py --days 110 --top 20
"""

import sys
import os
import json
import time
import argparse
from datetime import datetime, timedelta
from itertools import product

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from src.strategies.macd_cross import MACDStrategy


# ============================================================
# 参数扫描范围（短线优化）
# ============================================================
FAST_RANGE = [5, 6, 7, 8, 9, 10, 12]         # 快线
SLOW_RANGE = [13, 15, 18, 20, 22, 26, 30]     # 慢线
SIGNAL_RANGE = [5, 7, 9]                       # 信号线


def fetch_stock_data(code: str, days: int = 300) -> pd.DataFrame:
    """通过 baostock 获取数据"""
    import baostock as bs

    prefix = 'sh' if code.startswith(('5', '6')) else 'sz'
    bs_code = f'{prefix}.{code}'

    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=int(days * 1.6))).strftime('%Y-%m-%d')

    rs = bs.query_history_k_data_plus(
        bs_code,
        'date,open,high,low,close,volume,amount',
        start_date=start_date,
        end_date=end_date,
        frequency='d',
        adjustflag='2',
    )

    rows = []
    while rs.error_code == '0' and rs.next():
        rows.append(rs.get_row_data())

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume', 'amount'])
    for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['date'] = pd.to_datetime(df['date'])
    df.dropna(subset=['close'], inplace=True)
    return df


def load_stock_pool(pool_file: str, top: int = None) -> list:
    """加载股票池"""
    with open(pool_file, 'r', encoding='utf-8') as f:
        pool = json.load(f)

    stocks = []
    for sec_name, sec_stocks in pool['sectors'].items():
        for s in sec_stocks:
            s['sector'] = sec_name
            stocks.append(s)

    if top and top > 0:
        stocks = stocks[:top]
    return stocks


def run_param_scan(stocks_data: dict, days: int, initial_cash: float = 100000.0):
    """
    对所有参数组合进行扫描

    Args:
        stocks_data: {code: DataFrame} 预加载的股票数据
        days: 回看天数
        initial_cash: 初始资金

    Returns:
        DataFrame: 参数组合 × 平均表现
    """
    combos = list(product(FAST_RANGE, SLOW_RANGE, SIGNAL_RANGE))
    # 过滤无效组合（fast 必须 < slow）
    combos = [(f, s, sig) for f, s, sig in combos if f < s]

    total_combos = len(combos)
    total_stocks = len(stocks_data)
    print(f"\n📌 参数组合数: {total_combos}")
    print(f"📌 有效股票数: {total_stocks}")
    print(f"📌 总回测组数: {total_combos * total_stocks}")
    print()

    results = []

    for ci, (fast, slow, signal) in enumerate(combos, 1):
        strat = MACDStrategy(fast_period=fast, slow_period=slow, signal_period=signal)

        returns = []
        drawdowns = []
        win_rates = []
        sharpes = []
        trade_counts = []
        valid_count = 0

        for code, df in stocks_data.items():
            if len(df) < strat.min_bars:
                continue
            try:
                bt = strat.backtest(df, initial_cash=initial_cash)
                returns.append(bt['total_return'])
                drawdowns.append(bt['max_drawdown'])
                win_rates.append(bt['win_rate'])
                sharpes.append(bt['sharpe'])
                trade_counts.append(bt['trade_count'])
                valid_count += 1
            except Exception:
                pass

        if valid_count == 0:
            continue

        results.append({
            'fast': fast,
            'slow': slow,
            'signal': signal,
            'param_str': f'({fast},{slow},{signal})',
            'avg_return': np.mean(returns),
            'median_return': np.median(returns),
            'std_return': np.std(returns),
            'avg_drawdown': np.mean(drawdowns),
            'max_drawdown_worst': np.max(drawdowns),
            'avg_win_rate': np.mean(win_rates),
            'avg_sharpe': np.mean(sharpes),
            'avg_trades': np.mean(trade_counts),
            'stocks': valid_count,
            # 综合评分 = 夏普 * 0.4 + 收益率/10 * 0.3 + 胜率/100 * 0.2 - 回撤/10 * 0.1
            'score': (np.mean(sharpes) * 0.4
                      + np.mean(returns) / 10 * 0.3
                      + np.mean(win_rates) / 100 * 0.2
                      - np.mean(drawdowns) / 10 * 0.1),
        })

        # 进度
        pct = ci / total_combos * 100
        bar = '█' * int(pct / 2) + '░' * (50 - int(pct / 2))
        print(f"\r  [{bar}] {ci}/{total_combos} ({pct:.0f}%)", end='', flush=True)

    print()
    return pd.DataFrame(results)


def main():
    parser = argparse.ArgumentParser(description='MACD短线参数优化')
    parser.add_argument('--days', type=int, default=110, help='回看天数（默认110≈5个月）')
    parser.add_argument('--pool', type=str, default='stock_pool.json', help='股票池')
    parser.add_argument('--top', type=int, default=0, help='只取前N只（0=全部）')
    parser.add_argument('--cash', type=float, default=100000.0, help='初始资金')
    args = parser.parse_args()

    pool_file = os.path.join(os.path.dirname(__file__), '..', 'data', args.pool)
    stocks = load_stock_pool(pool_file, top=args.top if args.top > 0 else None)

    print(f"=" * 70)
    print(f"🔧 MACD 短线参数优化器")
    print(f"=" * 70)
    print(f"📌 股票池: {len(stocks)} 只")
    print(f"📌 回看天数: {args.days} (≈{args.days/22:.1f}个月)")
    print(f"📌 快线范围: {FAST_RANGE}")
    print(f"📌 慢线范围: {SLOW_RANGE}")
    print(f"📌 信号线范围: {SIGNAL_RANGE}")

    # 预加载数据
    print(f"\n📥 预加载股票数据...")
    import baostock as bs
    bs.login()

    stocks_data = {}
    fail = 0
    for i, stock in enumerate(stocks, 1):
        code = stock['code']
        if i % 20 == 0 or i == len(stocks):
            print(f"\r  加载中... {i}/{len(stocks)}", end='', flush=True)
        df = fetch_stock_data(code, args.days)
        if len(df) >= 30:
            stocks_data[code] = df
        else:
            fail += 1

    bs.logout()
    print(f"\n✅ 加载完成: {len(stocks_data)} 只有效 ({fail} 只跳过)")

    # 参数扫描
    t0 = time.time()
    df_results = run_param_scan(stocks_data, args.days, args.cash)
    elapsed = time.time() - t0
    print(f"\n⏱️ 扫描耗时: {elapsed:.1f}秒")

    if df_results.empty:
        print("❌ 没有有效结果")
        return

    # ============================================================
    # 输出结果
    # ============================================================

    # 1. 按综合评分排名
    df_sorted = df_results.sort_values('score', ascending=False)

    print(f"\n{'='*70}")
    print(f"📊 MACD参数优化结果 (TOP 15)")
    print(f"{'='*70}")
    print(f"{'排名':>4} {'参数':>14} {'平均收益%':>9} {'中位收益%':>9} "
          f"{'平均回撤%':>9} {'胜率%':>7} {'夏普':>6} {'交易次数':>8} {'综合评分':>8}")
    print("-" * 85)

    for rank, (_, row) in enumerate(df_sorted.head(15).iterrows(), 1):
        marker = ' 🏆' if rank == 1 else (' ⭐' if rank <= 3 else '')
        print(f"{rank:>4} {row['param_str']:>14} {row['avg_return']:>+9.2f} "
              f"{row['median_return']:>+9.2f} {row['avg_drawdown']:>9.2f} "
              f"{row['avg_win_rate']:>7.1f} {row['avg_sharpe']:>6.2f} "
              f"{row['avg_trades']:>8.1f} {row['score']:>8.3f}{marker}")

    # 2. 与默认参数对比
    default = df_results[(df_results['fast'] == 12) &
                          (df_results['slow'] == 26) &
                          (df_results['signal'] == 9)]
    best = df_sorted.iloc[0]

    print(f"\n{'='*70}")
    print(f"📈 最优 vs 默认参数对比")
    print(f"{'='*70}")
    print(f"{'':>14} {'最优参数':>14} {'默认(12,26,9)':>14}")
    print("-" * 45)
    if not default.empty:
        d = default.iloc[0]
        print(f"{'参数':>14} {best['param_str']:>14} {'(12,26,9)':>14}")
        print(f"{'平均收益%':>14} {best['avg_return']:>+14.2f} {d['avg_return']:>+14.2f}")
        print(f"{'中位收益%':>14} {best['median_return']:>+14.2f} {d['median_return']:>+14.2f}")
        print(f"{'平均回撤%':>14} {best['avg_drawdown']:>14.2f} {d['avg_drawdown']:>14.2f}")
        print(f"{'胜率%':>14} {best['avg_win_rate']:>14.1f} {d['avg_win_rate']:>14.1f}")
        print(f"{'夏普比率':>14} {best['avg_sharpe']:>14.2f} {d['avg_sharpe']:>14.2f}")
        print(f"{'综合评分':>14} {best['score']:>14.3f} {d['score']:>14.3f}")

        improve = (best['avg_return'] - d['avg_return'])
        print(f"\n🎯 最优参数收益提升: {improve:+.2f}% (相对默认)")
    else:
        print(f"  最优参数: {best['param_str']}")
        print(f"  平均收益: {best['avg_return']:+.2f}%")
        print(f"  综合评分: {best['score']:.3f}")

    # 3. 保存详细结果
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'output')
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, 'macd_param_optimization.csv')
    df_sorted.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"\n📄 详细结果已保存: {csv_path}")

    # 4. 按维度分析
    print(f"\n{'='*70}")
    print(f"🔍 各快线周期的平均表现")
    print(f"{'='*70}")
    fast_agg = df_results.groupby('fast').agg(
        平均收益=('avg_return', 'mean'),
        平均回撤=('avg_drawdown', 'mean'),
        平均夏普=('avg_sharpe', 'mean'),
        平均评分=('score', 'mean'),
    ).round(3)
    print(fast_agg.to_string())

    print(f"\n🔍 各慢线周期的平均表现")
    slow_agg = df_results.groupby('slow').agg(
        平均收益=('avg_return', 'mean'),
        平均回撤=('avg_drawdown', 'mean'),
        平均夏普=('avg_sharpe', 'mean'),
        平均评分=('score', 'mean'),
    ).round(3)
    print(slow_agg.to_string())

    print(f"\n🔍 各信号线周期的平均表现")
    sig_agg = df_results.groupby('signal').agg(
        平均收益=('avg_return', 'mean'),
        平均回撤=('avg_drawdown', 'mean'),
        平均夏普=('avg_sharpe', 'mean'),
        平均评分=('score', 'mean'),
    ).round(3)
    print(sig_agg.to_string())

    print(f"\n✅ 优化完成!")


if __name__ == '__main__':
    main()
