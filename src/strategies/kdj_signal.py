"""
KDJ策略（随机指标）

原理:
- K线上穿D线（金叉）→ 买入（仅K<50有效区）
- K线下穿D线（死叉）→ 卖出（仅K>50有效区）
- J > 100 超买，J < 0 超卖（需拐头确认）
- 低位金叉(K<30)信号最强，高位死叉(K>70)信号最强

信号强度动态化:
- K线斜率:  K值日变化量（diff()），交叉越陡峭信号越强
- J值拐头幅度: J值日变化量，回升/回落幅度越大信号越强
- 成交量:    当日成交量 / 20日均量 → 放量验证

置信度计算:
  conf = BASE + combined_factor * (MAX - BASE)
  combined_factor ∈ [0, 1], 由 K斜率(或J变化) + 量比加权合成

K斜率归一化（自适应）:
  使用过去 _SLOPE_LOOKBACK(60) 日 K 的 diff() 标准差作为基准
  norm_slope = min(abs(k_slope) / (k_slope_std * 2), 1.0)
  K 值在 [0, 100] 范围内，diff() 安全无除零风险

J值变化归一化（自适应）:
  使用过去 _SLOPE_LOOKBACK(60) 日 J 的 diff() 标准差作为基准
  norm_j_change = min(abs(j_change) / (j_change_std * 2), 1.0)
  J 值可超出 [0, 100]，但 diff() 仍然安全

HOLD 仓位（动态）:
  K > D 时（多头区域）：用 |K - D| 的自适应归一化驱动仓位
    position ∈ [_BULL_POS_MIN, _BULL_POS_MAX]
  K < D 时（空头区域）：同理
    position ∈ [_BEAR_POS_MIN, _BEAR_POS_MAX]

死叉仓位（平滑）:
  position = max(0, _SELL_POS_MAX * (1 - factor))
  缩量弱死叉保留少量仓位，放量强死叉趋近清仓

仓位层级保证:
  BUY low K   pos ∈ [0.75, 0.95] — 低位金叉（最强）
  BUY mid K   pos ∈ [0.55, 0.72] — 中位金叉
  BUY J极值   pos ∈ [0.35, 0.55] — J超卖拐头
  HOLD bull   pos ∈ [0.40, 0.55] — K>D 多头（上限 < BUY mid 下限）
  HOLD bear   pos ∈ [0.25, 0.40] — K<D 空头
  SELL        pos ∈ [0.0,  0.12] — 死叉（factor 衰减）
  SELL J极值  pos ∈ [0.05, 0.18] — J超买拐头

策略多样性:
  加入K斜率和成交量不破坏KDJ的震荡指标本质：
  KDJ由RSV(随机过程)驱动，与MA/MACD(趋势过程)信号触发逻辑完全不同。
  共享因子增强信号质量，不改变核心身份。

参数:
- n:   RSV 周期（默认9）    范围[5, 21]
- m1:  K值平滑周期（默认3）  范围[2, 5]
- m2:  D值平滑周期（默认3）  范围[2, 5]

仅 n / m1 / m2 参与参数优化。
以下内部常量为经验值，固定不参与网格搜索，避免过拟合:
  _BASE_CONF, _MAX_CONF, _SLOPE_W, _VOL_W 等

min_bars 计算: n + _SLOPE_LOOKBACK + 5
"""

import numpy as np
import pandas as pd
from .base import Strategy, StrategySignal
from .turnover_helper import (
    calc_relative_turnover_rate,
    check_turnover_liquidity,
    enhance_signal_with_turnover
)


