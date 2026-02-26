"""
RSI策略（相对强弱指标）

原理:
- RSI < 30 → 超卖区，考虑买入
- RSI > 70 → 超买区，考虑卖出
- RSI从超卖区回升突破 → 强买入信号（确认离开超卖区）
- RSI从超买区回落突破 → 强卖出信号（确认离开超买区）
- 仍在超卖/超买区 → 需"拐头"（连续两日反向运动）确认才发信号

信号强度动态化:
- RSI变化幅度: RSI 的日变化量（diff()），变化越陡信号越强
- 拐头强度:    两日累计变化量 / √2 → 缩放到日变化尺度后归一化
                （两日累计变化的 std ≈ 日变化 std × √2，需除以 √2 对齐）
- 成交量:      当日成交量 / 20日均量 → 放量验证

RSI变化归一化（自适应）:
  使用过去 _SLOPE_LOOKBACK(60) 日 RSI 的 diff() 标准差作为基准
  norm = min(abs(rsi_change) / (rsi_slope_std * 2), 1.0)
  RSI 有界 [0, 100]，diff() 安全无除零风险

置信度计算:
  conf = BASE + combined_factor * (MAX - BASE)
  combined_factor ∈ [0, 1], 由 RSI变化 + 量比加权合成

卖出仓位（平滑）:
  突破回落: position = max(0, _SELL_POS_MAX * (1 - factor))
            强回落→清仓, 弱回落→保留少量仓位
  拐头回落: position ∈ [_REV_SELL_POS_MIN, _REV_SELL_POS_MAX]
            强回落→低仓位, 弱回落→高仓位

仓位层级保证:
  BUY breakthrough pos ∈ [0.70, 0.90] — 突破回升（最强）
  BUY reversal     pos ∈ [0.35, 0.55] — 拐头买入
  HOLD oversold         pos = 0.30     — 超卖等待（< BUY reversal min）
  HOLD neutral          pos = 0.50
  HOLD overbought       pos = 0.60
  SELL reversal    pos ∈ [0.05, 0.20] — 拐头卖出
  SELL breakthrough pos ∈ [0.0, 0.12] — 突破回落（最强卖出）

参数:
- period:     RSI周期（默认14）    范围[6, 30]
- oversold:   超卖阈值（默认30）   范围[15, 35]
- overbought: 超买阈值（默认70）   范围[65, 85]

仅 period / oversold / overbought 参与参数优化。
以下内部常量为经验值，固定不参与网格搜索，避免过拟合:
  _BASE_CONF, _MAX_CONF, _SLOPE_W, _VOL_W 等

min_bars 计算: period + _SLOPE_LOOKBACK + 5
"""

import numpy as np
import pandas as pd
from .base import Strategy, StrategySignal


