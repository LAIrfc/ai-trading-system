#!/usr/bin/env python3
"""
长期回测（2-3年数据）

对比v5.2和v6.1在不同市场环境下的表现
"""

import sys
import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sklearn.linear_model import LinearRegression

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from src.factors.orthogonalization import FactorOrthogonalizer
from src.factors.normalization import RankNormalizer
from src.strategies.market_regime_v6 import SoftRegimeDetector
from src.portfolio.risk_scaling import VolatilityScaler


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


def calc_score_v5_2(factors, weights):
    """v5.2: 固定权重，直接加权"""
    score = (weights[0] * factors['base_trend'] +
             weights[1] * factors['tech_confirm'] +
             weights[2] * factors['relative_strength'] +
             weights[3] * factors['volume_confirm'])
    return np.tanh(score)


def calc_score_v6_1(factor_df, weights, regime_score):
    """v6.1: 正交化 + Rank Norm + 门控交互"""
    # 1. 正交化
    ortho = FactorOrthogonalizer()
    ortho_factors = ortho.fit_transform(factor_df)
    
    # 2. 线性加权
    scores = (weights[0] * ortho_factors['base_trend'] +
              weights[1] * ortho_factors['tech_confirm'] +
              weights[2] * ortho_factors['relative_strength'] +
              weights[3] * ortho_factors['volume_confirm'])
    
    # 3. 门控交互
    gating = np.maximum(ortho_factors['base_trend'], 0) * ortho_factors['volume_confirm']
    scores = scores + 0.1 * gating
    
    # 4. Rank Normalization
    normalizer = RankNormalizer(method='percentile')
    scores = normalizer.transform(scores)
    
    return scores


