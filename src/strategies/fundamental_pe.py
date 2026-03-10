"""
PE估值策略（基本面策略）

原理:
- 当PE低于历史分位数（如20%）时买入（估值低估）
- 当PE高于历史分位数（如80%）时卖出（估值高估）
- 其他情况持有

实盘标准:
- 必须分行业计算分位数（不能全市场统一）
- 分位数计算：默认使用3年滚动窗口（756天），覆盖1个完整牛熊周期，避免参数过拟合
- 异常值过滤：自动过滤PE<0或PE>100的异常值

参数:
- low_quantile:  买入阈值分位数（默认0.2）
- high_quantile: 卖出阈值分位数（默认0.8）
- rolling_window: 滚动窗口天数（默认756=3年）
- industry: 行业名称（可选）
- industry_pe_data: 行业PE数据序列（可选）
"""

import pandas as pd
from typing import Optional
from .base import StrategySignal
from .fundamental_base import FundamentalQuantileBase


class PEStrategy(FundamentalQuantileBase):
    """PE估值策略：基于市盈率历史分位数的均值回归策略"""

    name = 'PE估值'
    description = '基于PE历史分位数的估值策略，低PE买入高PE卖出'

    _FIELD   = 'pe_ttm'
    _VAL_MAX = 100.0

    param_ranges = {
        'low_quantile':  (0.1, 0.2, 0.3, 0.05),
        'high_quantile': (0.7, 0.8, 0.9, 0.05),
    }

    def __init__(self, low_quantile: float = 0.2,
                 high_quantile: float = 0.8,
                 rolling_window: int = None,
                 industry: Optional[str] = None,
                 industry_pe_data: Optional[pd.Series] = None,
                 **kwargs):
        super().__init__(
            low_quantile=low_quantile,
            high_quantile=high_quantile,
            rolling_window=rolling_window,
            industry=industry,
            industry_data=industry_pe_data,
        )

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        if 'pe_ttm' not in df.columns:
            return StrategySignal(action='HOLD', confidence=0.0, position=0.5,
                                  reason='缺少PE数据', indicators={})

        series = df['pe_ttm'].dropna()
        series = series[(series > self._VAL_MIN) & (series <= self._VAL_MAX)]

        if len(series) < self.min_bars:
            return StrategySignal(
                action='HOLD', confidence=0.0, position=0.5,
                reason=f'PE数据不足(需{self.min_bars}条，实际{len(series)}条)',
                indicators={'pe_ttm': None, 'pe_quantile': None},
            )

        current_val = float(series.iloc[-1])
        industry_series = None
        if self.industry_data is not None:
            ind = self.industry_data.dropna()
            industry_series = ind[(ind > self._VAL_MIN) & (ind <= self._VAL_MAX)]

        quantile, val_min, val_max, val_median, method = self._calc_quantile(
            series, current_val, industry_series)

        indicators = {
            'pe_ttm':         round(current_val, 2),
            'pe_quantile':    round(quantile, 3),
            'pe_min':         round(val_min, 2),
            'pe_max':         round(val_max, 2),
            'pe_median':      round(val_median, 2),
            'rolling_window': self.rolling_window,
            'industry':       self.industry or 'N/A',
            'quantile_method': method,
        }
        return self._make_signal_from_quantile(quantile, current_val, indicators)
