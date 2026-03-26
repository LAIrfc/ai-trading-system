#!/usr/bin/env python3
"""
趋势引擎组权重优化工具
使用网格搜索优化4层组权重，目标最大化趋势市中的Sharpe比率
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pandas as pd
import numpy as np
import json
from itertools import product
from concurrent.futures import ProcessPoolExecutor, as_completed

from src.strategies.trend_strategies import Trend_Composite, Momentum_Adj, TechnicalConfirmation, VolumeConfirmation, RelativeStrength

# 默认权重（Phase 2）
DEFAULT_WEIGHTS = {
    'base_trend': 0.4,
    'tech_confirm': 0.3,
    'relative_strength': 0.2,
    'volume_confirm': 0.1
}

# 网格搜索范围（步长0.1，总和必须为1.0）
WEIGHT_RANGES = {
    'base_trend': [0.3, 0.4, 0.5],
    'tech_confirm': [0.2, 0.3, 0.4],
    'relative_strength': [0.1, 0.2, 0.3],
    'volume_confirm': [0.0, 0.1, 0.2]
}

TREND_SCORE_WEIGHT = 0.7
MOMENTUM_SCORE_WEIGHT = 0.3

def load_kline(code, kline_dir):
    """加载K线数据"""
    parquet_path = os.path.join(kline_dir, f"{code}.parquet")
    if os.path.exists(parquet_path):
        return pd.read_parquet(parquet_path)
    return pd.DataFrame()

def calculate_all_factors(df, index_df=None):
    """
    计算所有因子得分
    
    Returns:
        dict with keys: trend_score, momentum_score, tech_confirm_score, 
                       volume_confirm_score, relative_strength_score
    """
    factors = {
        'trend_score': 0.0,
        'momentum_score': 0.0,
        'tech_confirm_score': 0.0,
        'volume_confirm_score': 0.0,
        'relative_strength_score': 0.0
    }
    
    # 基础趋势
    try:
        trend_strat = Trend_Composite()
        trend_df = trend_strat.generate_signals(df)
        if 'trend_score' in trend_df.columns and not trend_df.empty:
            factors['trend_score'] = float(trend_df['trend_score'].iloc[-1])
    except Exception:
        pass
    
    # 动量
    try:
        mom_strat = Momentum_Adj()
        mom_df = mom_strat.generate_signals(df)
        if 'score' in mom_df.columns and not mom_df.empty:
            factors['momentum_score'] = float(mom_df['score'].iloc[-1])
    except Exception:
        pass
    
    # 技术确认
    try:
        tech_strat = TechnicalConfirmation()
        tech_df = tech_strat.generate_signals(df)
        if 'tech_confirm_score' in tech_df.columns and not tech_df.empty:
            factors['tech_confirm_score'] = float(tech_df['tech_confirm_score'].iloc[-1])
    except Exception:
        pass
    
    # 量价配合
    try:
        vol_strat = VolumeConfirmation()
        vol_df = vol_strat.generate_signals(df)
        if 'volume_confirm_score' in vol_df.columns and not vol_df.empty:
            factors['volume_confirm_score'] = float(vol_df['volume_confirm_score'].iloc[-1])
    except Exception:
        pass
    
    # 相对强度
    try:
        rs_strat = RelativeStrength()
        rs_df = rs_strat.generate_signals(df, index_df=index_df)
        if 'relative_strength_score' in rs_df.columns and not rs_df.empty:
            factors['relative_strength_score'] = float(rs_df['relative_strength_score'].iloc[-1])
    except Exception:
        pass
    
    return factors

def compute_trend_rank_score(factors, weights):
    """
    根据给定权重计算趋势质量得分
    
    Args:
        factors: 因子得分字典
        weights: 组权重字典
    
    Returns:
        trend_rank_score
    """
    base_trend = (TREND_SCORE_WEIGHT * factors['trend_score'] +
                  MOMENTUM_SCORE_WEIGHT * factors['momentum_score'])
    
    trend_rank_score = (weights['base_trend'] * base_trend +
                       weights['tech_confirm'] * factors['tech_confirm_score'] +
                       weights['relative_strength'] * factors['relative_strength_score'] +
                       weights['volume_confirm'] * factors['volume_confirm_score'])
    
    return trend_rank_score

def backtest_single_stock(code, name, kline_dir, index_df, weights):
    """
    回测单只股票在给定权重下的表现
    
    Returns:
        dict with avg_return, win_rate, sharpe, total_signals
    """
    df = load_kline(code, kline_dir)
    if df.empty or len(df) < 60:
        return None
    
    signals = []
    returns = []
    
    # 滚动窗口回测
    for i in range(60, len(df) - 5):  # 保留5日用于计算未来收益
        window_df = df.iloc[:i+1].copy()
        
        # 计算所有因子
        factors = calculate_all_factors(window_df, index_df)
        
        # 计算趋势质量得分
        trend_rank_score = compute_trend_rank_score(factors, weights)
        
        # 如果得分 > 0.5，买入信号
        if trend_rank_score > 0.5:
            future_return = (df['close'].iloc[i+5] - df['close'].iloc[i]) / df['close'].iloc[i]
            signals.append(trend_rank_score)
            returns.append(future_return)
    
    if not returns:
        return None
    
    return {
        'code': code,
        'name': name,
        'avg_return': np.mean(returns),
        'win_rate': sum(1 for r in returns if r > 0) / len(returns),
        'sharpe': np.mean(returns) / (np.std(returns) + 1e-6) if len(returns) > 1 else 0,
        'total_signals': len(returns)
    }

def evaluate_weights(weights, stocks, kline_dir, index_df):
    """
    评估给定权重配置的整体表现
    
    Returns:
        dict with avg_return, avg_win_rate, avg_sharpe
    """
    results = []
    
    for stock in stocks[:100]:  # 限制100只股票以加快速度
        code = stock['code']
        name = stock['name']
        
        result = backtest_single_stock(code, name, kline_dir, index_df, weights)
        if result:
            results.append(result)
    
    if not results:
        return None
    
    df_results = pd.DataFrame(results)
    return {
        'weights': weights,
        'avg_return': df_results['avg_return'].mean(),
        'avg_win_rate': df_results['win_rate'].mean(),
        'avg_sharpe': df_results['sharpe'].mean(),
        'valid_stocks': len(df_results)
    }

def grid_search(stocks, kline_dir, index_df):
    """
    网格搜索最优组权重
    """
    print("=" * 80)
    print("趋势引擎组权重网格搜索")
    print("=" * 80)
    
    # 生成所有权重组合（总和必须为1.0）
    weight_combinations = []
    for bt, tc, rs, vc in product(
        WEIGHT_RANGES['base_trend'],
        WEIGHT_RANGES['tech_confirm'],
        WEIGHT_RANGES['relative_strength'],
        WEIGHT_RANGES['volume_confirm']
    ):
        if abs(bt + tc + rs + vc - 1.0) < 0.01:  # 总和必须为1.0
            weight_combinations.append({
                'base_trend': bt,
                'tech_confirm': tc,
                'relative_strength': rs,
                'volume_confirm': vc
            })
    
    print(f"\n搜索空间: {len(weight_combinations)} 种权重组合")
    print(f"测试股票: {min(100, len(stocks))} 只")
    
    # 评估每种权重组合
    all_results = []
    for i, weights in enumerate(weight_combinations, 1):
        print(f"\r  进度: {i}/{len(weight_combinations)}", end='', flush=True)
        
        result = evaluate_weights(weights, stocks, kline_dir, index_df)
        if result:
            all_results.append(result)
    
    print("\n")
    
    if not all_results:
        print("⚠️ 无有效结果")
        return None
    
    # 按Sharpe比率排序
    all_results.sort(key=lambda x: x['avg_sharpe'], reverse=True)
    
    # 输出TOP5
    print("\n" + "=" * 80)
    print("TOP 5 最优权重配置（按Sharpe排序）")
    print("=" * 80)
    
    for i, r in enumerate(all_results[:5], 1):
        w = r['weights']
        print(f"\n{i}. 权重配置:")
        print(f"   基础趋势={w['base_trend']:.1f} | 技术确认={w['tech_confirm']:.1f} | "
              f"相对强度={w['relative_strength']:.1f} | 量价配合={w['volume_confirm']:.1f}")
        print(f"   平均收益率: {r['avg_return']:.2%}")
        print(f"   平均胜率: {r['avg_win_rate']:.2%}")
        print(f"   平均Sharpe: {r['avg_sharpe']:.3f}")
        print(f"   有效股票: {r['valid_stocks']}")
    
    # 保存结果
    result_path = os.path.join(os.path.dirname(__file__), "../../results/trend_weights_optimization.json")
    os.makedirs(os.path.dirname(result_path), exist_ok=True)
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    
    print(f"\n📝 完整结果已保存到: {result_path}")
    
    return all_results[0]  # 返回最优配置

def main():
    # 加载股票池
    pool_path = os.path.join(os.path.dirname(__file__), "../../mydate/stock_pool_all.json")
    with open(pool_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    all_stocks = []
    if 'stocks' in data:
        for sector, stock_list in data['stocks'].items():
            all_stocks.extend(stock_list)
    
    print(f"股票池大小: {len(all_stocks)} 只")
    
    # 加载指数数据
    print("加载指数数据（沪深300）...")
    try:
        from src.data.fetchers.data_prefetch import fetch_stock_daily
        index_df = fetch_stock_daily('000300', datalen=800)
        print(f"✅ 指数数据加载成功: {len(index_df)} 条")
    except Exception as e:
        print(f"⚠️ 指数数据加载失败: {e}")
        index_df = None
    
    # K线数据目录
    kline_dir = os.path.join(os.path.dirname(__file__), "../../mydate/backtest_kline")
    
    # 网格搜索
    best_weights = grid_search(all_stocks, kline_dir, index_df)
    
    if best_weights:
        print("\n" + "=" * 80)
        print("🏆 最优权重配置")
        print("=" * 80)
        w = best_weights['weights']
        print(f"基础趋势: {w['base_trend']:.1f}")
        print(f"技术确认: {w['tech_confirm']:.1f}")
        print(f"相对强度: {w['relative_strength']:.1f}")
        print(f"量价配合: {w['volume_confirm']:.1f}")
        print(f"\n平均收益率: {best_weights['avg_return']:.2%}")
        print(f"平均胜率: {best_weights['avg_win_rate']:.2%}")
        print(f"平均Sharpe: {best_weights['avg_sharpe']:.3f}")

if __name__ == '__main__':
    main()
