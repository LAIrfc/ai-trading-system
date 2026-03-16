#!/usr/bin/env python3
"""
策略交叉验证工具

功能:
1. 加载100只股票池
2. 获取每只股票的历史数据（baostock）
3. 用所有策略对每只股票进行回测
4. 输出对比报告（终端 + Markdown + CSV）

用法:
    python3 tools/cross_validate.py                # 运行全部
    python3 tools/cross_validate.py --top 20       # 只取前20只
    python3 tools/cross_validate.py --sector 光伏   # 只跑某板块
    python3 tools/cross_validate.py --days 250     # 回看250天
"""

import sys
import os
import json
import time
import argparse
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

# 确保 src 在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from src.strategies import STRATEGY_REGISTRY, get_all_strategies


# ============================================================
# 数据获取
# ============================================================

def fetch_data(code: str, days: int = 300, source: str = 'unified') -> pd.DataFrame:
    """统一数据获取入口（通过 UnifiedDataProvider 多源自动降级）"""
    from src.data.provider.data_provider import get_default_kline_provider

    provider = get_default_kline_provider()
    df = provider.get_kline(
        symbol=code,
        datalen=days,
        min_bars=30,
        retries=2,
        timeout=10,
    )
    return df if df is not None and not df.empty else pd.DataFrame()


# ============================================================
# 加载股票池
# ============================================================

def load_stock_pool(pool_file: str, sector: str = None, top: int = None) -> list:
    """加载股票池（兼容多种格式）"""
    try:
        from src.utils.pool_loader import load_pool
        return load_pool(pool_file, max_count=top or 0, sector=sector, include_etf=False)
    except ImportError:
        pass

    with open(pool_file, 'r', encoding='utf-8') as f:
        pool = json.load(f)

    stocks = []
    sectors = pool.get('stocks', pool.get('sectors', {}))
    for sec_name, sec_stocks in sectors.items():
        if sector and sector not in sec_name:
            continue
        for s in sec_stocks:
            s['sector'] = sec_name
            stocks.append(s)

    if top and top > 0:
        stocks = stocks[:top]

    return stocks


# ============================================================
# 交叉验证核心
# ============================================================

def run_cross_validation(stocks: list, days: int = 300,
                         source: str = 'baostock',
                         initial_cash: float = 100000.0) -> pd.DataFrame:
    """
    运行交叉验证

    对每只股票 × 每个策略 运行回测，收集结果

    Returns:
        DataFrame: 每行一个 (股票, 策略) 组合
    """
    strategies = get_all_strategies()
    results = []
    total = len(stocks)

    for idx, stock in enumerate(stocks, 1):
        code = stock['code']
        name = stock['name']
        sector = stock.get('sector', '')

        verbose = total <= 50
        if verbose:
            print(f"\r[{idx:3d}/{total}] 获取 {code} {name:8s} ...", end='', flush=True)
        elif idx == 1 or idx % 50 == 0 or idx == total:
            pct = idx / total * 100
            bar = '█' * int(pct / 2) + '░' * (50 - int(pct / 2))
            print(f"\r  [{bar}] {idx}/{total} ({pct:.0f}%)", end='', flush=True)

        df = fetch_data(code, days=days, source=source)

        if len(df) < 30:
            fail_count = getattr(run_cross_validation, '_fail', 0) + 1
            run_cross_validation._fail = fail_count
            if verbose:
                print(f" ❌ 数据不足({len(df)}条)")
            continue

        if verbose:
            print(f" ✅ {len(df):3d}条 ", end='')

        for strat_name, strat in strategies.items():
            if len(df) < strat.min_bars:
                results.append({
                    'code': code, 'name': name, 'sector': sector,
                    'strategy': strat_name, 'bars': len(df),
                    'final_value': initial_cash, 'total_return': 0.0,
                    'annualized_return': 0.0, 'max_drawdown': 0.0,
                    'win_rate': 0.0, 'trade_count': 0, 'sharpe': 0.0,
                    'status': '数据不足',
                })
                continue

            try:
                bt = strat.backtest(df, initial_cash=initial_cash)
                results.append({
                    'code': code, 'name': name, 'sector': sector,
                    'strategy': strat_name, 'bars': len(df),
                    'final_value': bt['final_value'],
                    'total_return': bt['total_return'],
                    'annualized_return': bt['annualized_return'],
                    'max_drawdown': bt['max_drawdown'],
                    'win_rate': bt['win_rate'],
                    'trade_count': bt['trade_count'],
                    'sharpe': bt['sharpe'],
                    'status': 'OK',
                })
            except Exception as e:
                results.append({
                    'code': code, 'name': name, 'sector': sector,
                    'strategy': strat_name, 'bars': len(df),
                    'final_value': initial_cash, 'total_return': 0.0,
                    'annualized_return': 0.0, 'max_drawdown': 0.0,
                    'win_rate': 0.0, 'trade_count': 0, 'sharpe': 0.0,
                    'status': f'错误: {e}',
                })

        if verbose:
            print(f"| {len(strategies)}策略完成")

        time.sleep(0.05)

    fail_count = getattr(run_cross_validation, '_fail', 0)
    if fail_count:
        print(f"\n⚠️  {fail_count} 只股票数据不足，已跳过")
    run_cross_validation._fail = 0

    return pd.DataFrame(results)


