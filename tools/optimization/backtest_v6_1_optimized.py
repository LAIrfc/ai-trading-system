#!/usr/bin/env python3
"""
v6.1优化权重完整回测验证

对比v5.2 vs v6.1（优化权重）的性能差异
使用真实因子计算，完整3.3年数据
"""

import sys
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from src.factors.orthogonalization import FactorOrthogonalizer
from src.factors.normalization import RankNormalizer
from src.strategies.market_regime_v6 import SoftRegimeDetector
from src.portfolio.risk_scaling import VolatilityScaler
from src.strategies.trend_strategies import Trend_Composite, Momentum_Adj, TechnicalConfirmation, VolumeConfirmation, RelativeStrength


def load_cached_kline(code, cache_dir):
    """加载缓存的K线数据"""
    cache_file = os.path.join(cache_dir, f'{code}.parquet')
    if os.path.exists(cache_file):
        try:
            return pd.read_parquet(cache_file)
        except Exception:
            pass
    return pd.DataFrame()


def calc_factors_full(df, index_df=None):
    """
    计算4个因子（完整版）
    
    Returns:
        dict: {
            'base_trend': float,
            'tech_confirm': float,
            'relative_strength': float,
            'volume_confirm': float
        }
    """
    if len(df) < 60:
        return None
    
    try:
        # 1. Base Trend = 0.7 * trend_score + 0.3 * momentum_score
        trend_strat = Trend_Composite()
        trend_df = trend_strat.generate_signals(df)
        trend_score = float(trend_df['trend_score'].iloc[-1]) if len(trend_df) > 0 else 0.0
        
        mom_strat = Momentum_Adj()
        mom_df = mom_strat.generate_signals(df)
        momentum_score = float(mom_df['score'].iloc[-1]) if len(mom_df) > 0 else 0.0
        
        base_trend = 0.7 * trend_score + 0.3 * momentum_score
        
        # 2. Tech Confirm
        tech_strat = TechnicalConfirmation()
        tech_df = tech_strat.generate_signals(df)
        tech_confirm = float(tech_df['tech_confirm_score'].iloc[-1]) if len(tech_df) > 0 else 0.0
        
        # 3. Relative Strength
        rs_strat = RelativeStrength()
        rs_df = rs_strat.generate_signals(df, index_df=index_df, sector_df=None)
        relative_strength = float(rs_df['relative_strength_score'].iloc[-1]) if len(rs_df) > 0 else 0.0
        
        # 4. Volume Confirm
        vol_strat = VolumeConfirmation()
        vol_df = vol_strat.generate_signals(df)
        volume_confirm = float(vol_df['volume_confirm_score'].iloc[-1]) if len(vol_df) > 0 else 0.0
        
        return {
            'base_trend': base_trend,
            'tech_confirm': tech_confirm,
            'relative_strength': relative_strength,
            'volume_confirm': volume_confirm
        }
    except Exception:
        return None


