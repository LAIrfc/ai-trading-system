#!/usr/bin/env python3
"""
趋势策略模块
包含四个趋势相关策略类，用于双引擎调度架构
"""

import pandas as pd
import numpy as np


def wilder_smooth(series, period):
    """Wilder平滑（EMA with alpha=1/period）"""
    return series.ewm(alpha=1/period, adjust=False).mean()


class ADX_Trend:
    """ADX趋势开关，返回signal和score"""
    def __init__(self, adx_threshold=20, di_period=14, use_ma_filter=False, ma_period=20):
        self.adx_threshold = adx_threshold
        self.di_period = di_period
        self.use_ma_filter = use_ma_filter
        self.ma_period = ma_period

    def generate_signals(self, df, params=None):
        if params is not None:
            adx_threshold = params.get('adx_threshold', self.adx_threshold)
            di_period = params.get('di_period', self.di_period)
            use_ma_filter = params.get('use_ma_filter', self.use_ma_filter)
            ma_period = params.get('ma_period', self.ma_period)
        else:
            adx_threshold = self.adx_threshold
            di_period = self.di_period
            use_ma_filter = self.use_ma_filter
            ma_period = self.ma_period

        df = df.copy()
        close = df['close']
        high = df['high']
        low = df['low']

        tr = pd.DataFrame({
            'hl': high - low,
            'hc': abs(high - close.shift(1)),
            'lc': abs(low - close.shift(1))
        }).max(axis=1)
        atr = wilder_smooth(tr, di_period)

        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

        plus_di = 100 * wilder_smooth(pd.Series(plus_dm, index=df.index), di_period) / atr
        minus_di = 100 * wilder_smooth(pd.Series(minus_dm, index=df.index), di_period) / atr
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = wilder_smooth(dx, di_period)

        trend_strong = (adx > adx_threshold)
        long_cond = (plus_di > minus_di) & trend_strong
        short_cond = (minus_di > plus_di) & trend_strong

        if use_ma_filter:
            ma = close.rolling(ma_period).mean()
            long_cond = long_cond & (close > ma)
            short_cond = short_cond & (close < ma)

        df['signal'] = 0
        df.loc[long_cond, 'signal'] = 1
        df.loc[short_cond, 'signal'] = -1
        df['score'] = df['signal'].astype(float)

        valid_mask = (~atr.isna()) & (~adx.isna())
        df.loc[~valid_mask, ['signal', 'score']] = 0
        return df


class MA_Alignment:
    """均线排列，返回连续score和signal"""
    def __init__(self, ma_periods=[5,10,20,60], weights=[0.2,0.3,0.5],
                 long_threshold=0.66, short_threshold=0.33):
        self.ma_periods = ma_periods
        self.weights = weights
        self.long_threshold = long_threshold
        self.short_threshold = short_threshold

    def generate_signals(self, df, params=None):
        if params is not None:
            ma_periods = params.get('ma_periods', self.ma_periods)
            weights = params.get('weights', self.weights)
            long_threshold = params.get('long_threshold', self.long_threshold)
            short_threshold = params.get('short_threshold', self.short_threshold)
        else:
            ma_periods = self.ma_periods
            weights = self.weights
            long_threshold = self.long_threshold
            short_threshold = self.short_threshold
        
        # 校验weights长度与ma_periods匹配
        if len(weights) != len(ma_periods) - 1:
            raise ValueError(f"weights长度({len(weights)})必须等于ma_periods长度-1({len(ma_periods)-1})")

        df = df.copy()
        close = df['close']
        mas = {p: close.rolling(p).mean() for p in ma_periods}

        score = pd.Series(0.0, index=df.index)
        for i in range(len(ma_periods)-1):
            score += weights[i] * (mas[ma_periods[i]] > mas[ma_periods[i+1]]).astype(int)

        alignment_factor = (score - 0.5) * 2

        df['signal'] = 0
        df.loc[alignment_factor > long_threshold, 'signal'] = 1
        df.loc[alignment_factor < -short_threshold, 'signal'] = -1
        df['score'] = alignment_factor

        valid_mask = pd.Series(True, index=df.index)
        for ma in mas.values():
            valid_mask &= ~ma.isna()
        df.loc[~valid_mask, ['signal', 'score']] = 0
        return df


