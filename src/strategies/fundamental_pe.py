"""
PE估值策略（基本面策略）

原理:
- 当PE低于历史分位数（如20%）时买入（估值低估）
- 当PE高于历史分位数（如80%）时卖出（估值高估）
- 其他情况持有

信号强度动态化:
- 分位数越极端（接近0或1）→ 置信度越高
- 仓位随分位数动态调整

注意事项:
- 必须避免未来函数：只能使用已发布的基本面数据
- PE数据需要对齐到日线（使用 ffill 填充）
- ⚠️ 实盘标准：不同行业PE差异巨大，必须分行业计算分位数（当前为全历史分位数，待实现行业分类）
- 分位数计算：默认使用3年滚动窗口（756天），覆盖1个完整牛熊周期，避免参数过拟合
- 异常值过滤：自动过滤PE<0或PE>100的异常值

参数:
- low_quantile:  买入阈值分位数（默认0.2，即PE低于历史20%时买入）
- high_quantile: 卖出阈值分位数（默认0.8，即PE高于历史80%时卖出）
- rolling_window: 滚动窗口天数（默认None=全部历史，如252=1年，1260=5年）

仅 low_quantile / high_quantile 参与参数优化。
rolling_window 为内部常量，不参与优化（避免过拟合）。
"""

import pandas as pd
import numpy as np
from typing import Optional
from .base import Strategy, StrategySignal


