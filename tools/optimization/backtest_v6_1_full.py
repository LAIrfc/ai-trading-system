#!/usr/bin/env python3
"""
v6.1 完整回测验证脚本（使用真实因子计算）

对比v5.2和v6.1的性能差异
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
from src.strategies.market_regime_v6 import SoftRegimeDetector
from src.portfolio.risk_scaling import VolatilityScaler
from src.strategies.trend_strategies import Trend_Composite, Momentum_Adj, TechnicalConfirmation, VolumeConfirmation, RelativeStrength


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


def calc_factors_full(df, index_df=None):
    """
    计算4个因子（完整版，与recommend_today.py一致）
    
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
        trend_score = float(trend_df['trend_score'].iloc[-1]) if 'trend_score' in trend_df.columns else 0.0
        
        mom_strat = Momentum_Adj()
        mom_df = mom_strat.generate_signals(df)
        momentum_score = float(mom_df['score'].iloc[-1]) if 'score' in mom_df.columns else 0.0
        
        base_trend = 0.7 * trend_score + 0.3 * momentum_score
        
        # 2. Tech Confirm
        tech_strat = TechnicalConfirmation()
        tech_df = tech_strat.generate_signals(df)
        tech_confirm = float(tech_df['tech_confirm_score'].iloc[-1]) if 'tech_confirm_score' in tech_df.columns else 0.0
        
        # 3. Relative Strength
        rs_strat = RelativeStrength()
        rs_df = rs_strat.generate_signals(df, index_df=index_df, sector_df=None)
        relative_strength = float(rs_df['relative_strength_score'].iloc[-1]) if 'relative_strength_score' in rs_df.columns else 0.0
        
        # 4. Volume Confirm
        vol_strat = VolumeConfirmation()
        vol_df = vol_strat.generate_signals(df)
        volume_confirm = float(vol_df['volume_confirm_score'].iloc[-1]) if 'volume_confirm_score' in vol_df.columns else 0.0
        
        return {
            'base_trend': base_trend,
            'tech_confirm': tech_confirm,
            'relative_strength': relative_strength,
            'volume_confirm': volume_confirm
        }
    except Exception as e:
        return None


def backtest_single_stock(code, df, index_df, sample_freq=20):
    """
    单只股票的滚动窗口回测
    
    Returns:
        dict: {
            'code': str,
            'windows_v5_2': list,
            'windows_v6_1': list
        }
    """
    if len(df) < 100:
        return None
    
    results_v5_2 = []
    results_v6_1 = []
    
    # 滚动窗口
    for i in range(60, len(df) - 5, sample_freq):
        df_slice = df.iloc[:i+1]
        
        # 计算因子
        factors = calc_factors_full(df_slice, index_df)
        if not factors:
            continue
        
        # ========== v5.2: 固定权重 + tanh ==========
        weights_v5_2 = [0.4, 0.3, 0.1, 0.2]
        score_v5_2 = (weights_v5_2[0] * factors['base_trend'] +
                      weights_v5_2[1] * factors['tech_confirm'] +
                      weights_v5_2[2] * factors['relative_strength'] +
                      weights_v5_2[3] * factors['volume_confirm'])
        score_v5_2 = np.tanh(score_v5_2)
        
        # ========== v6.1: 动态权重（简化，不做正交化） ==========
        # 注：单股票无法做正交化，这里只测试Soft Regime + 门控交互
        regime_score = 0.0
        if index_df is not None and len(index_df) > i:
            try:
                index_slice = index_df.iloc[:i+1]
                regime_detector = SoftRegimeDetector()
                regime_score = regime_detector.calc_regime_score(index_slice)
                dynamic_weights = regime_detector.get_dynamic_weights(regime_score)
            except Exception:
                dynamic_weights = weights_v5_2
        else:
            dynamic_weights = weights_v5_2
        
        score_v6_1 = (dynamic_weights[0] * factors['base_trend'] +
                      dynamic_weights[1] * factors['tech_confirm'] +
                      dynamic_weights[2] * factors['relative_strength'] +
                      dynamic_weights[3] * factors['volume_confirm'])
        
        # 门控交互
        if factors['base_trend'] > 0:
            score_v6_1 += factors['base_trend'] * factors['volume_confirm'] * 0.1
        
        # 未来5日收益
        future_ret = df.iloc[i+5]['close'] / df.iloc[i]['close'] - 1
        
        results_v5_2.append({
            'window_idx': i,
            'score': score_v5_2,
            'future_return': future_ret
        })
        
        results_v6_1.append({
            'window_idx': i,
            'score': score_v6_1,
            'future_return': future_ret,
            'regime_score': regime_score
        })
    
    if not results_v5_2:
        return None
    
    return {
        'code': code,
        'windows_v5_2': results_v5_2,
        'windows_v6_1': results_v6_1
    }