# ============================================================
# 报告生成
# ============================================================

def generate_report(df: pd.DataFrame, output_dir: str):
    """生成交叉验证报告"""

    os.makedirs(output_dir, exist_ok=True)

    # 1. 保存原始数据
    csv_path = os.path.join(output_dir, 'cross_validation_results.csv')
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"\n📄 原始数据已保存: {csv_path}")

    # 2. 按策略汇总
    ok_df = df[df['status'] == 'OK'].copy()

    if len(ok_df) == 0:
        print("⚠️ 没有有效的回测结果")
        return

    strategy_summary = ok_df.groupby('strategy').agg({
        'total_return': ['mean', 'median', 'std', 'min', 'max'],
        'annualized_return': ['mean', 'median'],
        'max_drawdown': ['mean', 'max'],
        'win_rate': ['mean', 'median'],
        'trade_count': ['mean', 'sum'],
        'sharpe': ['mean', 'median'],
        'code': 'count',
    }).round(2)

    print("\n" + "=" * 80)
    print("📊 策略交叉验证报告")
    print("=" * 80)

    # 3. 各策略表现排名
    strat_rank = ok_df.groupby('strategy').agg(
        平均收益率=('total_return', 'mean'),
        中位收益率=('total_return', 'median'),
        平均年化=('annualized_return', 'mean'),
        平均回撤=('max_drawdown', 'mean'),
        平均胜率=('win_rate', 'mean'),
        平均夏普=('sharpe', 'mean'),
        股票数=('code', 'count'),
        平均交易次数=('trade_count', 'mean'),
    ).round(2)

    strat_rank = strat_rank.sort_values('平均收益率', ascending=False)
    print("\n【策略综合排名】（按平均收益率排序）")
    print(strat_rank.to_string())

    # 4. 按板块 × 策略
    sector_strat = ok_df.groupby(['sector', 'strategy']).agg(
        平均收益=('total_return', 'mean'),
        股票数=('code', 'count'),
    ).round(2)

    print("\n【板块 × 策略 平均收益率%】")
    pivot = ok_df.pivot_table(
        values='total_return', index='sector', columns='strategy',
        aggfunc='mean'
    ).round(2)
    print(pivot.to_string())

    # 5. 各策略最佳/最差股票
    print("\n【各策略最佳股票 TOP3】")
    for strat in ok_df['strategy'].unique():
        sub = ok_df[ok_df['strategy'] == strat].nlargest(3, 'total_return')
        top3 = ', '.join([
            f"{r['name']}({r['code']}) {r['total_return']:+.1f}%"
            for _, r in sub.iterrows()
        ])
        print(f"  {strat:6s}: {top3}")

    print("\n【各策略最差股票 BOTTOM3】")
    for strat in ok_df['strategy'].unique():
        sub = ok_df[ok_df['strategy'] == strat].nsmallest(3, 'total_return')
        bot3 = ', '.join([
            f"{r['name']}({r['code']}) {r['total_return']:+.1f}%"
            for _, r in sub.iterrows()
        ])
        print(f"  {strat:6s}: {bot3}")

    # 6. 生成 Markdown 报告
    md_path = os.path.join(output_dir, 'CROSS_VALIDATION_REPORT.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(f"# 策略交叉验证报告\n\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"- 股票池: {len(ok_df['code'].unique())} 只股票\n")
        f.write(f"- 策略数: {len(ok_df['strategy'].unique())} 个\n")
        f.write(f"- 回测组合: {len(ok_df)} 个\n\n")

        # 策略排名表
        f.write("## 一、策略综合排名\n\n")
        f.write("| 排名 | 策略 | 平均收益% | 中位收益% | 平均年化% | 平均回撤% | 平均胜率% | 平均夏普 | 股票数 |\n")
        f.write("|------|------|----------|----------|----------|----------|----------|---------|--------|\n")
        for rank, (strat, row) in enumerate(strat_rank.iterrows(), 1):
            f.write(f"| {rank} | {strat} | {row['平均收益率']:+.2f} | {row['中位收益率']:+.2f} | "
                    f"{row['平均年化']:+.2f} | {row['平均回撤']:.2f} | {row['平均胜率']:.1f} | "
                    f"{row['平均夏普']:.2f} | {int(row['股票数'])} |\n")

        # 板块×策略矩阵
        f.write("\n## 二、板块 × 策略 平均收益率矩阵\n\n")
        f.write(f"| 板块 | {' | '.join(pivot.columns)} |\n")
        f.write(f"|{'------|' * (len(pivot.columns) + 1)}\n")
        for sector, row in pivot.iterrows():
            vals = ' | '.join([f"{v:+.2f}" if not pd.isna(v) else '-' for v in row])
            f.write(f"| {sector} | {vals} |\n")

        # 各策略最佳股票
        f.write("\n## 三、各策略最佳股票 TOP5\n\n")
        for strat in strat_rank.index:
            f.write(f"### {strat}\n\n")
            f.write("| 排名 | 股票 | 代码 | 板块 | 收益率% | 年化% | 回撤% | 胜率% | 交易次数 |\n")
            f.write("|------|------|------|------|--------|-------|-------|-------|----------|\n")
            sub = ok_df[ok_df['strategy'] == strat].nlargest(5, 'total_return')
            for i, (_, r) in enumerate(sub.iterrows(), 1):
                f.write(f"| {i} | {r['name']} | {r['code']} | {r['sector']} | "
                        f"{r['total_return']:+.2f} | {r['annualized_return']:+.2f} | "
                        f"{r['max_drawdown']:.2f} | {r['win_rate']:.1f} | {r['trade_count']} |\n")
            f.write("\n")

        # 各策略最差股票
        f.write("\n## 四、各策略最差股票 BOTTOM5\n\n")
        for strat in strat_rank.index:
            f.write(f"### {strat}\n\n")
            f.write("| 排名 | 股票 | 代码 | 板块 | 收益率% | 年化% | 回撤% | 胜率% | 交易次数 |\n")
            f.write("|------|------|------|------|--------|-------|-------|-------|----------|\n")
            sub = ok_df[ok_df['strategy'] == strat].nsmallest(5, 'total_return')
            for i, (_, r) in enumerate(sub.iterrows(), 1):
                f.write(f"| {i} | {r['name']} | {r['code']} | {r['sector']} | "
                        f"{r['total_return']:+.2f} | {r['annualized_return']:+.2f} | "
                        f"{r['max_drawdown']:.2f} | {r['win_rate']:.1f} | {r['trade_count']} |\n")
            f.write("\n")

        # 总结
        f.write("\n## 五、结论\n\n")
        best_strat = strat_rank.index[0]
        best_ret = strat_rank.iloc[0]['平均收益率']
        f.write(f"- **最佳策略**: {best_strat}（平均收益率 {best_ret:+.2f}%）\n")

        # 最佳板块
        sector_avg = ok_df.groupby('sector')['total_return'].mean().sort_values(ascending=False)
        f.write(f"- **最佳板块**: {sector_avg.index[0]}（平均收益率 {sector_avg.iloc[0]:+.2f}%）\n")

        # 最稳健策略（回撤最小）
        most_stable = strat_rank.sort_values('平均回撤').index[0]
        f.write(f"- **最稳健策略**: {most_stable}（平均回撤 {strat_rank.loc[most_stable, '平均回撤']:.2f}%）\n")

    print(f"\n📝 Markdown报告已保存: {md_path}")


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='策略交叉验证工具')
    parser.add_argument('--top', type=int, default=0, help='只取前N只股票（默认全部）')
    parser.add_argument('--sector', type=str, default=None, help='只跑某板块（如 光伏）')
    parser.add_argument('--days', type=int, default=300, help='回看天数（默认300）')
    parser.add_argument('--source', type=str, default='unified',
                        choices=['unified', 'baostock', 'eastmoney'], help='数据源（默认使用统一接口）')
    parser.add_argument('--cash', type=float, default=100000.0, help='初始资金')
    parser.add_argument('--pool', type=str, default='stock_pool.json',
                        help='股票池文件名（默认 stock_pool.json）')
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pool_file = os.path.join(base_dir, 'mydate', args.pool)
    if not os.path.exists(pool_file):
        pool_file = os.path.join(base_dir, 'data', args.pool)

    if not os.path.exists(pool_file):
        print(f"❌ 找不到股票池文件: {pool_file}")
        sys.exit(1)

    stocks = load_stock_pool(pool_file, sector=args.sector,
                             top=args.top if args.top > 0 else None)
    print(f"📌 股票池: {len(stocks)} 只")
    print(f"📌 策略数: {len(STRATEGY_REGISTRY)} 个: {', '.join(STRATEGY_REGISTRY.keys())}")
    print(f"📌 数据源: {args.source}")
    print(f"📌 回看天数: {args.days}")
    print(f"📌 初始资金: ¥{args.cash:,.0f}")
    print(f"\n{'='*60}")
    print(f"开始交叉验证 ({len(stocks)}只 × {len(STRATEGY_REGISTRY)}策略 = {len(stocks) * len(STRATEGY_REGISTRY)}组)")
    print(f"{'='*60}\n")

    start_time = time.time()
    results_df = run_cross_validation(
        stocks, days=args.days, source=args.source,
        initial_cash=args.cash,
    )
    elapsed = time.time() - start_time
    print(f"\n⏱️ 耗时: {elapsed:.1f}秒")

    output_dir = os.path.join(os.path.dirname(__file__), '..', 'output')
    generate_report(results_df, output_dir)

    print(f"\n✅ 交叉验证完毕!")


if __name__ == '__main__':
    main()
