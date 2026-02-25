"""
MACD策略

原理:
- MACD线(DIF)上穿信号线(DEA) → 买入信号（金叉）
- MACD线(DIF)下穿信号线(DEA) → 卖出信号（死叉）
- 零轴上方金叉信号更强

参数:
- fast_period:   快速EMA周期（默认12）  范围[5, 20]
- slow_period:   慢速EMA周期（默认26）  范围[20, 60]
- signal_period: 信号线周期（默认9）    范围[5, 15]

min_bars 计算: max(fast, slow) + signal + 5
    EMA 需要至少 2*span 条数据才能稳定，这里取 max(fast,slow) + signal + 余量
"""

import pandas as pd
from .base import Strategy, StrategySignal


class MACDStrategy(Strategy):

    name = 'MACD'
    description = 'MACD金叉/死叉信号，零轴上方金叉为强势买入'

    param_ranges = {
        'fast_period':   (5, 12, 20, 1),
        'slow_period':   (20, 26, 60, 2),
        'signal_period': (5, 9, 15, 1),
    }

    def __init__(self, fast_period: int = 12, slow_period: int = 26,
                 signal_period: int = 9, **kwargs):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        # EMA需要足够多的数据来收敛，取 max(fast,slow)+signal+余量
        self.min_bars = max(fast_period, slow_period) + signal_period + 5

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        close = df['close']

        ema_fast = close.ewm(span=self.fast_period, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow_period, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=self.signal_period, adjust=False).mean()
        macd_hist = (dif - dea) * 2  # 柱状图

        cur_dif = float(dif.iloc[-1])
        cur_dea = float(dea.iloc[-1])
        cur_hist = float(macd_hist.iloc[-1])
        prev_dif = float(dif.iloc[-2])
        prev_dea = float(dea.iloc[-2])
        prev_hist = float(macd_hist.iloc[-2])

        indicators = {
            'DIF': round(cur_dif, 4),
            'DEA': round(cur_dea, 4),
            'MACD柱': round(cur_hist, 4),
        }

        # 金叉
        if prev_dif <= prev_dea and cur_dif > cur_dea:
            above_zero = cur_dif > 0
            conf = 0.78 if above_zero else 0.62
            pos = 0.85 if above_zero else 0.7
            return StrategySignal(
                action='BUY', confidence=conf, position=pos,
                reason=f'MACD金叉{"(零轴上方,强势)" if above_zero else ""}: '
                       f'DIF={cur_dif:.4f} 上穿 DEA={cur_dea:.4f}',
                indicators=indicators,
            )

        # 死叉
        if prev_dif >= prev_dea and cur_dif < cur_dea:
            return StrategySignal(
                action='SELL', confidence=0.72, position=0.0,
                reason=f'MACD死叉: DIF={cur_dif:.4f} 下穿 DEA={cur_dea:.4f}',
                indicators=indicators,
            )

        # 柱状图由负转正（辅助买入信号）
        if prev_hist < 0 and cur_hist > 0:
            return StrategySignal(
                action='BUY', confidence=0.55, position=0.5,
                reason=f'MACD柱状图转正({prev_hist:.4f}→{cur_hist:.4f})',
                indicators=indicators,
            )

        # 柱状图由正转负（辅助卖出信号）
        if prev_hist > 0 and cur_hist < 0:
            return StrategySignal(
                action='SELL', confidence=0.55, position=0.2,
                reason=f'MACD柱状图转负({prev_hist:.4f}→{cur_hist:.4f})',
                indicators=indicators,
            )

        return StrategySignal(
            action='HOLD', confidence=0.5, position=0.5,
            reason=f'MACD无交叉信号, DIF={cur_dif:.4f}, DEA={cur_dea:.4f}',
            indicators=indicators,
        )
