"""
换手率辅助工具（实盘标准）

实盘权威标准：
1. 使用相对换手率（当前换手率/20日均换手率），而非绝对数值
   - 小盘股日常换手率5%属于正常，大盘股5%就是异常放量
   - 相对换手率更标准化，不受股票规模影响

2. 流动性过滤：
   - 相对换手率<0.5倍 → 回避（缩量严重）
   - 相对换手率>3倍 → 警惕利好兑现（异常放量）

3. 信号增强：
   - 突破时要求相对换手率>1.2倍（确认有效突破）
   - 回调时要求<0.8倍（确认缩量回调，而非资金出逃）
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple


def calc_relative_turnover_rate(df: pd.DataFrame, 
                                 ma_period: int = 20) -> Optional[float]:
    """
    计算相对换手率（当前换手率/20日均换手率）
    
    Args:
        df: DataFrame，必须包含 'turnover_rate' 列（换手率，单位：%）
        ma_period: 均线周期（默认20日）
    
    Returns:
        相对换手率（float），如果数据不足或缺失，返回 None
    """
    if 'turnover_rate' not in df.columns:
        return None
    
    turnover = df['turnover_rate'].dropna()
    
    if len(turnover) < ma_period + 1:
        return None
    
    # 计算20日均换手率（不含当日，更稳健）
    avg_turnover = float(turnover.iloc[-(ma_period + 1):-1].mean())
    cur_turnover = float(turnover.iloc[-1])
    
    if avg_turnover <= 0:
        return None
    
    return cur_turnover / avg_turnover


def check_turnover_liquidity(relative_turnover: Optional[float]) -> Tuple[bool, str]:
    """
    检查换手率流动性（实盘标准）
    
    Args:
        relative_turnover: 相对换手率
    
    Returns:
        (is_valid, reason): 
        - is_valid: True表示流动性正常，False表示流动性异常需回避
        - reason: 原因说明
    """
    if relative_turnover is None:
        return True, '无换手率数据'  # 如果没有换手率数据，不强制过滤
    
    if relative_turnover < 0.5:
        return False, f'流动性差(相对换手率{relative_turnover:.2f}倍<0.5)'
    
    if relative_turnover > 3.0:
        return False, f'异常放量(相对换手率{relative_turnover:.2f}倍>3.0，警惕利好兑现)'
    
    return True, '流动性正常'


def enhance_signal_with_turnover(signal_type: str, 
                                  relative_turnover: Optional[float],
                                  base_confidence: float,
                                  base_position: float) -> Tuple[float, float, str]:
    """
    根据换手率增强信号（实盘标准）
    
    Args:
        signal_type: 信号类型 ('breakout', 'pullback', 'other')
        relative_turnover: 相对换手率
        base_confidence: 基础置信度
        base_position: 基础仓位
    
    Returns:
        (enhanced_confidence, enhanced_position, reason):
        - enhanced_confidence: 增强后的置信度
        - enhanced_position: 增强后的仓位
        - reason: 增强原因说明
    """
    if relative_turnover is None:
        return base_confidence, base_position, '无换手率数据'
    
    enhanced_conf = base_confidence
    enhanced_pos = base_position
    reason = ''
    
    if signal_type == 'breakout':
        # 突破时要求相对换手率>1.2倍（确认有效突破）
        if relative_turnover > 1.2:
            # 放量突破，增强信号
            conf_boost = min(0.1, (relative_turnover - 1.2) / 1.8 * 0.1)  # 最多增强0.1
            enhanced_conf = min(1.0, base_confidence + conf_boost)
            reason = f'放量突破(相对换手率{relative_turnover:.2f}倍>1.2)'
        elif relative_turnover < 0.8:
            # 缩量突破，可能是假突破，削弱信号
            conf_penalty = min(0.1, (0.8 - relative_turnover) / 0.8 * 0.1)  # 最多削弱0.1
            enhanced_conf = max(0.0, base_confidence - conf_penalty)
            reason = f'缩量突破(相对换手率{relative_turnover:.2f}倍<0.8，可能假突破)'
        else:
            reason = f'正常突破(相对换手率{relative_turnover:.2f}倍)'
    
    elif signal_type == 'pullback':
        # 回调时要求<0.8倍（确认缩量回调，而非资金出逃）
        if relative_turnover < 0.8:
            # 缩量回调，可能是正常调整，增强信号
            conf_boost = min(0.05, (0.8 - relative_turnover) / 0.8 * 0.05)  # 最多增强0.05
            enhanced_conf = min(1.0, base_confidence + conf_boost)
            reason = f'缩量回调(相对换手率{relative_turnover:.2f}倍<0.8，正常调整)'
        elif relative_turnover > 1.5:
            # 放量回调，可能是资金出逃，削弱信号
            conf_penalty = min(0.1, (relative_turnover - 1.5) / 1.5 * 0.1)  # 最多削弱0.1
            enhanced_conf = max(0.0, base_confidence - conf_penalty)
            reason = f'放量回调(相对换手率{relative_turnover:.2f}倍>1.5，可能资金出逃)'
        else:
            reason = f'正常回调(相对换手率{relative_turnover:.2f}倍)'
    
    else:
        # 其他信号类型，根据换手率适度调整
        if relative_turnover > 1.5:
            # 放量，适度增强
            conf_boost = min(0.05, (relative_turnover - 1.5) / 1.5 * 0.05)
            enhanced_conf = min(1.0, base_confidence + conf_boost)
            reason = f'放量(相对换手率{relative_turnover:.2f}倍>1.5)'
        elif relative_turnover < 0.7:
            # 缩量，适度削弱
            conf_penalty = min(0.05, (0.7 - relative_turnover) / 0.7 * 0.05)
            enhanced_conf = max(0.0, base_confidence - conf_penalty)
            reason = f'缩量(相对换手率{relative_turnover:.2f}倍<0.7)'
        else:
            reason = f'正常(相对换手率{relative_turnover:.2f}倍)'
    
    return enhanced_conf, enhanced_pos, reason
