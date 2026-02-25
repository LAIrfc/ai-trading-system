"""
RSI策略（相对强弱指标）

原理:
- RSI < 30 → 超卖区，考虑买入
- RSI > 70 → 超买区，考虑卖出
- RSI从超卖区回升 → 强买入信号（确认离开超卖区）
- RSI从超买区回落 → 强卖出信号（确认离开超买区）
- 仍在超卖/超买区 → 需"拐头"（连续两日反向运动）确认才发信号

参数:
- period:     RSI周期（默认14）    范围[6, 30]
- oversold:   超卖阈值（默认30）   范围[15, 35]
- overbought: 超买阈值（默认70）   范围[65, 85]

min_bars 计算: period + 5  (rolling + 3日回看)
"""

import pandas as pd
from .base import Strategy, StrategySignal


class RSIStrategy(Strategy):

    name = 'RSI'
    description = 'RSI超买超卖信号，拐头确认后触发，避免超卖区频繁开仓'

    param_ranges = {
        'period':     (6, 14, 30, 1),
        'oversold':   (15, 30, 35, 5),
        'overbought': (65, 70, 85, 5),
    }

    def __init__(self, period: int = 14, oversold: float = 30,
                 overbought: float = 70, **kwargs):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.min_bars = period + 5  # rolling(period) + 3日回看

    def _calc_rsi(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(self.period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(self.period).mean()
        rs = gain / loss.replace(0, 1e-10)
        return 100 - (100 / (1 + rs))

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        rsi = self._calc_rsi(df['close'])

        cur_rsi = float(rsi.iloc[-1])
        prev_rsi = float(rsi.iloc[-2])
        prev2_rsi = float(rsi.iloc[-3]) if len(rsi) >= 3 else prev_rsi

        indicators = {'RSI': round(cur_rsi, 2), 'RSI_prev': round(prev_rsi, 2)}

        # 从超卖区回升突破（强买入 — 确认离开超卖区）
        if prev_rsi < self.oversold and cur_rsi >= self.oversold:
            return StrategySignal(
                action='BUY', confidence=0.78, position=0.8,
                reason=f'RSI从超卖区回升突破 ({prev_rsi:.1f}→{cur_rsi:.1f})',
                indicators=indicators,
            )

        # 仍在超卖区：只有"拐头"（RSI连续两日回升）才给低置信度买入
        if cur_rsi < self.oversold:
            if cur_rsi > prev_rsi and prev_rsi > prev2_rsi:
                return StrategySignal(
                    action='BUY', confidence=0.58, position=0.4,
                    reason=f'RSI超卖区拐头确认 ({prev2_rsi:.1f}→{prev_rsi:.1f}→{cur_rsi:.1f})',
                    indicators=indicators,
                )
            else:
                return StrategySignal(
                    action='HOLD', confidence=0.4, position=0.3,
                    reason=f'RSI超卖({cur_rsi:.1f})但未拐头，等待底部确认',
                    indicators=indicators,
                )

        # 从超买区回落突破（强卖出）
        if prev_rsi > self.overbought and cur_rsi <= self.overbought:
            return StrategySignal(
                action='SELL', confidence=0.78, position=0.0,
                reason=f'RSI从超买区回落突破 ({prev_rsi:.1f}→{cur_rsi:.1f})',
                indicators=indicators,
            )

        # 仍在超买区：只有连续下滑才给卖出
        if cur_rsi > self.overbought:
            if cur_rsi < prev_rsi and prev_rsi < prev2_rsi:
                return StrategySignal(
                    action='SELL', confidence=0.58, position=0.2,
                    reason=f'RSI超买区拐头确认 ({prev2_rsi:.1f}→{prev_rsi:.1f}→{cur_rsi:.1f})',
                    indicators=indicators,
                )
            else:
                return StrategySignal(
                    action='HOLD', confidence=0.4, position=0.6,
                    reason=f'RSI超买({cur_rsi:.1f})但未拐头，继续观察',
                    indicators=indicators,
                )

        return StrategySignal(
            action='HOLD', confidence=0.5, position=0.5,
            reason=f'RSI中性区间 ({cur_rsi:.1f})',
            indicators=indicators,
        )
