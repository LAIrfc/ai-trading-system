#!/usr/bin/env python3
"""
因子IC/IR监控工具

计算因子的信息系数（IC）和信息比率（IR）
"""

import sys
import os
import json
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from src.strategies.trend_strategies import Trend_Composite, Momentum_Adj, TechnicalConfirmation, VolumeConfirmation, RelativeStrength


def load_cached_kline(code, cache_dir):
    """加载缓存的K线数据"""
    cache_file = os.path.join(cache_dir, f'{code}.parquet')
    if os.path.exists(cache_file):
        try:
            return pd.read_parquet(cache_file)
        except Exception:
            pass
    return pd.DataFrame()


def calc_factor_ic(factor_values, future_returns, method='spearman'):
    """
    计算因子IC（信息系数）
    
    Args:
        factor_values: pd.Series, 因子值
        future_returns: pd.Series, 未来收益
        method: 'spearman' or 'pearson'
    
    Returns:
        float: IC值
    """
    if len(factor_values) < 10:
        return np.nan
    
    return factor_values.corr(future_returns, method=method)


def monitor_factor_ic(stock_pool_file, cache_dir, lookback=20, num_stocks=200):
    """
    监控因子IC
    
    Args:
        stock_pool_file: 股票池文件
        cache_dir: K线缓存目录
        lookback: 计算未来收益的天数
        num_stocks: 使用股票数量
    """
    print("=" * 80)
    print("因子IC/IR监控")
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
    print(f"   股票数量: {len(stocks)} 只")
    
    # 2. 加载K线数据
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
    
    # 3. 计算最近一次的因子值和未来收益
    print(f"\n🔧 计算因子值...")
    
    factor_data = {
        'base_trend': [],
        'tech_confirm': [],
        'relative_strength': [],
        'volume_confirm': []
    }
    future_returns = []
    valid_codes = []
    
    for i, (code, df) in enumerate(stocks_data.items()):
        if (i + 1) % 50 == 0:
            print(f"   进度: {i+1}/{len(stocks_data)}")
        
        if len(df) < 60 + lookback:
            continue
        
        try:
            # 使用倒数第lookback+1个bar作为信号时点
            signal_idx = -lookback - 1
            df_slice = df.iloc[:signal_idx]
            
            # 计算因子
            # 1. Base Trend
            trend_strat = Trend_Composite()
            trend_df = trend_strat.generate_signals(df_slice)
            trend_score = float(trend_df['trend_score'].iloc[-1]) if len(trend_df) > 0 else 0.0
            
            mom_strat = Momentum_Adj()
            mom_df = mom_strat.generate_signals(df_slice)
            momentum_score = float(mom_df['score'].iloc[-1]) if len(mom_df) > 0 else 0.0
            
            base_trend = 0.7 * trend_score + 0.3 * momentum_score
            
            # 2. Tech Confirm
            tech_strat = TechnicalConfirmation()
            tech_df = tech_strat.generate_signals(df_slice)
            tech_confirm = float(tech_df['tech_confirm_score'].iloc[-1]) if len(tech_df) > 0 else 0.0
            
            # 3. Relative Strength（简化：20日收益率）
            ret_20d = df_slice['close'].iloc[-1] / df_slice['close'].iloc[-21] - 1 if len(df_slice) > 20 else 0.0
            
            # 4. Volume Confirm
            vol_strat = VolumeConfirmation()
            vol_df = vol_strat.generate_signals(df_slice)
            volume_confirm = float(vol_df['volume_confirm_score'].iloc[-1]) if len(vol_df) > 0 else 0.0
            
            # 未来收益
            future_ret = df.iloc[-1]['close'] / df.iloc[signal_idx]['close'] - 1
            
            # 保存
            factor_data['base_trend'].append(base_trend)
            factor_data['tech_confirm'].append(tech_confirm)
            factor_data['relative_strength'].append(ret_20d)
            factor_data['volume_confirm'].append(volume_confirm)
            future_returns.append(future_ret)
            valid_codes.append(code)
            
        except Exception as e:
            continue
    
    print(f"   有效样本: {len(valid_codes)} 只")
    
    if len(valid_codes) < 50:
        print("⚠️ 有效样本太少，退出")
        return
    
    # 4. 计算IC
    print(f"\n📊 计算因子IC...")
    
    future_returns_series = pd.Series(future_returns, index=valid_codes)
    
    ic_results = {}
    for factor_name, factor_values_list in factor_data.items():
        factor_series = pd.Series(factor_values_list, index=valid_codes)
        
        ic_spearman = calc_factor_ic(factor_series, future_returns_series, method='spearman')
        ic_pearson = calc_factor_ic(factor_series, future_returns_series, method='pearson')
        
        ic_results[factor_name] = {
            'ic_spearman': ic_spearman,
            'ic_pearson': ic_pearson
        }
    
    # 5. 输出结果
    print(f"\n" + "=" * 80)
    print("📈 因子IC分析（单期）")
    print("=" * 80)
    print(f"{'因子':>20} | {'IC(Spearman)':>15} | {'IC(Pearson)':>15}")
    print("-" * 80)
    
    for factor_name, ics in ic_results.items():
        print(f"{factor_name:>20} | {ics['ic_spearman']:>15.4f} | {ics['ic_pearson']:>15.4f}")
    
    # 6. 分层回测
    print(f"\n" + "=" * 80)
    print("📊 分层回测（按各因子分5组）")
    print("=" * 80)
    
    for factor_name, factor_values_list in factor_data.items():
        factor_series = pd.Series(factor_values_list, index=valid_codes)
        
        # 分5组
        try:
            groups = pd.qcut(factor_series, 5, labels=['Q1', 'Q2', 'Q3', 'Q4', 'Q5'], duplicates='drop')
            
            group_returns = {}
            for group in ['Q1', 'Q2', 'Q3', 'Q4', 'Q5']:
                mask = (groups == group)
                if mask.sum() > 0:
                    group_returns[group] = future_returns_series[mask].mean()
            
            print(f"\n{factor_name}:")
            for group, ret in group_returns.items():
                print(f"   {group}: {ret:+.2%}")
        except Exception:
            print(f"\n{factor_name}: ⚠️ 分组失败")
    
    # 7. 保存结果
    result_file = 'results/factor_ic_monitoring.json'
    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    
    summary = {
        'date': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
        'config': {
            'num_stocks': len(valid_codes),
            'lookback_days': lookback
        },
        'ic_results': {k: {kk: float(vv) for kk, vv in v.items()} for k, v in ic_results.items()}
    }
    
    with open(result_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n✅ 结果已保存: {result_file}")
    print("=" * 80)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='因子IC/IR监控')
    parser.add_argument('--pool', type=str, default='mydate/stock_pool_all.json',
                        help='股票池文件')
    parser.add_argument('--cache', type=str, default='mydate/backtest_kline',
                        help='K线缓存目录')
    parser.add_argument('--stocks', type=int, default=200,
                        help='使用股票数量')
    parser.add_argument('--lookback', type=int, default=20,
                        help='未来收益计算天数')
    
    args = parser.parse_args()
    
    monitor_factor_ic(
        stock_pool_file=args.pool,
        cache_dir=args.cache,
        lookback=args.lookback,
        num_stocks=args.stocks
    )