class PEStrategy(Strategy):
    """PE估值策略：基于市盈率历史分位数的均值回归策略"""
    
    name = 'PE估值'
    description = '基于PE历史分位数的估值策略，低PE买入高PE卖出'
    
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
                            # 历史：None=全部历史，252=1年，1260=5年
    
    def __init__(self, low_quantile: float = 0.2, 
                 high_quantile: float = 0.8,
                 rolling_window: int = None,
                 industry: Optional[str] = None,
                 industry_pe_data: Optional[pd.Series] = None,
                 **kwargs):
        """
        Args:
            low_quantile:  PE低于此分位数时买入（默认0.2，即历史20%分位）
            high_quantile: PE高于此分位数时卖出（默认0.8，即历史80%分位）
            rolling_window: 滚动窗口天数（默认756=3年）
                           实盘标准：固定3年（756天），覆盖1个完整牛熊周期，避免参数过拟合
                           历史：None=全部历史，252=1年，1260=5年
                           设置后只使用最近N天的PE数据计算分位数，避免早期数据影响
            industry: 行业名称（可选，如 '银行', '房地产', '电子' 等）
                      实盘标准：必须分行业计算PE分位数，不能全市场统一
                      如果提供，将使用行业PE数据计算分位数
            industry_pe_data: 行业PE数据序列（可选）
                             如果提供，将使用此数据计算行业分位数
                             如果未提供但industry不为None，将使用当前股票的PE数据作为行业数据（简化版本）
        """
        self.low_quantile = low_quantile
        self.high_quantile = high_quantile
        self.rolling_window = rolling_window or self._ROLLING_WINDOW
        self.industry = industry
        self.industry_pe_data = industry_pe_data
        # min_bars: 需要足够历史数据计算分位数
        # 如果使用滚动窗口，min_bars至少等于窗口大小
        if self.rolling_window:
            self.min_bars = max(60, self.rolling_window)
        else:
            self.min_bars = 60
    
    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        """
        分析基本面数据，生成交易信号
        
        Args:
            df: DataFrame，必须包含 'pe_ttm' 列（PE滚动市盈率）
        
        Returns:
            StrategySignal
        """
        # 检查是否有PE数据
        if 'pe_ttm' not in df.columns:
            return StrategySignal(
                action='HOLD', confidence=0.0, position=0.5,
                reason='缺少PE数据',
                indicators={}
            )
        
        pe_series = df['pe_ttm'].dropna()
        
        # 实盘标准：过滤异常值（PE<0或PE>100）
        # PE<0表示亏损，PE>100通常表示异常高估或数据错误
        pe_series = pe_series[(pe_series > 0) & (pe_series <= 100)]
        
        if len(pe_series) < self.min_bars:
            return StrategySignal(
                action='HOLD', confidence=0.0, position=0.5,
                reason=f'PE数据不足(需{self.min_bars}条，实际{len(pe_series)}条)',
                indicators={'pe_ttm': None, 'pe_quantile': None}
            )
        
        current_pe = float(pe_series.iloc[-1])
        
        # 实盘标准：分行业计算分位数
        # 如果提供了行业PE数据，使用行业数据计算分位数
        # 否则使用当前股票的PE数据（简化版本，后续可扩展为获取同行业所有股票的PE数据）
        if self.industry_pe_data is not None and len(self.industry_pe_data) > 0:
            # 使用行业PE数据计算分位数
            industry_pe = self.industry_pe_data.dropna()
            industry_pe = industry_pe[(industry_pe > 0) & (industry_pe <= 100)]
            
            if len(industry_pe) >= self.min_bars:
                # 计算当前PE在行业PE数据中的分位数
                quantile = float((industry_pe < current_pe).sum() / len(industry_pe))
                pe_min = float(industry_pe.min())
                pe_max = float(industry_pe.max())
                pe_median = float(industry_pe.median())
                quantile_method = 'industry'
            else:
                # 行业数据不足，回退到当前股票数据
                quantile_method = 'stock_fallback'
                if self.rolling_window and len(pe_series) > self.rolling_window:
                    window_size = min(self.rolling_window, len(pe_series))
                    recent_pe = pe_series.iloc[-window_size:]
                    quantile = float(recent_pe.rank(pct=True).iloc[-1])
                    pe_min = float(recent_pe.min())
                    pe_max = float(recent_pe.max())
                    pe_median = float(recent_pe.median())
                else:
                    quantile = float(pe_series.rank(pct=True).iloc[-1])
                    pe_min = float(pe_series.min())
                    pe_max = float(pe_series.max())
                    pe_median = float(pe_series.median())
        else:
            # 使用当前股票的PE数据计算分位数（默认方式）
            quantile_method = 'stock'
            if self.rolling_window and len(pe_series) > self.rolling_window:
                # 使用滚动窗口：只取最近N天的PE数据
                window_size = min(self.rolling_window, len(pe_series))
                recent_pe = pe_series.iloc[-window_size:]
                # 计算当前PE在滚动窗口中的分位数
                quantile = float(recent_pe.rank(pct=True).iloc[-1])
                # 更新indicators中的统计信息（使用滚动窗口）
                pe_min = float(recent_pe.min())
                pe_max = float(recent_pe.max())
                pe_median = float(recent_pe.median())
            else:
                # 使用全部历史数据
                quantile = float(pe_series.rank(pct=True).iloc[-1])
                pe_min = float(pe_series.min())
                pe_max = float(pe_series.max())
                pe_median = float(pe_series.median())
        
        indicators = {
            'pe_ttm': round(current_pe, 2),
            'pe_quantile': round(quantile, 3),
            'pe_min': round(pe_min, 2),
            'pe_max': round(pe_max, 2),
            'pe_median': round(pe_median, 2),
            'rolling_window': self.rolling_window if self.rolling_window else 'all',
            'industry': self.industry if self.industry else 'N/A',
            'quantile_method': quantile_method,  # 'industry', 'stock', 'stock_fallback'
        }
        
        # ---- 买入信号：PE低估 ----
        if quantile < self.low_quantile:
            # 分位数越接近0，信号越强
            # 例如：quantile=0.05 时，强度 = (0.2 - 0.05) / 0.2 = 0.75
            strength = (self.low_quantile - quantile) / self.low_quantile
            strength = min(1.0, max(0.0, strength))  # clamp to [0, 1]
            
            confidence = self._BASE_CONF + strength * (self._MAX_CONF - self._BASE_CONF)
            position = self._BUY_POS_MIN + strength * (self._BUY_POS_MAX - self._BUY_POS_MIN)
            
            return StrategySignal(
                action='BUY',
                confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f'PE低估(分位{quantile:.1%}，当前PE={current_pe:.1f})',
                indicators=indicators,
            )
        
        # ---- 卖出信号：PE高估 ----
        elif quantile > self.high_quantile:
            # 分位数越接近1，信号越强
            # 例如：quantile=0.95 时，强度 = (0.95 - 0.8) / (1 - 0.8) = 0.75
            strength = (quantile - self.high_quantile) / (1.0 - self.high_quantile)
            strength = min(1.0, max(0.0, strength))  # clamp to [0, 1]
            
            confidence = self._BASE_CONF + strength * (self._MAX_CONF - self._BASE_CONF)
            # 卖出仓位：强信号→清仓，弱信号→保留少量
            position = self._SELL_POS_MAX - strength * (self._SELL_POS_MAX - self._SELL_POS_MIN)
            
            return StrategySignal(
                action='SELL',
                confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f'PE高估(分位{quantile:.1%}，当前PE={current_pe:.1f})',
                indicators=indicators,
            )
        
        # ---- 持有：PE中性区间 ----
        else:
            # 根据分位数位置给出中性偏多/偏空的仓位建议
            # 分位数接近 low_quantile → 偏多，接近 high_quantile → 偏空
            if quantile < 0.5:
                # 偏低估区域，仓位稍高
                position = 0.5 + (0.5 - quantile) * 0.2  # [0.5, 0.6]
            else:
                # 偏高估区域，仓位稍低
                position = 0.5 - (quantile - 0.5) * 0.2  # [0.4, 0.5]
            
            return StrategySignal(
                action='HOLD',
                confidence=0.5,
                position=round(position, 2),
                reason=f'PE中性(分位{quantile:.1%}，当前PE={current_pe:.1f})',
                indicators=indicators,
            )
