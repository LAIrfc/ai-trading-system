#!/usr/bin/env python3
"""
A/B测试框架：v5.2 vs v6.1

每日运行两个版本，对比选股结果和收益
"""

import sys
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from src.factors.orthogonalization import FactorOrthogonalizer
from src.factors.normalization import RankNormalizer
from src.strategies.trend_strategies import Trend_Composite, Momentum_Adj, TechnicalConfirmation, VolumeConfirmation, RelativeStrength


def run_selection_v5_2(df_scores, weights=[0.40, 0.30, 0.10, 0.20], top_n=10):
    """
    v5.2选股逻辑
    
    Args:
        df_scores: DataFrame with columns [trend_score, momentum_score, tech_confirm_score, 
                   relative_strength_score, volume_confirm_score]
        weights: [base, tech, rs, vol]
        top_n: 选股数量
    
    Returns:
        list: 选中的股票代码
    """
    # 计算base_trend
    base_trend = (0.7 * df_scores['trend_score'] + 
                  0.3 * df_scores['momentum_score'])
    
    # 计算得分
    scores = {}
    for code in df_scores.index:
        score = (weights[0] * base_trend[code] +
                 weights[1] * df_scores.loc[code, 'tech_confirm_score'] +
                 weights[2] * df_scores.loc[code, 'relative_strength_score'] +
                 weights[3] * df_scores.loc[code, 'volume_confirm_score'])
        scores[code] = np.tanh(score)
    
    # 选TOP N
    top_codes = sorted(scores, key=scores.get, reverse=True)[:top_n]
    
    return top_codes, scores


def run_selection_v6_1(df_scores, weights=[0.42, 0.20, 0.30, 0.08], top_n=10):
    """
    v6.1选股逻辑（正交化 + 优化权重 + Rank Norm + 门控交互）
    
    Args:
        df_scores: DataFrame with columns [trend_score, momentum_score, tech_confirm_score, 
                   relative_strength_score, volume_confirm_score]
        weights: [base, tech, rs, vol]
        top_n: 选股数量
    
    Returns:
        list: 选中的股票代码
    """
    # 计算base_trend
    base_trend = (0.7 * df_scores['trend_score'] + 
                  0.3 * df_scores['momentum_score'])
    
    # 准备因子数据
    factor_df = pd.DataFrame({
        'base_trend': base_trend,
        'tech_confirm': df_scores['tech_confirm_score'],
        'relative_strength': df_scores['relative_strength_score'],
        'volume_confirm': df_scores['volume_confirm_score']
    })
    
    # 因子正交化
    orthogonalizer = FactorOrthogonalizer(method='sequential')
    try:
        orthogonal_factors = orthogonalizer.fit_transform(factor_df)
    except Exception:
        orthogonal_factors = factor_df
    
    # 计算得分（含门控交互）
    raw_scores = {}
    for code in orthogonal_factors.index:
        # 线性组合
        linear = (weights[0] * orthogonal_factors.loc[code, 'base_trend'] +
                  weights[1] * orthogonal_factors.loc[code, 'tech_confirm'] +
                  weights[2] * orthogonal_factors.loc[code, 'relative_strength'] +
                  weights[3] * orthogonal_factors.loc[code, 'volume_confirm'])
        
        # 门控交互
        if orthogonal_factors.loc[code, 'base_trend'] > 0:
            interaction = (orthogonal_factors.loc[code, 'base_trend'] *
                          orthogonal_factors.loc[code, 'volume_confirm'] * 0.1)
            linear += interaction
        
        raw_scores[code] = linear
    
    # Rank Normalization
    normalizer = RankNormalizer(method='percentile')
    normalized_scores = normalizer.transform(pd.Series(raw_scores))
    
    # 选TOP N
    top_codes = normalized_scores.nlargest(top_n).index.tolist()
    
    return top_codes, normalized_scores.to_dict()


def compare_selections(top_v5_2, top_v6_1, scores_v5_2, scores_v6_1):
    """
    对比两个版本的选股结果
    
    Returns:
        dict: 对比统计
    """
    common = set(top_v5_2) & set(top_v6_1)
    only_v5_2 = set(top_v5_2) - set(top_v6_1)
    only_v6_1 = set(top_v6_1) - set(top_v5_2)
    
    return {
        'overlap_count': len(common),
        'overlap_rate': len(common) / len(top_v5_2),
        'only_v5_2': list(only_v5_2),
        'only_v6_1': list(only_v6_1),
        'common': list(common)
    }


def save_ab_test_result(date, top_v5_2, top_v6_1, scores_v5_2, scores_v6_1, comparison):
    """保存A/B测试结果"""
    result_dir = 'results/ab_test'
    os.makedirs(result_dir, exist_ok=True)
    
    result = {
        'date': date,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'v5_2': {
            'top_stocks': top_v5_2,
            'scores': {k: float(v) for k, v in scores_v5_2.items() if k in top_v5_2}
        },
        'v6_1': {
            'top_stocks': top_v6_1,
            'scores': {k: float(v) for k, v in scores_v6_1.items() if k in top_v6_1}
        },
        'comparison': comparison
    }
    
    result_file = os.path.join(result_dir, f'ab_test_{date}.json')
    with open(result_file, 'w') as f:
        json.dump(result, f, indent=2)
    
    return result_file


def track_ab_test_performance(ab_test_dir='results/ab_test', lookback_days=5):
    """
    跟踪A/B测试的历史表现
    
    Args:
        ab_test_dir: A/B测试结果目录
        lookback_days: 回看天数
    """
    if not os.path.exists(ab_test_dir):
        print("⚠️ 无A/B测试历史数据")
        return
    
    # 加载所有历史测试
    test_files = sorted([f for f in os.listdir(ab_test_dir) if f.endswith('.json')])
    
    if len(test_files) < 2:
        print("⚠️ A/B测试数据不足")
        return
    
    print("=" * 80)
    print("📊 A/B测试历史表现跟踪")
    print("=" * 80)
    
    performance = {
        'v5_2': {'returns': [], 'win_count': 0},
        'v6_1': {'returns': [], 'win_count': 0}
    }
    
    # TODO: 实现收益跟踪逻辑
    # 需要获取每日选股后5日的实际收益
    
    print("\n⚠️ 收益跟踪功能待实现（需要实时价格数据）")
    print("   当前仅记录每日选股差异")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='A/B测试框架')
    parser.add_argument('--mode', choices=['run', 'track'], default='run',
                        help='运行模式：run=执行A/B测试，track=跟踪历史表现')
    parser.add_argument('--date', type=str, default=None,
                        help='测试日期（YYYY-MM-DD），默认今日')
    
    args = parser.parse_args()
    
    if args.mode == 'track':
        track_ab_test_performance()
    else:
        print("=" * 80)
        print("A/B测试框架")
        print("=" * 80)
        print("\n⚠️ A/B测试需要集成到recommend_today.py中")
        print("   当前提供的是框架代码，实际使用需要：")
        print("   1. 在recommend_today.py中同时运行v5.2和v6.1")
        print("   2. 保存每日选股结果")
        print("   3. 跟踪后续实际收益")
        print("\n📝 建议实施步骤：")
        print("   1. 修改recommend_today.py，添加--version参数（v5.2/v6.1）")
        print("   2. 每日分别运行两个版本")
        print("   3. 使用本脚本的save_ab_test_result保存结果")
        print("   4. 定期运行track模式查看对比")


if __name__ == '__main__':
    main()
