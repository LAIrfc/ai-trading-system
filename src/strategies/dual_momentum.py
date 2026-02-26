"""
双核动量策略（个股版本）

原理（从ETF轮动适配到个股）:
1. 绝对动量: 价格 > N日均线 → 趋势向上，适合持有
2. 相对动量: 过去M日涨幅 → 衡量动量强度
3. 如果趋势向上且动量为正 → 买入（仓位随动量增大）
4. 如果价格跌破均线或动量转负 → 卖出

自适应 confidence 映射:
    conf = BASE + (MAX - BASE) * tanh(|momentum| / (expected_mom_std * 2))
    其中 expected_mom_std = daily_return_std * sqrt(rel_period)
    利用 sqrt-time 规则，将日波动率缩放至动量周期的期望标准差。
    高波动股需要更大动量才获得高置信度，低波动股小幅动量即可。

自适应仓位映射:
    BUY:  pos = POS_MIN + norm * (POS_MAX - POS_MIN)
    SELL: pos = max(0, SELL_MAX * (1 - norm))
    norm = min(|momentum| / (expected_mom_std * 2), 1.0)

不引入成交量验证:
    双核动量是多日趋势状态信号（N日均线 + M日涨幅），不是单日事件。
    单日量比添加到多日趋势上会引入时间框架不匹配的噪声。
    同时保持本策略纯价格驱动，为组合策略提供多样性（其他3个策略都用了量比）。

参数:
- abs_period: 绝对动量均线周期（默认60）  范围[20, 200]
- rel_period: 相对动量周期（默认20）      范围[5, 120]

min_bars 计算: max(abs_period, rel_period) + 5
    需要同时满足 MA(abs_period) 和动量回看(rel_period) 的数据要求。
"""

import math
import pandas as pd
import numpy as np
from .base import Strategy, StrategySignal