class Momentum_Adj:
    """波动率调整动量，返回连续score和signal"""
    def __init__(self, lookback=20, atr_period=14, ewm_span=50, entry_threshold=0.5):
        self.lookback = lookback
        self.atr_period = atr_period
        self.ewm_span = ewm_span
        self.entry_threshold = entry_threshold

    def generate_signals(self, df, params=None):
        if params is not None:
            lookback = params.get('lookback', self.lookback)
            atr_period = params.get('atr_period', self.atr_period)
            ewm_span = params.get('ewm_span', self.ewm_span)
            entry_threshold = params.get('entry_threshold', self.entry_threshold)
        else:
            lookback = self.lookback
            atr_period = self.atr_period
            ewm_span = self.ewm_span
            entry_threshold = self.entry_threshold

        df = df.copy()
        close = df['close']
        high = df['high']
        low = df['low']

        tr = pd.DataFrame({
            'hl': high - low,
            'hc': abs(high - close.shift(1)),
            'lc': abs(low - close.shift(1))
        }).max(axis=1)
        atr = wilder_smooth(tr, atr_period)
        atr = atr.replace(0, np.nan)

        momentum = close.pct_change(lookback)
        adj_momentum = momentum / (atr + 1e-8)

        ewm_std = adj_momentum.ewm(span=ewm_span, min_periods=20).std()
        norm_momentum = adj_momentum / (ewm_std + 1e-8)
        norm_momentum = np.clip(norm_momentum, -3, 3) / 3

        df['signal'] = 0
        df.loc[norm_momentum > entry_threshold, 'signal'] = 1
        df.loc[norm_momentum < -entry_threshold, 'signal'] = -1
        df['score'] = norm_momentum

        valid_mask = (~atr.isna()) & (~ewm_std.isna())
        df.loc[~valid_mask, ['signal', 'score']] = 0
        return df


class Trend_Composite:
    """复合趋势因子，返回signal、score和trend_score"""
    def __init__(self, adx_threshold=20, adx_weight=0.5, alignment_weight=0.3, momentum_weight=0.2,
                 long_threshold=0.6, short_threshold=0.6):
        self.adx_threshold = adx_threshold
        self.adx_weight = adx_weight
        self.alignment_weight = alignment_weight
        self.momentum_weight = momentum_weight
        self.long_threshold = long_threshold
        self.short_threshold = short_threshold

    def generate_signals(self, df, params=None):
        if params is not None:
            adx_threshold = params.get('adx_threshold', self.adx_threshold)
            adx_weight = params.get('adx_weight', self.adx_weight)
            alignment_weight = params.get('alignment_weight', self.alignment_weight)
            momentum_weight = params.get('momentum_weight', self.momentum_weight)
            long_threshold = params.get('long_threshold', self.long_threshold)
            short_threshold = params.get('short_threshold', self.short_threshold)
        else:
            adx_threshold = self.adx_threshold
            adx_weight = self.adx_weight
            alignment_weight = self.alignment_weight
            momentum_weight = self.momentum_weight
            long_threshold = self.long_threshold
            short_threshold = self.short_threshold

        total = adx_weight + alignment_weight + momentum_weight
        if total == 0:
            adx_weight = alignment_weight = momentum_weight = 1/3
        else:
            adx_weight /= total
            alignment_weight /= total
            momentum_weight /= total

        df = df.copy()
        close = df['close']
        high = df['high']
        low = df['low']

        # ADX
        di_period = 14
        tr = pd.DataFrame({
            'hl': high - low,
            'hc': abs(high - close.shift(1)),
            'lc': abs(low - close.shift(1))
        }).max(axis=1)
        atr = wilder_smooth(tr, di_period)
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        plus_di = 100 * wilder_smooth(pd.Series(plus_dm, index=df.index), di_period) / atr
        minus_di = 100 * wilder_smooth(pd.Series(minus_dm, index=df.index), di_period) / atr
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = wilder_smooth(dx, di_period)

        adx_strength = (adx - adx_threshold) / 10
        adx_strength = np.clip(adx_strength, 0, 1)

        # 均线排列
        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()
        alignment = (0.2*(ma5>ma10).astype(int) + 0.3*(ma10>ma20).astype(int) + 0.5*(ma20>ma60).astype(int))
        alignment_factor = (alignment - 0.5) * 2

        # 波动率调整动量
        lookback = 20
        momentum = close.pct_change(lookback)
        atr_safe = atr.replace(0, np.nan)
        adj_momentum = momentum / (atr_safe + 1e-8)
        ewm_std = adj_momentum.ewm(span=50, min_periods=20).std()
        norm_momentum = adj_momentum / (ewm_std + 1e-8)
        norm_momentum = np.clip(norm_momentum, -3, 3) / 3
        momentum_factor = norm_momentum

        # 复合得分
        composite = (alignment_weight * alignment_factor + momentum_weight * momentum_factor)
        composite = composite * adx_strength

        # 输出
        df['signal'] = 0
        df.loc[composite > long_threshold, 'signal'] = 1
        df.loc[composite < -short_threshold, 'signal'] = -1
        df['score'] = composite
        df['trend_score'] = composite

        valid_mask = (~ma60.isna()) & (~ewm_std.isna()) & (~adx.isna())
        df.loc[~valid_mask, ['signal', 'score', 'trend_score']] = 0
        return df


