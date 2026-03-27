#!/usr/bin/env python3
"""
滚动IC/IR监控工具

计算因子的滚动信息系数（IC）和信息比率（IR）
"""

import sys
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from src.strategies.trend_strategies import Trend_Composite, Momentum_Adj, TechnicalConfirmation, VolumeConfirmation


def load_cached_kline(code, cache_dir):
    """加载缓存的K线数据"""
    cache_file = os.path.join(cache_dir, f'{code}.parquet')
    if os.path.exists(cache_file):
        try:
            return pd.read_parquet(cache_file)
        except Exception:
            pass
    return pd.DataFrame()


def calc_factors_simple(df):
    """简化因子计算"""
    if len(df) < 60:
        return None
    
    try:
        close = df['close']
        volume = df['volume']
        
        # 1. Base Trend
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()
        trend = (ma20.iloc[-1] / ma60.iloc[-1] - 1) if ma60.iloc[-1] > 0 else 0
        momentum = (close.iloc[-1] / close.iloc[-20] - 1) if len(close) > 20 else 0
        base_trend = 0.7 * trend + 0.3 * momentum
        
        # 2. Tech Confirm
        ma5 = close.rolling(5).mean()
        tech_confirm = (ma5.iloc[-1] / ma20.iloc[-1] - 1) if ma20.iloc[-1] > 0 else 0
        
        # 3. Relative Strength
        relative_strength = (close.iloc[-1] / close.iloc[-21] - 1) if len(close) > 20 else 0
        
        # 4. Volume Confirm
        vol_ma20 = volume.rolling(20).mean()
        vol_ratio = volume.iloc[-1] / vol_ma20.iloc[-1] if vol_ma20.iloc[-1] > 0 else 1
        price_change = (close.iloc[-1] / close.iloc[-6] - 1) if len(close) > 5 else 0
        volume_confirm = price_change * np.log(np.clip(vol_ratio, 0.5, 2))
        
        return {
            'base_trend': base_trend,
            'tech_confirm': tech_confirm,
            'relative_strength': relative_strength,
            'volume_confirm': volume_confirm
        }
    except Exception:
        return None


def calc_rolling_ic(stocks_data, window_size=20, lookback=5, sample_freq=10):
    """
    计算滚动IC
    
    Args:
        stocks_data: dict {code: df}
        window_size: IC计算窗口（多少个时间点）
        lookback: 未来收益天数
        sample_freq: 采样频率
    
    Returns:
        DataFrame: 滚动IC结果
    """
    min_len = min(len(df) for df in stocks_data.values())
    
    # 时间点
    time_points = list(range(60, min_len - lookback, sample_freq))
    
    if len(time_points) < window_size:
        print(f"⚠️ 时间点不足: {len(time_points)} < {window_size}")
        return pd.DataFrame()
    
    rolling_ic_results = []
    
    print(f"📊 计算滚动IC（窗口={window_size}，采样={sample_freq}日）...")
    
    for i in range(window_size, len(time_points)):
        window_start = i - window_size
        window_end = i
        
        window_points = time_points[window_start:window_end]
        
        # 收集该窗口内所有样本的因子值和未来收益
        factor_data = {
            'base_trend': [],
            'tech_confirm': [],
            'relative_strength': [],
            'volume_confirm': []
        }
        future_returns = []
        
        for t_idx in window_points:
            for code, df in stocks_data.items():
                if len(df) <= t_idx + lookback:
                    continue
                
                df_slice = df.iloc[:t_idx+1]
                factors = calc_factors_simple(df_slice)
                
                if factors:
                    for factor_name, factor_value in factors.items():
                        factor_data[factor_name].append(factor_value)
                    
                    future_ret = df.iloc[t_idx + lookback]['close'] / df.iloc[t_idx]['close'] - 1
                    future_returns.append(future_ret)
        
        if len(future_returns) < 50:
            continue
        
        # 计算IC
        future_returns_series = pd.Series(future_returns)
        
        ic_values = {}
        for factor_name, factor_values in factor_data.items():
            factor_series = pd.Series(factor_values)
            ic = factor_series.corr(future_returns_series, method='spearman')
            ic_values[factor_name] = ic
        
        rolling_ic_results.append({
            'window_end_idx': window_end,
            'time_point': time_points[window_end-1],
            'base_trend_ic': ic_values.get('base_trend', np.nan),
            'tech_confirm_ic': ic_values.get('tech_confirm', np.nan),
            'relative_strength_ic': ic_values.get('relative_strength', np.nan),
            'volume_confirm_ic': ic_values.get('volume_confirm', np.nan),
            'sample_count': len(future_returns)
        })
        
        if window_end % 5 == 0:
            print(f"\r   进度: {window_end}/{len(time_points)}", end='', flush=True)
    
    print()
    
    return pd.DataFrame(rolling_ic_results)


