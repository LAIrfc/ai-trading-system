#!/usr/bin/env python3
"""
因子标准化模块（Factor Normalization）

提供Rank Normalization等标准化方法
"""

import numpy as np
import pandas as pd
from scipy.stats import norm


class RankNormalizer:
    """
    排序标准化器（机构级）
    
    将因子值转换为横截面排序百分位，确保scale稳定
    """
    def __init__(self, method='percentile'):
        """
        Args:
            method: 'percentile'（百分位）或 'gaussian'（高斯化）
        """
        self.method = method
    
    def transform(self, scores):
        """
        排序标准化
        
        Args:
            scores: pd.Series, index=code, value=raw_score
        
        Returns:
            pd.Series: 标准化后的得分 [-1, 1]
        """
        if len(scores) < 2:
            return scores
        
        # 过滤NaN
        valid_scores = scores.dropna()
        if len(valid_scores) < 2:
            return scores
        
        if self.method == 'percentile':
            # 百分位排序：[0, 1] → [-1, 1]
            rank_pct = valid_scores.rank(pct=True, method='average')
            normalized = rank_pct * 2 - 1
        
        elif self.method == 'gaussian':
            # 高斯化：先排序，再映射到正态分布
            rank_pct = valid_scores.rank(pct=True, method='average')
            # 避免极值（0和1会导致inf）
            rank_pct = np.clip(rank_pct, 0.001, 0.999)
            normalized = pd.Series(norm.ppf(rank_pct), index=valid_scores.index)
            # 标准化到[-1, 1]（3-sigma范围）
            normalized = normalized / 3
            normalized = np.clip(normalized, -1, 1)
        
        else:
            raise ValueError(f"Unknown method: {self.method}")
        
        # 回填到原始索引（保留NaN）
        result = pd.Series(np.nan, index=scores.index)
        result.loc[normalized.index] = normalized
        
        return result
    
    def transform_batch(self, score_dict):
        """
        批量标准化（多个因子）
        
        Args:
            score_dict: dict {factor_name: pd.Series}
        
        Returns:
            dict: {factor_name: normalized_series}
        """
        return {name: self.transform(scores) for name, scores in score_dict.items()}
    
    def diagnose(self, scores_before, scores_after):
        """
        诊断标准化效果
        
        Returns:
            dict: 诊断信息
        """
        valid_before = scores_before.dropna()
        valid_after = scores_after.dropna()
        
        return {
            'mean_before': valid_before.mean(),
            'std_before': valid_before.std(),
            'min_before': valid_before.min(),
            'max_before': valid_before.max(),
            'mean_after': valid_after.mean(),
            'std_after': valid_after.std(),
            'min_after': valid_after.min(),
            'max_after': valid_after.max()
        }
