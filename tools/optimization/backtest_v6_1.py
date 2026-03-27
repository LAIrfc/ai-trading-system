#!/usr/bin/env python3
"""
v6.1 回测验证脚本

对比v5.2和v6.1的性能差异
"""

import sys
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from src.factors.orthogonalization import FactorOrthogonalizer
from src.factors.normalization import RankNormalizer
from src.strategies.market_regime_v6 import SoftRegimeDetector
from src.portfolio.risk_scaling import VolatilityScaler


def load_cached_kline(code, cache_dir):
    """加载缓存的K线数据"""
    cache_file = os.path.join(cache_dir, f'{code}.parquet')
    if os.path.exists(cache_file):
        try:
            df = pd.read_parquet(cache_file)
            return df
        except Exception:
            pass
    return pd.DataFrame()


def calc_factors(df):
    """计算4个因子（简化版）"""
    if len(df) < 60:
        return None
    
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']
    
    # 1. Base Trend（简化）
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    trend = (ma20 / ma60 - 1).fillna(0)
    
    # 2. Tech Confirm（简化）
    ma5 = close.rolling(5).mean()
    tech = ((ma5 - ma20) / ma20).fillna(0)
    
    # 3. Relative Strength（简化：20日收益率）
    rs = (close / close.shift(20) - 1).fillna(0)
    
    # 4. Volume Confirm（简化）
    vol_ma20 = volume.rolling(20).mean()
    vol_ratio = (volume / vol_ma20).fillna(1)
    price_change = close.pct_change(5).fillna(0)
    vol_confirm = price_change * np.log(vol_ratio.clip(0.5, 2))
    
    return {
        'base_trend': trend.iloc[-1],
        'tech_confirm': tech.iloc[-1],
        'relative_strength': rs.iloc[-1],
        'volume_confirm': vol_confirm.iloc[-1]
    }


def backtest_single_window_v5_2(stocks_data, window_idx, total_windows):
    """
    单个窗口回测（v5.2固定权重）
    
    Args:
        stocks_data: dict {code: df}
        window_idx: 窗口索引
        total_windows: 总窗口数
    
    Returns:
        dict: 回测结果
    """
    # v5.2固定权重
    weights_v5_2 = [0.4, 0.3, 0.1, 0.2]  # [base, tech, rs, vol]
    
    # 计算所有股票的因子
    factor_list = []
    for code, df in stocks_data.items():
        if len(df) <= window_idx + 5:
            continue
        
        df_slice = df.iloc[:window_idx+1]
        factors = calc_factors(df_slice)
        
        if factors:
            factors['code'] = code
            factor_list.append(factors)
    
    if len(factor_list) < 10:
        return None
    
    factor_df = pd.DataFrame(factor_list).set_index('code')
    
    # v5.2: 直接线性组合 + tanh
    scores_v5_2 = {}
    for code in factor_df.index:
        score = (weights_v5_2[0] * factor_df.loc[code, 'base_trend'] +
                 weights_v5_2[1] * factor_df.loc[code, 'tech_confirm'] +
                 weights_v5_2[2] * factor_df.loc[code, 'relative_strength'] +
                 weights_v5_2[3] * factor_df.loc[code, 'volume_confirm'])
        scores_v5_2[code] = np.tanh(score)
    
    # 选TOP 10
    top_codes_v5_2 = sorted(scores_v5_2, key=scores_v5_2.get, reverse=True)[:10]
    
    # 计算未来5日收益
    returns_v5_2 = []
    for code in top_codes_v5_2:
        df = stocks_data[code]
        if len(df) > window_idx + 5:
            ret = df.iloc[window_idx + 5]['close'] / df.iloc[window_idx]['close'] - 1
            returns_v5_2.append(ret)
    
    if not returns_v5_2:
        return None
    
    return {
        'window_idx': window_idx,
        'avg_return_v5_2': np.mean(returns_v5_2),
        'win_rate_v5_2': sum(1 for r in returns_v5_2 if r > 0) / len(returns_v5_2),
        'valid_stocks': len(returns_v5_2)
    }


