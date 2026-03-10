"""
PB估值策略（基本面策略）

原理:
- 当PB低于历史分位数（如20%）时买入（估值低估）
- 当PB高于历史分位数（如80%）时卖出（估值高估）
- 其他情况持有

实盘标准:
- 必须分行业计算分位数（不能全市场统一）
- 低PB必须搭配连续3年ROE>8%，否则可能是价值陷阱
- 适用行业：银行/地产/周期股用PB，其他行业保持PE
- 分位数计算：默认使用3年滚动窗口（756天），覆盖1个完整牛熊周期，避免参数过拟合
- 异常值过滤：自动过滤PB<0或PB>20的异常值

参数:
- low_quantile:  买入阈值分位数（默认0.2）
- high_quantile: 卖出阈值分位数（默认0.8）
- rolling_window: 滚动窗口天数（默认756=3年）
- industry: 行业名称（可选）
- industry_pb_data: 行业PB数据序列（可选）
- min_roe: 最低ROE要求（默认8%，用于过滤价值陷阱）
"""

import pandas as pd
from typing import Optional, Tuple
from .base import StrategySignal
from .fundamental_base import FundamentalQuantileBase


class PBStrategy(FundamentalQuantileBase):
    """PB估值策略：基于市净率历史分位数的均值回归策略"""

    name = 'PB估值'
    description = '基于PB历史分位数的估值策略，低PB买入高PB卖出'

    _FIELD   = 'pb'
    _VAL_MAX = 20.0

    # PB 买入仓位略低于 PE（需要 ROE 配合）
    _BUY_POS_MIN  = 0.65
    _BUY_POS_MAX  = 0.85
    _SELL_POS_MAX = 0.15

    _MIN_ROE = 8.0

    param_ranges = {
        'low_quantile':  (0.1, 0.2, 0.3, 0.05),
        'high_quantile': (0.7, 0.8, 0.9, 0.05),
    }

    def __init__(self, low_quantile: float = 0.2,
                 high_quantile: float = 0.8,
                 rolling_window: int = None,
                 industry: Optional[str] = None,
                 industry_pb_data: Optional[pd.Series] = None,
                 min_roe: float = 8.0,
                 **kwargs):
        super().__init__(
            low_quantile=low_quantile,
            high_quantile=high_quantile,
            rolling_window=rolling_window,
            industry=industry,
            industry_data=industry_pb_data,
        )
        self.min_roe = min_roe

    def _check_roe_filter(self, df: pd.DataFrame) -> Tuple[bool, str]:
        """检查ROE过滤条件（低PB必须搭配连续3年ROE>8%）"""
        if 'roe' not in df.columns:
            return True, '无ROE数据（待实现）'
        roe_series = df['roe'].dropna()
        if len(roe_series) < 12:
            return True, 'ROE数据不足（待实现）'
        recent_roe = roe_series.iloc[-12:]
        if (recent_roe > self.min_roe).all():
            return True, f'ROE过滤通过（最近3年均>{self.min_roe}%）'
        failed = (recent_roe <= self.min_roe).sum()
        return False, f'ROE过滤未通过（最近3年有{failed}个季度ROE<={self.min_roe}%，可能是价值陷阱）'

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        if 'pb' not in df.columns:
            return StrategySignal(action='HOLD', confidence=0.0, position=0.5,
                                  reason='缺少PB数据', indicators={})

        series = df['pb'].dropna()
        series = series[(series > self._VAL_MIN) & (series <= self._VAL_MAX)]

        if len(series) < self.min_bars:
            return StrategySignal(
                action='HOLD', confidence=0.0, position=0.5,
                reason=f'PB数据不足(需{self.min_bars}条，实际{len(series)}条)',
                indicators={'pb': None, 'pb_quantile': None},
            )

        current_val = float(series.iloc[-1])
        industry_series = None
        if self.industry_data is not None:
            ind = self.industry_data.dropna()
            industry_series = ind[(ind > self._VAL_MIN) & (ind <= self._VAL_MAX)]

        quantile, val_min, val_max, val_median, method = self._calc_quantile(
            series, current_val, industry_series)

        roe_valid, roe_reason = self._check_roe_filter(df)

        indicators = {
            'pb':             round(current_val, 2),
            'pb_quantile':    round(quantile, 3),
            'pb_min':         round(val_min, 2),
            'pb_max':         round(val_max, 2),
            'pb_median':      round(val_median, 2),
            'rolling_window': self.rolling_window,
            'industry':       self.industry or 'N/A',
            'quantile_method': method,
            'roe_filter':     roe_valid,
            'roe_reason':     roe_reason,
        }

        # 买入时叠加 ROE 惩罚
        if quantile < self.low_quantile and not roe_valid:
            strength = min(1.0, (self.low_quantile - quantile) / self.low_quantile)
            confidence = max(0.0, self._BASE_CONF + strength * (self._MAX_CONF - self._BASE_CONF) - 0.2)
            position = self._BUY_POS_MIN + strength * (self._BUY_POS_MAX - self._BUY_POS_MIN)
            return StrategySignal(
                action='BUY',
                confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f'PB低估(分位{quantile:.1%}，当前PB={current_val:.2f})，但{roe_reason}',
                indicators=indicators,
            )

        return self._make_signal_from_quantile(quantile, current_val, indicators)
