#!/usr/bin/env python3
"""
多日单期IC验证工具

连续多日计算单期IC，验证因子稳定性
"""

import sys
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

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


def calc_single_period_ic(stocks_data, signal_day_offset, lookback=5):
    """
    计算单期IC
    
    Args:
        stocks_data: dict {code: df}
        signal_day_offset: 信号日偏移（从最后一天往前数）
        lookback: 未来收益天数
    
    Returns:
        dict: IC结果
    """
    factor_data = {
        'base_trend': [],
        'tech_confirm': [],
        'relative_strength': [],
        'volume_confirm': []
    }
    future_returns = []
    valid_codes = []
    
    for code, df in stocks_data.items():
        if len(df) < 60 + signal_day_offset + lookback:
            continue
        
        # 信号时点
        signal_idx = -signal_day_offset - lookback - 1
        df_slice = df.iloc[:signal_idx]
        
        # 计算因子
        factors = calc_factors_simple(df_slice)
        
        if factors and all(not np.isnan(v) and not np.isinf(v) for v in factors.values()):
            for factor_name, factor_value in factors.items():
                factor_data[factor_name].append(factor_value)
            
            # 未来收益
            future_ret = df.iloc[signal_idx + lookback]['close'] / df.iloc[signal_idx]['close'] - 1
            future_returns.append(future_ret)
            valid_codes.append(code)
    
    if len(valid_codes) < 50:
        return None
    
    # 计算IC
    future_returns_series = pd.Series(future_returns, index=valid_codes)
    
    ic_results = {}
    for factor_name, factor_values_list in factor_data.items():
        factor_series = pd.Series(factor_values_list, index=valid_codes)
        
        ic_spearman = factor_series.corr(future_returns_series, method='spearman')
        ic_pearson = factor_series.corr(future_returns_series, method='pearson')
        
        ic_results[factor_name] = {
            'ic_spearman': ic_spearman,
            'ic_pearson': ic_pearson
        }
    
    return {
        'signal_day_offset': signal_day_offset,
        'valid_stocks': len(valid_codes),
        'ic_results': ic_results
    }


