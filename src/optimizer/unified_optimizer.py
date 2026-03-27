"""
统一组合优化器

凸优化：max ER_adj - λ_risk*Risk - λ_cost*Cost - λ_smooth*PathPenalty
趋势与均值回归股票同框统一优化。
无 cvxpy 依赖时降级为解析解（等权+风险调整）。
"""

import numpy as np
import pandas as pd
from typing import Optional, Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)

try:
    import cvxpy as cp
    HAS_CVXPY = True
except ImportError:
    HAS_CVXPY = False
    logger.info("cvxpy not installed, optimizer will use fallback analytical solution")


class UnifiedOptimizer:
    """
    统一组合优化器

    目标: max ER_adj - λ_risk * (var_weight*Var + cvar_weight*CVaR)
              - λ_cost * (turnover + impact) - λ_smooth * PathPenalty
    """

    def __init__(self,
                 max_weight: float = 0.10,
                 max_leverage: float = 1.5,
                 max_l2: float = 1.2,
                 target_vol: float = 0.15,
                 max_trend_pct: float = 0.20,
                 lambda_risk: float = 0.5,
                 lambda_cost: float = 0.1,
                 lambda_smooth: float = 0.1,
                 var_weight: float = 0.7,
                 cvar_weight: float = 0.3):
        self.max_weight = max_weight
        self.max_leverage = max_leverage
        self.max_l2 = max_l2
        self.target_vol = target_vol
        self.max_trend_pct = max_trend_pct
        self.lambda_risk = lambda_risk
        self.lambda_cost = lambda_cost
        self.lambda_smooth = lambda_smooth
        self.var_weight = var_weight
        self.cvar_weight = cvar_weight

    def optimize(self,
                 expected_returns: np.ndarray,
                 covariance: np.ndarray,
                 returns_hist: np.ndarray,
                 regime_prob: float,
                 prev_weights: Optional[np.ndarray] = None,
                 prev_weights2: Optional[np.ndarray] = None,
                 cost_vector: Optional[np.ndarray] = None,
                 trend_mask: Optional[np.ndarray] = None,
                 codes: Optional[List[str]] = None
                 ) -> Dict:
        """
        执行统一优化

        Args:
            expected_returns: (n,) 预期收益率
            covariance: (n, n) 协方差矩阵
            returns_hist: (T, n) 历史收益率（用于CVaR）
            regime_prob: 市场状态概率 [0, 1]
            prev_weights: (n,) 上期权重
            prev_weights2: (n,) 上上期权重（路径平滑）
            cost_vector: (n,) 每股交易成本
            trend_mask: (n,) bool 趋势股标记
            codes: 股票代码列表
        Returns:
            dict: {weights, status, diagnostics}
        """
        n = len(expected_returns)

        expected_returns = np.nan_to_num(expected_returns, nan=0.0, posinf=0.0, neginf=0.0)

        if prev_weights is None:
            prev_weights = np.zeros(n)
        if cost_vector is None:
            cost_vector = np.full(n, 0.003)
        if trend_mask is None:
            trend_mask = np.zeros(n, dtype=bool)

        covariance = np.nan_to_num(covariance, nan=0.0)
        np.fill_diagonal(covariance, np.maximum(np.diag(covariance), 1e-8))

        er_adj = expected_returns * (1.0 + 0.5 * (regime_prob - 0.5))

        cvar_w = self.cvar_weight * max(0, 1.0 - regime_prob)
        var_w = 1.0 - cvar_w

        if HAS_CVXPY:
            return self._optimize_cvxpy(
                er_adj, covariance, returns_hist, regime_prob,
                prev_weights, prev_weights2, cost_vector, trend_mask,
                var_w, cvar_w, codes
            )
        else:
            return self._optimize_fallback(
                er_adj, covariance, prev_weights, cost_vector,
                trend_mask, codes
            )

    def _optimize_cvxpy(self, er_adj, cov, returns_hist, regime_prob,
                        prev_w, prev_w2, cost_vec, trend_mask,
                        var_w, cvar_w, codes):
        n = len(er_adj)
        T = returns_hist.shape[0] if returns_hist is not None else 0
        w = cp.Variable(n)

        objective_terms = [er_adj @ w]

        risk_terms = []
        if var_w > 0:
            variance = cp.quad_form(w, cp.psd_wrap(cov))
            risk_terms.append(var_w * variance)

        if cvar_w > 0 and T > 10:
            loss = -returns_hist @ w
            alpha_cvar = 0.05
            t = cp.Variable()
            cvar_ru = t + (1.0 / (alpha_cvar * T)) * cp.sum(cp.pos(loss - t))
            risk_terms.append(cvar_w * cvar_ru)

        if risk_terms:
            downside_factor = max(0, 0.6 - regime_prob)
            risk_scale = float(np.exp(3.0 * downside_factor))
            objective_terms.append(-self.lambda_risk * risk_scale * sum(risk_terms))

        turnover = cp.sum(cp.multiply(cost_vec, cp.abs(w - prev_w)))
        impact = 0.5 * cp.sum_squares(w - prev_w)
        objective_terms.append(-self.lambda_cost * (turnover + impact))

        if prev_w2 is not None:
            smooth = cp.sum_squares(w - 2 * prev_w + prev_w2)
            objective_terms.append(-self.lambda_smooth * smooth)

        objective = cp.Maximize(sum(objective_terms))

        constraints = [
            cp.sum(w) == 1,
            w >= 0,
            w <= self.max_weight,
            cp.norm(w, 1) <= self.max_leverage,
        ]

        if n >= 2:
            constraints.append(cp.norm(w, 2) <= self.max_l2)

        if var_w > 0:
            constraints.append(cp.quad_form(w, cp.psd_wrap(cov)) <= self.target_vol ** 2)

        if trend_mask.any():
            trend_idx = np.where(trend_mask)[0]
            if len(trend_idx) > 0:
                constraints.append(cp.sum(w[trend_idx]) <= self.max_trend_pct)

        prob = cp.Problem(objective, constraints)

        status = 'failed'
        w_val = None
        solvers = [cp.CLARABEL, cp.SCS, cp.ECOS, cp.OSQP]
        for solver in solvers:
            try:
                prob.solve(solver=solver, max_iters=2000, verbose=False)
                if prob.status in ['optimal', 'optimal_inaccurate']:
                    w_val = w.value
                    status = prob.status
                    break
            except Exception as e:
                logger.debug("Solver %s failed: %s", solver, e)
                continue

        if w_val is None:
            return self._optimize_fallback(
                er_adj, cov, prev_w, cost_vec, trend_mask, codes
            )

        w_val = np.maximum(w_val, 0)
        w_sum = w_val.sum()
        if w_sum > 1e-6:
            w_val /= w_sum
        else:
            w_val = np.ones(n) / n

        diagnostics = {
            'solver_status': status,
            'portfolio_var': float(w_val @ cov @ w_val),
            'expected_return': float(er_adj @ w_val),
            'turnover': float(np.sum(np.abs(w_val - prev_w))),
            'max_weight': float(w_val.max()),
            'n_stocks': int((w_val > 0.001).sum()),
        }

        return {
            'weights': w_val,
            'status': status,
            'diagnostics': diagnostics,
            'codes': codes
        }

    def _optimize_fallback(self, er_adj, cov, prev_w, cost_vec,
                           trend_mask, codes):
        """无 cvxpy 时的解析降级方案：风险平价 + 预期收益调整"""
        n = len(er_adj)

        vols = np.sqrt(np.diag(cov)) + 1e-8
        inv_vol = 1.0 / vols

        er_rank = np.zeros(n)
        valid = np.isfinite(er_adj) & (er_adj != 0)
        if valid.any():
            from scipy.stats import rankdata
            er_rank[valid] = rankdata(er_adj[valid]) / valid.sum()

        w = inv_vol * (0.5 + 0.5 * er_rank)
        w = np.maximum(w, 0)
        w = np.minimum(w, self.max_weight * w.sum() / (w.max() + 1e-8))

        if trend_mask.any():
            trend_total = w[trend_mask].sum()
            total = w.sum()
            if total > 0 and trend_total / total > self.max_trend_pct:
                scale = self.max_trend_pct * total / (trend_total + 1e-8)
                w[trend_mask] *= scale

        w_sum = w.sum()
        if w_sum > 1e-6:
            w /= w_sum
        else:
            w = np.ones(n) / n

        return {
            'weights': w,
            'status': 'fallback_analytical',
            'diagnostics': {
                'solver_status': 'fallback',
                'portfolio_var': float(w @ cov @ w),
                'expected_return': float(er_adj @ w),
                'max_weight': float(w.max()),
                'n_stocks': int((w > 0.001).sum()),
            },
            'codes': codes
        }


def apply_liquidity_constraint(
    weights: np.ndarray,
    adv_values: np.ndarray,
    max_adv_pct: float = 0.05,
    total_capital: float = 1_000_000
) -> np.ndarray:
    """
    流动性约束：单票交易量不超过日均成交额的 max_adv_pct

    Args:
        weights: (n,) 权重
        adv_values: (n,) 日均成交额
        max_adv_pct: 最大占比
        total_capital: 总资金
    Returns:
        (n,) 约束后权重
    """
    w = weights.copy()
    for i in range(len(w)):
        if adv_values[i] > 0:
            max_w = max_adv_pct * adv_values[i] / total_capital
            w[i] = min(w[i], max_w)

    w_sum = w.sum()
    if w_sum > 1e-6:
        w /= w_sum
    return w
