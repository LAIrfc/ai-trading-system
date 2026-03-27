"""
前瞻性风险模型

EWMA + Shrinkage 协方差矩阵 + 极端情景模拟 CVaR
快速响应波动率突变，预测未来尾部风险。
"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple


def ewma_covariance(returns: pd.DataFrame, halflife: int = 30,
                    shrink_target: str = 'identity',
                    shrink_intensity: float = 0.2) -> np.ndarray:
    """
    EWMA + Shrinkage 协方差矩阵

    Args:
        returns: (T, n) 收益率矩阵
        halflife: EWMA半衰期（交易日）
        shrink_target: 收缩目标 'identity' 或 'diagonal'
        shrink_intensity: 收缩强度 [0, 1]
    Returns:
        (n, n) 协方差矩阵
    """
    ret = returns.values if isinstance(returns, pd.DataFrame) else returns
    T, n = ret.shape

    if T < 2 or n < 1:
        return np.eye(n) * 0.04

    decay = 0.5 ** (1.0 / halflife)
    weights = np.array([decay ** (T - 1 - t) for t in range(T)])
    weights /= weights.sum()

    mean = (ret * weights[:, None]).sum(axis=0)
    demeaned = ret - mean[None, :]
    weighted = demeaned * np.sqrt(weights[:, None])
    cov_ewma = weighted.T @ weighted

    if shrink_target == 'identity':
        target = np.eye(n) * np.diag(cov_ewma).mean()
    else:
        target = np.diag(np.diag(cov_ewma))

    cov = (1 - shrink_intensity) * cov_ewma + shrink_intensity * target

    min_var = 1e-8
    np.fill_diagonal(cov, np.maximum(np.diag(cov), min_var))

    return cov


def augment_returns_with_extreme(
    returns: np.ndarray,
    regime_prob: float,
    shock_factor: float = 2.0,
    tail_pct: float = 0.05
) -> np.ndarray:
    """
    极端情景增强：对历史最差的 tail_pct 场景放大

    Args:
        returns: (T, n) 收益率矩阵
        regime_prob: 当前市场状态概率 [0=极度恐慌, 1=强势]
        shock_factor: 基础放大倍数
        tail_pct: 尾部百分位
    Returns:
        (T, n) 增强后的收益率矩阵
    """
    ret = returns.copy()
    T = ret.shape[0]
    if T < 20:
        return ret

    eq_losses = -ret.mean(axis=1) if ret.ndim > 1 else -ret
    threshold = np.percentile(eq_losses, 100 * (1 - tail_pct))
    extreme_mask = eq_losses >= threshold

    if extreme_mask.any():
        shock = 1.0 + shock_factor * max(0, 1.0 - regime_prob)
        ret[extreme_mask] *= shock

    return ret


def regime_weighted_cvar(
    returns: np.ndarray,
    weights: np.ndarray,
    regime_prob: float,
    alpha: float = 0.05,
    stress_k: float = 3.0,
    shock_factor: float = 2.0
) -> float:
    """
    Regime 加权 CVaR（含极端情景模拟）

    Args:
        returns: (T, n) 收益率矩阵
        weights: (n,) 权重向量
        regime_prob: 市场状态概率
        alpha: CVaR 置信水平
        stress_k: 应力乘数系数
        shock_factor: 极端情景放大系数
    Returns:
        CVaR 值
    """
    ret_aug = augment_returns_with_extreme(returns, regime_prob, shock_factor)

    portfolio_loss = -(ret_aug @ weights)

    stress_mult = 1.0 + stress_k * max(0, 1.0 - regime_prob)
    loss_stressed = portfolio_loss * stress_mult

    T = len(loss_stressed)
    n_tail = max(1, int(alpha * T))
    sorted_loss = np.sort(loss_stressed)[::-1]
    cvar = sorted_loss[:n_tail].mean()

    return max(cvar, 0.0)


def compute_expected_return(
    alpha: np.ndarray,
    ic: float,
    vol: Optional[np.ndarray] = None
) -> np.ndarray:
    """
    预期收益率 = IC * vol * z(alpha)

    Args:
        alpha: (n,) 标准化alpha信号
        ic: 信息系数
        vol: (n,) 残差波动率（可选，默认20%）
    Returns:
        (n,) 预期收益率
    """
    alpha = np.asarray(alpha, dtype=float)
    alpha = np.nan_to_num(alpha, nan=0.0)

    z = alpha.copy()
    s = z.std()
    if s > 1e-10:
        z = (z - z.mean()) / s

    if vol is None:
        vol = np.full_like(alpha, 0.20)
    else:
        vol = np.asarray(vol, dtype=float)

    er = ic * vol * z
    return er


class RiskModel:
    """
    前瞻性风险模型：封装 EWMA协方差 + 极端CVaR
    """

    def __init__(self, ewma_halflife: int = 30, shrink_intensity: float = 0.2,
                 cvar_alpha: float = 0.05, cvar_stress_k: float = 3.0,
                 shock_factor: float = 2.0):
        self.ewma_halflife = ewma_halflife
        self.shrink_intensity = shrink_intensity
        self.cvar_alpha = cvar_alpha
        self.cvar_stress_k = cvar_stress_k
        self.shock_factor = shock_factor
        self._cov: Optional[np.ndarray] = None
        self._returns: Optional[np.ndarray] = None

    def fit(self, returns: pd.DataFrame) -> 'RiskModel':
        self._returns = returns.values if isinstance(returns, pd.DataFrame) else returns
        self._cov = ewma_covariance(
            returns, halflife=self.ewma_halflife,
            shrink_intensity=self.shrink_intensity
        )
        return self

    @property
    def covariance(self) -> np.ndarray:
        if self._cov is None:
            raise ValueError("Must call fit() first")
        return self._cov

    def portfolio_variance(self, weights: np.ndarray) -> float:
        return float(weights @ self._cov @ weights)

    def portfolio_cvar(self, weights: np.ndarray, regime_prob: float) -> float:
        if self._returns is None:
            return 0.0
        return regime_weighted_cvar(
            self._returns, weights, regime_prob,
            alpha=self.cvar_alpha, stress_k=self.cvar_stress_k,
            shock_factor=self.shock_factor
        )

    def get_stock_volatilities(self) -> np.ndarray:
        if self._cov is None:
            raise ValueError("Must call fit() first")
        return np.sqrt(np.diag(self._cov)) * np.sqrt(252)
