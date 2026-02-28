"""
PE+PB双因子策略（基本面策略）

实盘标准：双因子共振
- 买入：PE<20%分位 **AND** PB<20%分位（低估时"与"逻辑，提高确定性）
- 卖出：PE>80%分位 **OR** PB>80%分位（高估时"或"逻辑，快速止损）

原理:
- 同时考虑PE和PB两个估值指标
- 低估时要求两个因子都低估（提高确定性）
- 高估时只要一个因子高估就卖出（快速止损）

信号强度动态化:
- 两个因子都极端时，信号更强
- 仓位随信号强度动态调整

注意事项:
- 必须避免未来函数：只能使用已发布的基本面数据
- PE和PB数据需要对齐到日线（使用 ffill 填充）
- 实盘标准：必须分行业计算分位数
- 分位数计算：默认使用3年滚动窗口（756天），覆盖1个完整牛熊周期，避免参数过拟合
- PB策略会检查ROE过滤（低PB必须搭配连续3年ROE>8%）

参数:
- low_quantile:  买入阈值分位数（默认0.2）
- high_quantile: 卖出阈值分位数（默认0.8）
- rolling_window: 滚动窗口天数（默认756=3年）
- industry: 行业名称（可选）
- industry_pe_data: 行业PE数据序列（可选）
- industry_pb_data: 行业PB数据序列（可选）
- min_roe: 最低ROE要求（默认8%，用于PB策略过滤价值陷阱）

仅 low_quantile / high_quantile 参与参数优化。
"""

import pandas as pd
import numpy as np
from typing import Optional
from .base import Strategy, StrategySignal
from .fundamental_pe import PEStrategy
from .fundamental_pb import PBStrategy


