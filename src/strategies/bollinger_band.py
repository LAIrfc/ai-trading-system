"""
布林带策略 (Bollinger Bands)

原理:
- 价格触及下轨 → 超卖，需拐头确认后买入
- 价格触及上轨 → 超买，需拐头确认后卖出
- 价格从下轨向中轨回归 → 确认买入
- 价格在轨外未拐头 → HOLD（避免连续触发信号）

参数:
- period:  中轨均线周期（默认20）  范围[10, 40]
- std_dev: 标准差倍数（默认2.0）  范围[1.5, 3.0]

min_bars 计算: period + 5  (rolling(period) + 3日回看)
"""

import pandas as pd
import numpy as np
from .base import Strategy, StrategySignal


class BollingerBandStrategy(Strategy):

    name = '布林带'
    description = '价格触及上下轨+拐头确认产生信号，避免连续触发'

    param_ranges = {
        'period':  (10, 20, 40, 2),
        'std_dev': (1.5, 2.0, 3.0, 0.25),
    }

    def __init__(self, period: int = 20, std_dev: float = 2.0, **kwargs):
        self.period = period
        self.std_dev = std_dev
        self.min_bars = period + 5

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        close = df['close']

        mid = close.rolling(self.period).mean()
        std = close.rolling(self.period).std()
        upper = mid + self.std_dev * std
        lower = mid - self.std_dev * std

        cur_close = float(close.iloc[-1])
        prev_close = float(close.iloc[-2])
        prev2_close = float(close.iloc[-3]) if len(close) >= 3 else prev_close
        cur_mid = float(mid.iloc[-1])
        cur_upper = float(upper.iloc[-1])
        cur_lower = float(lower.iloc[-1])
        prev_upper = float(upper.iloc[-2])
        prev_lower = float(lower.iloc[-2])

        band_width = cur_upper - cur_lower
        pct_b = (cur_close - cur_lower) / band_width if band_width > 0 else 0.5
        bandwidth_pct = band_width / cur_mid * 100 if cur_mid > 0 else 0

        indicators = {
            '上轨': round(cur_upper, 3),
            '中轨': round(cur_mid, 3),
            '下轨': round(cur_lower, 3),
            '%B': round(pct_b, 3),
            '带宽%': round(bandwidth_pct, 2),
        }

        # 价格从下方突破下轨后回升（确认买入）
        if prev_close <= prev_lower and cur_close > cur_lower:
            return StrategySignal(
                action='BUY', confidence=0.75, position=0.75,
                reason=f'价格从下轨下方回升, %B={pct_b:.2f}',
                indicators=indicators,
            )

        # 价格在下轨下方：区分"拐头回升"与"持续下跌"
        if cur_close < cur_lower:
            if cur_close > prev_close and prev_close > prev2_close:
                return StrategySignal(
                    action='BUY', confidence=0.55, position=0.35,
                    reason=f'下轨下方拐头回升({prev2_close:.2f}→{prev_close:.2f}→{cur_close:.2f})',
                    indicators=indicators,
                )
            else:
                return StrategySignal(
                    action='HOLD', confidence=0.4, position=0.2,
                    reason=f'价格在下轨下方({cur_close:.2f}<{cur_lower:.2f})但未拐头，等待确认',
                    indicators=indicators,
                )

        # 价格从上方跌破上轨（确认卖出）
        if prev_close >= prev_upper and cur_close < cur_upper:
            return StrategySignal(
                action='SELL', confidence=0.75, position=0.0,
                reason=f'价格从上轨回落, %B={pct_b:.2f}',
                indicators=indicators,
            )

        # 价格在上轨上方：区分"拐头回落"与"持续上涨"
        if cur_close > cur_upper:
            if cur_close < prev_close and prev_close < prev2_close:
                return StrategySignal(
                    action='SELL', confidence=0.55, position=0.2,
                    reason=f'上轨上方拐头回落({prev2_close:.2f}→{prev_close:.2f}→{cur_close:.2f})',
                    indicators=indicators,
                )
            else:
                return StrategySignal(
                    action='HOLD', confidence=0.4, position=0.7,
                    reason=f'价格突破上轨({cur_close:.2f}>{cur_upper:.2f})且未拐头，强势持有',
                    indicators=indicators,
                )

        return StrategySignal(
            action='HOLD', confidence=0.5, position=0.5,
            reason=f'价格在布林带内, %B={pct_b:.2f}, 带宽={bandwidth_pct:.1f}%',
            indicators=indicators,
        )