def backtest_single_window_v6_1(stocks_data, window_idx, total_windows, index_df=None):
    """
    单个窗口回测（v6.1完整流程）
    
    Args:
        stocks_data: dict {code: df}
        window_idx: 窗口索引
        total_windows: 总窗口数
        index_df: 指数数据（用于Regime Score）
    
    Returns:
        dict: 回测结果
    """
    # 计算所有股票的因子
    factor_list = []
    for code, df in stocks_data.items():
        if len(df) <= window_idx + 5:
            continue
        
        df_slice = df.iloc[:window_idx+1]
        factors = calc_factors(df_slice)
        
        if factors:
            factors['code'] = code
            factor_list.append(factors)
    
    if len(factor_list) < 10:
        return None
    
    factor_df = pd.DataFrame(factor_list).set_index('code')
    
    # ========== v6.1 修复1: 因子正交化 ==========
    orthogonalizer = FactorOrthogonalizer()
    try:
        orthogonal_factors = orthogonalizer.fit_transform(factor_df)
    except Exception:
        orthogonal_factors = factor_df
    
    # ========== v6.1 修复4: Soft Regime Score ==========
    regime_score = 0.0
    if index_df is not None and len(index_df) > window_idx:
        try:
            index_slice = index_df.iloc[:window_idx+1]
            regime_detector = SoftRegimeDetector()
            regime_score = regime_detector.calc_regime_score(index_slice)
            dynamic_weights = regime_detector.get_dynamic_weights(regime_score)
        except Exception:
            dynamic_weights = [0.4, 0.3, 0.1, 0.2]
    else:
        dynamic_weights = [0.4, 0.3, 0.1, 0.2]
    
    # ========== 计算得分（含门控交互） ==========
    raw_scores = {}
    for code in orthogonal_factors.index:
        # 线性组合
        linear = (dynamic_weights[0] * orthogonal_factors.loc[code, 'base_trend'] +
                  dynamic_weights[1] * orthogonal_factors.loc[code, 'tech_confirm'] +
                  dynamic_weights[2] * orthogonal_factors.loc[code, 'relative_strength'] +
                  dynamic_weights[3] * orthogonal_factors.loc[code, 'volume_confirm'])
        
        # 门控交互
        if orthogonal_factors.loc[code, 'base_trend'] > 0:
            interaction = (orthogonal_factors.loc[code, 'base_trend'] *
                          orthogonal_factors.loc[code, 'volume_confirm'] * 0.1)
            linear += interaction
        
        raw_scores[code] = linear
    
    # ========== v6.1 修复2: Rank Normalization ==========
    normalizer = RankNormalizer(method='percentile')
    normalized_scores = normalizer.transform(pd.Series(raw_scores))
    
    # 选TOP 10
    top_codes_v6_1 = normalized_scores.nlargest(10).index.tolist()
    
    # 计算未来5日收益
    returns_v6_1 = []
    for code in top_codes_v6_1:
        df = stocks_data[code]
        if len(df) > window_idx + 5:
            ret = df.iloc[window_idx + 5]['close'] / df.iloc[window_idx]['close'] - 1
            returns_v6_1.append(ret)
    
    if not returns_v6_1:
        return None
    
    return {
        'window_idx': window_idx,
        'avg_return_v6_1': np.mean(returns_v6_1),
        'win_rate_v6_1': sum(1 for r in returns_v6_1 if r > 0) / len(returns_v6_1),
        'valid_stocks': len(returns_v6_1),
        'regime_score': regime_score
    }


