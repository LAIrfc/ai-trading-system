"""
布林带策略 (Bollinger Bands)

原理:
- 价格触及下轨 → 超卖，需拐头确认后买入
- 价格触及上轨 → 超买，需拐头确认后卖出
- 价格从下轨向中轨回归 → 确认买入
- 价格在轨外未拐头 → HOLD（避免连续触发信号）

信号强度动态化:
- 反弹/回落强度:  价格变动幅度（日收益率），归一化后衡量信号爆发力
- 成交量:         当日成交量 / 20日均量 → 放量验证
  注意：不引入中轨斜率。布林带是均值回归策略，趋势信息由 MA/MACD 提供。
  保持各策略哲学独立，才能让组合投票获得多样化收益。

置信度计算:
  BUY/SELL 信号分两档：
  - 突破回归（价格从轨外回到轨内）: conf ∈ [_BASE_CONF_BREAK, _MAX_CONF]
  - 拐头确认（价格仍在轨外但拐头）: conf ∈ [_BASE_CONF_REV, _MAX_CONF]
  conf = BASE + factor * (MAX - BASE)
  factor = 加权(反弹强度, 量比)

卖出仓位平滑:
  突破回落: position = max(0, _SELL_POS_MAX * (1 - factor))
  拐头回落: position = _SELL_REV_MAX - factor * (_SELL_REV_MAX - _SELL_REV_MIN)

HOLD 信号（已在前轮讨论中确定，不改动）:
  上轨上方未拐头: conf=0.4, pos=0.7（趋势跟踪哲学，让利润奔跑）
  下轨下方未拐头: conf=0.35, pos=0.15（防御性降仓）
  带内: conf=0.5, pos=0.5

仓位层级:
  BUY 突破回升  ∈ [0.65, 0.85]
  BUY 拐头回升  ∈ [0.25, 0.50]
  HOLD 上轨强势 = 0.70（固定，特殊哲学，前轮确定）
  HOLD 带内     = 0.50
  HOLD 下轨防御 = 0.15
  SELL 拐头回落 ∈ [0.10, 0.25]
  SELL 突破回落 ∈ [0.00, 0.10]

参数:
- period:  中轨均线周期（默认20）  范围[10, 40]
- std_dev: 标准差倍数（默认2.0）  范围[1.5, 3.0]

仅 period / std_dev 参与参数优化。
以下内部常量为经验值，固定不参与网格搜索，避免过拟合。
"""

import numpy as np
import pandas as pd
from .base import Strategy, StrategySignal