class PE_PB_CombinedStrategy(Strategy):
    """PE+PB双因子策略：同时考虑PE和PB两个估值指标"""
    
    name = 'PE+PB双因子'
    description = 'PE和PB双因子共振策略，低估时要求两个因子都低估，高估时只要一个因子高估就卖出'
    
    param_ranges = {
        'low_quantile':  (0.1, 0.2, 0.3, 0.05),
        'high_quantile': (0.7, 0.8, 0.9, 0.05),
    }
    
    # ---- 内部常量（不参与参数优化） ----
    _BASE_CONF = 0.65        # 基础置信度（双因子共振，比单因子略高）
    _MAX_CONF  = 0.90        # 置信度上限
    _BUY_POS_MIN  = 0.70     # 买入最低仓位（双因子共振，比单因子略高）
    _BUY_POS_MAX  = 0.90     # 买入最高仓位
    _SELL_POS_MIN = 0.0      # 卖出最低仓位（清仓）
    _SELL_POS_MAX = 0.10     # 卖出最高仓位（保留少量，比单因子更坚决）
    _ROLLING_WINDOW = 756    # 滚动窗口：3年（756天）
    
    def __init__(self, low_quantile: float = 0.2, 
                 high_quantile: float = 0.8,
                 rolling_window: int = None,
                 industry: Optional[str] = None,
                 industry_pe_data: Optional[pd.Series] = None,
                 industry_pb_data: Optional[pd.Series] = None,
                 min_roe: float = 8.0,
                 **kwargs):
        """
        Args:
            low_quantile:  PE/PB低于此分位数时买入（默认0.2）
            high_quantile: PE/PB高于此分位数时卖出（默认0.8）
            rolling_window: 滚动窗口天数（默认756=3年）
            industry: 行业名称（可选）
            industry_pe_data: 行业PE数据序列（可选）
            industry_pb_data: 行业PB数据序列（可选）
            min_roe: 最低ROE要求（默认8%，用于PB策略过滤价值陷阱）
        """
        self.low_quantile = low_quantile
        self.high_quantile = high_quantile
        self.rolling_window = rolling_window or self._ROLLING_WINDOW
        self.industry = industry
        self.industry_pe_data = industry_pe_data
        self.industry_pb_data = industry_pb_data
        self.min_roe = min_roe
        
        # 创建子策略实例
        self.pe_strategy = PEStrategy(
            low_quantile=low_quantile,
            high_quantile=high_quantile,
            rolling_window=rolling_window,
            industry=industry,
            industry_pe_data=industry_pe_data,
        )
        self.pb_strategy = PBStrategy(
            low_quantile=low_quantile,
            high_quantile=high_quantile,
            rolling_window=rolling_window,
            industry=industry,
            industry_pb_data=industry_pb_data,
            min_roe=min_roe,
        )
        
        # min_bars取两个子策略的最大值
        self.min_bars = max(self.pe_strategy.min_bars, self.pb_strategy.min_bars)
    
    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        """
        分析基本面数据，生成交易信号
        
        实盘标准：
        - 买入：PE<20%分位 **AND** PB<20%分位（低估时"与"逻辑，提高确定性）
        - 卖出：PE>80%分位 **OR** PB>80%分位（高估时"或"逻辑，快速止损）
        
        Args:
            df: DataFrame，必须包含 'pe_ttm' 和 'pb' 列
        
        Returns:
            StrategySignal
        """
        # 运行两个子策略
        pe_signal = self.pe_strategy.analyze(df)
        pb_signal = self.pb_strategy.analyze(df)
        
        # 提取分位数和当前值
        pe_quantile = pe_signal.indicators.get('pe_quantile')
        pb_quantile = pb_signal.indicators.get('pb_quantile')
        current_pe = pe_signal.indicators.get('pe_ttm')
        current_pb = pb_signal.indicators.get('pb')
        
        # 如果任一策略数据不足，返回HOLD
        if pe_quantile is None or pb_quantile is None:
            return StrategySignal(
                action='HOLD', confidence=0.0, position=0.5,
                reason=f'数据不足(PE分位={pe_quantile}, PB分位={pb_quantile})',
                indicators={
                    'pe_quantile': pe_quantile,
                    'pb_quantile': pb_quantile,
                    'pe_signal': pe_signal.action,
                    'pb_signal': pb_signal.action,
                }
            )
        
        indicators = {
            'pe_ttm': current_pe,
            'pb': current_pb,
            'pe_quantile': pe_quantile,
            'pb_quantile': pb_quantile,
            'pe_signal': pe_signal.action,
            'pb_signal': pb_signal.action,
            'pe_confidence': pe_signal.confidence,
            'pb_confidence': pb_signal.confidence,
            'roe_filter': pb_signal.indicators.get('roe_filter', True),
            'roe_reason': pb_signal.indicators.get('roe_reason', ''),
        }
        
        # ---- 买入信号：PE<20%分位 **AND** PB<20%分位 ----
        # 实盘标准：低估时"与"逻辑，提高确定性
        if pe_quantile < self.low_quantile and pb_quantile < self.low_quantile:
            # 两个因子都低估，信号更强
            # 计算综合强度：取两个分位数的平均值
            avg_quantile = (pe_quantile + pb_quantile) / 2
            strength = (self.low_quantile - avg_quantile) / self.low_quantile
            strength = min(1.0, max(0.0, strength))
            
            confidence = self._BASE_CONF + strength * (self._MAX_CONF - self._BASE_CONF)
            position = self._BUY_POS_MIN + strength * (self._BUY_POS_MAX - self._BUY_POS_MIN)
            
            # 如果PB策略的ROE过滤未通过，降低置信度
            if not pb_signal.indicators.get('roe_filter', True):
                confidence = max(0.0, confidence - 0.15)
                roe_suffix = f'，但{pb_signal.indicators.get("roe_reason", "")}'
            else:
                roe_suffix = ''
            
            return StrategySignal(
                action='BUY',
                confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f'PE+PB双低估(PE分位{pe_quantile:.1%}, PB分位{pb_quantile:.1%}, '
                       f'PE={current_pe:.1f}, PB={current_pb:.2f}){roe_suffix}',
                indicators=indicators,
            )
        
        # ---- 卖出信号：PE>80%分位 **OR** PB>80%分位 ----
        # 实盘标准：高估时"或"逻辑，快速止损
        elif pe_quantile > self.high_quantile or pb_quantile > self.high_quantile:
            # 计算综合强度：取两个分位数的最大值（哪个更极端用哪个）
            max_quantile = max(pe_quantile, pb_quantile)
            strength = (max_quantile - self.high_quantile) / (1.0 - self.high_quantile)
            strength = min(1.0, max(0.0, strength))
            
            confidence = self._BASE_CONF + strength * (self._MAX_CONF - self._BASE_CONF)
            position = self._SELL_POS_MAX - strength * (self._SELL_POS_MAX - self._SELL_POS_MIN)
            
            # 判断是哪个因子触发卖出
            if pe_quantile > self.high_quantile and pb_quantile > self.high_quantile:
                trigger = 'PE+PB双高估'
            elif pe_quantile > self.high_quantile:
                trigger = 'PE高估'
            else:
                trigger = 'PB高估'
            
            return StrategySignal(
                action='SELL',
                confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f'{trigger}(PE分位{pe_quantile:.1%}, PB分位{pb_quantile:.1%}, '
                       f'PE={current_pe:.1f}, PB={current_pb:.2f})',
                indicators=indicators,
            )
        
        # ---- 持有：其他情况 ----
        else:
            # 根据两个因子的综合情况给出仓位建议
            avg_quantile = (pe_quantile + pb_quantile) / 2
            if avg_quantile < 0.5:
                position = 0.5 + (0.5 - avg_quantile) * 0.2
            else:
                position = 0.5 - (avg_quantile - 0.5) * 0.2
            
            return StrategySignal(
                action='HOLD',
                confidence=0.5,
                position=round(position, 2),
                reason=f'PE+PB中性(PE分位{pe_quantile:.1%}, PB分位{pb_quantile:.1%}, '
                       f'PE={current_pe:.1f}, PB={current_pb:.2f})',
                indicators=indicators,
            )
