"""
MACD策略

原理:
- MACD线(DIF)上穿信号线(DEA) → 买入信号（金叉）
- MACD线(DIF)下穿信号线(DEA) → 卖出信号（死叉）
- DIF > DEA 无交叉            → 多头动能持有
- DIF < DEA 无交叉            → 空头动能持有

信号强度动态化:
- DIF斜率:   DIF 的日绝对变化量（diff()，非 pct_change()，因 DIF 会穿零）
- 成交量:    当日成交量 / 20日均量 → 放量验证
- 零轴位置:  DIF > 0 时金叉基础置信度上浮 _ABOVE_ZERO_BONUS（二值，不连续化）

置信度计算:
  conf = (BASE + 零轴加成) + combined_factor * (MAX - BASE - 零轴加成)
  combined_factor ∈ [0, 1], 由 DIF 斜率 + 量比加权合成
  严格落在 [BASE, MAX] 区间

DIF 斜率归一化（自适应）:
  使用过去 _SLOPE_LOOKBACK(60) 日 DIF 的 diff() 标准差作为基准
  norm_slope = min(abs(dif_slope) / (slope_std * 2), 1.0)
  注意：DIF 会穿越零轴，不能用 pct_change()（除零风险），必须用 diff()

HOLD 仓位（动态）:
  DIF > DEA 时（多头动能）：用 |DIF - DEA| 的自适应归一化驱动仓位
    gap_threshold = gap_std * 2, norm_gap = min(|gap| / gap_threshold, 1.0)
    position ∈ [_BULL_POS_MIN, _BULL_POS_MAX]
  DIF < DEA 时（空头动能）：同理
    position ∈ [_BEAR_POS_MIN, _BEAR_POS_MAX]
  gap_std 为过去 60 日 DIF-DEA 间距的标准差，自适应不同股票的波动特性

死叉仓位（平滑）:
  position = max(0, _SELL_POS_MAX * (1 - factor))
  缩量弱死叉保留少量仓位，放量强死叉趋近清仓

仓位层级保证:
  BUY position  ∈ [0.70, 0.95]  — 金叉信号
  HOLD bull pos ∈ [0.40, 0.65]  — 多头动能（上限 < BUY 下限，消除悖论）
  HOLD bear pos ∈ [0.05, 0.25]  — 空头动能
  SELL position ∈ [0.0,  0.12]  — 死叉（随 factor 平滑衰减）

关于柱状图辅助信号（已移除）:
  旧版有 "柱状图由负转正→BUY" 和 "由正转负→SELL" 的辅助信号。
  但 hist = (DIF - DEA) * 2，所以 hist 变号 ⟺ DIF 穿越 DEA，
  即金叉/死叉条件的严格子集。这些辅助信号是死代码（永远被金叉/死叉
  先拦截），已替换为有意义的 HOLD 信号（多头/空头动能）。

参数:
- fast_period:   快速EMA周期（默认12）  范围[5, 20]
- slow_period:   慢速EMA周期（默认26）  范围[20, 60]
- signal_period: 信号线周期（默认9）    范围[5, 15]

仅 fast_period / slow_period / signal_period 参与参数优化。
以下内部常量为经验值，固定不参与网格搜索，避免过拟合:
  _BASE_CONF, _MAX_CONF, _ABOVE_ZERO_BONUS, _SLOPE_W, _VOL_W 等
"""

import numpy as np
import pandas as pd
from .base import Strategy, StrategySignal


