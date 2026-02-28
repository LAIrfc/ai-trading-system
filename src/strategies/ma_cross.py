"""
MA均线交叉策略

原理:
- 短期均线上穿长期均线（金叉）→ 买入
- 短期均线下穿长期均线（死叉）→ 卖出
- 均线多头/空头排列       → 持有（仓位随乖离率动态调整）

信号强度动态化:
- 均线斜率:  短期均线日变化率越大 → 趋势越强
- 乖离率:    (MA_short - MA_long) / MA_long → 偏离越大趋势越强
- 成交量:    当日成交量 / 20日均量 → 放量验证（用 20 日均量而非 5 日，
             避免节假日或异常日导致基准偏移）

乖离率归一化（自适应）:
  使用该股票自身过去 _SLOPE_LOOKBACK(60) 日的乖离率标准差作为归一化基准，
  而非固定阈值 0.05。这样低波动蓝筹（乖离通常 <2%）和高波动小盘股（乖离
  经常 >5%）都能获得充分的区分度，与斜率处理对称。
  公式: norm_bias = min(abs(bias) / (bias_std * 2), 1.0)
  不增加任何可调参数，复用已有的 _SLOPE_LOOKBACK 回看窗口。

置信度计算:
  采用归一化公式: conf = BASE + combined_factor * (MAX - BASE)
  其中 combined_factor ∈ [0, 1]，由斜率、量比加权合成。
  保证输出严格落在 [BASE_CONF, MAX_CONF] 区间，不依赖 min() 截断。

斜率归一化（自适应）:
  使用该股票自身过去 _SLOPE_LOOKBACK(60) 日的均线斜率标准差作为归一化基准，
  而非固定阈值 0.02。这样低波动蓝筹（日均斜率 0.1%）和高波动小盘股（1-3%）
  都能获得充分的区分度，实现自适应。
  公式: norm_slope = min(abs(slope) / (slope_std * 2), 1.0)

死叉仓位:
  死叉后仓位随 factor 平滑衰减，而非硬阈值二值决策:
  position = max(0, _SELL_POS_MAX * (1 - factor))
  缩量弱死叉（factor 小）→ 保留少量仓位 ~12%
  放量强死叉（factor 大）→ 仓位趋近 0

仓位层级保证:
  BUY position  ∈ [0.75, 0.95]  — 金叉信号
  HOLD bull pos ∈ [0.45, 0.70]  — 多头排列（上限 < BUY 下限，消除悖论）
  HOLD bear pos ∈ [0.05, 0.25]  — 空头排列（弱空头 0.25, 强空头 0.05）
  SELL position ∈ [0.0,  0.12]  — 死叉（随 factor 平滑衰减）

参数:
- short_window: 短期均线周期（默认5日）   范围[3, 20]
- long_window:  长期均线周期（默认20日）  范围[10, 120]

仅 short_window / long_window 参与参数优化。
以下内部常量为经验值，固定不参与网格搜索，避免过拟合:
  _BASE_CONF, _MAX_CONF, _SLOPE_W, _VOL_W 等
"""

import numpy as np
import pandas as pd
from .base import Strategy, StrategySignal
from .turnover_helper import (
    calc_relative_turnover_rate,
    check_turnover_liquidity,
    enhance_signal_with_turnover
)


