#!/usr/bin/env python3
"""
简化版回测：v5.2 vs v6.1权重对比

使用简化的因子计算，确保稳定运行
"""

import sys
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from src.factors.orthogonalization import FactorOrthogonalizer
from src.factors.normalization import RankNormalizer


def load_cached_kline(code, cache_dir):
    """加载缓存的K线数据"""
    cache_file = os.path.join(cache_dir, f'{code}.parquet')
    if os.path.exists(cache_file):
        try:
            return pd.read_parquet(cache_file)
        except Exception:
            pass
    return pd.DataFrame()


def calc_factors_simple(df):
    """
    简化因子计算（确保稳定）
    
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
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        
        # 1. Base Trend = MA趋势 + 动量
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()
        trend = (ma20.iloc[-1] / ma60.iloc[-1] - 1) if ma60.iloc[-1] > 0 else 0
        
        momentum = (close.iloc[-1] / close.iloc[-20] - 1) if len(close) > 20 else 0
        
        base_trend = 0.7 * trend + 0.3 * momentum
        
        # 2. Tech Confirm = MA5相对MA20
        ma5 = close.rolling(5).mean()
        tech_confirm = (ma5.iloc[-1] / ma20.iloc[-1] - 1) if ma20.iloc[-1] > 0 else 0
        
        # 3. Relative Strength = 20日收益率
        relative_strength = (close.iloc[-1] / close.iloc[-21] - 1) if len(close) > 20 else 0
        
        # 4. Volume Confirm = 量价配合
        vol_ma20 = volume.rolling(20).mean()
        vol_ratio = volume.iloc[-1] / vol_ma20.iloc[-1] if vol_ma20.iloc[-1] > 0 else 1
        price_change = (close.iloc[-1] / close.iloc[-6] - 1) if len(close) > 5 else 0
        
        volume_confirm = price_change * np.log(np.clip(vol_ratio, 0.5, 2))
        
        return {
            'base_trend': base_trend,
            'tech_confirm': tech_confirm,
            'relative_strength': relative_strength,
            'volume_confirm': volume_confirm
        }
    except Exception:
        return None


def backtest_window(stocks_data, window_idx, weights_v5_2, weights_v6_1, top_n=10):
    """单个窗口回测"""
    # 计算所有股票的因子
    factor_list = []
    for code, df in stocks_data.items():
        if len(df) <= window_idx + 5:
            continue
        
        df_slice = df.iloc[:window_idx+1]
        factors = calc_factors_simple(df_slice)
        
        if factors and all(not np.isnan(v) and not np.isinf(v) for v in factors.values()):
            factors['code'] = code
            factor_list.append(factors)
    
    if len(factor_list) < top_n * 2:
        return None
    
    factor_df = pd.DataFrame(factor_list).set_index('code')
    
    # ========== v5.2 ==========
    scores_v5_2 = {}
    for code in factor_df.index:
        score = (weights_v5_2[0] * factor_df.loc[code, 'base_trend'] +
                 weights_v5_2[1] * factor_df.loc[code, 'tech_confirm'] +
                 weights_v5_2[2] * factor_df.loc[code, 'relative_strength'] +
                 weights_v5_2[3] * factor_df.loc[code, 'volume_confirm'])
        scores_v5_2[code] = np.tanh(score)
    
    # ========== v6.1 ==========
    try:
        orthogonalizer = FactorOrthogonalizer(method='sequential')
        orthogonal_factors = orthogonalizer.fit_transform(factor_df)
    except Exception:
        orthogonal_factors = factor_df
    
    raw_scores_v6_1 = {}
    for code in orthogonal_factors.index:
        linear = (weights_v6_1[0] * orthogonal_factors.loc[code, 'base_trend'] +
                  weights_v6_1[1] * orthogonal_factors.loc[code, 'tech_confirm'] +
                  weights_v6_1[2] * orthogonal_factors.loc[code, 'relative_strength'] +
                  weights_v6_1[3] * orthogonal_factors.loc[code, 'volume_confirm'])
        
        if orthogonal_factors.loc[code, 'base_trend'] > 0:
            linear += orthogonal_factors.loc[code, 'base_trend'] * orthogonal_factors.loc[code, 'volume_confirm'] * 0.1
        
        raw_scores_v6_1[code] = linear
    
    normalizer = RankNormalizer(method='percentile')
    scores_v6_1 = normalizer.transform(pd.Series(raw_scores_v6_1))
    
    # 选TOP N
    top_v5_2 = sorted(scores_v5_2, key=scores_v5_2.get, reverse=True)[:top_n]
    top_v6_1 = scores_v6_1.nlargest(top_n).index.tolist()
    
    # 计算未来5日收益
    ret_v5_2 = []
    ret_v6_1 = []
    
    for code in top_v5_2:
        df = stocks_data[code]
        if len(df) > window_idx + 5:
            r = df.iloc[window_idx + 5]['close'] / df.iloc[window_idx]['close'] - 1
            ret_v5_2.append(r)
    
    for code in top_v6_1:
        df = stocks_data[code]
        if len(df) > window_idx + 5:
            r = df.iloc[window_idx + 5]['close'] / df.iloc[window_idx]['close'] - 1
            ret_v6_1.append(r)
    
    if not ret_v5_2 or not ret_v6_1:
        return None
    
    return {
        'avg_return_v5_2': np.mean(ret_v5_2),
        'win_rate_v5_2': sum(1 for r in ret_v5_2 if r > 0) / len(ret_v5_2),
        'avg_return_v6_1': np.mean(ret_v6_1),
        'win_rate_v6_1': sum(1 for r in ret_v6_1 if r > 0) / len(ret_v6_1)
    }


def main():
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--pool', default='mydate/stock_pool_all.json')
    parser.add_argument('--cache', default='mydate/backtest_kline')
    parser.add_argument('--stocks', type=int, default=300)
    parser.add_argument('--freq', type=int, default=10)
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("v6.1 vs v5.2 简化回测（优化权重）")
    print("=" * 80)
    
    weights_v5_2 = [0.40, 0.30, 0.10, 0.20]
    weights_v6_1 = [0.42, 0.20, 0.30, 0.08]
    
    print(f"\n⚙️  权重配置:")
    print(f"   v5.2: {weights_v5_2}")
    print(f"   v6.1: {weights_v6_1}")
    
    # 加载股票池
    print(f"\n📊 加载股票池...")
    with open(args.pool, 'r') as f:
        pool_data = json.load(f)
    
    stocks = []
    if isinstance(pool_data, dict) and 'stocks' in pool_data:
        for category, stock_list in pool_data['stocks'].items():
            stocks.extend(stock_list)
    elif isinstance(pool_data, list):
        stocks = pool_data
    
    stocks = stocks[:args.stocks]
    
    # 加载K线
    print(f"\n📈 加载K线缓存...")
    stocks_data = {}
    for stock in stocks:
        code = stock.get('code', '')
        if not code:
            continue
        
        df = load_cached_kline(code, args.cache)
        if len(df) >= 100:
            stocks_data[code] = df
    
    print(f"   有效股票: {len(stocks_data)} 只")
    
    if len(stocks_data) < 50:
        print("⚠️ 有效股票太少")
        return
    
    # 确定窗口
    min_len = min(len(df) for df in stocks_data.values())
    windows = list(range(60, min_len - 5, args.freq))
    
    print(f"\n⏱️  回测窗口: {len(windows)} 个")
    print(f"   时间跨度: 约 {len(windows) * args.freq / 252:.1f} 年")
    
    # 并行回测
    print(f"\n🚀 开始回测...")
    
    results = []
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(backtest_window, stocks_data, idx, weights_v5_2, weights_v6_1): idx
            for idx in windows
        }
        
        completed = 0
        for future in as_completed(futures):
            completed += 1
            if completed % 5 == 0 or completed == len(windows):
                print(f"\r   进度: {completed}/{len(windows)} ({completed/len(windows)*100:.0f}%)", end='', flush=True)
            
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception:
                pass
        
        print()
    
    if len(results) < 5:
        print(f"⚠️ 有效窗口太少: {len(results)}")
        return
    
    # 汇总
    df_results = pd.DataFrame(results)
    
    avg_v5_2 = df_results['avg_return_v5_2'].mean()
    win_v5_2 = df_results['win_rate_v5_2'].mean()
    sharpe_v5_2 = avg_v5_2 / (df_results['avg_return_v5_2'].std() + 1e-8)
    
    avg_v6_1 = df_results['avg_return_v6_1'].mean()
    win_v6_1 = df_results['win_rate_v6_1'].mean()
    sharpe_v6_1 = avg_v6_1 / (df_results['avg_return_v6_1'].std() + 1e-8)
    
    print(f"\n" + "=" * 80)
    print("📊 回测结果")
    print("=" * 80)
    
    print(f"\n【v5.2】权重 [0.40, 0.30, 0.10, 0.20]")
    print(f"   平均收益: {avg_v5_2:+.2%}")
    print(f"   胜率: {win_v5_2:.2%}")
    print(f"   Sharpe: {sharpe_v5_2:.3f}")
    
    print(f"\n【v6.1】权重 [0.42, 0.20, 0.30, 0.08] + 正交化 + Rank Norm")
    print(f"   平均收益: {avg_v6_1:+.2%}")
    print(f"   胜率: {win_v6_1:.2%}")
    print(f"   Sharpe: {sharpe_v6_1:.3f}")
    
    print(f"\n【改善】")
    ret_imp = (avg_v6_1 - avg_v5_2) / abs(avg_v5_2) * 100 if avg_v5_2 != 0 else 0
    print(f"   收益: {ret_imp:+.1f}%")
    print(f"   胜率: {(win_v6_1 - win_v5_2)*100:+.1f}pp")
    print(f"   Sharpe: {(sharpe_v6_1 - sharpe_v5_2)/abs(sharpe_v5_2)*100:+.1f}%")
    
    # 保存
    result = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'config': {
            'stocks': len(stocks_data),
            'windows': len(results),
            'freq': args.freq
        },
        'v5_2': {'return': float(avg_v5_2), 'win_rate': float(win_v5_2), 'sharpe': float(sharpe_v5_2)},
        'v6_1': {'return': float(avg_v6_1), 'win_rate': float(win_v6_1), 'sharpe': float(sharpe_v6_1)},
        'improvement': {'return_pct': float(ret_imp), 'win_rate_pp': float((win_v6_1-win_v5_2)*100)}
    }
    
    os.makedirs('results', exist_ok=True)
    with open('results/backtest_simple.json', 'w') as f:
        json.dump(result, f, indent=2)
    
    print(f"\n✅ 结果已保存: results/backtest_simple.json")
    print("=" * 80)


if __name__ == '__main__':
    main()
