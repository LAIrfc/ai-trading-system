"""
执行层反馈闭环

冲击深度模型 + 真实成交反馈修正
用实际滑点持续校准冲击模型参数。
"""

import os
import json
import numpy as np
from datetime import datetime
from typing import Optional, Dict, List


class ExecutionFeedback:
    """
    执行反馈闭环：
    - 冲击深度模型: impact = (trade_size / ADV) ^ gamma
    - 实盘反馈: 用真实滑点修正 gamma
    """

    def __init__(self, initial_gamma: float = 1.5,
                 gamma_ewma_decay: float = 0.95,
                 max_history: int = 200,
                 persist_path: Optional[str] = None):
        self.gamma = initial_gamma
        self.gamma_ewma_decay = gamma_ewma_decay
        self.max_history = max_history
        self.persist_path = persist_path
        self.history: List[dict] = []

        if persist_path and os.path.exists(persist_path):
            self._load(persist_path)

    def get_impact_cost(self, trade_value: float, adv: float) -> float:
        """
        计算冲击成本（基点）

        Args:
            trade_value: 交易金额
            adv: 日均成交额
        Returns:
            冲击成本（0~1之间的比例）
        """
        if adv <= 0:
            return 0.01
        participation = trade_value / adv
        impact = participation ** self.gamma
        return min(impact, 0.05)

    def get_cost_vector(self, trade_values: np.ndarray,
                        adv_values: np.ndarray,
                        base_cost: float = 0.003) -> np.ndarray:
        """
        计算成本向量 = 基础佣金 + 冲击成本

        Args:
            trade_values: (n,) 每只股票交易金额
            adv_values: (n,) 日均成交额
            base_cost: 基础交易成本
        Returns:
            (n,) 总成本向量
        """
        costs = np.full(len(trade_values), base_cost)
        for i in range(len(trade_values)):
            costs[i] += self.get_impact_cost(trade_values[i], adv_values[i])
        return costs

    def record_trade(self, code: str, trade_size: float, adv: float,
                     expected_impact: float, actual_slippage: float) -> None:
        """
        记录一笔交易的实际执行结果

        Args:
            code: 股票代码
            trade_size: 交易量
            adv: 日均成交量
            expected_impact: 模型预测冲击
            actual_slippage: 实际滑点
        """
        self.history.append({
            'timestamp': datetime.now().isoformat(),
            'code': code,
            'trade_size': trade_size,
            'adv': adv,
            'expected_impact': expected_impact,
            'actual_slippage': actual_slippage
        })

        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

        if abs(expected_impact) > 1e-10:
            ratio = actual_slippage / expected_impact
            ratio = np.clip(ratio, 0.1, 10.0)
            self.gamma = (self.gamma_ewma_decay * self.gamma
                          + (1 - self.gamma_ewma_decay) * self.gamma * ratio)
            self.gamma = np.clip(self.gamma, 0.5, 3.0)

    def get_diagnostics(self) -> dict:
        """获取执行反馈诊断信息"""
        if not self.history:
            return {
                'gamma': self.gamma,
                'n_trades': 0,
                'avg_slippage_ratio': None
            }

        ratios = []
        for h in self.history[-50:]:
            if abs(h['expected_impact']) > 1e-10:
                ratios.append(h['actual_slippage'] / h['expected_impact'])

        return {
            'gamma': self.gamma,
            'n_trades': len(self.history),
            'avg_slippage_ratio': np.mean(ratios) if ratios else None,
            'last_10_slippages': [h['actual_slippage'] for h in self.history[-10:]]
        }

    def save(self, path: Optional[str] = None) -> None:
        path = path or self.persist_path
        if path is None:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            'gamma': self.gamma,
            'history': self.history[-50:],
            'timestamp': datetime.now().isoformat()
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    def _load(self, path: str) -> None:
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            self.gamma = data.get('gamma', self.gamma)
            self.history = data.get('history', [])
        except Exception:
            pass


def get_dynamic_cost_vector(
    codes: list,
    stock_data: Dict[str, 'pd.DataFrame'],
    regime_prob: float,
    total_capital: float = 1_000_000,
    weights: Optional[np.ndarray] = None,
    feedback: Optional[ExecutionFeedback] = None
) -> np.ndarray:
    """
    计算动态成本向量

    Args:
        codes: 股票代码列表
        stock_data: {code: DataFrame} K线数据
        regime_prob: 市场状态
        total_capital: 总资金
        weights: 目标权重（用于计算交易金额）
        feedback: 执行反馈对象
    Returns:
        (n,) 成本向量
    """
    import pandas as pd

    n = len(codes)
    if weights is None:
        weights = np.ones(n) / n

    base_cost = 0.003 * (1 + 0.5 * max(0, 1 - regime_prob))

    if feedback is None:
        feedback = ExecutionFeedback()

    trade_values = weights * total_capital
    adv_values = np.zeros(n)

    for i, code in enumerate(codes):
        df = stock_data.get(code)
        if df is not None and isinstance(df, pd.DataFrame) and 'volume' in df.columns and 'close' in df.columns:
            recent = df.tail(20)
            adv = (recent['volume'] * recent['close']).mean()
            adv_values[i] = adv if np.isfinite(adv) else 0
        else:
            adv_values[i] = 0

    costs = feedback.get_cost_vector(trade_values, adv_values, base_cost)
    return costs
