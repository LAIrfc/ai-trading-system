"""
双核动量策略（个股版本）

原理（从ETF轮动适配到个股）:
1. 绝对动量: 价格 > N日均线 → 趋势向上，适合持有
2. 相对动量: 过去M日涨幅 → 衡量动量强度
3. 如果趋势向上且动量为正 → 买入（仓位随动量增大）
4. 如果价格跌破均线或动量转负 → 卖出

confidence 使用 sigmoid 映射，避免线性溢出:
    conf = base + (cap - base) * tanh(|momentum| / k)

参数:
- abs_period: 绝对动量均线周期（默认60）  范围[20, 200]
- rel_period: 相对动量周期（默认20）      范围[5, 120]

min_bars 计算: abs_period + 5
"""

import math
import pandas as pd
import numpy as np
from .base import Strategy, StrategySignal


class DualMomentumSingleStrategy(Strategy):

    name = '双核动量'
    description = '绝对动量(均线过滤) + 相对动量(涨幅) + sigmoid置信度映射'

    param_ranges = {
        'abs_period': (20, 60, 200, 10),
        'rel_period': (5, 20, 120, 5),
    }

    def __init__(self, abs_period: int = 60, rel_period: int = 20, **kwargs):
        self.abs_period = abs_period
        self.rel_period = rel_period
        self.min_bars = abs_period + 5

    @staticmethod
    def _momentum_to_confidence(momentum_pct: float,
                                base: float = 0.55,
                                cap: float = 0.85) -> float:
        """
        将动量百分比映射到 [base, cap] 的置信度

        使用 sigmoid 风格映射:
            conf = base + (cap - base) * tanh(|m| / k)
        其中 k=10 控制曲线斜率。

        动量 ±5%  → ~0.62
        动量 ±10% → ~0.68
        动量 ±20% → ~0.76
        动量 ±50% → ~0.83
        """
        k = 10.0
        x = abs(momentum_pct)
        sigmoid = (1 - math.exp(-x / k)) / (1 + math.exp(-x / k))
        return round(base + (cap - base) * sigmoid, 2)

    @staticmethod
    def _momentum_to_position(momentum_pct: float, is_buy: bool) -> float:
        """根据动量强度计算建议仓位"""
        if is_buy:
            # 动量越大→仓位越高，范围 [0.4, 0.9]
            return round(min(0.9, 0.4 + abs(momentum_pct) / 50), 2)
        else:
            # 卖出信号→动量越负→仓位越低
            return round(max(0.0, 0.3 - abs(momentum_pct) / 50), 2)

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        close = df['close']

        ma_n = float(close.rolling(self.abs_period).mean().iloc[-1])
        cur_price = float(close.iloc[-1])
        above_ma = cur_price > ma_n

        if len(close) >= self.rel_period:
            past_price = float(close.iloc[-self.rel_period])
            momentum = (cur_price / past_price - 1) * 100
        else:
            momentum = 0.0

        ma5 = close.rolling(5).mean()
        slope = float(ma5.iloc[-1] - ma5.iloc[-3]) if len(ma5) >= 3 else 0.0

        indicators = {
            f'MA{self.abs_period}': round(ma_n, 3),
            '动量%': round(momentum, 2),
            'MA5斜率': round(slope, 3),
            '趋势': '上' if above_ma else '下',
        }

        if above_ma and momentum > 0:
            conf = self._momentum_to_confidence(momentum)
            pos = self._momentum_to_position(momentum, is_buy=True)
            return StrategySignal(
                action='BUY', confidence=conf, position=pos,
                reason=f'双重确认: 价格({cur_price:.2f})在MA{self.abs_period}({ma_n:.2f})上方, '
                       f'{self.rel_period}日动量={momentum:+.2f}%',
                indicators=indicators,
            )

        if not above_ma and momentum < 0:
            conf = self._momentum_to_confidence(momentum)
            pos = self._momentum_to_position(momentum, is_buy=False)
            return StrategySignal(
                action='SELL', confidence=conf, position=pos,
                reason=f'双重预警: 价格({cur_price:.2f})在MA{self.abs_period}({ma_n:.2f})下方, '
                       f'{self.rel_period}日动量={momentum:+.2f}%',
                indicators=indicators,
            )

        if not above_ma and momentum > 0:
            return StrategySignal(
                action='HOLD', confidence=0.45, position=0.3,
                reason=f'信号矛盾: 均线下方但动量转正({momentum:+.2f}%)，等待确认',
                indicators=indicators,
            )

        if above_ma and momentum < 0:
            return StrategySignal(
                action='HOLD', confidence=0.45, position=0.4,
                reason=f'趋势减弱: 均线上方但动量转负({momentum:+.2f}%)，关注回调',
                indicators=indicators,
            )

        return StrategySignal(
            action='HOLD', confidence=0.5, position=0.5,
            reason=f'动量中性, 价格={cur_price:.2f}, MA{self.abs_period}={ma_n:.2f}',
            indicators=indicators,
        )
