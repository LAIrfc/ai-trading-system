#!/usr/bin/env python3
"""
板块专项分析：对指定板块/个股列表运行 14 策略评分，输出 TOP-N 推荐。

用法:
    python3 tools/analysis/sector_analyze.py --codes 300442,688158,300383 --names 润泽科技,优刻得,光环新网
    python3 tools/analysis/sector_analyze.py --sector 创业板_AI算力 --top 5
"""

import sys
import os
import json
import argparse
import warnings

warnings.filterwarnings('ignore')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

import pandas as pd
import numpy as np


def _load_stock_pool(pool_path: str) -> dict:
    with open(pool_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _get_sector_stocks(pool: dict, sector_name: str) -> list:
    for sec, stocks in pool.items():
        if sector_name in sec:
            return [(s['code'], s['name']) for s in stocks]
    return []


def main():
    parser = argparse.ArgumentParser(description='板块专项分析')
    parser.add_argument('--codes', type=str, default='',
                        help='逗号分隔的股票代码列表')
    parser.add_argument('--names', type=str, default='',
                        help='逗号分隔的股票名称列表（与codes一一对应）')
    parser.add_argument('--sector', type=str, default='',
                        help='从stock_pool_all.json中的板块名称')
    parser.add_argument('--pool', type=str, default='mydate/stock_pool_all.json')
    parser.add_argument('--top', type=int, default=5)
    parser.add_argument('--cache-only', action='store_true',
                        help='仅使用缓存数据')
    args = parser.parse_args()

    pool_path = os.path.join(PROJECT_ROOT, args.pool)

    target_stocks = []

    if args.codes:
        codes = [c.strip() for c in args.codes.split(',')]
        names = [n.strip() for n in args.names.split(',')] if args.names else [''] * len(codes)
        for c, n in zip(codes, names):
            target_stocks.append((c, n))
    elif args.sector:
        pool = _load_stock_pool(pool_path)
        target_stocks = _get_sector_stocks(pool, args.sector)
        if not target_stocks:
            print(f"未找到板块: {args.sector}")
            return

    if not target_stocks:
        print("请指定 --codes 或 --sector")
        return

    print("=" * 70)
    print(f"板块专项分析 | 标的数: {len(target_stocks)} | TOP-{args.top}")
    print("=" * 70)

    from tools.analysis.recommend_today import (
        update_kline_cache, _sanitize_ohlcv,
        run_full_12_analysis,
    )
    from src.data.fetchers.fundamental_fetcher import FundamentalFetcher

    cache_dir = os.path.join(PROJECT_ROOT, 'mydate', 'backtest_kline')
    fetcher = FundamentalFetcher()

    print("\n📥 获取行情数据...")
    prepared = []
    for code, name in target_stocks:
        try:
            if args.cache_only:
                cache_file = os.path.join(cache_dir, f'{code}.parquet')
                if os.path.exists(cache_file):
                    df = pd.read_parquet(cache_file)
                    df = _sanitize_ohlcv(df)
                else:
                    print(f"  ⚠️ {code} {name} 无缓存，跳过")
                    continue
            else:
                df = update_kline_cache(code, cache_dir, days=200)
                if df is None:
                    df = pd.DataFrame()
                df = _sanitize_ohlcv(df)
        except Exception as e:
            print(f"  ⚠️ {code} {name} 获取失败: {e}")
            continue

        if len(df) >= 60:
            prepared.append((code, name, df))
            print(f"  ✅ {code} {name} ({len(df)} 根K线)")
        else:
            print(f"  ⚠️ {code} {name} 数据不足 ({len(df)} bars)")

    if not prepared:
        print("\n❌ 无有效数据")
        return

    print(f"\n📊 运行14策略分析 ({len(prepared)} 只)...")

    sector_codes = set(c for c, _, _ in prepared)

    results = []
    for i, (code, name, df) in enumerate(prepared):
        try:
            r = run_full_12_analysis(
                code, name, '算力', df, fetcher,
                skip_industry=False,
                sector_codes=sector_codes,
            )
            if r:
                r['code'] = code
                r['name'] = name
                results.append(r)
                score = r.get('score', 0)
                action = 'BUY' if score > 2 else ('SELL' if score < -2 else 'HOLD')
                print(f"  [{i+1}/{len(prepared)}] {code} {name}: score={score:+.2f} {action}")
        except Exception as e:
            print(f"  ⚠️ {code} {name} 分析失败: {e}")

    results.sort(key=lambda x: x.get('score', 0), reverse=True)

    print("\n" + "=" * 70)
    print(f"📈 算力板块 TOP-{args.top} 推荐")
    print("=" * 70)
    print(f"{'排名':<4} {'代码':<8} {'名称':<10} {'综合分':<8} {'趋势':<10} {'5日涨跌':<8} {'20日涨跌':<9} {'信号'}")
    print("-" * 90)

    top_n = results[:args.top]
    for rank, r in enumerate(top_n, 1):
        code = r.get('code', '')
        name = r.get('name', '')
        score = r.get('score', 0)
        trend = r.get('trend', '-')
        chg5 = r.get('change_5d', 0)
        chg20 = r.get('change_20d', 0)
        signals = r.get('signals', [])

        buy_strats = [s[0] for s in signals if s[1] == 'BUY']
        sell_strats = [s[0] for s in signals if s[1] == 'SELL']

        sig_str = f"↑{','.join(buy_strats[:4])}" if buy_strats else ""
        if sell_strats:
            sig_str += f" ↓{','.join(sell_strats[:3])}"

        print(f" {rank:<3} {code:<8} {name:<10} {score:>+6.2f}  {trend:<10} {chg5:>+6.1f}%  {chg20:>+7.1f}%  {sig_str}")

    print("\n" + "-" * 90)
    print("详细信号:")
    for rank, r in enumerate(top_n, 1):
        code = r.get('code', '')
        name = r.get('name', '')
        score = r.get('score', 0)
        signals = r.get('signals', [])
        fund_score = r.get('fundamental_score', 0)
        tech_score = r.get('technical_score', 0)

        print(f"\n  [{rank}] {code} {name} (综合: {score:+.2f}, 基本面: {fund_score:+.4f}, 技术面: {tech_score:+.4f})")
        for s_name, s_action, s_conf, s_reason in signals:
            emoji = '🟢' if s_action == 'BUY' else ('🔴' if s_action == 'SELL' else '⚪')
            print(f"      {emoji} {s_name:<16} {s_action:<6} conf={s_conf:.2f}  {s_reason}")

    if len(results) > args.top:
        print(f"\n  (剩余 {len(results) - args.top} 只未列出，可增大 --top 查看)")

    # ====== 十倍股模型 ======
    print(f"\n{'='*70}")
    print("🏔️ 长周期十倍股模型 (3-5年) — 7条铁律")
    print(f"{'='*70}\n")
    try:
        from src.strategies.tenbagger_model import batch_evaluate_tenbagger
        tb_results = batch_evaluate_tenbagger(results, top_n=len(results))
        print(f"{'排名':<4} {'代码':<8} {'名称':<10} {'总分':<6} {'评级':<4} {'赛道':<5} {'市值':<5} {'壁垒':<5} {'拐点':<5} {'替代':<5} {'催化':<5} {'估值':<5} {'赛道匹配'}")
        print("-" * 95)
        for i, tr in enumerate(tb_results, 1):
            tracks_str = '/'.join(tr.matched_tracks[:2]) if tr.matched_tracks else '-'
            print(f" {i:<3} {tr.code:<8} {tr.name:<10} {tr.tenbagger_score:>4.0f}  {tr.tenbagger_grade:<4} "
                  f"{tr.score_track:>4.0f} {tr.score_mcap:>4.0f} {tr.score_moat:>4.0f} "
                  f"{tr.score_earning:>4.0f} {tr.score_replace:>4.0f} {tr.score_catalyst:>4.0f} "
                  f"{tr.score_value:>4.0f}  {tracks_str}")
        print()
        for i, tr in enumerate(tb_results, 1):
            print(f"  [{i}] {tr.name}({tr.code}) — {tr.tenbagger_score:.0f}/700 ({tr.tenbagger_grade}级)")
            if hasattr(tr, 'risk_flags') and tr.risk_flags:
                print(f"      ⚠️ 风险: {', '.join(tr.risk_flags)}")
            if hasattr(tr, 'detail_reasons') and tr.detail_reasons:
                for reason in tr.detail_reasons[:5]:
                    print(f"      • {reason}")
    except Exception as e:
        print(f"  ❌ 十倍股模型异常: {e}")
        import traceback; traceback.print_exc()

    # ====== 翻倍股模型 ======
    print(f"\n{'='*70}")
    print("🚀 短周期翻倍股模型 (3-6个月)")
    print(f"{'='*70}\n")
    try:
        from src.strategies.doubler_model import batch_evaluate_doubler
        db_results = batch_evaluate_doubler(results, top_n=len(results))
        print(f"{'排名':<4} {'代码':<8} {'名称':<10} {'评分':<6} {'评级':<4} {'热度':<6} {'资金':<6} {'催化':<6} {'预期差':<6} {'筹码':<6} {'赛道'}")
        print("-" * 90)
        for i, dr in enumerate(db_results, 1):
            hot = getattr(dr, 'hot_sector', '') or ''
            print(f" {i:<3} {dr.code:<8} {dr.name:<10} {dr.doubler_score:>4.0f}  {dr.doubler_grade:<4} "
                  f"{dr.sector_heat:>5.0%} {dr.capital_intensity:>5.0%} "
                  f"{dr.catalyst_density:>5.0%} {dr.expectation_diff:>5.0%} "
                  f"{dr.chip_concentration:>5.0%}  {hot}")
        print()
        for i, dr in enumerate(db_results, 1):
            desc = getattr(dr, 'catalyst_desc', '') or ''
            print(f"  [{i}] {dr.name}({dr.code}) — {dr.doubler_score:.0f}/100 ({dr.doubler_grade}级)")
            if desc:
                print(f"      催化: {desc}")
            if hasattr(dr, 'risk_flags') and dr.risk_flags:
                print(f"      ⚠️ 风险: {', '.join(dr.risk_flags)}")
    except Exception as e:
        print(f"  ❌ 翻倍股模型异常: {e}")
        import traceback; traceback.print_exc()

    # ====== 黄金交叉 ======
    try:
        from src.strategies.tenbagger_model import find_golden_cross_enhanced
        if tb_results and db_results:
            golden = find_golden_cross_enhanced(tb_results, db_results)
            if golden and golden.strip():
                print(f"\n{'='*70}")
                print("🏆 黄金交叉（十倍逻辑 + 短期资金启动）")
                print(f"{'='*70}")
                print(golden)
    except Exception as e:
        pass

    print()


if __name__ == '__main__':
    main()
