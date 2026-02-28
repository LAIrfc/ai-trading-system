"""
PB估值策略（基本面策略）

原理:
- 当PB低于历史分位数（如20%）时买入（估值低估）
- 当PB高于历史分位数（如80%）时卖出（估值高估）
- 其他情况持有

信号强度动态化:
- 分位数越极端（接近0或1）→ 置信度越高
- 仓位随分位数动态调整

实盘标准:
- 必须分行业计算分位数（不能全市场统一）
- 低PB必须搭配连续3年ROE>8%，否则可能是价值陷阱（待实现ROE数据获取）
- 适用行业：银行/地产/周期股用PB，其他行业保持PE
- 分位数计算：默认使用3年滚动窗口（756天），覆盖1个完整牛熊周期，避免参数过拟合
- 异常值过滤：自动过滤PB<0或PB>20的异常值

参数:
- low_quantile:  买入阈值分位数（默认0.2，即PB低于历史20%时买入）
- high_quantile: 卖出阈值分位数（默认0.8，即PB高于历史80%时卖出）
- rolling_window: 滚动窗口天数（默认756=3年）
- industry: 行业名称（可选）
- industry_pb_data: 行业PB数据序列（可选）
- min_roe: 最低ROE要求（默认8%，用于过滤价值陷阱）

仅 low_quantile / high_quantile 参与参数优化。
rolling_window 为内部常量，不参与优化（避免过拟合）。
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple
from .base import Strategy, StrategySignal


class PBStrategy(Strategy):
    """PB估值策略：基于市净率历史分位数的均值回归策略"""
    
    name = 'PB估值'
    description = '基于PB历史分位数的估值策略，低PB买入高PB卖出'
    
    param_ranges = {
        'low_quantile':  (0.1, 0.2, 0.3, 0.05),
        'high_quantile': (0.7, 0.8, 0.9, 0.05),
    }
    
    # ---- 内部常量（不参与参数优化） ----
    _BASE_CONF = 0.60        # 基础置信度
    _MAX_CONF  = 0.85        # 置信度上限
    _BUY_POS_MIN  = 0.65     # 买入最低仓位
    _BUY_POS_MAX  = 0.85     # 买入最高仓位
    _SELL_POS_MIN = 0.0      # 卖出最低仓位（清仓）
    _SELL_POS_MAX = 0.15     # 卖出最高仓位（保留少量）
    _ROLLING_WINDOW = 756    # 滚动窗口：3年（756天），覆盖1个完整牛熊周期
                            # 实盘标准：固定3年，避免参数过拟合
    _MIN_ROE = 8.0          # 最低ROE要求（%，用于过滤价值陷阱）
    _PB_MAX = 20.0          # PB最大值（过滤异常值）
    
    def __init__(self, low_quantile: float = 0.2, 
                 high_quantile: float = 0.8,
                 rolling_window: int = None,
                 industry: Optional[str] = None,
                 industry_pb_data: Optional[pd.Series] = None,
                 min_roe: float = 8.0,
                 **kwargs):
        """
        Args:
            low_quantile:  PB低于此分位数时买入（默认0.2，即历史20%分位）
            high_quantile: PB高于此分位数时卖出（默认0.8，即历史80%分位）
            rolling_window: 滚动窗口天数（默认756=3年）
                           实盘标准：固定3年（756天），覆盖1个完整牛熊周期，避免参数过拟合
            industry: 行业名称（可选，如 '银行', '房地产', '电子' 等）
                      实盘标准：必须分行业计算PB分位数，不能全市场统一
            industry_pb_data: 行业PB数据序列（可选）
                             如果提供，将使用此数据计算行业分位数
            min_roe: 最低ROE要求（默认8%，用于过滤价值陷阱）
                     实盘标准：低PB必须搭配连续3年ROE>8%，否则可能是价值陷阱
        """
        self.low_quantile = low_quantile
        self.high_quantile = high_quantile
        self.rolling_window = rolling_window or self._ROLLING_WINDOW
        self.industry = industry
        self.industry_pb_data = industry_pb_data
        self.min_roe = min_roe
        # min_bars: 需要足够历史数据计算分位数
        if self.rolling_window:
            self.min_bars = max(60, self.rolling_window)
        else:
            self.min_bars = 60
    
    def _check_roe_filter(self, df: pd.DataFrame) -> Tuple[bool, str]:
        """
        检查ROE过滤条件（实盘标准：低PB必须搭配连续3年ROE>8%）
        
        Args:
            df: DataFrame，可能包含 'roe' 列
        
        Returns:
            (is_valid, reason): 
            - is_valid: True表示通过ROE过滤，False表示未通过
            - reason: 原因说明
        """
        if 'roe' not in df.columns:
            # 如果没有ROE数据，暂时不强制过滤（待ROE数据获取实现后启用）
            return True, '无ROE数据（待实现）'
        
        roe_series = df['roe'].dropna()
        if len(roe_series) < 12:  # 至少需要3年数据（12个季度）
            return True, 'ROE数据不足（待实现）'
        
        # 检查最近3年（12个季度）的ROE是否都>min_roe
        recent_roe = roe_series.iloc[-12:]
        if (recent_roe > self.min_roe).all():
            return True, f'ROE过滤通过（最近3年均>{self.min_roe}%）'
        else:
            failed_count = (recent_roe <= self.min_roe).sum()
            return False, f'ROE过滤未通过（最近3年有{failed_count}个季度ROE<={self.min_roe}%，可能是价值陷阱）'
    
    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        """
        分析基本面数据，生成交易信号
        
        Args:
            df: DataFrame，必须包含 'pb' 列（市净率）
        
        Returns:
            StrategySignal
        """
        # 检查是否有PB数据
        if 'pb' not in df.columns:
            return StrategySignal(
                action='HOLD', confidence=0.0, position=0.5,
                reason='缺少PB数据',
                indicators={}
            )
        
        pb_series = df['pb'].dropna()
        
        # 实盘标准：过滤异常值（PB<0或PB>20）
        # PB<0表示异常，PB>20通常表示异常高估或数据错误
        pb_series = pb_series[(pb_series > 0) & (pb_series <= self._PB_MAX)]
        
        if len(pb_series) < self.min_bars:
            return StrategySignal(
                action='HOLD', confidence=0.0, position=0.5,
                reason=f'PB数据不足(需{self.min_bars}条，实际{len(pb_series)}条)',
                indicators={'pb': None, 'pb_quantile': None}
            )
        
        current_pb = float(pb_series.iloc[-1])
        
        # 实盘标准：分行业计算分位数
        if self.industry_pb_data is not None and len(self.industry_pb_data) > 0:
            # 使用行业PB数据计算分位数
            industry_pb = self.industry_pb_data.dropna()
            industry_pb = industry_pb[(industry_pb > 0) & (industry_pb <= self._PB_MAX)]
            
            if len(industry_pb) >= self.min_bars:
                quantile = float((industry_pb < current_pb).sum() / len(industry_pb))
                pb_min = float(industry_pb.min())
                pb_max = float(industry_pb.max())
                pb_median = float(industry_pb.median())
                quantile_method = 'industry'
            else:
                # 行业数据不足，回退到当前股票数据
                quantile_method = 'stock_fallback'
                if self.rolling_window and len(pb_series) > self.rolling_window:
                    window_size = min(self.rolling_window, len(pb_series))
                    recent_pb = pb_series.iloc[-window_size:]
                    quantile = float(recent_pb.rank(pct=True).iloc[-1])
                    pb_min = float(recent_pb.min())
                    pb_max = float(recent_pb.max())
                    pb_median = float(recent_pb.median())
                else:
                    quantile = float(pb_series.rank(pct=True).iloc[-1])
                    pb_min = float(pb_series.min())
                    pb_max = float(pb_series.max())
                    pb_median = float(pb_series.median())
        else:
            # 使用当前股票的PB数据计算分位数（默认方式）
            quantile_method = 'stock'
            if self.rolling_window and len(pb_series) > self.rolling_window:
                window_size = min(self.rolling_window, len(pb_series))
                recent_pb = pb_series.iloc[-window_size:]
                quantile = float(recent_pb.rank(pct=True).iloc[-1])
                pb_min = float(recent_pb.min())
                pb_max = float(recent_pb.max())
                pb_median = float(recent_pb.median())
            else:
                quantile = float(pb_series.rank(pct=True).iloc[-1])
                pb_min = float(pb_series.min())
                pb_max = float(pb_series.max())
                pb_median = float(pb_series.median())
        
        # 实盘标准：ROE过滤（低PB必须搭配连续3年ROE>8%）
        roe_valid, roe_reason = self._check_roe_filter(df)
        
        indicators = {
            'pb': round(current_pb, 2),
            'pb_quantile': round(quantile, 3),
            'pb_min': round(pb_min, 2),
            'pb_max': round(pb_max, 2),
            'pb_median': round(pb_median, 2),
            'rolling_window': self.rolling_window if self.rolling_window else 'all',
            'industry': self.industry if self.industry else 'N/A',
            'quantile_method': quantile_method,
            'roe_filter': roe_valid,
            'roe_reason': roe_reason,
        }
        
        # ---- 买入信号：PB低估 ----
        if quantile < self.low_quantile:
            # ROE过滤：如果未通过ROE过滤，降低置信度或回避
            if not roe_valid:
                # 可能是价值陷阱，降低置信度
                roe_penalty = 0.2
                reason_suffix = f'，但{roe_reason}'
            else:
                roe_penalty = 0.0
                reason_suffix = ''
            
            strength = (self.low_quantile - quantile) / self.low_quantile
            strength = min(1.0, max(0.0, strength))
            
            base_confidence = self._BASE_CONF + strength * (self._MAX_CONF - self._BASE_CONF)
            confidence = max(0.0, base_confidence - roe_penalty)
            position = self._BUY_POS_MIN + strength * (self._BUY_POS_MAX - self._BUY_POS_MIN)
            
            return StrategySignal(
                action='BUY',
                confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f'PB低估(分位{quantile:.1%}，当前PB={current_pb:.2f}){reason_suffix}',
                indicators=indicators,
            )
        
        # ---- 卖出信号：PB高估 ----
        elif quantile > self.high_quantile:
            strength = (quantile - self.high_quantile) / (1.0 - self.high_quantile)
            strength = min(1.0, max(0.0, strength))
            
            confidence = self._BASE_CONF + strength * (self._MAX_CONF - self._BASE_CONF)
            position = self._SELL_POS_MAX - strength * (self._SELL_POS_MAX - self._SELL_POS_MIN)
            
            return StrategySignal(
                action='SELL',
                confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f'PB高估(分位{quantile:.1%}，当前PB={current_pb:.2f})',
                indicators=indicators,
            )
        
        # ---- 持有：PB中性区间 ----
        else:
            if quantile < 0.5:
                position = 0.5 + (0.5 - quantile) * 0.2
            else:
                position = 0.5 - (quantile - 0.5) * 0.2
            
            return StrategySignal(
                action='HOLD',
                confidence=0.5,
                position=round(position, 2),
                reason=f'PB中性(分位{quantile:.1%}，当前PB={current_pb:.2f})',
                indicators=indicators,
            )