def calc_ir(ic_series):
    """
    计算信息比率（IR）
    
    IR = IC均值 / IC标准差
    """
    return ic_series.mean() / (ic_series.std() + 1e-8)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='滚动IC/IR监控')
    parser.add_argument('--pool', type=str, default='mydate/stock_pool_all.json')
    parser.add_argument('--cache', type=str, default='mydate/backtest_kline')
    parser.add_argument('--stocks', type=int, default=200)
    parser.add_argument('--window', type=int, default=20,
                        help='IC计算窗口大小')
    parser.add_argument('--freq', type=int, default=10,
                        help='采样频率')
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("滚动IC/IR监控")
    print("=" * 80)
    
    # 1. 加载股票池
    print(f"\n📊 加载股票池...")
    with open(args.pool, 'r') as f:
        pool_data = json.load(f)
    
    stocks = []
    if isinstance(pool_data, dict) and 'stocks' in pool_data:
        for category, stock_list in pool_data['stocks'].items():
            stocks.extend(stock_list)
    elif isinstance(pool_data, list):
        stocks = pool_data
    
    stocks = stocks[:args.stocks]
    
    # 2. 加载K线
    print(f"\n📈 加载K线缓存...")
    stocks_data = {}
    for stock in stocks:
        code = stock.get('code', '')
        if not code:
            continue
        
        df = load_cached_kline(code, args.cache)
        if len(df) >= 100:
            stocks_data[code] = df
    
    print(f"   有效股票: {len(stocks_data)} 只")
    
    if len(stocks_data) < 50:
        print("⚠️ 有效股票太少")
        return
    
    # 3. 计算滚动IC
    df_rolling_ic = calc_rolling_ic(stocks_data, window_size=args.window, 
                                     lookback=5, sample_freq=args.freq)
    
    if df_rolling_ic.empty:
        print("⚠️ 滚动IC计算失败")
        return
    
    # 4. 计算IR
    print(f"\n" + "=" * 80)
    print("📈 滚动IC/IR统计")
    print("=" * 80)
    
    print(f"\n{'因子':>20} | {'平均IC':>10} | {'IC标准差':>10} | {'IR':>10} | {'最新IC':>10}")
    print("-" * 80)
    
    for factor in ['base_trend', 'tech_confirm', 'relative_strength', 'volume_confirm']:
        ic_col = f'{factor}_ic'
        ic_series = df_rolling_ic[ic_col].dropna()
        
        if len(ic_series) > 0:
            avg_ic = ic_series.mean()
            std_ic = ic_series.std()
            ir = calc_ir(ic_series)
            latest_ic = ic_series.iloc[-1]
            
            print(f"{factor:>20} | {avg_ic:>10.3f} | {std_ic:>10.3f} | {ir:>10.3f} | {latest_ic:>10.3f}")
    
    # 5. IC时序图数据
    print(f"\n📊 IC时序趋势（最近10个窗口）:")
    recent = df_rolling_ic.tail(10)
    
    for _, row in recent.iterrows():
        print(f"\n   时间点{row['time_point']}:")
        print(f"      base={row['base_trend_ic']:.3f}, tech={row['tech_confirm_ic']:.3f}, "
              f"rs={row['relative_strength_ic']:.3f}, vol={row['volume_confirm_ic']:.3f}")
    
    # 6. 因子衰减检测
    print(f"\n" + "=" * 80)
    print("⚠️  因子衰减检测")
    print("=" * 80)
    
    for factor in ['base_trend', 'tech_confirm', 'relative_strength', 'volume_confirm']:
        ic_col = f'{factor}_ic'
        ic_series = df_rolling_ic[ic_col].dropna()
        
        if len(ic_series) < 10:
            continue
        
        # 对比前半段和后半段
        mid = len(ic_series) // 2
        first_half = ic_series.iloc[:mid].mean()
        second_half = ic_series.iloc[mid:].mean()
        
        decay = (second_half - first_half) / abs(first_half) * 100 if first_half != 0 else 0
        
        status = "✅ 稳定" if decay > -20 else "⚠️ 衰减"
        print(f"\n{factor}:")
        print(f"   前半段IC: {first_half:.3f}")
        print(f"   后半段IC: {second_half:.3f}")
        print(f"   变化: {decay:+.1f}% {status}")
    
    # 7. 保存结果
    result_file = 'results/rolling_ic_monitor.json'
    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    
    summary = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'config': {
            'num_stocks': len(stocks_data),
            'window_size': args.window,
            'sample_freq': args.freq
        },
        'ic_stats': {}
    }
    
    for factor in ['base_trend', 'tech_confirm', 'relative_strength', 'volume_confirm']:
        ic_col = f'{factor}_ic'
        ic_series = df_rolling_ic[ic_col].dropna()
        
        if len(ic_series) > 0:
            summary['ic_stats'][factor] = {
                'avg_ic': float(ic_series.mean()),
                'std_ic': float(ic_series.std()),
                'ir': float(calc_ir(ic_series)),
                'latest_ic': float(ic_series.iloc[-1])
            }
    
    with open(result_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n✅ 结果已保存: {result_file}")
    print("=" * 80)


if __name__ == '__main__':
    main()
