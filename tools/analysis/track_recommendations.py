"""
推荐回测追踪器 — 统计历史每日推荐的 T+5 / T+20 胜率和收益

使用方式:
    python tools/analysis/track_recommendations.py
    python tools/analysis/track_recommendations.py --top 10    # 只统计每天 Top10
    python tools/analysis/track_recommendations.py --since 2026-04-21
"""

import os
import re
import sys
import argparse
from datetime import datetime, timedelta
from collections import defaultdict

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


def parse_report(filepath: str, top_n: int = 20) -> list:
    """从每日推荐报告中解析推荐股票代码和价格"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(filepath))
    if not date_match:
        return []
    report_date = date_match.group(1)

    # 匹配完整推荐列表中的股票行: | 类型 | 排名 | 代码 | 名称 | 价格 | ...
    pattern = r'\|\s*[⭐🟢🔵⚪]\S*\s*\|\s*(\d+)\s*\|\s*(\d{6})\s*\|\s*(\S+)\s*\|\s*([\d.]+)\s*\|'
    matches = re.findall(pattern, content)

    stocks = []
    for rank_str, code, name, price_str in matches:
        rank = int(rank_str)
        if rank > top_n:
            continue
        try:
            price = float(price_str)
        except ValueError:
            continue
        stocks.append({
            'date': report_date,
            'rank': rank,
            'code': code,
            'name': name,
            'rec_price': price,
        })

    return stocks


def load_kline(code: str, cache_dir: str) -> pd.DataFrame:
    """加载本地K线缓存"""
    parquet_path = os.path.join(cache_dir, f'{code}.parquet')
    if os.path.exists(parquet_path):
        try:
            df = pd.read_parquet(parquet_path)
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
            return df
        except Exception:
            pass
    return pd.DataFrame()


def get_future_return(df: pd.DataFrame, rec_date: str, horizon: int) -> float:
    """计算推荐日后 horizon 个交易日的收益率"""
    if df.empty or 'date' not in df.columns or 'close' not in df.columns:
        return None

    rec_dt = pd.Timestamp(rec_date)
    mask = df['date'] >= rec_dt
    future_df = df[mask]

    if len(future_df) < 2:
        return None

    # T+0 收盘价（推荐当天）
    t0_close = float(future_df.iloc[0]['close'])
    if t0_close <= 0:
        return None

    # T+horizon 收盘价
    target_idx = min(horizon, len(future_df) - 1)
    if target_idx < 1:
        return None
    th_close = float(future_df.iloc[target_idx]['close'])

    return (th_close / t0_close - 1) * 100


def main():
    parser = argparse.ArgumentParser(description='推荐回测追踪器')
    parser.add_argument('--top', type=int, default=20, help='统计每天 Top N 推荐')
    parser.add_argument('--since', type=str, default=None, help='起始日期 (YYYY-MM-DD)')
    parser.add_argument('--horizons', type=str, default='5,20', help='回测天数，逗号分隔')
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    reports_dir = os.path.join(base_dir, 'mydate', 'daily_reports')
    kline_dir = os.path.join(base_dir, 'mydate', 'backtest_kline')

    horizons = [int(h.strip()) for h in args.horizons.split(',')]

    # 收集所有历史推荐
    report_files = sorted([
        f for f in os.listdir(reports_dir)
        if f.startswith('daily_recommendation_') and f.endswith('.md')
    ])

    all_recs = []
    for rf in report_files:
        if args.since:
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', rf)
            if date_match and date_match.group(1) < args.since:
                continue
        filepath = os.path.join(reports_dir, rf)
        recs = parse_report(filepath, top_n=args.top)
        all_recs.extend(recs)

    if not all_recs:
        print("未找到历史推荐记录")
        return

    print(f"📊 推荐回测追踪报告")
    print(f"{'='*70}")
    print(f"推荐记录: {len(all_recs)} 只次 ({len(report_files)} 个交易日)")
    print(f"统计范围: Top{args.top} | 回测周期: T+{'/T+'.join(str(h) for h in horizons)}")
    print()

    # 加载K线并计算收益
    kline_cache = {}
    for rec in all_recs:
        code = rec['code']
        if code not in kline_cache:
            kline_cache[code] = load_kline(code, kline_dir)

        for h in horizons:
            ret = get_future_return(kline_cache[code], rec['date'], h)
            rec[f'ret_t{h}'] = ret

    df = pd.DataFrame(all_recs)

    # 总体统计
    for h in horizons:
        col = f'ret_t{h}'
        valid = df[df[col].notna()]
        if len(valid) == 0:
            print(f"T+{h}: 无有效数据")
            continue

        wins = (valid[col] > 0).sum()
        total = len(valid)
        win_rate = wins / total * 100
        avg_ret = valid[col].mean()
        median_ret = valid[col].median()
        max_ret = valid[col].max()
        min_ret = valid[col].min()

        print(f"📈 T+{h} 统计 (有效 {total} 只次):")
        print(f"   胜率: {win_rate:.1f}% ({wins}/{total})")
        print(f"   平均收益: {avg_ret:+.2f}%")
        print(f"   中位数收益: {median_ret:+.2f}%")
        print(f"   最大收益: {max_ret:+.2f}%")
        print(f"   最大亏损: {min_ret:+.2f}%")
        print()

    # 分日统计
    print(f"\n{'='*70}")
    print(f"📅 分日统计")
    print(f"{'='*70}")

    dates = sorted(df['date'].unique())
    header = f"| {'日期':^12} | {'推荐数':^6} |"
    for h in horizons:
        header += f" {'T+'+str(h)+'胜率':^10} | {'T+'+str(h)+'均收益':^12} |"
    print(header)
    print('|' + '-'*14 + '|' + '-'*8 + '|' + ('|'.join(['-'*12 + '|' + '-'*14] * len(horizons))) + '|')

    for d in dates:
        day_df = df[df['date'] == d]
        row = f"| {d:^12} | {len(day_df):^6} |"
        for h in horizons:
            col = f'ret_t{h}'
            valid = day_df[day_df[col].notna()]
            if len(valid) > 0:
                wr = (valid[col] > 0).sum() / len(valid) * 100
                ar = valid[col].mean()
                row += f" {wr:>6.1f}%    | {ar:>+8.2f}%     |"
            else:
                row += f" {'N/A':^10} | {'N/A':^12} |"
        print(row)

    # 分排名统计
    print(f"\n{'='*70}")
    print(f"🏆 分排名统计（排名越靠前是否越准？）")
    print(f"{'='*70}")

    rank_groups = [(1, 5, 'Top1-5'), (6, 10, 'Top6-10'), (11, 20, 'Top11-20')]
    header = f"| {'排名组':^10} | {'只次':^6} |"
    for h in horizons:
        header += f" {'T+'+str(h)+'胜率':^10} | {'T+'+str(h)+'均收益':^12} |"
    print(header)
    print('|' + '-'*12 + '|' + '-'*8 + '|' + ('|'.join(['-'*12 + '|' + '-'*14] * len(horizons))) + '|')

    for lo, hi, label in rank_groups:
        grp = df[(df['rank'] >= lo) & (df['rank'] <= hi)]
        row = f"| {label:^10} | {len(grp):^6} |"
        for h in horizons:
            col = f'ret_t{h}'
            valid = grp[grp[col].notna()]
            if len(valid) > 0:
                wr = (valid[col] > 0).sum() / len(valid) * 100
                ar = valid[col].mean()
                row += f" {wr:>6.1f}%    | {ar:>+8.2f}%     |"
            else:
                row += f" {'N/A':^10} | {'N/A':^12} |"
        print(row)

    # 保存结果
    result_file = os.path.join(base_dir, 'mydate', 'daily_reports', 'tracking_review.md')
    lines = [
        f"# 📊 推荐回测追踪报告",
        f"",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**统计范围**: {dates[0]} ~ {dates[-1]} ({len(dates)}个交易日, {len(all_recs)}只次)",
        f"",
    ]

    for h in horizons:
        col = f'ret_t{h}'
        valid = df[df[col].notna()]
        if len(valid) > 0:
            wins = (valid[col] > 0).sum()
            lines.append(f"## T+{h} 总体")
            lines.append(f"- 胜率: **{wins/len(valid)*100:.1f}%** ({wins}/{len(valid)})")
            lines.append(f"- 平均收益: **{valid[col].mean():+.2f}%**")
            lines.append(f"- 中位数: {valid[col].median():+.2f}%")
            lines.append(f"- 最大: {valid[col].max():+.2f}% | 最小: {valid[col].min():+.2f}%")
            lines.append("")

    with open(result_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"\n✅ 报告已保存到: {result_file}")


if __name__ == '__main__':
    main()