def analyze_results(all_results):
    """分析回测结果"""
    if not all_results:
        print("⚠️ 无有效回测结果")
        return None
    
    # 汇总所有窗口
    all_v5_2 = []
    all_v6_1 = []
    
    for result in all_results:
        all_v5_2.extend(result['windows_v5_2'])
        all_v6_1.extend(result['windows_v6_1'])
    
    if not all_v5_2 or not all_v6_1:
        print("⚠️ 窗口数据为空")
        return None
    
    df_v5_2 = pd.DataFrame(all_v5_2)
    df_v6_1 = pd.DataFrame(all_v6_1)
    
    # 按得分分组，计算IC（信息系数）
    # IC = 因子值与未来收益的相关性
    ic_v5_2 = df_v5_2['score'].corr(df_v5_2['future_return'], method='spearman')
    ic_v6_1 = df_v6_1['score'].corr(df_v6_1['future_return'], method='spearman')
    
    # 分层回测：按得分分5组，看各组收益
    df_v5_2['score_group'] = pd.qcut(df_v5_2['score'], 5, labels=['Q1', 'Q2', 'Q3', 'Q4', 'Q5'], duplicates='drop')
    df_v6_1['score_group'] = pd.qcut(df_v6_1['score'], 5, labels=['Q1', 'Q2', 'Q3', 'Q4', 'Q5'], duplicates='drop')
    
    group_ret_v5_2 = df_v5_2.groupby('score_group')['future_return'].mean()
    group_ret_v6_1 = df_v6_1.groupby('score_group')['future_return'].mean()
    
    return {
        'ic_v5_2': ic_v5_2,
        'ic_v6_1': ic_v6_1,
        'group_ret_v5_2': group_ret_v5_2,
        'group_ret_v6_1': group_ret_v6_1,
        'total_windows_v5_2': len(df_v5_2),
        'total_windows_v6_1': len(df_v6_1)
    }


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='v6.1完整回测验证')
    parser.add_argument('--pool', type=str, default='mydate/stock_pool_all.json',
                        help='股票池文件')
    parser.add_argument('--cache', type=str, default='mydate/backtest_kline',
                        help='K线缓存目录')
    parser.add_argument('--stocks', type=int, default=200,
                        help='使用股票数量')
    parser.add_argument('--freq', type=int, default=20,
                        help='采样频率（每N个交易日）')
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("v6.1 完整回测验证（使用真实因子计算）")
    print("=" * 80)
    
    # 1. 加载股票池
    print(f"\n📊 加载股票池: {args.pool}")
    with open(args.pool, 'r') as f:
        pool_data = json.load(f)
    
    stocks = []
    if isinstance(pool_data, dict) and 'stocks' in pool_data:
        for category, stock_list in pool_data['stocks'].items():
            stocks.extend(stock_list)
    elif isinstance(pool_data, list):
        stocks = pool_data
    
    stocks = stocks[:args.stocks]
    print(f"   股票数量: {len(stocks)} 只")
    
    # 2. 加载K线数据
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
        print("⚠️ 有效股票太少，退出")
        return
    
    # 3. 加载指数数据
    print(f"\n📉 加载指数数据（000300）...")
    index_df = load_cached_kline('000300', args.cache)
    if index_df.empty:
        print("   ⚠️ 指数数据缺失，Regime Score将使用默认值")
        index_df = None
    else:
        print(f"   指数数据: {len(index_df)} 条")
    
    # 4. 并行回测
    print(f"\n🚀 开始并行回测（8进程，每{args.freq}日采样）...")
    
    all_results = []
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(backtest_single_stock, code, df, index_df, args.freq): code
            for code, df in stocks_data.items()
        }
        
        completed = 0
        total = len(stocks_data)
        for future in as_completed(futures):
            completed += 1
            if completed % 20 == 0 or completed == total:
                pct = completed / total * 100
                print(f"\r   进度: {completed}/{total} ({pct:.0f}%)", end='', flush=True)
            
            try:
                result = future.result()
                if result:
                    all_results.append(result)
            except Exception:
                pass
        
        print()
    
    print(f"\n✅ 回测完成: {len(all_results)} 只股票有效")
    
    if len(all_results) == 0:
        print("⚠️ 无有效回测结果，可能原因：")
        print("   1. 因子计算失败（数据不足）")
        print("   2. 策略类导入失败")
        print("   3. K线数据质量问题")
        return
    
    # 5. 分析结果
    print(f"\n📊 分析结果...")
    analysis = analyze_results(all_results)
    
    if analysis is None:
        print("⚠️ 分析失败，退出")
        return
    
    print(f"\n" + "=" * 80)
    print("📈 因子有效性分析（IC - Information Coefficient）")
    print("=" * 80)
    print(f"v5.2 IC（Spearman）: {analysis['ic_v5_2']:.4f}")
    print(f"v6.1 IC（Spearman）: {analysis['ic_v6_1']:.4f}")
    print(f"改善: {(analysis['ic_v6_1'] - analysis['ic_v5_2']):.4f}")
    
    print(f"\n" + "=" * 80)
    print("📊 分层回测（按得分分5组）")
    print("=" * 80)
    print(f"\nv5.2 各组平均收益:")
    for group, ret in analysis['group_ret_v5_2'].items():
        print(f"   {group}: {ret:+.2%}")
    
    print(f"\nv6.1 各组平均收益:")
    for group, ret in analysis['group_ret_v6_1'].items():
        print(f"   {group}: {ret:+.2%}")
    
    # 6. 保存结果
    result_file = 'results/backtest_v6_1_full_comparison.json'
    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    
    summary = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'config': {
            'num_stocks': len(stocks_data),
            'sample_freq': args.freq,
            'valid_stocks': len(all_results)
        },
        'ic_analysis': {
            'ic_v5_2': float(analysis['ic_v5_2']),
            'ic_v6_1': float(analysis['ic_v6_1']),
            'improvement': float(analysis['ic_v6_1'] - analysis['ic_v5_2'])
        },
        'group_returns': {
            'v5_2': {str(k): float(v) for k, v in analysis['group_ret_v5_2'].items()},
            'v6_1': {str(k): float(v) for k, v in analysis['group_ret_v6_1'].items()}
        }
    }
    
    with open(result_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n✅ 结果已保存: {result_file}")
    print("=" * 80)


if __name__ == '__main__':
    main()
