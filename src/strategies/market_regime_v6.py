#!/usr/bin/env python3
"""
市场状态检测模块 v6.1（Soft Regime Score）

输出连续的regime score，而非硬标签
"""

import numpy as np
import pandas as pd


class SoftRegimeDetector:
    """
    软市场状态检测器（机构级）
    
    输出连续的regime score，而非硬标签
    """
    def __init__(self, trend_weight=0.6, vol_weight=0.4):
        """
        Args:
            trend_weight: 趋势强度权重
            vol_weight: 波动率权重（负向）
        """
        self.trend_weight = trend_weight
        self.vol_weight = vol_weight
    
    def calc_regime_score(self, index_df):
        """
        计算市场状态得分（连续）
        
        Args:
            index_df: 指数K线数据
        
        Returns:
            float: regime_score ∈ [-1, 1]
                +1: 强趋势市
                 0: 中性
                -1: 强震荡市
        """
        close = index_df['close']
        
        # 1. 趋势强度：MA20/MA60 - 1
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        
        if pd.isna(ma20) or pd.isna(ma60) or ma60 == 0:
            return 0.0
        
        trend_strength = ma20 / ma60 - 1
        
        # 2. 波动率：20日收益率标准差
        returns = close.pct_change()
        vol = returns.rolling(20).std().iloc[-1]
        
        if pd.isna(vol):
            vol = 0.02  # 默认波动率
        
        # 3. 复合得分
        # 趋势强 + 波动率低 → 趋势市（正分）
        # 趋势弱 + 波动率高 → 震荡市（负分）
        score = self.trend_weight * trend_strength - self.vol_weight * vol
        
        # 4. tanh压缩到[-1, 1]
        regime_score = np.tanh(score)
        
        return regime_score
    
    def get_dynamic_weights(self, regime_score):
        """
        根据regime score动态调整因子权重
        
        Args:
            regime_score: float ∈ [-1, 1]
        
        Returns:
            list: [w_base, w_tech, w_rs, w_vol]
        """
        # 趋势市权重
        w_trend = np.array([0.5, 0.3, 0.1, 0.1])
        
        # 震荡市权重
        w_range = np.array([0.3, 0.3, 0.2, 0.2])
        
        # 线性插值（连续过渡）
        # regime_score = +1 → 100% w_trend
        # regime_score =  0 → 50% w_trend + 50% w_range
        # regime_score = -1 → 100% w_range
        alpha = (regime_score + 1) / 2  # 映射到[0, 1]
        weights = alpha * w_trend + (1 - alpha) * w_range
        
        return weights.tolist()
    
    def get_regime_features(self, index_df):
        """
        提取市场状态特征（用于监控）
        
        Returns:
            dict: {
                'regime_score': float,
                'trend_strength': float,
                'volatility': float,
                'adx': float,
                'ma20_slope': float
            }
        """
        close = index_df['close']
        
        # 趋势强度
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        trend_strength = ma20 / ma60 - 1 if ma60 != 0 else 0.0
        
        # 波动率
        returns = close.pct_change()
        volatility = returns.rolling(20).std().iloc[-1]
        if pd.isna(volatility):
            volatility = 0.02
        
        # ADX
        adx = self._calc_adx(index_df)
        
        # MA20斜率
        ma20_series = close.rolling(20).mean()
        ma20_slope = ma20_series.iloc[-1] / ma20_series.iloc[-5] - 1 if len(ma20_series) >= 5 else 0.0
        
        # Regime Score
        regime_score = self.calc_regime_score(index_df)
        
        return {
            'regime_score': regime_score,
            'trend_strength': trend_strength,
            'volatility': volatility,
            'adx': adx,
            'ma20_slope': ma20_slope
        }
    
    def _calc_adx(self, df, period=14):
        """计算ADX（辅助函数）"""
        try:
            high, low, close = df['high'], df['low'], df['close']
            
            # True Range
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)
            
            atr = tr.rolling(period).mean()
            
            # Directional Movement
            plus_dm = (high - high.shift()).clip(lower=0)
            minus_dm = (low.shift() - low).clip(lower=0)
            
            plus_di = 100 * (plus_dm.rolling(period).mean() / (atr + 1e-8))
            minus_di = 100 * (minus_dm.rolling(period).mean() / (atr + 1e-8))
            
            dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-8)
            adx = dx.rolling(period).mean().iloc[-1]
            
            return adx if not pd.isna(adx) else 20.0
        except Exception:
            return 20.0  # 默认ADX