class TechnicalConfirmation:
    """
    技术确认因子（Phase 1增强）
    包含：MA金叉/死叉、MACD金叉/死叉、布林带位置
    返回 tech_confirm_score [-1, 1]
    """
    def __init__(self, ma_fast=5, ma_slow=20, macd_fast=12, macd_slow=26, macd_signal=9,
                 bb_period=20, bb_std=2.0):
        self.ma_fast = ma_fast
        self.ma_slow = ma_slow
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.bb_period = bb_period
        self.bb_std = bb_std
    
    def generate_signals(self, df, params=None):
        """
        计算技术确认得分
        返回 DataFrame，包含 tech_confirm_score 列
        """
        if params is not None:
            ma_fast = params.get('ma_fast', self.ma_fast)
            ma_slow = params.get('ma_slow', self.ma_slow)
            macd_fast = params.get('macd_fast', self.macd_fast)
            macd_slow = params.get('macd_slow', self.macd_slow)
            macd_signal = params.get('macd_signal', self.macd_signal)
            bb_period = params.get('bb_period', self.bb_period)
            bb_std = params.get('bb_std', self.bb_std)
        else:
            ma_fast = self.ma_fast
            ma_slow = self.ma_slow
            macd_fast = self.macd_fast
            macd_slow = self.macd_slow
            macd_signal = self.macd_signal
            bb_period = self.bb_period
            bb_std = self.bb_std
        
        df = df.copy()
        close = df['close']
        
        # ========== 1. MA金叉/死叉 ==========
        ma_f = close.rolling(ma_fast).mean()
        ma_s = close.rolling(ma_slow).mean()
        
        # 金叉：快线上穿慢线（前一日快<=慢，当日快>慢）
        golden_cross = (ma_f.shift(1) <= ma_s.shift(1)) & (ma_f > ma_s)
        # 死叉：快线下穿慢线
        death_cross = (ma_f.shift(1) >= ma_s.shift(1)) & (ma_f < ma_s)
        
        ma_cross_score = pd.Series(0.0, index=df.index)
        ma_cross_score[golden_cross] = 1.0
        ma_cross_score[death_cross] = -1.0
        
        # 如果没有交叉，根据当前位置给弱信号
        no_cross = ~golden_cross & ~death_cross
        ma_cross_score[no_cross & (ma_f > ma_s)] = 0.3  # 多头排列但未金叉
        ma_cross_score[no_cross & (ma_f < ma_s)] = -0.3  # 空头排列但未死叉
        
        # ========== 2. MACD金叉/死叉 ==========
        ema_fast = close.ewm(span=macd_fast, adjust=False).mean()
        ema_slow = close.ewm(span=macd_slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=macd_signal, adjust=False).mean()
        
        macd_golden = (dif.shift(1) <= dea.shift(1)) & (dif > dea)
        macd_death = (dif.shift(1) >= dea.shift(1)) & (dif < dea)
        
        macd_cross_score = pd.Series(0.0, index=df.index)
        macd_cross_score[macd_golden] = 1.0
        macd_cross_score[macd_death] = -1.0
        
        # 如果没有交叉，根据当前位置给弱信号
        no_macd_cross = ~macd_golden & ~macd_death
        macd_cross_score[no_macd_cross & (dif > dea)] = 0.3
        macd_cross_score[no_macd_cross & (dif < dea)] = -0.3
        
        # ========== 3. 布林带位置（%B） ==========
        ma_bb = close.rolling(bb_period).mean()
        std_bb = close.rolling(bb_period).std()
        upper = ma_bb + bb_std * std_bb
        lower = ma_bb - bb_std * std_bb
        
        # %B: (close - lower) / (upper - lower)
        bb_width = upper - lower
        bb_position = (close - lower) / (bb_width + 1e-8)
        bb_position = np.clip(bb_position, 0, 1)
        
        # 映射到[-1, 1]：
        # %B < 0.2 → 超卖区 → -0.5（弱空）
        # %B 0.2-0.4 → 下轨附近 → 0（中性）
        # %B 0.4-0.6 → 中轨附近 → 0.5（偏多）
        # %B 0.6-0.8 → 上轨附近 → 1.0（强多）
        # %B > 0.8 → 超买区 → 0.5（警惕回调）
        bb_score = pd.Series(0.0, index=df.index)
        bb_score[bb_position < 0.2] = -0.5
        bb_score[(bb_position >= 0.2) & (bb_position < 0.4)] = 0.0
        bb_score[(bb_position >= 0.4) & (bb_position < 0.6)] = 0.5
        bb_score[(bb_position >= 0.6) & (bb_position < 0.8)] = 1.0
        bb_score[bb_position >= 0.8] = 0.5  # 超买区降低得分
        
        # ========== 复合技术确认得分 ==========
        # 权重：MA金叉30%、MACD金叉30%、布林带40%
        tech_confirm_score = (0.3 * ma_cross_score + 
                             0.3 * macd_cross_score + 
                             0.4 * bb_score)
        
        df['tech_confirm_score'] = tech_confirm_score
        df['signal'] = 0
        df.loc[tech_confirm_score > 0.5, 'signal'] = 1
        df.loc[tech_confirm_score < -0.5, 'signal'] = -1
        df['score'] = tech_confirm_score
        
        # 有效性检查
        valid_mask = (~ma_f.isna()) & (~ma_s.isna()) & (~dea.isna()) & (~bb_width.isna())
        df.loc[~valid_mask, ['signal', 'score', 'tech_confirm_score']] = 0
        
        return df