def run_backtest_comparison(stock_pool_file, kline_cache_dir, num_stocks=200, sample_freq=5):
    """
    运行v5.2 vs v6.1对比回测
    
    Args:
        stock_pool_file: 股票池文件
        kline_cache_dir: K线缓存目录
        num_stocks: 使用股票数量
        sample_freq: 采样频率（每N个交易日）
    """
    print("=" * 80)
    print("v6.1 vs v5.2 回测对比")
    print("=" * 80)
    
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
    
    # 3. 加载指数数据（用于Regime Score）
    print(f"\n📉 加载指数数据（000300）...")
    index_df = load_cached_kline('000300', kline_cache_dir)
    if index_df.empty:
        print("   ⚠️ 指数数据缺失，Regime Score将使用默认值")
        index_df = None
    else:
        print(f"   指数数据: {len(index_df)} 条")
    
    # 4. 确定回测窗口
    min_len = min(len(df) for df in stocks_data.values())
    start_idx = 60  # 需要60日历史计算因子
    end_idx = min_len - 5  # 保留5日计算未来收益
    
    windows = list(range(start_idx, end_idx, sample_freq))
    print(f"\n⏱️  回测窗口: {len(windows)} 个（每{sample_freq}日采样）")
    print(f"   时间跨度: 约 {len(windows) * sample_freq / 252:.1f} 年")
    
    # 5. 并行回测
    print(f"\n🚀 开始并行回测（8进程）...")
    
    results_v5_2 = []
    results_v6_1 = []
    
    with ProcessPoolExecutor(max_workers=8) as executor:
        # v5.2回测
        print("\n   【v5.2】固定权重 + tanh...")
        futures_v5_2 = {
            executor.submit(backtest_single_window_v5_2, stocks_data, idx, len(windows)): idx
            for idx in windows
        }
        
        completed = 0
        for future in as_completed(futures_v5_2):
            completed += 1
            if completed % 20 == 0 or completed == len(windows):
                pct = completed / len(windows) * 100
                print(f"\r      进度: {completed}/{len(windows)} ({pct:.0f}%)", end='', flush=True)
            
            try:
                result = future.result()
                if result:
                    results_v5_2.append(result)
            except Exception:
                pass
        
        print()
        
        # v6.1回测
        print("\n   【v6.1】正交化 + Rank Norm + Soft Regime + 门控...")
        futures_v6_1 = {
            executor.submit(backtest_single_window_v6_1, stocks_data, idx, len(windows), index_df): idx
            for idx in windows
        }
        
        completed = 0
        for future in as_completed(futures_v6_1):
            completed += 1
            if completed % 20 == 0 or completed == len(windows):
                pct = completed / len(windows) * 100
                print(f"\r      进度: {completed}/{len(windows)} ({pct:.0f}%)", end='', flush=True)
            
            try:
                result = future.result()
                if result:
                    results_v6_1.append(result)
            except Exception:
                pass
        
        print()
    
    # 6. 汇总结果
    print(f"\n" + "=" * 80)
    print("📊 回测结果汇总")
    print("=" * 80)
    
    if not results_v5_2 or not results_v6_1:
        print("⚠️ 回测结果不足，无法对比")
        return
    
    df_v5_2 = pd.DataFrame(results_v5_2)
    df_v6_1 = pd.DataFrame(results_v6_1)
    
    # v5.2统计
    avg_ret_v5_2 = df_v5_2['avg_return_v5_2'].mean()
    win_rate_v5_2 = df_v5_2['win_rate_v5_2'].mean()
    sharpe_v5_2 = avg_ret_v5_2 / (df_v5_2['avg_return_v5_2'].std() + 1e-8)
    
    # v6.1统计
    avg_ret_v6_1 = df_v6_1['avg_return_v6_1'].mean()
    win_rate_v6_1 = df_v6_1['win_rate_v6_1'].mean()
    sharpe_v6_1 = avg_ret_v6_1 / (df_v6_1['avg_return_v6_1'].std() + 1e-8)
    
    print(f"\n【v5.2】固定权重 + tanh")
    print(f"   平均收益: {avg_ret_v5_2:+.2%}")
    print(f"   胜率: {win_rate_v5_2:.2%}")
    print(f"   Sharpe: {sharpe_v5_2:.3f}")
    print(f"   有效窗口: {len(results_v5_2)}")
    
    print(f"\n【v6.1】正交化 + Rank Norm + Soft Regime + 门控")
    print(f"   平均收益: {avg_ret_v6_1:+.2%}")
    print(f"   胜率: {win_rate_v6_1:.2%}")
    print(f"   Sharpe: {sharpe_v6_1:.3f}")
    print(f"   有效窗口: {len(results_v6_1)}")
    
    print(f"\n【改善】")
    print(f"   收益提升: {(avg_ret_v6_1 - avg_ret_v5_2) / abs(avg_ret_v5_2) * 100:+.1f}%")
    print(f"   胜率提升: {(win_rate_v6_1 - win_rate_v5_2) * 100:+.1f}pp")
    print(f"   Sharpe提升: {(sharpe_v6_1 - sharpe_v5_2) / abs(sharpe_v5_2) * 100:+.1f}%")
    
    # 7. 保存结果
    result_file = 'results/backtest_v6_1_comparison.json'
    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    
    summary = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'config': {
            'num_stocks': len(stocks_data),
            'num_windows': len(windows),
            'sample_freq': sample_freq,
            'time_span_years': len(windows) * sample_freq / 252
        },
        'v5_2': {
            'avg_return': float(avg_ret_v5_2),
            'win_rate': float(win_rate_v5_2),
            'sharpe': float(sharpe_v5_2),
            'valid_windows': len(results_v5_2)
        },
        'v6_1': {
            'avg_return': float(avg_ret_v6_1),
            'win_rate': float(win_rate_v6_1),
            'sharpe': float(sharpe_v6_1),
            'valid_windows': len(results_v6_1)
        },
        'improvement': {
            'return_pct': float((avg_ret_v6_1 - avg_ret_v5_2) / abs(avg_ret_v5_2) * 100),
            'win_rate_pp': float((win_rate_v6_1 - win_rate_v5_2) * 100),
            'sharpe_pct': float((sharpe_v6_1 - sharpe_v5_2) / abs(sharpe_v5_2) * 100)
        }
    }
    
    with open(result_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n✅ 结果已保存: {result_file}")
    print("=" * 80)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='v6.1 vs v5.2 回测对比')
    parser.add_argument('--pool', type=str, default='mydate/stock_pool_all.json',
                        help='股票池文件')
    parser.add_argument('--cache', type=str, default='mydate/backtest_kline',
                        help='K线缓存目录')
    parser.add_argument('--stocks', type=int, default=200,
                        help='使用股票数量')
    parser.add_argument('--freq', type=int, default=5,
                        help='采样频率（每N个交易日）')
    
    args = parser.parse_args()
    
    run_backtest_comparison(
        stock_pool_file=args.pool,
        kline_cache_dir=args.cache,
        num_stocks=args.stocks,
        sample_freq=args.freq
    )
