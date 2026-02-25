"""
MA均线交叉策略

原理:
- 短期均线上穿长期均线（金叉）→ 买入
- 短期均线下穿长期均线（死叉）→ 卖出
- 价格在均线上方 → 持有

参数:
- short_window: 短期均线周期（默认5日）   范围[3, 20]
- long_window:  长期均线周期（默认20日）  范围[10, 120]
"""

import pandas as pd
from .base import Strategy, StrategySignal


class MACrossStrategy(Strategy):

    name = 'MA均线交叉'
    description = '短期MA上穿/下穿长期MA产生金叉/死叉信号'

    param_ranges = {
        'short_window': (3, 5, 20, 1),
        'long_window':  (10, 20, 120, 5),
    }

    def __init__(self, short_window: int = 5, long_window: int = 20, **kwargs):
        self.short_window = short_window
        self.long_window = long_window
        self.min_bars = max(short_window, long_window) + 3

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        close = df['close']

        ma_short = close.rolling(self.short_window).mean()
        ma_long = close.rolling(self.long_window).mean()

        cur_short = float(ma_short.iloc[-1])
        cur_long = float(ma_long.iloc[-1])
        prev_short = float(ma_short.iloc[-2])
        prev_long = float(ma_long.iloc[-2])

        indicators = {
            f'MA{self.short_window}': round(cur_short, 3),
            f'MA{self.long_window}': round(cur_long, 3),
        }

        # 金叉: 短期均线从下方上穿长期均线
        if prev_short <= prev_long and cur_short > cur_long:
            return StrategySignal(
                action='BUY', confidence=0.72, position=0.8,
                reason=f'金叉: MA{self.short_window}({cur_short:.2f}) '
                       f'上穿 MA{self.long_window}({cur_long:.2f})',
                indicators=indicators,
            )

        # 死叉: 短期均线从上方下穿长期均线
        if prev_short >= prev_long and cur_short < cur_long:
            return StrategySignal(
                action='SELL', confidence=0.72, position=0.0,
                reason=f'死叉: MA{self.short_window}({cur_short:.2f}) '
                       f'下穿 MA{self.long_window}({cur_long:.2f})',
                indicators=indicators,
            )

        # 均线多头排列 → 持有
        if cur_short > cur_long:
            return StrategySignal(
                action='HOLD', confidence=0.5, position=0.6,
                reason=f'均线多头排列, MA{self.short_window}={cur_short:.2f} '
                       f'> MA{self.long_window}={cur_long:.2f}',
                indicators=indicators,
            )

        return StrategySignal(
            action='HOLD', confidence=0.5, position=0.3,
            reason=f'均线空头排列, MA{self.short_window}={cur_short:.2f} '
                   f'< MA{self.long_window}={cur_long:.2f}',
            indicators=indicators,
        )