class BollingerBandStrategy(Strategy):

    name = '布林带'
    description = '价格触及上下轨+拐头确认产生信号，反弹强度+量比动态置信度'

    param_ranges = {
        'period':  (10, 20, 40, 2),
        'std_dev': (1.5, 2.0, 3.0, 0.25),
    }

    # ---- 内部常量（不参与参数优化） ----
    _BASE_CONF_BREAK = 0.65     # 突破回归基础置信度
    _BASE_CONF_REV   = 0.50     # 拐头确认基础置信度
    _MAX_CONF         = 0.85    # 置信度上限
    _STRENGTH_W       = 0.6     # 反弹/回落强度权重
    _VOL_W            = 0.4     # 量比权重
    _VOL_MA           = 20      # 成交量基准均线天数
    _SELL_POS_MAX     = 0.10    # 突破回落最大保留仓位

    # 仓位范围
    _BUY_BREAK_POS_MIN = 0.65   # 突破回升最低仓位
    _BUY_BREAK_POS_MAX = 0.85   # 突破回升最高仓位
    _BUY_REV_POS_MIN   = 0.25   # 拐头回升最低仓位
    _BUY_REV_POS_MAX   = 0.50   # 拐头回升最高仓位
    _SELL_REV_POS_MIN  = 0.10   # 拐头回落最低仓位（强拐头→卖更多）
    _SELL_REV_POS_MAX  = 0.25   # 拐头回落最高仓位（弱拐头→留更多）

    def __init__(self, period: int = 20, std_dev: float = 2.0, **kwargs):
        self.period = period
        self.std_dev = std_dev
        # max(period, _VOL_MA) 保证均线和均量都有有效值 + 5 缓冲
        self.min_bars = max(period, self._VOL_MA) + 5

    def _calc_dynamics(self, df: pd.DataFrame,
                       close: pd.Series) -> dict:
        """
        计算动态因子:
        - price_std:  过去 N 日日收益率标准差（用于自适应归一化反弹/回落强度）
        - vol_ratio:  当日成交量 / 20日均量
        """
        n = max(self.period, 20)

        # 日收益率标准差: 用于归一化反弹/回落幅度
        # 高波动股（std ~3%）需要更大反弹才算"强"
        # 低波动股（std ~0.5%）小幅反弹即为"强"
        price_std = 0.01  # 降级默认值
        returns = close.pct_change().replace([np.inf, -np.inf], np.nan)
        if len(returns) > n:
            recent_std = float(returns.iloc[-n:].dropna().std())
            if recent_std > 1e-8:
                price_std = recent_std

        # 成交量比: 当日量 / 20日均量（不含当日）
        vol_ratio = 1.0
        if 'volume' in df.columns:
            vol = df['volume']
            vm = self._VOL_MA
            if len(vol) > vm:
                avg_vol = float(vol.iloc[-(vm + 1):-1].mean())
                cur_vol = float(vol.iloc[-1])
                vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 1.0

        return {'price_std': price_std, 'vol_ratio': vol_ratio}

    def _combined_factor(self, price_change: float, price_std: float,
                         vol_ratio: float) -> float:
        """
        将反弹/回落强度和量比归一化为 [0, 1] 的综合因子。

        反弹强度归一化（自适应）:
          norm_strength = min(|price_change| / (price_std * 2), 1.0)
          2σ 覆盖约 95% 的日常波动，超过 2σ 即视为异常强反弹/回落。

        量比归一化:
          (vol_ratio - 0.5) / 2.5 映射后 clamp 到 [0,1]
        """
        norm_strength = min(abs(price_change) / (price_std * 2), 1.0)
        norm_vol = max(0.0, min((vol_ratio - 0.5) / 2.5, 1.0))

        return self._STRENGTH_W * norm_strength + self._VOL_W * norm_vol

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

        dyn = self._calc_dynamics(df, close)
        price_std = dyn['price_std']
        vol_ratio = dyn['vol_ratio']

        indicators = {
            '上轨': round(cur_upper, 3),
            '中轨': round(cur_mid, 3),
            '下轨': round(cur_lower, 3),
            '%B': round(pct_b, 3),
            '带宽%': round(bandwidth_pct, 2),
            'price_std_pct': round(price_std * 100, 3),
            'vol_ratio': round(vol_ratio, 2),
        }

        # ---- 1. 价格从下方突破下轨后回升（确认买入）----
        #  价格昨日在下轨下方，今日回到下轨上方 → 均值回归确认
        #  反弹幅度+量比 → 动态置信度和仓位
        if prev_close <= prev_lower and cur_close > cur_lower:
            price_change = (cur_close - prev_close) / prev_close
            factor = self._combined_factor(price_change, price_std, vol_ratio)
            confidence = self._BASE_CONF_BREAK + factor * (self._MAX_CONF - self._BASE_CONF_BREAK)
            position = self._BUY_BREAK_POS_MIN + factor * (self._BUY_BREAK_POS_MAX - self._BUY_BREAK_POS_MIN)

            vol_desc = f', 量比{vol_ratio:.1f}' if vol_ratio > 1.2 else ''
            return StrategySignal(
                action='BUY', confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f'价格从下轨下方回升, %B={pct_b:.2f}{vol_desc}',
                indicators=indicators,
            )

        # ---- 2. 价格在下轨下方：拐头 vs 持续下跌 ----
        if cur_close < cur_lower:
            if cur_close > prev_close and prev_close > prev2_close:
                # 连续两日回升，底部拐头确认
                # 用两日累计涨幅衡量拐头强度
                reversal = (cur_close - prev2_close) / prev2_close
                factor = self._combined_factor(reversal, price_std, vol_ratio)
                confidence = self._BASE_CONF_REV + factor * (self._MAX_CONF - self._BASE_CONF_REV)
                position = self._BUY_REV_POS_MIN + factor * (self._BUY_REV_POS_MAX - self._BUY_REV_POS_MIN)

                return StrategySignal(
                    action='BUY', confidence=round(confidence, 2),
                    position=round(position, 2),
                    reason=f'下轨下方拐头回升({prev2_close:.2f}→{prev_close:.2f}→{cur_close:.2f})',
                    indicators=indicators,
                )
            else:
                # 未拐头：可能仍在下跌中，低置信度匹配低仓位，防御性等待
                # （前轮已确定 conf=0.35, pos=0.15，不改动）
                return StrategySignal(
                    action='HOLD', confidence=0.35, position=0.15,
                    reason=f'价格在下轨下方({cur_close:.2f}<{cur_lower:.2f})但未拐头，等待确认',
                    indicators=indicators,
                )

        # ---- 3. 价格从上方跌破上轨（确认卖出）----
        #  价格昨日在上轨上方，今日回到上轨下方 → 均值回归确认
        #  回落幅度+量比 → 动态因子 → 平滑仓位衰减
        if prev_close >= prev_upper and cur_close < cur_upper:
            price_change = (prev_close - cur_close) / prev_close  # 正值=下跌
            factor = self._combined_factor(price_change, price_std, vol_ratio)
            confidence = self._BASE_CONF_BREAK + factor * (self._MAX_CONF - self._BASE_CONF_BREAK)

            # 仓位随 factor 平滑衰减:
            #   factor→0 (缩量弱回落): pos ≈ _SELL_POS_MAX (0.10)
            #   factor→1 (放量强回落): pos → 0
            position = round(max(0, self._SELL_POS_MAX * (1 - factor)), 2)

            vol_desc = f', 量比{vol_ratio:.1f}' if vol_ratio > 1.2 else ''
            return StrategySignal(
                action='SELL', confidence=round(confidence, 2),
                position=position,
                reason=f'价格从上轨回落, %B={pct_b:.2f}{vol_desc}',
                indicators=indicators,
            )

        # ---- 4. 价格在上轨上方：拐头 vs 持续上涨 ----
        if cur_close > cur_upper:
            if cur_close < prev_close and prev_close < prev2_close:
                # 连续两日回落，顶部拐头确认
                reversal = (prev2_close - cur_close) / prev2_close  # 正值=下跌
                factor = self._combined_factor(reversal, price_std, vol_ratio)
                confidence = self._BASE_CONF_REV + factor * (self._MAX_CONF - self._BASE_CONF_REV)

                # 仓位: 拐头越强 → 卖出越多（仓位越低）
                position = self._SELL_REV_POS_MAX - factor * (self._SELL_REV_POS_MAX - self._SELL_REV_POS_MIN)

                return StrategySignal(
                    action='SELL', confidence=round(confidence, 2),
                    position=round(position, 2),
                    reason=f'上轨上方拐头回落({prev2_close:.2f}→{prev_close:.2f}→{cur_close:.2f})',
                    indicators=indicators,
                )
            else:
                # 突破上轨且仍在上涨 — 统计极端区域，方向不确定性高(conf低)，
                # 但趋势跟踪哲学下不应恐慌卖出(pos高)，让利润奔跑。
                # （前轮已确定 conf=0.4, pos=0.7，不改动）
                return StrategySignal(
                    action='HOLD', confidence=0.4, position=0.7,
                    reason=f'价格突破上轨({cur_close:.2f}>{cur_upper:.2f})且未拐头，强势持有',
                    indicators=indicators,
                )

        # ---- 5. 价格在布林带内 ----
        return StrategySignal(
            action='HOLD', confidence=0.5, position=0.5,
            reason=f'价格在布林带内, %B={pct_b:.2f}, 带宽={bandwidth_pct:.1f}%',
            indicators=indicators,
        )