class VolumeConfirmation:
    """
    量价配合因子
    评估成交量与价格变动的配合程度
    """
    def __init__(self, vol_ma_period=20, breakout_threshold=1.2, pullback_threshold=0.8):
        self.vol_ma_period = vol_ma_period
        self.breakout_threshold = breakout_threshold
        self.pullback_threshold = pullback_threshold
    
    def generate_signals(self, df, params=None):
        """
        计算量价配合得分
        返回 volume_confirm_score [-1, 1]
        """
        if params is not None:
            vol_ma_period = params.get('vol_ma_period', self.vol_ma_period)
            breakout_threshold = params.get('breakout_threshold', self.breakout_threshold)
            pullback_threshold = params.get('pullback_threshold', self.pullback_threshold)
        else:
            vol_ma_period = self.vol_ma_period
            breakout_threshold = self.breakout_threshold
            pullback_threshold = self.pullback_threshold
        
        df = df.copy()
        volume = df['volume'] if 'volume' in df.columns else pd.Series(0, index=df.index)
        close = df['close']
        
        # 量比：当日成交量 / N日平均成交量
        vol_ma = volume.rolling(vol_ma_period).mean()
        vol_ratio = volume / (vol_ma + 1e-8)
        
        # 价格变动方向
        price_change = close.pct_change()
        
        # 量价配合评分
        volume_confirm_score = pd.Series(0.0, index=df.index)
        
        # 放量上涨（量比 > 1.2 且价格上涨）→ 强多信号
        breakout_up = (vol_ratio > breakout_threshold) & (price_change > 0)
        volume_confirm_score[breakout_up] = 1.0
        
        # 放量下跌（量比 > 1.2 且价格下跌）→ 强空信号
        breakout_down = (vol_ratio > breakout_threshold) & (price_change < 0)
        volume_confirm_score[breakout_down] = -1.0
        
        # 缩量上涨（量比 < 0.8 且价格上涨）→ 弱多信号（可能后继乏力）
        pullback_up = (vol_ratio < pullback_threshold) & (price_change > 0)
        volume_confirm_score[pullback_up] = 0.3
        
        # 缩量下跌（量比 < 0.8 且价格下跌）→ 弱空信号（可能止跌）
        pullback_down = (vol_ratio < pullback_threshold) & (price_change < 0)
        volume_confirm_score[pullback_down] = -0.3
        
        # 正常量能（0.8 <= 量比 <= 1.2）→ 中性
        normal_vol = (vol_ratio >= pullback_threshold) & (vol_ratio <= breakout_threshold)
        volume_confirm_score[normal_vol] = 0.0
        
        df['volume_confirm_score'] = volume_confirm_score
        df['vol_ratio'] = vol_ratio
        df['signal'] = 0
        df.loc[volume_confirm_score > 0.5, 'signal'] = 1
        df.loc[volume_confirm_score < -0.5, 'signal'] = -1
        df['score'] = volume_confirm_score
        
        # 有效性检查
        valid_mask = ~vol_ma.isna()
        df.loc[~valid_mask, ['signal', 'score', 'volume_confirm_score']] = 0
        
        return df


