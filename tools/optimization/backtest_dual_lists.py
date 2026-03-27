#!/usr/bin/env python3
"""
双引擎双榜单完整回测
回测超跌榜和趋势榜的实际表现

用法:
  python3 tools/optimization/backtest_dual_lists.py --stocks 200
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pandas as pd
import numpy as np
import json
import argparse
from datetime import datetime, timedelta

from src.strategies.trend_strategies import Trend_Composite, Momentum_Adj, TechnicalConfirmation, VolumeConfirmation, RelativeStrength

# 策略权重配置
MR_WEIGHTS = {
    'PB': 2.0, 'BOLL': 1.95, 'RSI': 1.82, 'PE': 1.68,
    'PEPB': 1.61, 'KDJ': 1.5, 'DUAL': 1.39,
    'SENTIMENT': 0.32, 'NEWS': 0.32, 'MONEY_FLOW': 0.3,
    'MACD': 0.5, 'MA': 0.3,
}

TREND_WEIGHT_BASE = 0.5
TREND_WEIGHT_RANGE = 0.5
TREND_SCORE_WEIGHT = 0.7
MOMENTUM_SCORE_WEIGHT = 0.3

# Phase 2 组权重
TREND_COMPONENT_WEIGHTS = {
    'base_trend': 0.4,
    'tech_confirm': 0.3,
    'relative_strength': 0.2,
    'volume_confirm': 0.1
}

def load_kline(code, kline_dir):
    """加载K线数据"""
    parquet_path = os.path.join(kline_dir, f"{code}.parquet")
    if os.path.exists(parquet_path):
        return pd.read_parquet(parquet_path)
    return pd.DataFrame()

def calculate_mr_score_simple(df):
    """
    简化版均值回归得分计算（用于回测）
    只使用技术指标，不使用基本面（回测中基本面数据不完整）
    """
    score = 0.0
    
    # BOLL
    try:
        close = df['close']
        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        
        last_close = close.iloc[-1]
        last_lower = lower.iloc[-1]
        last_upper = upper.iloc[-1]
        
        if last_close < last_lower:
            score += 1.95  # BOLL权重
        elif last_close > last_upper:
            score -= 1.95
    except Exception:
        pass
    
    # RSI
    try:
        close = df['close']
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-8)
        rsi = 100 - (100 / (1 + rs))
        
        last_rsi = rsi.iloc[-1]
        if last_rsi < 30:
            score += 1.82  # RSI权重
        elif last_rsi > 70:
            score -= 1.82
    except Exception:
        pass
    
    # KDJ
    try:
        high = df['high']
        low = df['low']
        close = df['close']
        
        low_min = low.rolling(9).min()
        high_max = high.rolling(9).max()
        rsv = (close - low_min) / (high_max - low_min + 1e-8) * 100
        k = rsv.ewm(alpha=1/3, adjust=False).mean()
        d = k.ewm(alpha=1/3, adjust=False).mean()
        
        last_k = k.iloc[-1]
        last_d = d.iloc[-1]
        
        if last_k < 20 and last_d < 20:
            score += 1.5  # KDJ权重
        elif last_k > 80 and last_d > 80:
            score -= 1.5
    except Exception:
        pass
    
    return score

def calculate_trend_factors(df, index_df=None):
    """计算所有趋势因子"""
    factors = {
        'trend_score': 0.0,
        'momentum_score': 0.0,
        'tech_confirm_score': 0.0,
        'volume_confirm_score': 0.0,
        'relative_strength_score': 0.0
    }
    
    try:
        trend_strat = Trend_Composite()
        trend_df = trend_strat.generate_signals(df)
        if 'trend_score' in trend_df.columns:
            factors['trend_score'] = float(trend_df['trend_score'].iloc[-1])
    except Exception:
        pass
    
    try:
        mom_strat = Momentum_Adj()
        mom_df = mom_strat.generate_signals(df)
        if 'score' in mom_df.columns:
            factors['momentum_score'] = float(mom_df['score'].iloc[-1])
    except Exception:
        pass
    
    try:
        tech_strat = TechnicalConfirmation()
        tech_df = tech_strat.generate_signals(df)
        if 'tech_confirm_score' in tech_df.columns:
            factors['tech_confirm_score'] = float(tech_df['tech_confirm_score'].iloc[-1])
    except Exception:
        pass
    
    try:
        vol_strat = VolumeConfirmation()
        vol_df = vol_strat.generate_signals(df)
        if 'volume_confirm_score' in vol_df.columns:
            factors['volume_confirm_score'] = float(vol_df['volume_confirm_score'].iloc[-1])
    except Exception:
        pass
    
    try:
        rs_strat = RelativeStrength()
        rs_df = rs_strat.generate_signals(df, index_df=index_df)
        if 'relative_strength_score' in rs_df.columns:
            factors['relative_strength_score'] = float(rs_df['relative_strength_score'].iloc[-1])
    except Exception:
        pass
    
    return factors

def backtest_dual_lists(stocks, kline_dir, index_df, n_stocks=200):
    """
    回测双榜单推荐效果
    
    模拟每周选股一次，持有5个交易日，计算收益
    """
    print("\n" + "=" * 80)
    print("双引擎双榜单回测")
    print("=" * 80)
    
    # 回测参数
    mr_n = 15  # 超跌榜数量
    trend_n = 5  # 趋势榜数量
    holding_days = 5
    
    # 回测结果
    mr_trades = []  # 超跌榜交易记录
    trend_trades = []  # 趋势榜交易记录
    dual_trades = []  # 双优股票交易记录
    
    print(f"\n回测配置:")
    print(f"  股票数量: {min(n_stocks, len(stocks))}")
    print(f"  超跌榜: {mr_n} 只")
    print(f"  趋势榜: {trend_n} 只")
    print(f"  持有周期: {holding_days} 日")
    
    # 加载所有股票数据
    print(f"\n加载股票数据...")
    stock_data = {}
    for i, stock in enumerate(stocks[:n_stocks], 1):
        if i % 50 == 0:
            print(f"  进度: {i}/{min(n_stocks, len(stocks))}")
        
        code = stock['code']
        df = load_kline(code, kline_dir)
        if not df.empty and len(df) >= 60:
            stock_data[code] = {
                'name': stock['name'],
                'df': df
            }
    
    print(f"✅ 加载完成: {len(stock_data)} 只有效股票")
    
    if len(stock_data) < 20:
        print("⚠️ 有效股票数量不足，无法回测")
        return
    
    # 回测周期：每5个交易日选股一次
    all_codes = list(stock_data.keys())
    max_len = max(len(stock_data[code]['df']) for code in all_codes)
    
    print(f"\n开始回测（每{holding_days}日选股一次）...")
    backtest_count = 0
    
    for start_idx in range(60, max_len - holding_days, holding_days):
        backtest_count += 1
        if backtest_count % 10 == 0:
            print(f"  回测周期: {backtest_count}")
        
        # 计算所有股票的得分
        scores = []
        for code in all_codes:
            df = stock_data[code]['df']
            if len(df) <= start_idx:
                continue
            
            window_df = df.iloc[:start_idx+1].copy()
            
            # 计算均值回归得分
            mr_score = calculate_mr_score_simple(window_df)
            
            # 计算趋势因子
            factors = calculate_trend_factors(window_df, index_df)
            
            # 软过滤
            trend_weight = max(0.0, min(1.0, factors['trend_score']))
            adjusted_mr_score = mr_score * (TREND_WEIGHT_BASE + TREND_WEIGHT_RANGE * trend_weight)
            
            # 趋势质量得分
            base_trend = (TREND_SCORE_WEIGHT * factors['trend_score'] +
                         MOMENTUM_SCORE_WEIGHT * factors['momentum_score'])
            trend_rank_score = (TREND_COMPONENT_WEIGHTS['base_trend'] * base_trend +
                               TREND_COMPONENT_WEIGHTS['tech_confirm'] * factors['tech_confirm_score'] +
                               TREND_COMPONENT_WEIGHTS['relative_strength'] * factors['relative_strength_score'] +
                               TREND_COMPONENT_WEIGHTS['volume_confirm'] * factors['volume_confirm_score'])
            
            scores.append({
                'code': code,
                'name': stock_data[code]['name'],
                'mr_score': mr_score,
                'adjusted_mr_score': adjusted_mr_score,
                'trend_rank_score': trend_rank_score,
                'start_idx': start_idx
            })
        
        if len(scores) < 20:
            continue
        
        # 生成双榜单
        df_scores = pd.DataFrame(scores)
        mr_list = df_scores.nlargest(mr_n, 'adjusted_mr_score')['code'].tolist()
        trend_list = df_scores.nlargest(trend_n, 'trend_rank_score')['code'].tolist()
        dual_advantage = [code for code in mr_list if code in trend_list]
        
        # 计算未来收益
        for code in mr_list:
            df = stock_data[code]['df']
            if len(df) > start_idx + holding_days:
                entry_price = df['close'].iloc[start_idx]
                exit_price = df['close'].iloc[start_idx + holding_days]
                ret = (exit_price - entry_price) / entry_price
                
                mr_trades.append({
                    'code': code,
                    'name': stock_data[code]['name'],
                    'entry_date': df.index[start_idx],
                    'return': ret,
                    'is_dual': code in dual_advantage
                })
        
        for code in trend_list:
            df = stock_data[code]['df']
            if len(df) > start_idx + holding_days:
                entry_price = df['close'].iloc[start_idx]
                exit_price = df['close'].iloc[start_idx + holding_days]
                ret = (exit_price - entry_price) / entry_price
                
                trend_trades.append({
                    'code': code,
                    'name': stock_data[code]['name'],
                    'entry_date': df.index[start_idx],
                    'return': ret,
                    'is_dual': code in dual_advantage
                })
        
        # 双优股票单独记录
        for code in dual_advantage:
            df = stock_data[code]['df']
            if len(df) > start_idx + holding_days:
                entry_price = df['close'].iloc[start_idx]
                exit_price = df['close'].iloc[start_idx + holding_days]
                ret = (exit_price - entry_price) / entry_price
                
                dual_trades.append({
                    'code': code,
                    'name': stock_data[code]['name'],
                    'entry_date': df.index[start_idx],
                    'return': ret
                })
    
    # 统计结果
    print("\n" + "=" * 80)
    print("回测结果")
    print("=" * 80)
    
    if mr_trades:
        df_mr = pd.DataFrame(mr_trades)
        print(f"\n【超跌榜】均值回归引擎")
        print(f"  交易次数: {len(df_mr)}")
        print(f"  平均收益率: {df_mr['return'].mean():.2%}")
        print(f"  胜率: {(df_mr['return'] > 0).sum() / len(df_mr):.2%}")
        print(f"  Sharpe比率: {df_mr['return'].mean() / (df_mr['return'].std() + 1e-6):.3f}")
        print(f"  最大单次收益: {df_mr['return'].max():.2%}")
        print(f"  最大单次亏损: {df_mr['return'].min():.2%}")
        
        # 双优股票在超跌榜中的表现
        df_mr_dual = df_mr[df_mr['is_dual']]
        if len(df_mr_dual) > 0:
            print(f"\n  其中双优股票:")
            print(f"    交易次数: {len(df_mr_dual)}")
            print(f"    平均收益率: {df_mr_dual['return'].mean():.2%}")
            print(f"    胜率: {(df_mr_dual['return'] > 0).sum() / len(df_mr_dual):.2%}")
    
    if trend_trades:
        df_trend = pd.DataFrame(trend_trades)
        print(f"\n【趋势榜】趋势跟随引擎")
        print(f"  交易次数: {len(df_trend)}")
        print(f"  平均收益率: {df_trend['return'].mean():.2%}")
        print(f"  胜率: {(df_trend['return'] > 0).sum() / len(df_trend):.2%}")
        print(f"  Sharpe比率: {df_trend['return'].mean() / (df_trend['return'].std() + 1e-6):.3f}")
        print(f"  最大单次收益: {df_trend['return'].max():.2%}")
        print(f"  最大单次亏损: {df_trend['return'].min():.2%}")
        
        # 双优股票在趋势榜中的表现
        df_trend_dual = df_trend[df_trend['is_dual']]
        if len(df_trend_dual) > 0:
            print(f"\n  其中双优股票:")
            print(f"    交易次数: {len(df_trend_dual)}")
            print(f"    平均收益率: {df_trend_dual['return'].mean():.2%}")
            print(f"    胜率: {(df_trend_dual['return'] > 0).sum() / len(df_trend_dual):.2%}")
    
    if dual_trades:
        df_dual = pd.DataFrame(dual_trades)
        print(f"\n【⭐双优股票】既超跌又趋势强")
        print(f"  出现次数: {len(df_dual)}")
        print(f"  平均收益率: {df_dual['return'].mean():.2%}")
        print(f"  胜率: {(df_dual['return'] > 0).sum() / len(df_dual):.2%}")
        print(f"  Sharpe比率: {df_dual['return'].mean() / (df_dual['return'].std() + 1e-6):.3f}")
        print(f"  最大单次收益: {df_dual['return'].max():.2%}")
        print(f"  最大单次亏损: {df_dual['return'].min():.2%}")
    
    # 对比分析
    if mr_trades and trend_trades:
        print("\n" + "=" * 80)
        print("对比分析")
        print("=" * 80)
        
        mr_return = df_mr['return'].mean()
        trend_return = df_trend['return'].mean()
        mr_winrate = (df_mr['return'] > 0).sum() / len(df_mr)
        trend_winrate = (df_trend['return'] > 0).sum() / len(df_trend)
        
        print(f"\n超跌榜 vs 趋势榜:")
        print(f"  收益率: {mr_return:.2%} vs {trend_return:.2%} (差异 {trend_return - mr_return:+.2%})")
        print(f"  胜率: {mr_winrate:.2%} vs {trend_winrate:.2%} (差异 {trend_winrate - mr_winrate:+.2%})")
        
        if dual_trades:
            dual_return = df_dual['return'].mean()
            dual_winrate = (df_dual['return'] > 0).sum() / len(df_dual)
            print(f"\n双优股票 vs 单一类型:")
            print(f"  收益率: {dual_return:.2%} (超跌榜{dual_return - mr_return:+.2%}, 趋势榜{dual_return - trend_return:+.2%})")
            print(f"  胜率: {dual_winrate:.2%} (超跌榜{dual_winrate - mr_winrate:+.2%}, 趋势榜{dual_winrate - trend_winrate:+.2%})")
    
    # 保存详细结果
    result_dir = os.path.join(os.path.dirname(__file__), "../../results")
    os.makedirs(result_dir, exist_ok=True)
    
    if mr_trades:
        df_mr.to_csv(os.path.join(result_dir, "backtest_mr_list.csv"), index=False)
    if trend_trades:
        df_trend.to_csv(os.path.join(result_dir, "backtest_trend_list.csv"), index=False)
    if dual_trades:
        df_dual.to_csv(os.path.join(result_dir, "backtest_dual_advantage.csv"), index=False)
    
    print(f"\n📝 详细结果已保存到: {result_dir}/")

def main():
    parser = argparse.ArgumentParser(description='双引擎双榜单回测')
    parser.add_argument('--stocks', type=int, default=200, help='回测股票数量')
    args = parser.parse_args()
    
    # 加载股票池
    pool_path = os.path.join(os.path.dirname(__file__), "../../mydate/stock_pool_all.json")
    with open(pool_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    all_stocks = []
    if 'stocks' in data:
        for sector, stock_list in data['stocks'].items():
            all_stocks.extend(stock_list)
    
    print(f"股票池大小: {len(all_stocks)} 只")
    print(f"回测股票数: {min(args.stocks, len(all_stocks))} 只")
    
    # 加载指数数据（暂时跳过，因为数据源不稳定）
    print("\n⚠️ 跳过指数数据加载（数据源不稳定），相对强度因子将使用默认值0")
    index_df = None
    
    # K线数据目录
    kline_dir = os.path.join(os.path.dirname(__file__), "../../mydate/backtest_kline")
    
    # 运行回测
    backtest_dual_lists(all_stocks, kline_dir, index_df, args.stocks)

if __name__ == '__main__':
    main()