class MACrossStrategy(Strategy):

    name = 'MA均线交叉'
    description = '短期MA上穿/下穿长期MA产生金叉/死叉信号，动态置信度'

    param_ranges = {
        'short_window': (3, 5, 20, 1),
        'long_window':  (10, 20, 120, 5),
    }

    # ---- 内部常量（不参与参数优化） ----
    _BASE_CONF = 0.65        # 裸金叉/死叉基础置信度
    _MAX_CONF  = 0.90        # 置信度上限
    _SLOPE_W   = 0.6         # 斜率因子权重（占增量部分）
    _VOL_W     = 0.4         # 量比因子权重（占增量部分）
    _VOL_MA    = 20          # 成交量基准均线天数
    _SLOPE_LOOKBACK = 60    # 斜率标准差回看天数（用于自适应归一化）
    _SELL_POS_MAX   = 0.12  # 死叉时最大保留仓位（缩量弱死叉，factor→0 时）

    # 仓位范围 — 保证 BUY_min > HOLD_bull_max，消除层级悖论
    _BUY_POS_MIN  = 0.75     # 金叉最低仓位
    _BUY_POS_MAX  = 0.95     # 金叉最高仓位
    _BULL_POS_MIN = 0.45     # 多头排列最低仓位
    _BULL_POS_MAX = 0.70     # 多头排列最高仓位（< _BUY_POS_MIN）
    _BEAR_POS_MIN = 0.05     # 空头排列最低仓位（强空头）
    _BEAR_POS_MAX = 0.25     # 空头排列最高仓位（弱空头）

    def __init__(self, short_window: int = 5, long_window: int = 20, **kwargs):
        self.short_window = short_window
        self.long_window = long_window
        # min_bars 拆解:
        #   max(short_window, long_window)  → 第一个有效 MA 值
        #   + _SLOPE_LOOKBACK               → 需要连续 60 个有效斜率算 std
        #   + 5                             → 余量（拐头判断等）
        # VOL_MA(20) < _SLOPE_LOOKBACK(60)，被后者覆盖
        ma_warmup = max(short_window, long_window)
        self.min_bars = ma_warmup + self._SLOPE_LOOKBACK + 5

    def _calc_dynamics(self, df: pd.DataFrame,
                       ma_short: pd.Series, ma_long: pd.Series) -> dict:
        """
        计算动态因子:
        - slope:      短期均线日变化率 (正=上行, 负=下行)
        - slope_std:  过去 _SLOPE_LOOKBACK 日斜率的标准差（用于自适应归一化）
        - bias:       乖离率 (MA_short - MA_long) / MA_long
        - bias_std:   过去 _SLOPE_LOOKBACK 日乖离率的标准差（用于自适应归一化）
        - vol_ratio:  当日成交量 / 20日均量 (>1 放量, <1 缩量)
        """
        cur_short = float(ma_short.iloc[-1])
        prev_short = float(ma_short.iloc[-2])
        cur_long = float(ma_long.iloc[-1])

        slope = (cur_short - prev_short) / prev_short if prev_short != 0 else 0
        bias = (cur_short - cur_long) / cur_long if cur_long != 0 else 0

        n = self._SLOPE_LOOKBACK

        # 斜率标准差: 过去 N 日均线日变化率的 std，作为自适应归一化基准
        # 这样低波动蓝筹和高波动小盘股都能获得充分的区分度
        slope_std = 0.01  # 降级默认值（如果数据不足）
        slopes = ma_short.pct_change().replace([np.inf, -np.inf], np.nan)
        if len(slopes) > n:
            recent_std = float(slopes.iloc[-n:].dropna().std())
            if recent_std > 1e-8:  # 避免除零（如停牌股）
                slope_std = recent_std

        # 乖离率标准差: 过去 N 日乖离率的 std，作为自适应归一化基准
        # 与斜率处理对称：低波动蓝筹（乖离 std ~0.5%）和高波动小盘股（std ~3%）
        # 都能获得充分的区分度，不再依赖固定 5% 阈值
        bias_std = 0.025  # 降级默认值（5% / 2 = 2.5%，保持与旧行为兼容）
        bias_series = ((ma_short - ma_long) / ma_long).replace(
            [np.inf, -np.inf], np.nan
        )
        if len(bias_series) > n:
            recent_bias_std = float(bias_series.iloc[-n:].dropna().std())
            if recent_bias_std > 1e-8:  # 避免除零（如停牌股）
                bias_std = recent_bias_std

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
            'slope': slope, 'slope_std': slope_std,
            'bias': bias, 'bias_std': bias_std,
            'vol_ratio': vol_ratio,
        }

    def _combined_factor(self, slope: float, slope_std: float,
                         vol_ratio: float) -> float:
        """
        将斜率和量比归一化为 [0, 1] 的综合因子。

        斜率归一化（自适应）:
          用该股票自身过去 60 日均线斜率的 2 倍标准差作为"满分"基准。
          norm_slope = min(abs(slope) / (slope_std * 2), 1.0)
          2σ 覆盖约 95% 的日常波动，超过 2σ 即视为异常强趋势。

        量比归一化:
          vol_ratio 通常 0.5~3.0，
          (vol_ratio - 0.5) / 2.5 映射后 clamp 到 [0,1]
          截断合理：量比超过 3 后对趋势确认的边际信息递减。
        """
        # 自适应斜率归一化: 以 2σ 为满分基准
        threshold = max(slope_std * 2, 1e-6)
        norm_slope = min(abs(slope) / threshold, 1.0)

        norm_vol = max(0.0, min((vol_ratio - 0.5) / 2.5, 1.0))

        # 加权合成，权重之和为 1，输出 ∈ [0, 1]
        return self._SLOPE_W * norm_slope + self._VOL_W * norm_vol

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        close = df['close']

        ma_short = close.rolling(self.short_window).mean()
        ma_long = close.rolling(self.long_window).mean()

        cur_short = float(ma_short.iloc[-1])
        cur_long = float(ma_long.iloc[-1])
        prev_short = float(ma_short.iloc[-2])
        prev_long = float(ma_long.iloc[-2])

        dyn = self._calc_dynamics(df, ma_short, ma_long)
        slope = dyn['slope']
        slope_std = dyn['slope_std']
        bias = dyn['bias']
        bias_std = dyn['bias_std']
        vol_ratio = dyn['vol_ratio']
        
        # 实盘标准：计算相对换手率（当前换手率/20日均换手率）
        relative_turnover = calc_relative_turnover_rate(df, ma_period=20)

        indicators = {
            f'MA{self.short_window}': round(cur_short, 3),
            f'MA{self.long_window}': round(cur_long, 3),
            'slope_pct': round(slope * 100, 3),
            'slope_std_pct': round(slope_std * 100, 3),
            'bias_pct': round(bias * 100, 3),
            'bias_std_pct': round(bias_std * 100, 3),
            'vol_ratio': round(vol_ratio, 2),
            'relative_turnover': round(relative_turnover, 2) if relative_turnover else None,
        }

        # ---- 金叉: 短期均线从下方上穿长期均线 ----
        if prev_short <= prev_long and cur_short > cur_long:
            # 实盘标准：流动性过滤
            is_valid, liquidity_reason = check_turnover_liquidity(relative_turnover)
            if not is_valid:
                # 流动性异常，回避交易
                return StrategySignal(
                    action='HOLD', confidence=0.3, position=0.5,
                    reason=f'金叉但{liquidity_reason}，回避交易',
                    indicators=indicators,
                )
            
            factor = self._combined_factor(slope, slope_std, vol_ratio)
            # 归一化置信度: 严格 ∈ [BASE, MAX]
            base_confidence = self._BASE_CONF + factor * (self._MAX_CONF - self._BASE_CONF)
            # 仓位: 同样用 factor 插值
            base_position = self._BUY_POS_MIN + factor * (self._BUY_POS_MAX - self._BUY_POS_MIN)
            
            # 实盘标准：突破时要求相对换手率>1.2倍（确认有效突破）
            confidence, position, turnover_reason = enhance_signal_with_turnover(
                'breakout', relative_turnover, base_confidence, base_position
            )

            vol_desc = f', 量比{vol_ratio:.1f}' if vol_ratio > 1.2 else ''
            turnover_desc = f', {turnover_reason}' if turnover_reason else ''
            return StrategySignal(
                action='BUY', confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f'金叉: MA{self.short_window}({cur_short:.2f}) '
                       f'上穿 MA{self.long_window}({cur_long:.2f})'
                       f'{vol_desc}{turnover_desc}',
                indicators=indicators,
            )

        # ---- 死叉: 短期均线从上方下穿长期均线 ----
        #  放量死叉 → 空方确认 → 更坚决卖出（factor 高 → conf 高, pos 低）
        #  缩量死叉 → 可能假死叉 → 降低置信度，保留少量仓位
        if prev_short >= prev_long and cur_short < cur_long:
            # 实盘标准：流动性过滤（死叉时也检查，但更宽松）
            is_valid, liquidity_reason = check_turnover_liquidity(relative_turnover)
            # 死叉时，如果流动性异常，仍然执行卖出，但降低置信度
            liquidity_penalty = 0.0 if is_valid else 0.1
            
            factor = self._combined_factor(slope, slope_std, vol_ratio)
            base_confidence = self._BASE_CONF + factor * (self._MAX_CONF - self._BASE_CONF)
            base_confidence = max(0.0, base_confidence - liquidity_penalty)

            # 仓位随 factor 平滑衰减:
            #   factor→0 (缩量弱死叉): position ≈ _SELL_POS_MAX (0.12)
            #   factor→1 (放量强死叉): position → 0
            base_position = max(0, self._SELL_POS_MAX * (1 - factor))
            
            # 实盘标准：回调时要求<0.8倍（确认缩量回调，而非资金出逃）
            confidence, position, turnover_reason = enhance_signal_with_turnover(
                'pullback', relative_turnover, base_confidence, base_position
            )

            vol_desc = f', 量比{vol_ratio:.1f}' if vol_ratio > 1.2 else ''
            turnover_desc = f', {turnover_reason}' if turnover_reason else ''
            liquidity_desc = f', {liquidity_reason}' if not is_valid else ''
            return StrategySignal(
                action='SELL', confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f'死叉: MA{self.short_window}({cur_short:.2f}) '
                       f'下穿 MA{self.long_window}({cur_long:.2f})'
                       f'{vol_desc}{turnover_desc}{liquidity_desc}',
                indicators=indicators,
            )

        # ---- 多头排列: MA_short > MA_long, 无交叉 ----
        #  仓位随乖离率动态调整，映射到 [BULL_MIN, BULL_MAX]
        #  乖离率归一化（自适应）: 以该股票过去 60 日乖离率的 2σ 为"满分"基准
        #  低波动蓝筹（bias_std ~0.5%）→ 1% 乖离即可达到高仓位
        #  高波动小盘（bias_std ~3%）  → 需要 6% 乖离才达到满分
        #  上限 0.70 < 金叉最低 0.75，保证层级：BUY > HOLD_bull
        if cur_short > cur_long:
            bias_threshold = max(bias_std * 2, 1e-6)
            norm_bias = min(abs(bias) / bias_threshold, 1.0)
            position = self._BULL_POS_MIN + norm_bias * (self._BULL_POS_MAX - self._BULL_POS_MIN)

            return StrategySignal(
                action='HOLD', confidence=0.5,
                position=round(position, 2),
                reason=f'均线多头排列, MA{self.short_window}={cur_short:.2f} '
                       f'> MA{self.long_window}={cur_long:.2f}'
                       f', 乖离{bias*100:.1f}%',
                indicators=indicators,
            )

        # ---- 空头排列: MA_short < MA_long ----
        #  乖离越大(空头越强) → 仓位越低
        #  乖离率归一化（自适应）: 与多头排列对称，以 2σ 为满分基准
        #  范围 [BEAR_MIN=0.05, BEAR_MAX=0.25]
        #  死叉后第一天(乖离接近0) position≈0.25, 与死叉的 0.0 有差距,
        #  但 HOLD 不触发交易, 仅供组合策略参考趋势强度
        bias_threshold = max(bias_std * 2, 1e-6)
        norm_bias = min(abs(bias) / bias_threshold, 1.0)
        position = self._BEAR_POS_MAX - norm_bias * (self._BEAR_POS_MAX - self._BEAR_POS_MIN)

        return StrategySignal(
            action='HOLD', confidence=0.5,
            position=round(position, 2),
            reason=f'均线空头排列, MA{self.short_window}={cur_short:.2f} '
                   f'< MA{self.long_window}={cur_long:.2f}'
                   f', 乖离{bias*100:.1f}%',
            indicators=indicators,
        )
