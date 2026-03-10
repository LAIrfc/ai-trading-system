"""
基本面分位数策略基类

抽取 PE/PB 策略共用的分位数计算逻辑，避免代码重复。
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple
from .base import Strategy, StrategySignal


class FundamentalQuantileBase(Strategy):
    """
    基本面分位数策略基类。

    子类需要定义：
        _FIELD:     DataFrame 中的列名，如 'pe_ttm' 或 'pb'
        _VAL_MAX:   异常值上限（PE 用 100，PB 用 20）
        _VAL_MIN:   异常值下限（默认 0）
    """

    _FIELD: str = ''
    _VAL_MAX: float = 100.0
    _VAL_MIN: float = 0.0

    _BASE_CONF    = 0.60
    _MAX_CONF     = 0.85
    _BUY_POS_MIN  = 0.65
    _BUY_POS_MAX  = 0.85
    _SELL_POS_MIN = 0.0
    _SELL_POS_MAX = 0.15
    _ROLLING_WINDOW = 756   # 3年，覆盖1个完整牛熊周期

    def __init__(self,
                 low_quantile: float = 0.2,
                 high_quantile: float = 0.8,
                 rolling_window: int = None,
                 industry: Optional[str] = None,
                 industry_data: Optional[pd.Series] = None,
                 **kwargs):
        self.low_quantile = low_quantile
        self.high_quantile = high_quantile
        self.rolling_window = rolling_window or self._ROLLING_WINDOW
        self.industry = industry
        self.industry_data = industry_data
        self.min_bars = max(60, self.rolling_window)

    def _calc_quantile(self, series: pd.Series, current_val: float,
                       industry_series: Optional[pd.Series] = None
                       ) -> Tuple[float, float, float, float, str]:
        """
        计算当前值在历史序列中的分位数。

        Returns:
            (quantile, val_min, val_max, val_median, method)
        """
        if industry_series is not None and len(industry_series) >= self.min_bars:
            ref = industry_series
            method = 'industry'
        elif self.rolling_window and len(series) > self.rolling_window:
            ref = series.iloc[-self.rolling_window:]
            method = 'stock'
        else:
            ref = series
            method = 'stock'

        quantile = float((ref < current_val).sum() / len(ref))
        return quantile, float(ref.min()), float(ref.max()), float(ref.median()), method

    def _make_signal_from_quantile(self,
                                   quantile: float,
                                   current_val: float,
                                   indicators: dict) -> StrategySignal:
        """根据分位数生成标准化的买/卖/持有信号。"""
        field_label = self._FIELD.upper().replace('_TTM', '')

        if quantile < self.low_quantile:
            strength = min(1.0, (self.low_quantile - quantile) / self.low_quantile)
            confidence = self._BASE_CONF + strength * (self._MAX_CONF - self._BASE_CONF)
            position = self._BUY_POS_MIN + strength * (self._BUY_POS_MAX - self._BUY_POS_MIN)
            return StrategySignal(
                action='BUY',
                confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f'{field_label}低估(分位{quantile:.1%}，当前{field_label}={current_val:.2f})',
                indicators=indicators,
            )

        if quantile > self.high_quantile:
            strength = min(1.0, (quantile - self.high_quantile) / (1.0 - self.high_quantile))
            confidence = self._BASE_CONF + strength * (self._MAX_CONF - self._BASE_CONF)
            position = self._SELL_POS_MAX - strength * (self._SELL_POS_MAX - self._SELL_POS_MIN)
            return StrategySignal(
                action='SELL',
                confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f'{field_label}高估(分位{quantile:.1%}，当前{field_label}={current_val:.2f})',
                indicators=indicators,
            )

        position = 0.5 + (0.5 - quantile) * 0.2 if quantile < 0.5 else 0.5 - (quantile - 0.5) * 0.2
        return StrategySignal(
            action='HOLD',
            confidence=0.5,
            position=round(position, 2),
            reason=f'{field_label}中性(分位{quantile:.1%}，当前{field_label}={current_val:.2f})',
            indicators=indicators,
        )

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        raise NotImplementedError("子类必须实现 analyze()")