def validate_multi_day_ic(stock_pool_file, cache_dir, num_stocks=200, num_days=10, lookback=5):
    """
    多日单期IC验证
    
    Args:
        stock_pool_file: 股票池文件
        cache_dir: K线缓存目录
        num_stocks: 使用股票数量
        num_days: 验证天数
        lookback: 未来收益天数
    """
    print("=" * 80)
    print("多日单期IC验证")
    print("=" * 80)
    
    # 1. 加载股票池
    print(f"\n📊 加载股票池...")
    with open(stock_pool_file, 'r') as f:
        pool_data = json.load(f)
    
    stocks = []
    if isinstance(pool_data, dict) and 'stocks' in pool_data:
        for category, stock_list in pool_data['stocks'].items():
            stocks.extend(stock_list)
    elif isinstance(pool_data, list):
        stocks = pool_data
    
    stocks = stocks[:num_stocks]
    
    # 2. 加载K线
    print(f"\n📈 加载K线缓存...")
    stocks_data = {}
    for stock in stocks:
        code = stock.get('code', '')
        if not code:
            continue
        
        df = load_cached_kline(code, cache_dir)
        if len(df) >= 100:
            stocks_data[code] = df
    
    print(f"   有效股票: {len(stocks_data)} 只")
    
    if len(stocks_data) < 50:
        print("⚠️ 有效股票太少")
        return
    
    # 3. 计算多日IC
    print(f"\n🔧 计算最近{num_days}日的单期IC...")
    
    daily_ic_results = []
    for day_offset in range(num_days):
        print(f"\r   进度: {day_offset+1}/{num_days}", end='', flush=True)
        
        result = calc_single_period_ic(stocks_data, day_offset, lookback)
        
        if result:
            daily_ic_results.append(result)
    
    print()
    
    if len(daily_ic_results) < 3:
        print("⚠️ 有效天数太少")
        return
    
    # 4. 汇总统计
    print(f"\n" + "=" * 80)
    print("📊 多日IC统计")
    print("=" * 80)
    
    # 转换为DataFrame
    ic_records = []
    for day_result in daily_ic_results:
        record = {'day_offset': day_result['signal_day_offset']}
        for factor, ics in day_result['ic_results'].items():
            record[f'{factor}_ic'] = ics['ic_spearman']
        ic_records.append(record)
    
    df_ic = pd.DataFrame(ic_records)
    
    print(f"\n{'因子':>20} | {'平均IC':>10} | {'IC标准差':>10} | {'最小IC':>10} | {'最大IC':>10} | {'稳定性':>10}")
    print("-" * 100)
    
    stability_scores = {}
    for factor in ['base_trend', 'tech_confirm', 'relative_strength', 'volume_confirm']:
        ic_col = f'{factor}_ic'
        ic_series = df_ic[ic_col]
        
        avg_ic = ic_series.mean()
        std_ic = ic_series.std()
        min_ic = ic_series.min()
        max_ic = ic_series.max()
        
        # 稳定性评分：平均IC高 且 标准差低
        stability = avg_ic / (std_ic + 0.01)  # 避免除0
        stability_scores[factor] = stability
        
        stability_label = "✅ 稳定" if stability > 1.0 else "⚠️ 不稳定"
        
        print(f"{factor:>20} | {avg_ic:>10.3f} | {std_ic:>10.3f} | {min_ic:>10.3f} | {max_ic:>10.3f} | {stability:>9.2f} {stability_label}")
    
    # 5. IC时序图
    print(f"\n" + "=" * 80)
    print("📈 IC时序趋势（从最近到最早）")
    print("=" * 80)
    
    print(f"\n{'天数':>6} | {'Base':>8} | {'Tech':>8} | {'RS':>8} | {'Vol':>8}")
    print("-" * 50)
    
    for _, row in df_ic.iterrows():
        day = row['day_offset']
        print(f"T-{day:>4} | {row['base_trend_ic']:>8.3f} | {row['tech_confirm_ic']:>8.3f} | "
              f"{row['relative_strength_ic']:>8.3f} | {row['volume_confirm_ic']:>8.3f}")
    
    # 6. 趋势分析
    print(f"\n" + "=" * 80)
    print("📉 IC趋势分析（是否衰减）")
    print("=" * 80)
    
    for factor in ['base_trend', 'tech_confirm', 'relative_strength', 'volume_confirm']:
        ic_col = f'{factor}_ic'
        ic_series = df_ic[ic_col].values
        
        # 线性回归拟合趋势
        x = np.arange(len(ic_series))
        slope = np.polyfit(x, ic_series, 1)[0]
        
        trend_label = "📈 上升" if slope > 0.01 else ("📉 下降" if slope < -0.01 else "➡️ 平稳")
        
        print(f"\n{factor}:")
        print(f"   趋势斜率: {slope:+.4f} {trend_label}")
        print(f"   最近3日平均: {ic_series[:3].mean():.3f}")
        print(f"   最早3日平均: {ic_series[-3:].mean():.3f}")
    
    # 7. 保存结果
    result_file = 'results/multi_day_ic_validation.json'
    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    
    summary = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'config': {
            'num_stocks': len(stocks_data),
            'num_days': num_days,
            'lookback': lookback
        },
        'ic_stats': {},
        'stability_scores': {k: float(v) for k, v in stability_scores.items()}
    }
    
    for factor in ['base_trend', 'tech_confirm', 'relative_strength', 'volume_confirm']:
        ic_col = f'{factor}_ic'
        ic_series = df_ic[ic_col]
        
        summary['ic_stats'][factor] = {
            'avg_ic': float(ic_series.mean()),
            'std_ic': float(ic_series.std()),
            'min_ic': float(ic_series.min()),
            'max_ic': float(ic_series.max()),
            'latest_ic': float(ic_series.iloc[0])
        }
    
    with open(result_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n✅ 结果已保存: {result_file}")
    print("=" * 80)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='多日单期IC验证')
    parser.add_argument('--pool', type=str, default='mydate/stock_pool_all.json')
    parser.add_argument('--cache', type=str, default='mydate/backtest_kline')
    parser.add_argument('--stocks', type=int, default=200)
    parser.add_argument('--days', type=int, default=10,
                        help='验证天数')
    parser.add_argument('--lookback', type=int, default=5,
                        help='未来收益天数')
    
    args = parser.parse_args()
    
    validate_multi_day_ic(
        stock_pool_file=args.pool,
        cache_dir=args.cache,
        num_stocks=args.stocks,
        num_days=args.days,
        lookback=args.lookback
    )