def backtest_cross_section(stocks_data, window_idx, index_df, weights_v5_2, weights_v6_1, top_n=10):
    """
    单个时间窗口的横截面回测
    
    Args:
        stocks_data: dict {code: df}
        window_idx: 窗口索引
        index_df: 指数数据
        weights_v5_2: v5.2权重 [base, tech, rs, vol]
        weights_v6_1: v6.1权重 [base, tech, rs, vol]
        top_n: 选股数量
    
    Returns:
        dict: 回测结果
    """
    # 计算所有股票的因子
    factor_list = []
    for code, df in stocks_data.items():
        if len(df) <= window_idx + 5:
            continue
        
        df_slice = df.iloc[:window_idx+1]
        index_slice = index_df.iloc[:window_idx+1] if index_df is not None else None
        
        factors = calc_factors_full(df_slice, index_slice)
        
        if factors:
            factors['code'] = code
            factor_list.append(factors)
    
    if len(factor_list) < top_n * 2:
        return None
    
    factor_df = pd.DataFrame(factor_list).set_index('code')
    
    # ========== v5.2: 固定权重，无正交化 ==========
    scores_v5_2 = {}
    for code in factor_df.index:
        score = (weights_v5_2[0] * factor_df.loc[code, 'base_trend'] +
                 weights_v5_2[1] * factor_df.loc[code, 'tech_confirm'] +
                 weights_v5_2[2] * factor_df.loc[code, 'relative_strength'] +
                 weights_v5_2[3] * factor_df.loc[code, 'volume_confirm'])
        scores_v5_2[code] = np.tanh(score)
    
    # ========== v6.1: 正交化 + 优化权重 + Rank Norm ==========
    orthogonalizer = FactorOrthogonalizer(method='sequential')
    try:
        orthogonal_factors = orthogonalizer.fit_transform(factor_df)
    except Exception:
        orthogonal_factors = factor_df
    
    # 计算得分（含门控交互）
    raw_scores_v6_1 = {}
    for code in orthogonal_factors.index:
        # 线性组合（使用v6.1优化权重）
        linear = (weights_v6_1[0] * orthogonal_factors.loc[code, 'base_trend'] +
                  weights_v6_1[1] * orthogonal_factors.loc[code, 'tech_confirm'] +
                  weights_v6_1[2] * orthogonal_factors.loc[code, 'relative_strength'] +
                  weights_v6_1[3] * orthogonal_factors.loc[code, 'volume_confirm'])
        
        # 门控交互
        if orthogonal_factors.loc[code, 'base_trend'] > 0:
            interaction = (orthogonal_factors.loc[code, 'base_trend'] *
                          orthogonal_factors.loc[code, 'volume_confirm'] * 0.1)
            linear += interaction
        
        raw_scores_v6_1[code] = linear
    
    # Rank Normalization
    normalizer = RankNormalizer(method='percentile')
    scores_v6_1 = normalizer.transform(pd.Series(raw_scores_v6_1))
    
    # 选TOP N
    top_codes_v5_2 = sorted(scores_v5_2, key=scores_v5_2.get, reverse=True)[:top_n]
    top_codes_v6_1 = scores_v6_1.nlargest(top_n).index.tolist()
    
    # 计算未来5日收益
    returns_v5_2 = []
    returns_v6_1 = []
    
    for code in top_codes_v5_2:
        df = stocks_data[code]
        if len(df) > window_idx + 5:
            ret = df.iloc[window_idx + 5]['close'] / df.iloc[window_idx]['close'] - 1
            returns_v5_2.append(ret)
    
    for code in top_codes_v6_1:
        df = stocks_data[code]
        if len(df) > window_idx + 5:
            ret = df.iloc[window_idx + 5]['close'] / df.iloc[window_idx]['close'] - 1
            returns_v6_1.append(ret)
    
    if not returns_v5_2 or not returns_v6_1:
        return None
    
    return {
        'window_idx': window_idx,
        'avg_return_v5_2': np.mean(returns_v5_2),
        'win_rate_v5_2': sum(1 for r in returns_v5_2 if r > 0) / len(returns_v5_2),
        'avg_return_v6_1': np.mean(returns_v6_1),
        'win_rate_v6_1': sum(1 for r in returns_v6_1 if r > 0) / len(returns_v6_1),
        'valid_stocks_v5_2': len(returns_v5_2),
        'valid_stocks_v6_1': len(returns_v6_1)
    }


