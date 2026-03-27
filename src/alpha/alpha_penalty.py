"""
Alpha 相关性惩罚（去拥挤度）

对原始 alpha 施加因子暴露协方差惩罚，
避免多因子共振导致隐性集中风险。
"""

import numpy as np
import pandas as pd
from typing import Optional


def compute_alpha_with_penalty(
    alpha_raw: np.ndarray,
    factor_exposures: np.ndarray,
    lambda_penalty: float = 0.1
) -> np.ndarray:
    """
    对原始 alpha 施加相关性惩罚

    Args:
        alpha_raw: (n,) 原始alpha向量
        factor_exposures: (n, k) 因子暴露矩阵（n只股票, k个因子）
        lambda_penalty: 惩罚强度
    Returns:
        (n,) 惩罚后的alpha
    """
    alpha = np.nan_to_num(np.asarray(alpha_raw, dtype=float).copy(), nan=0.0)
    F = np.nan_to_num(np.asarray(factor_exposures, dtype=float), nan=0.0)

    if F.ndim != 2 or F.shape[0] != len(alpha):
        return alpha

    valid = np.isfinite(alpha) & np.all(np.isfinite(F), axis=1)
    if valid.sum() < 10:
        return alpha

    F_v = F[valid]
    a_v = alpha[valid]

    factor_cov = np.cov(F_v, rowvar=False)
    if factor_cov.ndim == 0:
        factor_cov = np.array([[factor_cov]])

    crowding = a_v @ F_v @ factor_cov @ F_v.T @ a_v
    crowding_norm = crowding / (np.linalg.norm(a_v) ** 2 + 1e-12)

    penalty_scale = lambda_penalty * crowding_norm
    penalty_scale = min(penalty_scale, 0.5)

    alpha[valid] = a_v * (1.0 - penalty_scale)
    return alpha


def build_factor_exposures(
    df_scores: pd.DataFrame,
    factor_cols: Optional[list] = None
) -> np.ndarray:
    """
    从 df_scores 构建因子暴露矩阵

    Args:
        df_scores: 包含因子列的 DataFrame
        factor_cols: 因子列名列表
    Returns:
        (n, k) 因子暴露矩阵
    """
    if factor_cols is None:
        factor_cols = ['base_trend_orth', 'tech_confirm_orth',
                       'relative_strength_orth', 'volume_confirm_orth']

    available = [c for c in factor_cols if c in df_scores.columns]
    if not available:
        return np.zeros((len(df_scores), 1))

    exposures = df_scores[available].fillna(0.0).values
    return exposures


def nonlinear_alpha_mapping(alpha: np.ndarray, power: float = 1.5) -> np.ndarray:
    """
    非线性 alpha 映射：放大尾部信号

    alpha_mapped = sign(alpha) * |alpha|^power
    """
    alpha = np.nan_to_num(np.asarray(alpha, dtype=float), nan=0.0)
    return np.sign(alpha) * np.abs(alpha) ** power