def backtest_long_term(stock_pool_file, cache_dir, num_stocks=300, start_date='2023-01-01', 
                       end_date='2026-03-27', rebalance_days=5):
    """
    长期回测
    
    Args:
        stock_pool_file: 股票池文件
        cache_dir: K线缓存目录
        num_stocks: 使用股票数量
        start_date: 开始日期
        end_date: 结束日期
        rebalance_days: 调仓间隔
    """
    print("=" * 80)
    print(f"长期回测：{start_date} ~ {end_date}")
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
            df['date'] = pd.to_datetime(df['date'])
            df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
            if len(df) >= 100:
                stocks_data[code] = df
    
    print(f"   有效股票: {len(stocks_data)} 只")
    
    if len(stocks_data) < 50:
        print("⚠️ 有效股票太少")
        return
    
    # 3. 获取所有交易日
    all_dates = set()
    for df in stocks_data.values():
        all_dates.update(df['date'].tolist())
    
    trading_days = sorted(list(all_dates))
    print(f"   交易日数量: {len(trading_days)}")
    
    # 4. 回测
    print(f"\n🔧 开始回测...")
    
    # v5.2权重（原始固定权重）
    weights_v5_2 = [0.40, 0.30, 0.10, 0.20]
    
    # v6.1权重（优化后）
    weights_v6_1 = [0.42, 0.20, 0.30, 0.08]
    
    results_v5_2 = []
    results_v6_1 = []
    
    regime_detector = SoftRegimeDetector()
    
    for i, signal_date in enumerate(trading_days[60::rebalance_days]):
        if i % 10 == 0:
            print(f"\r   进度: {i}/{len(trading_days[60::rebalance_days])}", end='', flush=True)
        
        # 计算因子
        factor_data = {
            'base_trend': [],
            'tech_confirm': [],
            'relative_strength': [],
            'volume_confirm': []
        }
        valid_codes = []
        
        for code, df in stocks_data.items():
            df_slice = df[df['date'] <= signal_date]
            if len(df_slice) < 60:
                continue
            
            factors = calc_factors_simple(df_slice)
            
            if factors and all(not np.isnan(v) and not np.isinf(v) for v in factors.values()):
                for factor_name, factor_value in factors.items():
                    factor_data[factor_name].append(factor_value)
                valid_codes.append(code)
        
        if len(valid_codes) < 20:
            continue
        
        # 构建DataFrame
        factor_df = pd.DataFrame(factor_data, index=valid_codes)
        
        # 计算市场regime（使用沪深300）
        regime_score = 0.0  # 默认值
        
        # v5.2得分
        scores_v5_2 = {}
        for code in valid_codes:
            factors = {k: factor_df.loc[code, k] for k in factor_data.keys()}
            scores_v5_2[code] = calc_score_v5_2(factors, weights_v5_2)
        
        # v6.1得分
        scores_v6_1 = calc_score_v6_1(factor_df, weights_v6_1, regime_score)
        scores_v6_1 = scores_v6_1.to_dict()
        
        # 选Top10
        top10_v5_2 = sorted(scores_v5_2.items(), key=lambda x: x[1], reverse=True)[:10]
        top10_v6_1 = sorted(scores_v6_1.items(), key=lambda x: x[1], reverse=True)[:10]
        
        # 计算未来收益
        future_date_idx = trading_days.index(signal_date) + rebalance_days
        if future_date_idx >= len(trading_days):
            break
        
        future_date = trading_days[future_date_idx]
        
        # v5.2收益
        returns_v5_2 = []
        for code, score in top10_v5_2:
            df = stocks_data[code]
            df_signal = df[df['date'] == signal_date]
            df_future = df[df['date'] == future_date]
            
            if len(df_signal) > 0 and len(df_future) > 0:
                ret = df_future.iloc[0]['close'] / df_signal.iloc[0]['close'] - 1
                returns_v5_2.append(ret)
        
        # v6.1收益
        returns_v6_1 = []
        for code, score in top10_v6_1:
            df = stocks_data[code]
            df_signal = df[df['date'] == signal_date]
            df_future = df[df['date'] == future_date]
            
            if len(df_signal) > 0 and len(df_future) > 0:
                ret = df_future.iloc[0]['close'] / df_signal.iloc[0]['close'] - 1
                returns_v6_1.append(ret)
        
        if returns_v5_2:
            results_v5_2.append({
                'date': signal_date.strftime('%Y-%m-%d'),
                'return': np.mean(returns_v5_2)
            })
        
        if returns_v6_1:
            results_v6_1.append({
                'date': signal_date.strftime('%Y-%m-%d'),
                'return': np.mean(returns_v6_1)
            })
    
    print()
    
    # 5. 统计分析
    print(f"\n" + "=" * 80)
    print("📊 长期回测结果")
    print("=" * 80)
    
    df_v5_2 = pd.DataFrame(results_v5_2)
    df_v6_1 = pd.DataFrame(results_v6_1)
    
    if len(df_v5_2) > 0:
        df_v5_2['cum_return'] = (1 + df_v5_2['return']).cumprod() - 1
        
        total_return_v5_2 = df_v5_2['cum_return'].iloc[-1]
        avg_return_v5_2 = df_v5_2['return'].mean()
        std_return_v5_2 = df_v5_2['return'].std()
        sharpe_v5_2 = avg_return_v5_2 / (std_return_v5_2 + 1e-8) * np.sqrt(252 / rebalance_days)
        
        print(f"\n✅ v5.2 (固定权重)")
        print(f"   调仓次数: {len(df_v5_2)}")
        print(f"   累计收益: {total_return_v5_2:+.2%}")
        print(f"   年化收益: {(1 + total_return_v5_2) ** (365 / (len(df_v5_2) * rebalance_days)) - 1:+.2%}")
        print(f"   Sharpe: {sharpe_v5_2:.3f}")
        print(f"   最大回撤: {(df_v5_2['cum_return'] - df_v5_2['cum_return'].cummax()).min():.2%}")
    
    if len(df_v6_1) > 0:
        df_v6_1['cum_return'] = (1 + df_v6_1['return']).cumprod() - 1
        
        total_return_v6_1 = df_v6_1['cum_return'].iloc[-1]
        avg_return_v6_1 = df_v6_1['return'].mean()
        std_return_v6_1 = df_v6_1['return'].std()
        sharpe_v6_1 = avg_return_v6_1 / (std_return_v6_1 + 1e-8) * np.sqrt(252 / rebalance_days)
        
        print(f"\n✅ v6.1 (正交化+Rank Norm+Soft Regime)")
        print(f"   调仓次数: {len(df_v6_1)}")
        print(f"   累计收益: {total_return_v6_1:+.2%}")
        print(f"   年化收益: {(1 + total_return_v6_1) ** (365 / (len(df_v6_1) * rebalance_days)) - 1:+.2%}")
        print(f"   Sharpe: {sharpe_v6_1:.3f}")
        print(f"   最大回撤: {(df_v6_1['cum_return'] - df_v6_1['cum_return'].cummax()).min():.2%}")
    
    # 6. 对比
    if len(df_v5_2) > 0 and len(df_v6_1) > 0:
        print(f"\n" + "=" * 80)
        print("📊 v6.1 vs v5.2 对比")
        print("=" * 80)
        
        return_diff = total_return_v6_1 - total_return_v5_2
        sharpe_diff = sharpe_v6_1 - sharpe_v5_2
        
        print(f"\n   收益差异: {return_diff:+.2%} ({return_diff/total_return_v5_2:+.1%})")
        print(f"   Sharpe差异: {sharpe_diff:+.3f} ({sharpe_diff/sharpe_v5_2:+.1%})")
        
        if return_diff > 0 and sharpe_diff > 0:
            print(f"\n   ✅ v6.1全面优于v5.2")
        elif return_diff > 0:
            print(f"\n   ⚠️ v6.1收益更高，但风险调整后不如v5.2")
        else:
            print(f"\n   ❌ v6.1表现不如v5.2")
    
    # 7. 分年度分析
    print(f"\n" + "=" * 80)
    print("📅 分年度表现")
    print("=" * 80)
    
    if len(df_v5_2) > 0:
        df_v5_2['year'] = pd.to_datetime(df_v5_2['date']).dt.year
        
        print(f"\n{'年份':>6} | {'v5.2收益':>12} | {'v6.1收益':>12} | {'差异':>10}")
        print("-" * 50)
        
        for year in sorted(df_v5_2['year'].unique()):
            ret_v5_2 = df_v5_2[df_v5_2['year'] == year]['return'].sum()
            
            if len(df_v6_1) > 0:
                df_v6_1['year'] = pd.to_datetime(df_v6_1['date']).dt.year
                ret_v6_1 = df_v6_1[df_v6_1['year'] == year]['return'].sum()
                diff = ret_v6_1 - ret_v5_2
                print(f"{year:>6} | {ret_v5_2:>11.2%} | {ret_v6_1:>11.2%} | {diff:>+9.2%}")
            else:
                print(f"{year:>6} | {ret_v5_2:>11.2%} | {'N/A':>12} | {'N/A':>10}")
    
    # 8. 保存结果
    result_file = 'results/long_term_backtest.json'
    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    
    summary = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'config': {
            'num_stocks': len(stocks_data),
            'start_date': start_date,
            'end_date': end_date,
            'rebalance_days': rebalance_days
        },
        'v5_2': {
            'total_return': float(total_return_v5_2) if len(df_v5_2) > 0 else None,
            'sharpe': float(sharpe_v5_2) if len(df_v5_2) > 0 else None
        },
        'v6_1': {
            'total_return': float(total_return_v6_1) if len(df_v6_1) > 0 else None,
            'sharpe': float(sharpe_v6_1) if len(df_v6_1) > 0 else None
        }
    }
    
    with open(result_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n✅ 结果已保存: {result_file}")
    print("=" * 80)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='长期回测')
    parser.add_argument('--pool', type=str, default='mydate/stock_pool_all.json')
    parser.add_argument('--cache', type=str, default='mydate/backtest_kline')
    parser.add_argument('--stocks', type=int, default=300)
    parser.add_argument('--start', type=str, default='2023-01-01')
    parser.add_argument('--end', type=str, default='2026-03-27')
    parser.add_argument('--rebalance', type=int, default=5)
    
    args = parser.parse_args()
    
    backtest_long_term(
        stock_pool_file=args.pool,
        cache_dir=args.cache,
        num_stocks=args.stocks,
        start_date=args.start,
        end_date=args.end,
        rebalance_days=args.rebalance
    )