class DualMomentumSingleStrategy(Strategy):

    name = '双核动量'
    description = '绝对动量(均线过滤) + 相对动量(涨幅) + 自适应sigmoid置信度'

    param_ranges = {
        'abs_period': (20, 60, 200, 10),
        'rel_period': (5, 20, 120, 5),
    }

    # ---- 内部常量（不参与参数优化） ----
    _BASE_CONF    = 0.55    # BUY/SELL 基础置信度
    _MAX_CONF     = 0.85    # 置信度上限
    _BUY_POS_MIN  = 0.40    # BUY 最低仓位
    _BUY_POS_MAX  = 0.90    # BUY 最高仓位
    _SELL_POS_MAX = 0.15    # SELL 时最大保留仓位（弱卖出保留）

    def __init__(self, abs_period: int = 60, rel_period: int = 20, **kwargs):
        self.abs_period = abs_period
        self.rel_period = rel_period
        # 需要同时满足 MA 和动量回看
        self.min_bars = max(abs_period, rel_period) + 5

    def _calc_expected_mom_std(self, close: pd.Series) -> float:
        """
        用 sqrt-time 规则估算动量的期望标准差。

        expected_mom_std = daily_return_std * sqrt(rel_period)

        原理：如果日收益率 std 为 σ_d，则 N 日累计收益率的 std ≈ σ_d * √N。
        例如：日 std=2%, rel_period=20 → expected_mom_std ≈ 2% * √20 ≈ 8.94%

        这意味着对该股票来说，20日涨幅 ±9% 是"正常"波动（1σ），
        18% 是"异常"波动（2σ），应该获得接近满分的置信度/仓位。
        """
        n = max(self.abs_period, 20)

        returns = close.pct_change().replace([np.inf, -np.inf], np.nan)
        if len(returns) > n:
            daily_std = float(returns.iloc[-n:].dropna().std())
            if daily_std > 1e-8:
                return daily_std * math.sqrt(self.rel_period) * 100

        # 降级默认值：假设日 std ≈ 2%（A股平均水平）
        return 2.0 * math.sqrt(self.rel_period)

    def _momentum_to_confidence(self, momentum_pct: float,
                                expected_std: float) -> float:
        """
        将动量百分比映射到 [_BASE_CONF, _MAX_CONF] 的置信度。

        使用自适应 sigmoid 映射:
            conf = BASE + (MAX - BASE) * tanh(|m| / (expected_std * 2))

        2σ 覆盖约 95% 的正常波动。超过 2σ 的动量 → tanh 趋近 1 → conf 趋近 MAX。

        示例（日 std=2%, rel_period=20, expected_std≈8.94%）:
            动量 ±5%  → tanh(0.28) ≈ 0.27 → conf ≈ 0.63
            动量 ±10% → tanh(0.56) ≈ 0.51 → conf ≈ 0.70
            动量 ±20% → tanh(1.12) ≈ 0.81 → conf ≈ 0.79
        """
        scaling = expected_std * 2
        x = abs(momentum_pct) / scaling if scaling > 1e-8 else 0.0
        return round(self._BASE_CONF + (self._MAX_CONF - self._BASE_CONF) * math.tanh(x), 2)

    def _momentum_to_position(self, momentum_pct: float,
                              expected_std: float,
                              is_buy: bool) -> float:
        """
        自适应仓位映射。

        BUY:  pos ∈ [0.40, 0.90]  动量越强 → 仓位越高
        SELL: pos ∈ [0.00, 0.15]  动量越负 → 仓位越低（清仓越坚决）

        归一化: norm = min(|momentum| / (expected_std * 2), 1.0)
        """
        scaling = expected_std * 2
        norm = min(abs(momentum_pct) / scaling, 1.0) if scaling > 1e-8 else 0.0

        if is_buy:
            return round(self._BUY_POS_MIN + norm * (self._BUY_POS_MAX - self._BUY_POS_MIN), 2)
        else:
            # norm→0 (弱卖出): pos → _SELL_POS_MAX (保留一些)
            # norm→1 (强卖出): pos → 0 (完全清仓)
            return round(max(0.0, self._SELL_POS_MAX * (1 - norm)), 2)

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

        expected_std = self._calc_expected_mom_std(close)

        ma5 = close.rolling(5).mean()
        slope = float(ma5.iloc[-1] - ma5.iloc[-3]) if len(ma5) >= 3 else 0.0

        indicators = {
            f'MA{self.abs_period}': round(ma_n, 3),
            '动量%': round(momentum, 2),
            'MA5斜率': round(slope, 3),
            '趋势': '上' if above_ma else '下',
            'expected_mom_std': round(expected_std, 2),
        }

        # ---- 1. 双重确认: 均线上方 + 正动量 → BUY ----
        if above_ma and momentum > 0:
            conf = self._momentum_to_confidence(momentum, expected_std)
            pos = self._momentum_to_position(momentum, expected_std, is_buy=True)
            return StrategySignal(
                action='BUY', confidence=conf, position=pos,
                reason=f'双重确认: 价格({cur_price:.2f})在MA{self.abs_period}({ma_n:.2f})上方, '
                       f'{self.rel_period}日动量={momentum:+.2f}%',
                indicators=indicators,
            )

        # ---- 2. 双重预警: 均线下方 + 负动量 → SELL ----
        if not above_ma and momentum < 0:
            conf = self._momentum_to_confidence(momentum, expected_std)
            pos = self._momentum_to_position(momentum, expected_std, is_buy=False)
            return StrategySignal(
                action='SELL', confidence=conf, position=pos,
                reason=f'双重预警: 价格({cur_price:.2f})在MA{self.abs_period}({ma_n:.2f})下方, '
                       f'{self.rel_period}日动量={momentum:+.2f}%',
                indicators=indicators,
            )

        # ---- 3. 矛盾信号: 均线下方但动量转正 ----
        #  动量越强 → 仓位越高（回升力度越大，乐观度越高）
        #  pos ∈ [0.20, 0.40]
        if not above_ma and momentum > 0:
            scaling = expected_std * 2
            norm = min(abs(momentum) / scaling, 1.0) if scaling > 1e-8 else 0.0
            position = round(0.20 + norm * 0.20, 2)
            return StrategySignal(
                action='HOLD', confidence=0.45, position=position,
                reason=f'信号矛盾: 均线下方但动量转正({momentum:+.2f}%)，等待确认',
                indicators=indicators,
            )

        # ---- 4. 趋势减弱: 均线上方但动量转负 ----
        #  动量越负 → 仓位越低（减弱程度越大，防御越强）
        #  pos ∈ [0.30, 0.50]
        if above_ma and momentum < 0:
            scaling = expected_std * 2
            norm = min(abs(momentum) / scaling, 1.0) if scaling > 1e-8 else 0.0
            position = round(0.50 - norm * 0.20, 2)
            return StrategySignal(
                action='HOLD', confidence=0.45, position=position,
                reason=f'趋势减弱: 均线上方但动量转负({momentum:+.2f}%)，关注回调',
                indicators=indicators,
            )

        return StrategySignal(
            action='HOLD', confidence=0.5, position=0.5,
            reason=f'动量中性, 价格={cur_price:.2f}, MA{self.abs_period}={ma_n:.2f}',
            indicators=indicators,
        )