def run_full_backtest(stock_pool_file, kline_cache_dir, num_stocks=300, sample_freq=10):
    """
    运行完整回测对比
    
    Args:
        stock_pool_file: 股票池文件
        kline_cache_dir: K线缓存目录
        num_stocks: 使用股票数量
        sample_freq: 采样频率（每N个交易日）
    """
    print("=" * 80)
    print("v6.1 vs v5.2 完整回测对比（优化权重）")
    print("=" * 80)
    
    # 权重配置
    weights_v5_2 = [0.40, 0.30, 0.10, 0.20]  # v5.2基线
    weights_v6_1 = [0.42, 0.20, 0.30, 0.08]  # v6.1优化（基于IC）
    
    print(f"\n⚙️  权重配置:")
    print(f"   v5.2: {weights_v5_2} [base, tech, rs, vol]")
    print(f"   v6.1: {weights_v6_1} [base, tech, rs, vol]")
    print(f"   差异: base+2pp, tech-10pp, rs+20pp, vol-12pp")
    
    # 1. 加载股票池
    print(f"\n📊 加载股票池: {stock_pool_file}")
    with open(stock_pool_file, 'r') as f:
        pool_data = json.load(f)
    
    stocks = []
    if isinstance(pool_data, dict) and 'stocks' in pool_data:
        for category, stock_list in pool_data['stocks'].items():
            stocks.extend(stock_list)
    elif isinstance(pool_data, list):
        stocks = pool_data
    
    stocks = stocks[:num_stocks]
    print(f"   股票数量: {len(stocks)} 只")
    
    # 2. 加载K线数据
    print(f"\n📈 加载K线缓存...")
    stocks_data = {}
    for stock in stocks:
        code = stock.get('code', '')
        if not code:
            continue
        
        df = load_cached_kline(code, kline_cache_dir)
        if len(df) >= 100:
            stocks_data[code] = df
    
    print(f"   有效股票: {len(stocks_data)} 只")
    
    if len(stocks_data) < 50:
        print("⚠️ 有效股票太少，退出")
        return
    
    # 3. 加载指数数据
    print(f"\n📉 加载指数数据（000300）...")
    index_df = load_cached_kline('000300', kline_cache_dir)
    if index_df.empty:
        print("   ⚠️ 指数数据缺失")
        index_df = None
    else:
        print(f"   指数数据: {len(index_df)} 条")
    
    # 4. 确定回测窗口
    min_len = min(len(df) for df in stocks_data.values())
    start_idx = 60
    end_idx = min_len - 5
    
    windows = list(range(start_idx, end_idx, sample_freq))
    print(f"\n⏱️  回测窗口: {len(windows)} 个（每{sample_freq}日采样）")
    print(f"   时间跨度: 约 {len(windows) * sample_freq / 252:.1f} 年")
    
    # 5. 并行回测
    print(f"\n🚀 开始并行回测（8进程）...")
    
    results = []
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(backtest_cross_section, stocks_data, idx, index_df, 
                          weights_v5_2, weights_v6_1, 10): idx
            for idx in windows
        }
        
        completed = 0
        for future in as_completed(futures):
            completed += 1
            if completed % 10 == 0 or completed == len(windows):
                pct = completed / len(windows) * 100
                print(f"\r   进度: {completed}/{len(windows)} ({pct:.0f}%)", end='', flush=True)
            
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception:
                pass
        
        print()
    
    print(f"\n✅ 回测完成: {len(results)} 个有效窗口")
    
    if len(results) < 10:
        print("⚠️ 有效窗口太少，退出")
        return
    
    # 6. 汇总结果
    df_results = pd.DataFrame(results)
    
    # 统计指标
    avg_ret_v5_2 = df_results['avg_return_v5_2'].mean()
    win_rate_v5_2 = df_results['win_rate_v5_2'].mean()
    sharpe_v5_2 = avg_ret_v5_2 / (df_results['avg_return_v5_2'].std() + 1e-8)
    max_ret_v5_2 = df_results['avg_return_v5_2'].max()
    min_ret_v5_2 = df_results['avg_return_v5_2'].min()
    
    avg_ret_v6_1 = df_results['avg_return_v6_1'].mean()
    win_rate_v6_1 = df_results['win_rate_v6_1'].mean()
    sharpe_v6_1 = avg_ret_v6_1 / (df_results['avg_return_v6_1'].std() + 1e-8)
    max_ret_v6_1 = df_results['avg_return_v6_1'].max()
    min_ret_v6_1 = df_results['avg_return_v6_1'].min()
    
    # 7. 输出结果
    print(f"\n" + "=" * 80)
    print("📊 回测结果对比")
    print("=" * 80)
    
    print(f"\n【v5.2】固定权重 [0.40, 0.30, 0.10, 0.20]")
    print(f"   平均收益: {avg_ret_v5_2:+.2%}")
    print(f"   胜率: {win_rate_v5_2:.2%}")
    print(f"   Sharpe: {sharpe_v5_2:.3f}")
    print(f"   最大收益: {max_ret_v5_2:+.2%}")
    print(f"   最小收益: {min_ret_v5_2:+.2%}")
    print(f"   有效窗口: {len(results)}")
    
    print(f"\n【v6.1】优化权重 [0.42, 0.20, 0.30, 0.08] + 正交化 + Rank Norm")
    print(f"   平均收益: {avg_ret_v6_1:+.2%}")
    print(f"   胜率: {win_rate_v6_1:.2%}")
    print(f"   Sharpe: {sharpe_v6_1:.3f}")
    print(f"   最大收益: {max_ret_v6_1:+.2%}")
    print(f"   最小收益: {min_ret_v6_1:+.2%}")
    print(f"   有效窗口: {len(results)}")
    
    print(f"\n【改善】")
    ret_improve = (avg_ret_v6_1 - avg_ret_v5_2) / abs(avg_ret_v5_2) * 100 if avg_ret_v5_2 != 0 else 0
    win_improve = (win_rate_v6_1 - win_rate_v5_2) * 100
    sharpe_improve = (sharpe_v6_1 - sharpe_v5_2) / abs(sharpe_v5_2) * 100 if sharpe_v5_2 != 0 else 0
    
    print(f"   收益提升: {ret_improve:+.1f}%")
    print(f"   胜率提升: {win_improve:+.1f}pp")
    print(f"   Sharpe提升: {sharpe_improve:+.1f}%")
    
    # 8. 分段分析（按时间）
    print(f"\n" + "=" * 80)
    print("📈 分段表现分析")
    print("=" * 80)
    
    n_segments = 3
    segment_size = len(results) // n_segments
    
    for i in range(n_segments):
        start = i * segment_size
        end = (i + 1) * segment_size if i < n_segments - 1 else len(results)
        
        segment = df_results.iloc[start:end]
        
        seg_ret_v5_2 = segment['avg_return_v5_2'].mean()
        seg_ret_v6_1 = segment['avg_return_v6_1'].mean()
        
        print(f"\n第{i+1}段（窗口{start}-{end}）:")
        print(f"   v5.2: {seg_ret_v5_2:+.2%}")
        print(f"   v6.1: {seg_ret_v6_1:+.2%}")
        print(f"   差异: {(seg_ret_v6_1 - seg_ret_v5_2):+.2%}")
    
    # 9. 保存结果
    result_file = 'results/backtest_v6_1_optimized.json'
    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    
    summary = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'config': {
            'num_stocks': len(stocks_data),
            'num_windows': len(windows),
            'sample_freq': sample_freq,
            'time_span_years': len(windows) * sample_freq / 252,
            'weights_v5_2': weights_v5_2,
            'weights_v6_1': weights_v6_1
        },
        'v5_2': {
            'avg_return': float(avg_ret_v5_2),
            'win_rate': float(win_rate_v5_2),
            'sharpe': float(sharpe_v5_2),
            'max_return': float(max_ret_v5_2),
            'min_return': float(min_ret_v5_2),
            'valid_windows': len(results)
        },
        'v6_1': {
            'avg_return': float(avg_ret_v6_1),
            'win_rate': float(win_rate_v6_1),
            'sharpe': float(sharpe_v6_1),
            'max_return': float(max_ret_v6_1),
            'min_return': float(min_ret_v6_1),
            'valid_windows': len(results)
        },
        'improvement': {
            'return_pct': float(ret_improve),
            'win_rate_pp': float(win_improve),
            'sharpe_pct': float(sharpe_improve)
        }
    }
    
    with open(result_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n✅ 结果已保存: {result_file}")
    print("=" * 80)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='v6.1优化权重完整回测')
    parser.add_argument('--pool', type=str, default='mydate/stock_pool_all.json',
                        help='股票池文件')
    parser.add_argument('--cache', type=str, default='mydate/backtest_kline',
                        help='K线缓存目录')
    parser.add_argument('--stocks', type=int, default=300,
                        help='使用股票数量')
    parser.add_argument('--freq', type=int, default=10,
                        help='采样频率（每N个交易日）')
    
    args = parser.parse_args()
    
    run_full_backtest(
        stock_pool_file=args.pool,
        kline_cache_dir=args.cache,
        num_stocks=args.stocks,
        sample_freq=args.freq
    )
