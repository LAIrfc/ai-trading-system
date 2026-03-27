#!/usr/bin/env python3
"""
因子正交化模块（Factor Orthogonalization）

使用Gram-Schmidt正交化过程，去除因子间的线性相关性
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression


class FactorOrthogonalizer:
    """
    因子正交化器（机构级）
    
    使用顺序回归残差化方法，去除因子间的线性相关性
    """
    def __init__(self, method='sequential'):
        """
        Args:
            method: 'sequential'（顺序正交化）
        """
        self.method = method
        self.models = {}  # 保存回归模型，用于样本外预测
        self.factor_order = None
    
    def fit_transform(self, factor_df, factor_order=None):
        """
        训练并转换因子（去相关性）
        
        Args:
            factor_df: DataFrame, columns=['base_trend', 'tech_confirm', 'relative_strength', 'volume_confirm']
            factor_order: list, 因子正交化顺序（默认按重要性排序）
        
        Returns:
            DataFrame: 正交化后的因子
        """
        if factor_order is None:
            # 默认顺序：重要性从高到低
            # RS最独立 → Base最重要 → Tech次之 → Vol最后
            factor_order = ['relative_strength', 'base_trend', 'tech_confirm', 'volume_confirm']
        
        self.factor_order = factor_order
        
        # 确保所有因子列都存在
        available_factors = [f for f in factor_order if f in factor_df.columns]
        if len(available_factors) == 0:
            raise ValueError(f"No valid factors found in factor_df. Available columns: {factor_df.columns.tolist()}")
        
        factors = factor_df[available_factors].copy()
        result = pd.DataFrame(index=factors.index)
        
        for i, col in enumerate(available_factors):
            y = factors[col].values.reshape(-1, 1)
            
            if i == 0:
                # 第一个因子保持不变（作为基准）
                result[col] = factors[col]
                self.models[col] = None
            else:
                # 对后续因子进行残差化
                X = result[available_factors[:i]].values
                
                # 过滤NaN
                valid_mask = ~(np.isnan(X).any(axis=1) | np.isnan(y.flatten()))
                if valid_mask.sum() < 10:
                    # 有效样本太少，保持原值
                    result[col] = factors[col]
                    self.models[col] = None
                    continue
                
                X_valid = X[valid_mask]
                y_valid = y[valid_mask]
                
                # 线性回归：y = X * beta + residual
                model = LinearRegression(fit_intercept=True)
                model.fit(X_valid, y_valid)
                
                # 残差 = 原因子 - 可被前序因子解释的部分
                y_pred = model.predict(X)
                residual = y.flatten() - y_pred.flatten()
                
                result[col] = residual
                self.models[col] = model
        
        return result
    
    def transform(self, factor_df):
        """
        转换新样本（使用已训练的模型）
        
        用于样本外预测，避免look-ahead bias
        """
        if self.factor_order is None:
            raise ValueError("Must call fit_transform() before transform()")
        
        available_factors = [f for f in self.factor_order if f in factor_df.columns]
        factors = factor_df[available_factors].copy()
        result = pd.DataFrame(index=factors.index)
        
        for i, col in enumerate(available_factors):
            if i == 0 or self.models[col] is None:
                result[col] = factors[col]
            else:
                X = result[available_factors[:i]].values
                y = factors[col].values.reshape(-1, 1)
                
                y_pred = self.models[col].predict(X)
                residual = y.flatten() - y_pred.flatten()
                
                result[col] = residual
        
        return result
    
    def get_correlation_matrix(self, factor_df, orthogonalized_df):
        """
        对比正交化前后的因子相关性
        
        Returns:
            tuple: (原始相关矩阵, 正交化后相关矩阵)
        """
        corr_before = factor_df.corr()
        corr_after = orthogonalized_df.corr()
        
        return corr_before, corr_after
    
    def diagnose(self, factor_df, orthogonalized_df):
        """
        诊断正交化效果
        
        Returns:
            dict: 诊断信息
        """
        corr_before, corr_after = self.get_correlation_matrix(factor_df, orthogonalized_df)
        
        # 计算平均绝对相关性（排除对角线）
        n = len(corr_before)
        avg_corr_before = (corr_before.abs().sum().sum() - n) / (n * (n - 1))
        avg_corr_after = (corr_after.abs().sum().sum() - n) / (n * (n - 1))
        
        improvement = (avg_corr_before - avg_corr_after) / avg_corr_before * 100
        
        return {
            'avg_corr_before': avg_corr_before,
            'avg_corr_after': avg_corr_after,
            'improvement_pct': improvement,
            'corr_matrix_before': corr_before,
            'corr_matrix_after': corr_after
        }
