"""
KDJ策略（随机指标）

原理:
- K线上穿D线（金叉）→ 买入（仅K<50有效区）
- K线下穿D线（死叉）→ 卖出（仅K>50有效区）
- J > 100 超买，J < 0 超卖（需拐头确认）
- 低位金叉(K<30)信号最强，高位死叉(K>70)信号最强

参数:
- n:   RSV 周期（默认9）    范围[5, 21]
- m1:  K值平滑周期（默认3）  范围[2, 5]
- m2:  D值平滑周期（默认3）  范围[2, 5]

min_bars 计算: n + m1 + m2 + 3
"""

import pandas as pd
import numpy as np
from .base import Strategy, StrategySignal


class KDJStrategy(Strategy):

    name = 'KDJ'
    description = 'KDJ金叉/死叉信号(K位置过滤)，J值拐头确认超买超卖'

    param_ranges = {
        'n':  (5, 9, 21, 1),
        'm1': (2, 3, 5, 1),
        'm2': (2, 3, 5, 1),
    }

    def __init__(self, n: int = 9, m1: int = 3, m2: int = 3, **kwargs):
        self.n = n
        self.m1 = m1
        self.m2 = m2
        self.min_bars = n + m1 + m2 + 3

    def _calc_kdj(self, df: pd.DataFrame):
        """计算KDJ指标"""
        high = df['high']
        low = df['low']
        close = df['close']

        lowest = low.rolling(self.n).min()
        highest = high.rolling(self.n).max()
        rsv = (close - lowest) / (highest - lowest).replace(0, 1e-10) * 100

        k = rsv.ewm(com=self.m1 - 1, adjust=False).mean()
        d = k.ewm(com=self.m2 - 1, adjust=False).mean()
        j = 3 * k - 2 * d

        return k, d, j

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        k, d, j = self._calc_kdj(df)

        cur_k = float(k.iloc[-1])
        cur_d = float(d.iloc[-1])
        cur_j = float(j.iloc[-1])
        prev_k = float(k.iloc[-2])
        prev_d = float(d.iloc[-2])
        prev_j = float(j.iloc[-2])

        indicators = {
            'K': round(cur_k, 2),
            'D': round(cur_d, 2),
            'J': round(cur_j, 2),
        }

        # ---- 金叉信号 ----
        if prev_k <= prev_d and cur_k > cur_d:
            if cur_k < 30:
                # 低位金叉 → 强买入
                return StrategySignal(
                    action='BUY', confidence=0.80, position=0.85,
                    reason=f'KDJ低位金叉: K={cur_k:.1f}↑ 上穿 D={cur_d:.1f}, J={cur_j:.1f}',
                    indicators=indicators,
                )
            elif cur_k < 50:
                # 中低位金叉 → 有效买入
                return StrategySignal(
                    action='BUY', confidence=0.62, position=0.6,
                    reason=f'KDJ中位金叉: K={cur_k:.1f}↑ 上穿 D={cur_d:.1f} (K<50有效区)',
                    indicators=indicators,
                )
            else:
                # K≥50 的金叉 → 位置偏高，仅观望
                return StrategySignal(
                    action='HOLD', confidence=0.45, position=0.5,
                    reason=f'KDJ高位金叉(K={cur_k:.1f}≥50)，信号偏弱，观望',
                    indicators=indicators,
                )

        # ---- J值超卖（需拐头确认）----
        if cur_j < 0:
            if cur_j > prev_j:
                return StrategySignal(
                    action='BUY', confidence=0.58, position=0.45,
                    reason=f'J值超卖拐头 ({prev_j:.1f}→{cur_j:.1f})',
                    indicators=indicators,
                )
            else:
                return StrategySignal(
                    action='HOLD', confidence=0.4, position=0.2,
                    reason=f'J值超卖({cur_j:.1f})但仍下行，等待拐头',
                    indicators=indicators,
                )

        # ---- 死叉信号 ----
        if prev_k >= prev_d and cur_k < cur_d:
            if cur_k > 70:
                # 高位死叉 → 强卖出
                return StrategySignal(
                    action='SELL', confidence=0.80, position=0.0,
                    reason=f'KDJ高位死叉: K={cur_k:.1f}↓ 下穿 D={cur_d:.1f}, J={cur_j:.1f}',
                    indicators=indicators,
                )
            elif cur_k > 50:
                # 中高位死叉 → 有效卖出
                return StrategySignal(
                    action='SELL', confidence=0.62, position=0.15,
                    reason=f'KDJ中位死叉: K={cur_k:.1f}↓ 下穿 D={cur_d:.1f}',
                    indicators=indicators,
                )
            else:
                # K≤50 的死叉 → 位置偏低，观望
                return StrategySignal(
                    action='HOLD', confidence=0.45, position=0.4,
                    reason=f'KDJ低位死叉(K={cur_k:.1f}≤50)，位置偏低，观望',
                    indicators=indicators,
                )

        # ---- J值超买（需拐头确认）----
        if cur_j > 100:
            if cur_j < prev_j:
                return StrategySignal(
                    action='SELL', confidence=0.58, position=0.15,
                    reason=f'J值超买拐头 ({prev_j:.1f}→{cur_j:.1f})',
                    indicators=indicators,
                )
            else:
                return StrategySignal(
                    action='HOLD', confidence=0.4, position=0.6,
                    reason=f'J值超买({cur_j:.1f})但仍上行，强势持有',
                    indicators=indicators,
                )

        return StrategySignal(
            action='HOLD', confidence=0.5, position=0.5,
            reason=f'KDJ无信号, K={cur_k:.1f}, D={cur_d:.1f}, J={cur_j:.1f}',
            indicators=indicators,
        )
