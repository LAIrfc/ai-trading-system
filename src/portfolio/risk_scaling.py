#!/usr/bin/env python3
"""
风险调整模块（Volatility Scaling）

根据个股波动率调整权重，实现风险平价
"""

import numpy as np
import pandas as pd


class VolatilityScaler:
    """
    波动率调整器（机构级）
    
    根据个股波动率调整权重，实现风险平价
    """
    def __init__(self, target_vol=0.15, lookback=60):
        """
        Args:
            target_vol: 目标组合波动率（年化）
            lookback: 波动率计算窗口（交易日）
        """
        self.target_vol = target_vol
        self.lookback = lookback
    
    def calc_volatility(self, df):
        """
        计算个股波动率（年化）
        
        Args:
            df: K线数据
        
        Returns:
            float: 年化波动率
        """
        if 'close' not in df.columns or len(df) < 2:
            return np.nan
        
        returns = df['close'].pct_change().dropna()
        if len(returns) < self.lookback:
            # 数据不足，使用全部数据
            recent_returns = returns
        else:
            # 使用最近lookback日的收益率
            recent_returns = returns.iloc[-self.lookback:]
        
        if len(recent_returns) < 5:
            return np.nan
        
        # 日波动率 → 年化波动率（√252）
        daily_vol = recent_returns.std()
        annual_vol = daily_vol * np.sqrt(252)
        
        return annual_vol
    
    def scale_weights(self, raw_weights, vol_dict):
        """
        波动率调整权重
        
        Args:
            raw_weights: dict {code: raw_weight}
            vol_dict: dict {code: volatility}
        
        Returns:
            dict: {code: scaled_weight}
        """
        scaled = {}
        for code, w in raw_weights.items():
            vol = vol_dict.get(code, np.nan)
            if np.isnan(vol) or vol < 0.01:
                # 波动率缺失或过小，使用原权重
                scaled[code] = w
            else:
                # 权重 ∝ 1/波动率（风险平价）
                scaled[code] = w / vol
        
        # 归一化
        total = sum(scaled.values())
        if total > 0:
            scaled = {k: v / total for k, v in scaled.items()}
        else:
            # 全部无效，使用原权重
            return raw_weights
        
        return scaled
    
    def target_volatility_scaling(self, weights, vol_dict, current_capital=None):
        """
        目标波动率调整（组合级别）
        
        根据组合整体波动率，调整杠杆倍数
        
        Args:
            weights: dict {code: weight}
            vol_dict: dict {code: volatility}
            current_capital: 当前资金（未使用，保留接口）
        
        Returns:
            tuple: (adjusted_weights, leverage)
        """
        # 计算组合波动率（简化：假设个股不相关）
        portfolio_vol = 0.0
        for code, w in weights.items():
            vol = vol_dict.get(code, 0.0)
            if not np.isnan(vol):
                portfolio_vol += (w * vol) ** 2
        portfolio_vol = np.sqrt(portfolio_vol)
        
        # 杠杆倍数 = 目标波动率 / 组合波动率
        if portfolio_vol > 0.01:
            leverage = self.target_vol / portfolio_vol
        else:
            leverage = 1.0
        
        # 限制杠杆范围 [0.5, 2.0]
        leverage = np.clip(leverage, 0.5, 2.0)
        
        # 调整权重
        adjusted_weights = {k: v * leverage for k, v in weights.items()}
        
        return adjusted_weights, leverage