class RelativeStrength:
    """
    相对强度因子
    评估个股相对指数和行业的表现
    """
    def __init__(self, lookback=20, index_code='000300'):
        self.lookback = lookback
        self.index_code = index_code
    
    def generate_signals(self, df, index_df=None, sector_df=None, params=None):
        """
        计算相对强度得分
        
        Args:
            df: 个股K线数据
            index_df: 指数K线数据（可选）
            sector_df: 行业K线数据（可选）
            params: 参数字典（可选）
        
        Returns:
            DataFrame with relative_strength_score [-1, 1]
        """
        if params is not None:
            lookback = params.get('lookback', self.lookback)
        else:
            lookback = self.lookback
        
        df = df.copy()
        close = df['close']
        
        # 个股收益率
        stock_returns = close.pct_change(lookback)
        
        # ========== 1. 相对指数强度 ==========
        index_strength = 0.0
        if index_df is not None and not index_df.empty:
            try:
                index_close = index_df['close']
                index_returns = index_close.pct_change(lookback)
                
                # 对齐索引
                common_idx = stock_returns.index.intersection(index_returns.index)
                if len(common_idx) > 0:
                    stock_ret_aligned = stock_returns.loc[common_idx]
                    index_ret_aligned = index_returns.loc[common_idx]
                    
                    # 超额收益
                    excess_return = stock_ret_aligned - index_ret_aligned
                    
                    # 信息比率风格：超额收益 / 跟踪误差
                    tracking_error = excess_return.rolling(lookback).std()
                    relative_strength_series = excess_return / (tracking_error + 1e-6)
                    relative_strength_series = np.clip(relative_strength_series, -2, 2) / 2  # 标准化到[-1,1]
                    
                    # 回填到原始索引
                    index_strength_series = pd.Series(0.0, index=df.index)
                    index_strength_series.loc[common_idx] = relative_strength_series
                    index_strength = index_strength_series.iloc[-1] if not index_strength_series.empty else 0.0
            except Exception:
                pass
        
        # ========== 2. 相对行业强度 ==========
        sector_strength = 0.0
        if sector_df is not None and not sector_df.empty:
            try:
                sector_close = sector_df['close']
                sector_returns = sector_close.pct_change(lookback)
                
                # 对齐索引
                common_idx = stock_returns.index.intersection(sector_returns.index)
                if len(common_idx) > 0:
                    stock_ret_aligned = stock_returns.loc[common_idx]
                    sector_ret_aligned = sector_returns.loc[common_idx]
                    
                    # 超额收益
                    excess_return = stock_ret_aligned - sector_ret_aligned
                    
                    # 信息比率风格
                    tracking_error = excess_return.rolling(lookback).std()
                    relative_strength_series = excess_return / (tracking_error + 1e-6)
                    relative_strength_series = np.clip(relative_strength_series, -2, 2) / 2
                    
                    # 回填到原始索引
                    sector_strength_series = pd.Series(0.0, index=df.index)
                    sector_strength_series.loc[common_idx] = relative_strength_series
                    sector_strength = sector_strength_series.iloc[-1] if not sector_strength_series.empty else 0.0
            except Exception:
                pass
        
        # ========== 复合相对强度得分 ==========
        # 如果有指数和行业数据，各占50%；否则用有的那个
        if index_df is not None and sector_df is not None:
            relative_strength_score = 0.6 * index_strength + 0.4 * sector_strength
        elif index_df is not None:
            relative_strength_score = index_strength
        elif sector_df is not None:
            relative_strength_score = sector_strength
        else:
            relative_strength_score = 0.0
        
        df['relative_strength_score'] = relative_strength_score
        df['signal'] = 0
        df.loc[relative_strength_score > 0.3, 'signal'] = 1
        df.loc[relative_strength_score < -0.3, 'signal'] = -1
        df['score'] = relative_strength_score
        
        return df