class KDJStrategy(Strategy):

    name = 'KDJ'
    description = 'KDJ金叉/死叉(K位置过滤)+J值拐头，K斜率+量比动态置信度'

    param_ranges = {
        'n':  (5, 9, 21, 1),
        'm1': (2, 3, 5, 1),
        'm2': (2, 3, 5, 1),
    }

    # ---- 内部常量（不参与参数优化） ----
    _BASE_CONF = 0.62           # 裸金叉/死叉基础置信度
    _MAX_CONF  = 0.88           # 置信度上限
    _K_POS_BONUS = 0.05         # K值极端位置(K<30金叉/K>70死叉)基础加成
    _J_BASE_CONF = 0.52         # J值极端信号基础置信度（弱于交叉信号）
    _J_MAX_CONF  = 0.72         # J值极端信号置信度上限
    _SLOPE_W   = 0.6            # K斜率/J变化因子权重
    _VOL_W     = 0.4            # 量比因子权重
    _VOL_MA    = 20             # 成交量基准均线天数
    _SLOPE_LOOKBACK = 60        # K/J 斜率标准差回看天数
    _SELL_POS_MAX   = 0.12      # 死叉时最大保留仓位（缩量弱死叉）

    # 金叉仓位范围（低位 > 中位，保证层级）
    _LOW_CROSS_POS_MIN  = 0.75  # 低位金叉(K<30)
    _LOW_CROSS_POS_MAX  = 0.95
    _MID_CROSS_POS_MIN  = 0.55  # 中位金叉(30≤K<50)
    _MID_CROSS_POS_MAX  = 0.72

    # J值极端信号仓位
    _J_BUY_POS_MIN  = 0.35      # J超卖拐头
    _J_BUY_POS_MAX  = 0.55
    _J_SELL_POS_MIN = 0.05      # J超买拐头
    _J_SELL_POS_MAX = 0.18

    # HOLD 仓位范围
    _BULL_POS_MIN = 0.40        # K>D 多头（上限 < _MID_CROSS_POS_MIN）
    _BULL_POS_MAX = 0.55
    _BEAR_POS_MIN = 0.25        # K<D 空头
    _BEAR_POS_MAX = 0.40

    def __init__(self, n: int = 9, m1: int = 3, m2: int = 3, **kwargs):
        self.n = n
        self.m1 = m1
        self.m2 = m2
        # min_bars 拆解:
        #   n                  → RSV 需要 n 条数据计算 rolling min/max
        #   + _SLOPE_LOOKBACK  → K/J 斜率 std 需要 60 个有效数据
        #   + 5                → 余量（EWM 收敛 + 拐头判断）
        #   m1, m2 的 EWM 收敛被 _SLOPE_LOOKBACK(60) 远远覆盖
        self.min_bars = self.n + self._SLOPE_LOOKBACK + 5

    def _calc_kdj(self, df: pd.DataFrame):
        """计算KDJ指标"""
        high = df['high']
        low = df['low']
        close = df['close']

        lowest = low.rolling(self.n).min()
        highest = high.rolling(self.n).max()
        rsv = (close - lowest) / (highest - lowest).replace(0, 1e-10) * 100

        k = rsv.ewm(com=self.m1 - 1, adjust=False).mean()
        d = k.ewm(com=self.m2 - 1, adjust=False).mean()
        j = 3 * k - 2 * d

        return k, d, j

    def _calc_dynamics(self, df: pd.DataFrame,
                       k: pd.Series, d: pd.Series,
                       j: pd.Series) -> dict:
        """
        计算动态因子:
        - k_slope:       K值日变化量 (k.diff())
        - k_slope_std:   过去 60 日 K diff 的标准差（自适应归一化）
        - j_change:      J值日变化量 (j.diff())
        - j_change_std:  过去 60 日 J diff 的标准差（自适应归一化）
        - kd_gap_std:    过去 60 日 (K-D) 的标准差（HOLD 仓位归一化）
        - vol_ratio:     当日成交量 / 20日均量
        """
        k_slope = float(k.iloc[-1] - k.iloc[-2])
        j_change = float(j.iloc[-1] - j.iloc[-2])

        n = self._SLOPE_LOOKBACK

        # K 斜率标准差: K ∈ [0,100], 日变化通常 3~8 点
        k_slope_std = 5.0  # 降级默认值
        k_diffs = k.diff().replace([np.inf, -np.inf], np.nan)
        if len(k_diffs) > n:
            std = float(k_diffs.iloc[-n:].dropna().std())
            if std > 1e-8:
                k_slope_std = std

        # J 变化标准差: J 波动比 K 大（3K-2D 放大效应），通常 10~20 点
        j_change_std = 15.0  # 降级默认值
        j_diffs = j.diff().replace([np.inf, -np.inf], np.nan)
        if len(j_diffs) > n:
            std = float(j_diffs.iloc[-n:].dropna().std())
            if std > 1e-8:
                j_change_std = std

        # K-D 间距标准差（HOLD 仓位归一化）
        kd_gap_std = 10.0  # 降级默认值
        kd_gap = (k - d).replace([np.inf, -np.inf], np.nan)
        if len(kd_gap) > n:
            std = float(kd_gap.iloc[-n:].dropna().std())
            if std > 1e-8:
                kd_gap_std = std

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
            'k_slope': k_slope, 'k_slope_std': k_slope_std,
            'j_change': j_change, 'j_change_std': j_change_std,
            'kd_gap_std': kd_gap_std,
            'vol_ratio': vol_ratio,
        }

    def _combined_factor(self, change: float, change_std: float,
                         vol_ratio: float) -> float:
        """
        将变化量（K斜率或J变化）和量比归一化为 [0, 1] 的综合因子。

        变化量归一化（自适应）:
          以 2σ 为满分基准: norm = min(abs(change) / (std * 2), 1.0)
          2σ 覆盖约 95% 的日常波动，超过 2σ 即视为异常强势。

        量比归一化:
          vol_ratio 通常 0.5~3.0，
          (vol_ratio - 0.5) / 2.5 映射后 clamp 到 [0,1]。
          截断合理：量比超过 3 后对信号确认的边际信息递减。
        """
        threshold = max(change_std * 2, 1e-6)
        norm_change = min(abs(change) / threshold, 1.0)
        norm_vol = max(0.0, min((vol_ratio - 0.5) / 2.5, 1.0))

        # 加权合成，权重之和为 1，输出 ∈ [0, 1]
        return self._SLOPE_W * norm_change + self._VOL_W * norm_vol

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        k, d, j = self._calc_kdj(df)

        cur_k = float(k.iloc[-1])
        cur_d = float(d.iloc[-1])
        cur_j = float(j.iloc[-1])
        prev_k = float(k.iloc[-2])
        prev_d = float(d.iloc[-2])
        prev_j = float(j.iloc[-2])

        dyn = self._calc_dynamics(df, k, d, j)
        k_slope = dyn['k_slope']
        k_slope_std = dyn['k_slope_std']
        j_change = dyn['j_change']
        j_change_std = dyn['j_change_std']
        kd_gap_std = dyn['kd_gap_std']
        vol_ratio = dyn['vol_ratio']
        
        # 实盘标准：计算相对换手率（当前换手率/20日均换手率）
        relative_turnover = calc_relative_turnover_rate(df, ma_period=20)

        indicators = {
            'K': round(cur_k, 2),
            'D': round(cur_d, 2),
            'J': round(cur_j, 2),
            'k_slope': round(k_slope, 2),
            'k_slope_std': round(k_slope_std, 2),
            'j_change': round(j_change, 2),
            'vol_ratio': round(vol_ratio, 2),
            'relative_turnover': round(relative_turnover, 2) if relative_turnover else None,
        }

        # ---- 金叉: K 从下方上穿 D ----
        #  K斜率越陡 + 量比越大 → factor 越高 → 置信度和仓位越高
        #  低位金叉(K<30): K位置加成 → base 上浮
        if prev_k <= prev_d and cur_k > cur_d:
            # 实盘标准：流动性过滤
            is_valid, liquidity_reason = check_turnover_liquidity(relative_turnover)
            if not is_valid:
                # 流动性异常，回避交易
                return StrategySignal(
                    action='HOLD', confidence=0.3, position=0.5,
                    reason=f'KDJ金叉但{liquidity_reason}，回避交易',
                    indicators=indicators,
                )
            
            factor = self._combined_factor(k_slope, k_slope_std, vol_ratio)
            vol_desc = f', 量比{vol_ratio:.1f}' if vol_ratio > 1.2 else ''

            if cur_k < 30:
                # 低位金叉 → 最强买入, K位置加成
                base = self._BASE_CONF + self._K_POS_BONUS
                base_confidence = base + factor * (self._MAX_CONF - base)
                base_position = (self._LOW_CROSS_POS_MIN +
                                factor * (self._LOW_CROSS_POS_MAX -
                                          self._LOW_CROSS_POS_MIN))
                
                # 实盘标准：突破时要求相对换手率>1.2倍（确认有效突破）
                confidence, position, turnover_reason = enhance_signal_with_turnover(
                    'breakout', relative_turnover, base_confidence, base_position
                )
                
                turnover_desc = f', {turnover_reason}' if turnover_reason else ''
                return StrategySignal(
                    action='BUY', confidence=round(confidence, 2),
                    position=round(position, 2),
                    reason=f'KDJ低位金叉: K={cur_k:.1f}↑ 上穿 D={cur_d:.1f}'
                           f', J={cur_j:.1f}{vol_desc}{turnover_desc}',
                    indicators=indicators,
                )

            elif cur_k < 50:
                # 中低位金叉 → 有效买入
                base_confidence = (self._BASE_CONF +
                                  factor * (self._MAX_CONF - self._BASE_CONF))
                base_position = (self._MID_CROSS_POS_MIN +
                                factor * (self._MID_CROSS_POS_MAX -
                                          self._MID_CROSS_POS_MIN))
                
                # 实盘标准：突破时要求相对换手率>1.2倍（确认有效突破）
                confidence, position, turnover_reason = enhance_signal_with_turnover(
                    'breakout', relative_turnover, base_confidence, base_position
                )
                
                turnover_desc = f', {turnover_reason}' if turnover_reason else ''
                return StrategySignal(
                    action='BUY', confidence=round(confidence, 2),
                    position=round(position, 2),
                    reason=f'KDJ中位金叉: K={cur_k:.1f}↑ 上穿 D={cur_d:.1f}'
                           f' (K<50有效区){vol_desc}{turnover_desc}',
                    indicators=indicators,
                )

            else:
                # K≥50 的金叉 → 位置偏高，仅观望
                return StrategySignal(
                    action='HOLD', confidence=0.45, position=0.50,
                    reason=f'KDJ高位金叉(K={cur_k:.1f}≥50)，信号偏弱，观望',
                    indicators=indicators,
                )

        # ---- J值超卖（需拐头确认）----
        #  J < 0 且回升: 用 J 变化幅度 + 量比合成 factor
        #  回升幅度越大 → 置信度和仓位越高
        if cur_j < 0:
            if cur_j > prev_j:
                # 实盘标准：流动性过滤（拐头信号也检查）
                is_valid, liquidity_reason = check_turnover_liquidity(relative_turnover)
                if not is_valid:
                    # 流动性异常，回避交易
                    return StrategySignal(
                        action='HOLD', confidence=0.3, position=0.5,
                        reason=f'J值超卖拐头但{liquidity_reason}，回避交易',
                        indicators=indicators,
                    )
                
                j_factor = self._combined_factor(
                    j_change, j_change_std, vol_ratio)
                base_confidence = (self._J_BASE_CONF +
                                  j_factor * (self._J_MAX_CONF -
                                              self._J_BASE_CONF))
                base_position = (self._J_BUY_POS_MIN +
                                j_factor * (self._J_BUY_POS_MAX -
                                            self._J_BUY_POS_MIN))
                
                # 实盘标准：回调时要求<0.8倍（确认缩量回调，而非资金出逃）
                # 但这里是超卖区拐头，更像是突破，使用'breakout'类型
                confidence, position, turnover_reason = enhance_signal_with_turnover(
                    'breakout', relative_turnover, base_confidence, base_position
                )
                
                vol_desc = f', 量比{vol_ratio:.1f}' if vol_ratio > 1.2 else ''
                turnover_desc = f', {turnover_reason}' if turnover_reason else ''
                return StrategySignal(
                    action='BUY', confidence=round(confidence, 2),
                    position=round(position, 2),
                    reason=f'J值超卖拐头 ({prev_j:.1f}→{cur_j:.1f}){vol_desc}{turnover_desc}',
                    indicators=indicators,
                )
            else:
                return StrategySignal(
                    action='HOLD', confidence=0.4, position=0.20,
                    reason=f'J值超卖({cur_j:.1f})但仍下行，等待拐头',
                    indicators=indicators,
                )

        # ---- 死叉: K 从上方下穿 D ----
        #  K斜率越陡 + 量比越大 → factor 越高 → 置信度越高, 仓位衰减越强
        #  高位死叉(K>70): K位置加成 → base 上浮
        #  仓位随 factor 平滑衰减: pos = max(0, _SELL_POS_MAX * (1 - factor))
        if prev_k >= prev_d and cur_k < cur_d:
            # 实盘标准：流动性过滤（死叉时也检查，但更宽松）
            is_valid, liquidity_reason = check_turnover_liquidity(relative_turnover)
            liquidity_penalty = 0.0 if is_valid else 0.1
            
            factor = self._combined_factor(k_slope, k_slope_std, vol_ratio)
            base_position = max(0, self._SELL_POS_MAX * (1 - factor))
            vol_desc = f', 量比{vol_ratio:.1f}' if vol_ratio > 1.2 else ''

            if cur_k > 70:
                # 高位死叉 → 强卖出, K位置加成
                base = self._BASE_CONF + self._K_POS_BONUS
                base_confidence = base + factor * (self._MAX_CONF - base)
                base_confidence = max(0.0, base_confidence - liquidity_penalty)
                
                # 实盘标准：回调时要求<0.8倍（确认缩量回调，而非资金出逃）
                confidence, position, turnover_reason = enhance_signal_with_turnover(
                    'pullback', relative_turnover, base_confidence, base_position
                )
                
                turnover_desc = f', {turnover_reason}' if turnover_reason else ''
                liquidity_desc = f', {liquidity_reason}' if not is_valid else ''
                return StrategySignal(
                    action='SELL', confidence=round(confidence, 2),
                    position=round(position, 2),
                    reason=f'KDJ高位死叉: K={cur_k:.1f}↓ 下穿 D={cur_d:.1f}'
                           f', J={cur_j:.1f}{vol_desc}{turnover_desc}{liquidity_desc}',
                    indicators=indicators,
                )

            elif cur_k > 50:
                # 中高位死叉 → 有效卖出
                base_confidence = (self._BASE_CONF +
                                  factor * (self._MAX_CONF - self._BASE_CONF))
                base_confidence = max(0.0, base_confidence - liquidity_penalty)
                
                # 实盘标准：回调时要求<0.8倍（确认缩量回调，而非资金出逃）
                confidence, position, turnover_reason = enhance_signal_with_turnover(
                    'pullback', relative_turnover, base_confidence, base_position
                )
                
                turnover_desc = f', {turnover_reason}' if turnover_reason else ''
                liquidity_desc = f', {liquidity_reason}' if not is_valid else ''
                return StrategySignal(
                    action='SELL', confidence=round(confidence, 2),
                    position=round(position, 2),
                    reason=f'KDJ中位死叉: K={cur_k:.1f}↓ 下穿 D={cur_d:.1f}'
                           f'{vol_desc}{turnover_desc}{liquidity_desc}',
                    indicators=indicators,
                )

            else:
                # K≤50 的死叉 → 位置偏低，观望
                return StrategySignal(
                    action='HOLD', confidence=0.45, position=0.40,
                    reason=f'KDJ低位死叉(K={cur_k:.1f}≤50)，位置偏低，观望',
                    indicators=indicators,
                )

        # ---- J值超买（需拐头确认）----
        #  J > 100 且回落: 用 J 变化幅度 + 量比合成 factor
        #  回落幅度越大 → 置信度越高, 仓位越低
        if cur_j > 100:
            if cur_j < prev_j:
                # 实盘标准：流动性过滤（死叉时也检查，但更宽松）
                is_valid, liquidity_reason = check_turnover_liquidity(relative_turnover)
                liquidity_penalty = 0.0 if is_valid else 0.1
                
                j_factor = self._combined_factor(
                    j_change, j_change_std, vol_ratio)
                base_confidence = (self._J_BASE_CONF +
                                  j_factor * (self._J_MAX_CONF -
                                              self._J_BASE_CONF))
                base_confidence = max(0.0, base_confidence - liquidity_penalty)
                # 强回落(factor高) → 低仓位, 弱回落(factor低) → 高仓位
                base_position = (self._J_SELL_POS_MAX -
                                j_factor * (self._J_SELL_POS_MAX -
                                            self._J_SELL_POS_MIN))
                
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
                    reason=f'J值超买拐头 ({prev_j:.1f}→{cur_j:.1f}){vol_desc}{turnover_desc}{liquidity_desc}',
                    indicators=indicators,
                )
            else:
                return StrategySignal(
                    action='HOLD', confidence=0.4, position=0.60,
                    reason=f'J值超买({cur_j:.1f})但仍上行，强势持有',
                    indicators=indicators,
                )

        # ---- 默认 HOLD: 用 K-D 间距动态调整仓位 ----
        #  K > D: 多头区域, |K-D| 越大 → 仓位越高
        #  K < D: 空头区域, |K-D| 越大 → 仓位越低
        #  自适应归一化: 以 kd_gap_std * 2 为满分基准
        cur_gap = abs(cur_k - cur_d)
        gap_threshold = max(kd_gap_std * 2, 1e-6)
        norm_gap = min(cur_gap / gap_threshold, 1.0)

        if cur_k > cur_d:
            position = (self._BULL_POS_MIN +
                        norm_gap * (self._BULL_POS_MAX - self._BULL_POS_MIN))
            return StrategySignal(
                action='HOLD', confidence=0.5,
                position=round(position, 2),
                reason=f'KDJ多头(K>D), K={cur_k:.1f}, D={cur_d:.1f},'
                       f' J={cur_j:.1f}',
                indicators=indicators,
            )

        if cur_k < cur_d:
            position = (self._BEAR_POS_MAX -
                        norm_gap * (self._BEAR_POS_MAX - self._BEAR_POS_MIN))
            return StrategySignal(
                action='HOLD', confidence=0.5,
                position=round(position, 2),
                reason=f'KDJ空头(K<D), K={cur_k:.1f}, D={cur_d:.1f},'
                       f' J={cur_j:.1f}',
                indicators=indicators,
            )

        return StrategySignal(
            action='HOLD', confidence=0.5, position=0.50,
            reason=f'KDJ中性, K={cur_k:.1f}, D={cur_d:.1f}, J={cur_j:.1f}',
            indicators=indicators,
        )