class RSIStrategy(Strategy):

    name = 'RSI'
    description = 'RSI超买超卖信号，拐头确认+RSI变化幅度/量比动态置信度'

    param_ranges = {
        'period':     (6, 14, 30, 1),
        'oversold':   (15, 30, 35, 5),
        'overbought': (65, 70, 85, 5),
    }

    # ---- 内部常量（不参与参数优化） ----
    _BASE_CONF     = 0.65       # 突破信号基础置信度
    _MAX_CONF      = 0.90       # 置信度上限
    _REV_BASE_CONF = 0.52       # 拐头信号基础置信度（弱于突破）
    _REV_MAX_CONF  = 0.72       # 拐头信号置信度上限
    _SLOPE_W       = 0.6        # RSI变化因子权重
    _VOL_W         = 0.4        # 量比因子权重
    _VOL_MA        = 20         # 成交量基准均线天数
    _SLOPE_LOOKBACK = 60        # RSI 变化标准差回看天数
    _SELL_POS_MAX  = 0.12       # 突破回落时最大保留仓位（弱信号）

    # 买入仓位范围
    _BREAK_BUY_POS_MIN = 0.70   # 突破回升最低仓位
    _BREAK_BUY_POS_MAX = 0.90   # 突破回升最高仓位
    _REV_BUY_POS_MIN   = 0.35   # 拐头买入最低仓位
    _REV_BUY_POS_MAX   = 0.55   # 拐头买入最高仓位

    # 卖出拐头仓位范围
    _REV_SELL_POS_MIN  = 0.05   # 拐头卖出最低仓位（强回落）
    _REV_SELL_POS_MAX  = 0.20   # 拐头卖出最高仓位（弱回落）

    def __init__(self, period: int = 14, oversold: float = 30,
                 overbought: float = 70, **kwargs):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        # min_bars 拆解:
        #   period              → RSI rolling(period) 需要 period 条数据
        #   + _SLOPE_LOOKBACK   → RSI diff std 需要 60 个有效数据
        #   + 5                 → 余量（拐头判断回看 3 日等）
        self.min_bars = self.period + self._SLOPE_LOOKBACK + 5

    def _calc_rsi(self, close: pd.Series) -> pd.Series:
        """计算RSI指标"""
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(self.period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(self.period).mean()
        rs = gain / loss.replace(0, 1e-10)
        return 100 - (100 / (1 + rs))

    def _calc_dynamics(self, df: pd.DataFrame,
                       rsi: pd.Series) -> dict:
        """
        计算动态因子:
        - rsi_slope:     RSI 日变化量 (rsi.diff())
        - rsi_slope_std: 过去 60 日 RSI diff 的标准差（自适应归一化）
        - vol_ratio:     当日成交量 / 20日均量
        """
        rsi_slope = float(rsi.iloc[-1] - rsi.iloc[-2])

        n = self._SLOPE_LOOKBACK

        # RSI 变化标准差: RSI ∈ [0,100], 日变化通常 2~5 点
        rsi_slope_std = 3.0  # 降级默认值
        rsi_diffs = rsi.diff().replace([np.inf, -np.inf], np.nan)
        if len(rsi_diffs) > n:
            std = float(rsi_diffs.iloc[-n:].dropna().std())
            if std > 1e-8:
                rsi_slope_std = std

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
            'rsi_slope': rsi_slope,
            'rsi_slope_std': rsi_slope_std,
            'vol_ratio': vol_ratio,
        }

    def _combined_factor(self, change: float, change_std: float,
                         vol_ratio: float) -> float:
        """
        将 RSI 变化量和量比归一化为 [0, 1] 的综合因子。

        RSI 变化归一化（自适应）:
          以 2σ 为满分基准: norm = min(abs(change) / (std * 2), 1.0)

        量比归一化:
          (vol_ratio - 0.5) / 2.5 映射后 clamp 到 [0,1]
        """
        threshold = max(change_std * 2, 1e-6)
        norm_change = min(abs(change) / threshold, 1.0)
        norm_vol = max(0.0, min((vol_ratio - 0.5) / 2.5, 1.0))

        # 加权合成，权重之和为 1，输出 ∈ [0, 1]
        return self._SLOPE_W * norm_change + self._VOL_W * norm_vol

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        rsi = self._calc_rsi(df['close'])

        cur_rsi = float(rsi.iloc[-1])
        prev_rsi = float(rsi.iloc[-2])
        prev2_rsi = float(rsi.iloc[-3]) if len(rsi) >= 3 else prev_rsi

        dyn = self._calc_dynamics(df, rsi)
        rsi_slope = dyn['rsi_slope']
        rsi_slope_std = dyn['rsi_slope_std']
        vol_ratio = dyn['vol_ratio']

        indicators = {
            'RSI': round(cur_rsi, 2),
            'RSI_prev': round(prev_rsi, 2),
            'rsi_slope': round(rsi_slope, 2),
            'rsi_slope_std': round(rsi_slope_std, 2),
            'vol_ratio': round(vol_ratio, 2),
        }

        # ---- 从超卖区回升突破（强买入）----
        #  RSI 从 < oversold 穿越到 >= oversold，确认离开超卖区
        #  RSI 变化幅度 + 量比 → factor → 动态置信度/仓位
        if prev_rsi < self.oversold and cur_rsi >= self.oversold:
            factor = self._combined_factor(
                rsi_slope, rsi_slope_std, vol_ratio)
            confidence = (self._BASE_CONF +
                          factor * (self._MAX_CONF - self._BASE_CONF))
            position = (self._BREAK_BUY_POS_MIN +
                        factor * (self._BREAK_BUY_POS_MAX -
                                  self._BREAK_BUY_POS_MIN))
            vol_desc = f', 量比{vol_ratio:.1f}' if vol_ratio > 1.2 else ''
            return StrategySignal(
                action='BUY', confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f'RSI从超卖区回升突破 '
                       f'({prev_rsi:.1f}→{cur_rsi:.1f}){vol_desc}',
                indicators=indicators,
            )

        # ---- 仍在超卖区：拐头确认 ----
        #  连续两日回升: 用两日累计回升幅度 + 量比合成 factor
        #  回升幅度越大 → 置信度和仓位越高
        if cur_rsi < self.oversold:
            if cur_rsi > prev_rsi and prev_rsi > prev2_rsi:
                reversal = cur_rsi - prev2_rsi  # 两日累计回升（正值）
                # 两日累计变化的标准差 ≈ 日变化标准差 × √2
                # 除以 √2 缩放到日变化尺度, 使 _combined_factor 的 2σ 阈值正确
                daily_eq = reversal / np.sqrt(2)
                rev_factor = self._combined_factor(
                    daily_eq, rsi_slope_std, vol_ratio)
                confidence = (self._REV_BASE_CONF +
                              rev_factor * (self._REV_MAX_CONF -
                                            self._REV_BASE_CONF))
                position = (self._REV_BUY_POS_MIN +
                            rev_factor * (self._REV_BUY_POS_MAX -
                                          self._REV_BUY_POS_MIN))
                vol_desc = (f', 量比{vol_ratio:.1f}'
                            if vol_ratio > 1.2 else '')
                return StrategySignal(
                    action='BUY', confidence=round(confidence, 2),
                    position=round(position, 2),
                    reason=f'RSI超卖区拐头确认 '
                           f'({prev2_rsi:.1f}→{prev_rsi:.1f}'
                           f'→{cur_rsi:.1f}){vol_desc}',
                    indicators=indicators,
                )
            else:
                return StrategySignal(
                    action='HOLD', confidence=0.4, position=0.30,
                    reason=f'RSI超卖({cur_rsi:.1f})但未拐头，等待底部确认',
                    indicators=indicators,
                )

        # ---- 从超买区回落突破（强卖出）----
        #  RSI 从 > overbought 跌到 <= overbought，确认离开超买区
        #  平滑卖出: 强回落(factor高)→清仓, 弱回落(factor低)→保留少量
        if prev_rsi > self.overbought and cur_rsi <= self.overbought:
            factor = self._combined_factor(
                rsi_slope, rsi_slope_std, vol_ratio)
            confidence = (self._BASE_CONF +
                          factor * (self._MAX_CONF - self._BASE_CONF))
            # 仓位随 factor 平滑衰减:
            #   factor→0 (弱回落): position ≈ _SELL_POS_MAX (0.12)
            #   factor→1 (强回落): position → 0
            position = round(max(0, self._SELL_POS_MAX * (1 - factor)), 2)
            vol_desc = f', 量比{vol_ratio:.1f}' if vol_ratio > 1.2 else ''
            return StrategySignal(
                action='SELL', confidence=round(confidence, 2),
                position=position,
                reason=f'RSI从超买区回落突破 '
                       f'({prev_rsi:.1f}→{cur_rsi:.1f}){vol_desc}',
                indicators=indicators,
            )

        # ---- 仍在超买区：拐头确认 ----
        #  连续两日回落: 用两日累计回落幅度 + 量比合成 factor
        #  回落幅度越大 → 置信度越高, 仓位越低
        if cur_rsi > self.overbought:
            if cur_rsi < prev_rsi and prev_rsi < prev2_rsi:
                reversal = cur_rsi - prev2_rsi  # 两日累计回落（负值）
                # 同买入拐头: 缩放到日变化尺度
                daily_eq = reversal / np.sqrt(2)
                rev_factor = self._combined_factor(
                    daily_eq, rsi_slope_std, vol_ratio)
                confidence = (self._REV_BASE_CONF +
                              rev_factor * (self._REV_MAX_CONF -
                                            self._REV_BASE_CONF))
                # 强回落(factor高) → 低仓位, 弱回落(factor低) → 高仓位
                position = (self._REV_SELL_POS_MAX -
                            rev_factor * (self._REV_SELL_POS_MAX -
                                          self._REV_SELL_POS_MIN))
                vol_desc = (f', 量比{vol_ratio:.1f}'
                            if vol_ratio > 1.2 else '')
                return StrategySignal(
                    action='SELL', confidence=round(confidence, 2),
                    position=round(position, 2),
                    reason=f'RSI超买区拐头确认 '
                           f'({prev2_rsi:.1f}→{prev_rsi:.1f}'
                           f'→{cur_rsi:.1f}){vol_desc}',
                    indicators=indicators,
                )
            else:
                return StrategySignal(
                    action='HOLD', confidence=0.4, position=0.60,
                    reason=f'RSI超买({cur_rsi:.1f})但未拐头，继续观察',
                    indicators=indicators,
                )

        # ---- 中性区间 ----
        return StrategySignal(
            action='HOLD', confidence=0.5, position=0.50,
            reason=f'RSI中性区间 ({cur_rsi:.1f})',
            indicators=indicators,
        )