class MACDStrategy(Strategy):

    name = 'MACD'
    description = 'MACD金叉/死叉信号，DIF斜率+量比动态置信度'

    param_ranges = {
        'fast_period':   (5, 12, 20, 1),
        'slow_period':   (20, 26, 60, 2),
        'signal_period': (5, 9, 15, 1),
    }

    # ---- 内部常量（不参与参数优化） ----
    _BASE_CONF = 0.65           # 裸金叉/死叉基础置信度
    _MAX_CONF  = 0.90           # 置信度上限
    _ABOVE_ZERO_BONUS = 0.05    # 零轴上方金叉时 base 上浮
    _SLOPE_W   = 0.6            # DIF斜率因子权重
    _VOL_W     = 0.4            # 量比因子权重
    _VOL_MA    = 20             # 成交量基准均线天数
    _SLOPE_LOOKBACK = 60        # DIF斜率/gap标准差回看天数
    _SELL_POS_MAX   = 0.12      # 死叉时最大保留仓位（缩量弱死叉）

    # 仓位范围 — 保证 BUY_min > HOLD_bull_max，消除层级悖论
    _BUY_POS_MIN  = 0.70        # 金叉最低仓位
    _BUY_POS_MAX  = 0.95        # 金叉最高仓位
    _BULL_POS_MIN = 0.40        # 多头动能最低仓位
    _BULL_POS_MAX = 0.65        # 多头动能最高仓位（< _BUY_POS_MIN）
    _BEAR_POS_MIN = 0.05        # 空头动能最低仓位（强空头）
    _BEAR_POS_MAX = 0.25        # 空头动能最高仓位（弱空头）

    def __init__(self, fast_period: int = 12, slow_period: int = 26,
                 signal_period: int = 9, **kwargs):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        # min_bars 拆解:
        #   max(fast, slow)   → EMA 基本收敛
        #   + _SLOPE_LOOKBACK → 需要 60 个稳定的 DIF 值算斜率 std
        #   + 5               → 余量
        #   signal_period(9) << _SLOPE_LOOKBACK(60)，被后者覆盖
        self.min_bars = max(fast_period, slow_period) + self._SLOPE_LOOKBACK + 5

    def _calc_dynamics(self, df: pd.DataFrame,
                       dif: pd.Series, dea: pd.Series) -> dict:
        """
        计算动态因子:
        - dif_slope:  DIF 日绝对变化量（diff()，非 pct_change()，因 DIF 穿零）
        - slope_std:  过去 _SLOPE_LOOKBACK 日 DIF diff 的标准差（自适应归一化）
        - gap_std:    过去 _SLOPE_LOOKBACK 日 |DIF-DEA| 的标准差（HOLD 仓位归一化）
        - vol_ratio:  当日成交量 / 20日均量
        """
        dif_slope = float(dif.iloc[-1] - dif.iloc[-2])

        n = self._SLOPE_LOOKBACK

        # DIF 斜率标准差: 用 diff() 而非 pct_change()
        # DIF 可正可负可为零，pct_change 会产生 inf / 除零
        slope_std = 0.01  # 降级默认值
        dif_diffs = dif.diff().replace([np.inf, -np.inf], np.nan)
        if len(dif_diffs) > n:
            recent_std = float(dif_diffs.iloc[-n:].dropna().std())
            if recent_std > 1e-8:
                slope_std = recent_std

        # DIF-DEA 间距标准差: 用于 HOLD 仓位的自适应归一化
        # gap = DIF - DEA = hist/2，反映动能强度
        gap_std = 0.1  # 降级默认值
        gap_series = (dif - dea).replace([np.inf, -np.inf], np.nan)
        if len(gap_series) > n:
            recent_gap_std = float(gap_series.iloc[-n:].dropna().std())
            if recent_gap_std > 1e-8:
                gap_std = recent_gap_std

        # 成交量比: 当日量 / 20日均量（不含当日，更稳健）
        vol_ratio = 1.0
        if 'volume' in df.columns:
            vol = df['volume']
            vm = self._VOL_MA
            if len(vol) > vm:
                avg_vol = float(vol.iloc[-(vm + 1):-1].mean())
                cur_vol = float(vol.iloc[-1])
                vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 1.0

        return {
            'dif_slope': dif_slope, 'slope_std': slope_std,
            'gap_std': gap_std, 'vol_ratio': vol_ratio,
        }

    def _combined_factor(self, dif_slope: float, slope_std: float,
                         vol_ratio: float) -> float:
        """
        将 DIF 斜率和量比归一化为 [0, 1] 的综合因子。

        DIF 斜率归一化（自适应）:
          用过去 60 日 DIF.diff() 的 2σ 作为"满分"基准
          norm_slope = min(abs(dif_slope) / (slope_std * 2), 1.0)
          注意: DIF 穿零，必须用 diff() 的绝对值，不能用 pct_change()

        量比归一化:
          (vol_ratio - 0.5) / 2.5 映射后 clamp 到 [0,1]
        """
        threshold = max(slope_std * 2, 1e-6)
        norm_slope = min(abs(dif_slope) / threshold, 1.0)

        norm_vol = max(0.0, min((vol_ratio - 0.5) / 2.5, 1.0))

        # 加权合成，权重之和为 1，输出 ∈ [0, 1]
        return self._SLOPE_W * norm_slope + self._VOL_W * norm_vol

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        close = df['close']

        ema_fast = close.ewm(span=self.fast_period, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow_period, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=self.signal_period, adjust=False).mean()
        macd_hist = (dif - dea) * 2

        cur_dif = float(dif.iloc[-1])
        cur_dea = float(dea.iloc[-1])
        cur_hist = float(macd_hist.iloc[-1])
        prev_dif = float(dif.iloc[-2])
        prev_dea = float(dea.iloc[-2])

        dyn = self._calc_dynamics(df, dif, dea)
        dif_slope = dyn['dif_slope']
        slope_std = dyn['slope_std']
        gap_std = dyn['gap_std']
        vol_ratio = dyn['vol_ratio']

        indicators = {
            'DIF': round(cur_dif, 4),
            'DEA': round(cur_dea, 4),
            'MACD柱': round(cur_hist, 4),
            'DIF_slope': round(dif_slope, 6),
            'slope_std': round(slope_std, 6),
            'gap_std': round(gap_std, 6),
            'vol_ratio': round(vol_ratio, 2),
        }

        # ---- 金叉: DIF 从下方上穿 DEA ----
        #  DIF 斜率越陡 + 量比越大 → factor 越高 → 置信度和仓位越高
        #  零轴上方金叉: base 上浮 _ABOVE_ZERO_BONUS（趋势延续确认）
        if prev_dif <= prev_dea and cur_dif > cur_dea:
            factor = self._combined_factor(dif_slope, slope_std, vol_ratio)
            above_zero = cur_dif > 0
            base = self._BASE_CONF + (self._ABOVE_ZERO_BONUS if above_zero else 0)
            confidence = base + factor * (self._MAX_CONF - base)
            position = self._BUY_POS_MIN + factor * (self._BUY_POS_MAX - self._BUY_POS_MIN)

            vol_desc = f', 量比{vol_ratio:.1f}' if vol_ratio > 1.2 else ''
            zero_desc = '(零轴上方,强势)' if above_zero else ''
            return StrategySignal(
                action='BUY', confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f'MACD金叉{zero_desc}: '
                       f'DIF={cur_dif:.4f} 上穿 DEA={cur_dea:.4f}'
                       f'{vol_desc}',
                indicators=indicators,
            )

        # ---- 死叉: DIF 从上方下穿 DEA ----
        #  放量陡峭死叉 → factor 高 → 更坚决卖出（conf 高, pos 低）
        #  缩量平缓死叉 → factor 低 → 保留少量仓位
        if prev_dif >= prev_dea and cur_dif < cur_dea:
            factor = self._combined_factor(dif_slope, slope_std, vol_ratio)
            confidence = self._BASE_CONF + factor * (self._MAX_CONF - self._BASE_CONF)

            # 仓位随 factor 平滑衰减:
            #   factor→0: position ≈ _SELL_POS_MAX (0.12)
            #   factor→1: position → 0
            position = round(max(0, self._SELL_POS_MAX * (1 - factor)), 2)

            vol_desc = f', 量比{vol_ratio:.1f}' if vol_ratio > 1.2 else ''
            return StrategySignal(
                action='SELL', confidence=round(confidence, 2),
                position=position,
                reason=f'MACD死叉: '
                       f'DIF={cur_dif:.4f} 下穿 DEA={cur_dea:.4f}'
                       f'{vol_desc}',
                indicators=indicators,
            )

        # ---- 多头动能: DIF > DEA，无交叉 ----
        #  仓位随 DIF-DEA 间距动态调整（自适应归一化）
        #  间距越大（动能越强） → 仓位越高
        #  上限 0.65 < 金叉最低 0.70，保证层级：BUY > HOLD_bull
        if cur_dif > cur_dea:
            cur_gap = abs(cur_dif - cur_dea)
            gap_threshold = max(gap_std * 2, 1e-6)
            norm_gap = min(cur_gap / gap_threshold, 1.0)
            position = self._BULL_POS_MIN + norm_gap * (self._BULL_POS_MAX - self._BULL_POS_MIN)

            return StrategySignal(
                action='HOLD', confidence=0.5,
                position=round(position, 2),
                reason=f'DIF>DEA 多头动能, '
                       f'DIF={cur_dif:.4f}, DEA={cur_dea:.4f}, '
                       f'柱={cur_hist:.4f}',
                indicators=indicators,
            )

        # ---- 空头动能: DIF < DEA ----
        #  间距越大（空头越强） → 仓位越低
        #  范围 [BEAR_MIN=0.05, BEAR_MAX=0.25]
        cur_gap = abs(cur_dif - cur_dea)
        gap_threshold = max(gap_std * 2, 1e-6)
        norm_gap = min(cur_gap / gap_threshold, 1.0)
        position = self._BEAR_POS_MAX - norm_gap * (self._BEAR_POS_MAX - self._BEAR_POS_MIN)

        return StrategySignal(
            action='HOLD', confidence=0.5,
            position=round(position, 2),
            reason=f'DIF<DEA 空头动能, '
                   f'DIF={cur_dif:.4f}, DEA={cur_dea:.4f}, '
                   f'柱={cur_hist:.4f}',
            indicators=indicators,
        )
