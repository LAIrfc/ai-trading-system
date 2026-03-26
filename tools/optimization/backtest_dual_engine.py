#!/usr/bin/env python3
"""
双引擎调度架构回测验证工具

对比测试：
1. 单引擎（仅均值回归，旧权重）
2. 单引擎（仅均值回归，新权重）
3. 双引擎（均值回归 + 趋势引擎）

评估指标：
- Sharpe比率
- 年化收益
- 最大回撤
- 胜率
- 交易次数

用法:
  python3 tools/optimization/backtest_dual_engine.py                # 全量回测（本地数据）
  python3 tools/optimization/backtest_dual_engine.py --stocks 100   # 前100只（本地数据）
  python3 tools/optimization/backtest_dual_engine.py --quick        # 快速测试（前50只）
  python3 tools/optimization/backtest_dual_engine.py --online --pool mydate/stock_pool_all.json --stocks 808  # 在线数据
"""

import sys
import os
import time
import json
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.strategies.trend_strategies import Trend_Composite, Momentum_Adj
from src.data.fetchers.data_prefetch import fetch_stock_daily
from src.utils.pool_loader import load_pool

BACKTEST_DIR = os.path.join(os.path.dirname(__file__), "../../mydate/backtest_kline")
RESULT_DIR = os.path.join(os.path.dirname(__file__), "../../results/dual_engine_backtest")
os.makedirs(RESULT_DIR, exist_ok=True)


def p(*a, **kw):
    print(*a, **kw, flush=True)


# MA/MACD 配置对比验证
# 配置A：完全排除 MA/MACD（方案1）
WEIGHTS_NO_MA_MACD = {
    'PB': 2.0, 'BOLL': 1.95, 'RSI': 1.82, 'PE': 1.68,
    'PEPB': 1.61, 'KDJ': 1.5, 'DUAL': 1.39,
    'SENTIMENT': 0.32, 'NEWS': 0.32, 'MONEY_FLOW': 0.3,
    # MA 和 MACD 完全不参与
}

# 配置B：降权 MA/MACD（方案3，当前推荐）
WEIGHTS_LOW_MA_MACD = {
    'PB': 2.0, 'BOLL': 1.95, 'RSI': 1.82, 'PE': 1.68,
    'PEPB': 1.61, 'KDJ': 1.5, 'DUAL': 1.39,
    'SENTIMENT': 0.32, 'NEWS': 0.32, 'MONEY_FLOW': 0.3,
    'MACD': 0.5,  # 降权：技术确认因子
    'MA': 0.3,    # 降权：技术确认因子
}

# 配置C：原权重 MA/MACD（方案2）
WEIGHTS_FULL_MA_MACD = {
    'PB': 2.0, 'BOLL': 1.95, 'RSI': 1.82, 'PE': 1.68,
    'PEPB': 1.61, 'KDJ': 1.5, 'DUAL': 1.39, 'MACD': 1.13,
    'MA': 0.88, 'SENTIMENT': 0.32, 'NEWS': 0.32, 'MONEY_FLOW': 0.3,
}

# 旧配置（用于对比）
OLD_WEIGHTS = {
    'BOLL': 1.5, 'MACD': 1.3, 'KDJ': 1.1, 'MA': 1.0,
    'DUAL': 0.9, 'RSI': 0.8,
    'PEPB': 0.8, 'PE': 0.6, 'PB': 0.6,
    'NEWS': 0.5, 'SENTIMENT': 0.5, 'MONEY_FLOW': 0.4,
}

# 双引擎配置
TREND_WEIGHT_BASE = 0.5
TREND_WEIGHT_RANGE = 0.5
TREND_SCORE_WEIGHT = 0.7
MOMENTUM_SCORE_WEIGHT = 0.3


def simple_backtest(signals, prices):
    """
    简单回测：根据信号序列和价格序列计算收益
    
    Args:
        signals: 信号序列 (1=买入, -1=卖出, 0=空仓)
        prices: 价格序列
    
    Returns:
        dict: 包含收益、Sharpe、最大回撤等指标
    """
    if len(signals) != len(prices) or len(signals) == 0:
        return None
    
    # 计算每日收益
    returns = []
    position = 0
    
    for i in range(1, len(signals)):
        if signals[i-1] == 1:  # 持仓
            ret = (prices[i] - prices[i-1]) / prices[i-1]
            returns.append(ret)
            position = 1
        else:
            returns.append(0)
            position = 0
    
    if len(returns) == 0:
        return None
    
    returns = np.array(returns)
    
    # 累计收益
    cum_returns = (1 + returns).cumprod()
    total_return = cum_returns[-1] - 1
    
    # Sharpe比率
    if returns.std() > 0:
        sharpe = returns.mean() / returns.std() * np.sqrt(252)
    else:
        sharpe = 0
    
    # 最大回撤
    peak = np.maximum.accumulate(cum_returns)
    drawdown = (cum_returns - peak) / peak
    max_drawdown = drawdown.min()
    
    # 年化收益
    years = len(returns) / 252
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
    
    # 胜率
    positive_returns = returns[returns > 0]
    win_rate = len(positive_returns) / len(returns[returns != 0]) if len(returns[returns != 0]) > 0 else 0
    
    # 交易次数
    trades = np.sum(np.diff(signals) != 0)
    
    return {
        'total_return': total_return * 100,
        'annual_return': annual_return * 100,
        'sharpe': sharpe,
        'max_drawdown': max_drawdown * 100,
        'win_rate': win_rate * 100,
        'trades': trades,
    }


def backtest_single_engine(df, weights, reverse_dual=True):
    """
    单引擎回测（仅均值回归）
    
    模拟 recommend_today.py 中的12策略加权投票逻辑
    """
    from src.strategies.ma_cross import MACrossStrategy
    from src.strategies.macd_cross import MACDStrategy
    from src.strategies.rsi_signal import RSIStrategy
    from src.strategies.bollinger_band import BollingerBandStrategy
    from src.strategies.kdj_signal import KDJStrategy
    from src.strategies.dual_momentum import DualMomentumSingleStrategy
    from src.strategies.fundamental_pe import PEStrategy
    from src.strategies.fundamental_pb import PBStrategy
    from src.strategies.fundamental_pe_pb import PE_PB_CombinedStrategy
    from src.strategies.base import Strategy
    
    Strategy._BACKTEST_ACTIVE = True
    
    strategies = {
        'MA': MACrossStrategy(),
        'MACD': MACDStrategy(),
        'RSI': RSIStrategy(),
        'BOLL': BollingerBandStrategy(),
        'KDJ': KDJStrategy(),
        'DUAL': DualMomentumSingleStrategy(),
        'PE': PEStrategy(),
        'PB': PBStrategy(),
        'PEPB': PE_PB_CombinedStrategy(),
    }
    
    # 生成信号序列
    signals = []
    for idx in range(len(df)):
        if idx < 60:  # 需要足够的历史数据
            signals.append(0)
            continue
        
        df_slice = df.iloc[:idx+1]
        score = 0
        
        for name, strat in strategies.items():
            try:
                if len(df_slice) < strat.min_bars:
                    continue
                
                sig = strat.safe_analyze(df_slice)
                
                # DUAL反向
                if reverse_dual and name == 'DUAL':
                    if sig.action == 'BUY':
                        sig.action = 'SELL'
                    elif sig.action == 'SELL':
                        sig.action = 'BUY'
                
                w = weights.get(name, 1.0)
                if sig.action == 'BUY':
                    score += w * sig.confidence
                elif sig.action == 'SELL':
                    score -= w * sig.confidence
            except Exception:
                pass
        
        # 信号判断
        if score > 5:
            signals.append(1)
        elif score < -5:
            signals.append(-1)
        else:
            signals.append(0)
    
    return simple_backtest(signals, df['close'].values)


def backtest_dual_engine(df, mr_weights, trend_base=0.5, trend_range=0.5):
    """
    双引擎回测（均值回归 + 趋势引擎）
    
    逻辑：
    1. 计算均值回归得分（mr_score）
    2. 计算趋势得分（trend_score）
    3. 软过滤：adjusted_score = mr_score × (trend_base + trend_range × trend_weight)
    4. 根据adjusted_score生成信号
    """
    from src.strategies.ma_cross import MACrossStrategy
    from src.strategies.macd_cross import MACDStrategy
    from src.strategies.rsi_signal import RSIStrategy
    from src.strategies.bollinger_band import BollingerBandStrategy
    from src.strategies.kdj_signal import KDJStrategy
    from src.strategies.dual_momentum import DualMomentumSingleStrategy
    from src.strategies.fundamental_pe import PEStrategy
    from src.strategies.fundamental_pb import PBStrategy
    from src.strategies.fundamental_pe_pb import PE_PB_CombinedStrategy
    from src.strategies.base import Strategy
    
    Strategy._BACKTEST_ACTIVE = True
    
    strategies = {
        'MA': MACrossStrategy(),
        'MACD': MACDStrategy(),
        'RSI': RSIStrategy(),
        'BOLL': BollingerBandStrategy(),
        'KDJ': KDJStrategy(),
        'DUAL': DualMomentumSingleStrategy(),
        'PE': PEStrategy(),
        'PB': PBStrategy(),
        'PEPB': PE_PB_CombinedStrategy(),
    }
    
    # 趋势策略
    trend_strat = Trend_Composite()
    
    # 生成信号序列
    signals = []
    for idx in range(len(df)):
        if idx < 60:
            signals.append(0)
            continue
        
        df_slice = df.iloc[:idx+1]
        
        # 均值回归得分
        mr_score = 0
        for name, strat in strategies.items():
            try:
                if len(df_slice) < strat.min_bars:
                    continue
                
                sig = strat.safe_analyze(df_slice)
                
                # DUAL反向
                if name == 'DUAL':
                    if sig.action == 'BUY':
                        sig.action = 'SELL'
                    elif sig.action == 'SELL':
                        sig.action = 'BUY'
                
                w = mr_weights.get(name, 1.0)
                if sig.action == 'BUY':
                    mr_score += w * sig.confidence
                elif sig.action == 'SELL':
                    mr_score -= w * sig.confidence
            except Exception:
                pass
        
        # 趋势得分
        try:
            trend_df = trend_strat.generate_signals(df_slice)
            if 'trend_score' in trend_df.columns and not trend_df.empty:
                trend_score = float(trend_df['trend_score'].iloc[-1])
                trend_weight = max(0.0, min(1.0, trend_score))
            else:
                trend_weight = 0.0
        except Exception:
            trend_weight = 0.0
        
        # 软过滤调整
        adjusted_score = mr_score * (trend_base + trend_range * trend_weight)
        
        # 信号判断
        if adjusted_score > 5:
            signals.append(1)
        elif adjusted_score < -5:
            signals.append(-1)
        else:
            signals.append(0)
    
    return simple_backtest(signals, df['close'].values)


def run_backtest_comparison(stock_files, max_stocks=0):
    """
    运行MA/MACD配置对比回测
    
    对比三种配置：
    - 配置A：完全排除 MA/MACD
    - 配置B：降权 MA/MACD（当前推荐）
    - 配置C：原权重 MA/MACD
    
    Returns:
        dict: 三种配置的汇总统计
    """
    if max_stocks > 0:
        stock_files = stock_files[:max_stocks]
    
    results = {
        'config_a_no_ma_macd': [],      # 配置A：排除MA/MACD
        'config_b_low_ma_macd': [],     # 配置B：降权MA/MACD（推荐）
        'config_c_full_ma_macd': [],    # 配置C：原权重MA/MACD
    }
    
    total = len(stock_files)
    p(f"\n{'='*80}")
    p(f"🔬 MA/MACD 技术确认因子验证回测")
    p(f"{'='*80}")
    p(f"📊 回测股票数: {total}")
    p(f"📈 配置A: 完全排除 MA/MACD（方案1）")
    p(f"📈 配置B: 降权 MA/MACD (MA=0.3, MACD=0.5)（方案3，推荐）⭐")
    p(f"📈 配置C: 原权重 MA/MACD (MA=0.88, MACD=1.13)（方案2）")
    p(f"{'='*80}\n")
    
    for i, fname in enumerate(stock_files):
        code = fname.replace('.parquet', '')
        path = os.path.join(BACKTEST_DIR, fname)
        
        try:
            df = pd.read_parquet(path)
            if len(df) < 200:
                continue
            
            # 配置A：排除 MA/MACD
            r_a = backtest_single_engine(df, WEIGHTS_NO_MA_MACD, reverse_dual=True)
            if r_a:
                results['config_a_no_ma_macd'].append(r_a)
            
            # 配置B：降权 MA/MACD（推荐）
            r_b = backtest_single_engine(df, WEIGHTS_LOW_MA_MACD, reverse_dual=True)
            if r_b:
                results['config_b_low_ma_macd'].append(r_b)
            
            # 配置C：原权重 MA/MACD
            r_c = backtest_single_engine(df, WEIGHTS_FULL_MA_MACD, reverse_dual=True)
            if r_c:
                results['config_c_full_ma_macd'].append(r_c)
            
            if (i + 1) % 50 == 0 or i < 5:
                p(f"  进度: {i+1}/{total} ({(i+1)/total*100:.1f}%) - {code}")
        
        except Exception as e:
            continue
    
    p(f"\n✅ 回测完成: {len(results['config_a_no_ma_macd'])} 只有效股票")
    return results


def run_backtest_comparison_online(stock_data):
    """
    在线模式：使用DataFrame字典进行MA/MACD配置对比回测
    
    Args:
        stock_data: dict {code: DataFrame}
    
    Returns:
        dict: 回测结果
    """
    results = {
        'config_a_no_ma_macd': [],      # 配置A：排除MA/MACD
        'config_b_low_ma_macd': [],     # 配置B：降权MA/MACD（推荐）
        'config_c_full_ma_macd': [],    # 配置C：原权重MA/MACD
    }
    
    total = len(stock_data)
    p(f"\n开始回测 {total} 只股票（在线数据）...")
    
    for i, (code, df) in enumerate(stock_data.items()):
        if (i + 1) % 50 == 0 or i < 5:
            p(f"  [{i+1}/{total}] 回测 {code}...")
        
        # 确保数据格式正确
        if df is None or df.empty or len(df) < 100:
            continue
        
        # 配置A：排除 MA/MACD
        r_a = backtest_single_engine(df, WEIGHTS_NO_MA_MACD, reverse_dual=True)
        if r_a:
            results['config_a_no_ma_macd'].append(r_a)
        
        # 配置B：降权 MA/MACD（推荐）
        r_b = backtest_single_engine(df, WEIGHTS_LOW_MA_MACD, reverse_dual=True)
        if r_b:
            results['config_b_low_ma_macd'].append(r_b)
        
        # 配置C：原权重 MA/MACD
        r_c = backtest_single_engine(df, WEIGHTS_FULL_MA_MACD, reverse_dual=True)
        if r_c:
            results['config_c_full_ma_macd'].append(r_c)
    
    p(f"\n✅ 回测完成: {len(results['config_a_no_ma_macd'])} 只有效股票")
    return results


def summarize_results(results):
    """汇总统计各配置的表现"""
    summary = {}
    
    for config_name, data_list in results.items():
        if len(data_list) == 0:
            continue
        
        df = pd.DataFrame(data_list)
        
        summary[config_name] = {
            'stock_count': len(df),
            'avg_sharpe': df['sharpe'].mean(),
            'median_sharpe': df['sharpe'].median(),
            'avg_annual_return': df['annual_return'].mean(),
            'avg_max_drawdown': df['max_drawdown'].mean(),
            'avg_win_rate': df['win_rate'].mean(),
            'avg_trades': df['trades'].mean(),
            'positive_sharpe_pct': (df['sharpe'] > 0).sum() / len(df) * 100,
            'positive_return_pct': (df['total_return'] > 0).sum() / len(df) * 100,
        }
    
    return summary


def print_comparison_table(summary):
    """打印MA/MACD配置对比表格"""
    p("\n" + "="*90)
    p("📊 MA/MACD 技术确认因子验证结果")
    p("="*90)
    
    configs = ['config_a_no_ma_macd', 'config_b_low_ma_macd', 'config_c_full_ma_macd']
    config_names = {
        'config_a_no_ma_macd': '配置A: 排除MA/MACD',
        'config_b_low_ma_macd': '配置B: 降权MA/MACD ⭐',
        'config_c_full_ma_macd': '配置C: 原权重MA/MACD',
    }
    
    # 表头
    p(f"\n{'指标':<20} {'配置A(排除)':>16} {'配置B(降权)⭐':>17} {'配置C(原权重)':>17} {'最优'}")
    p("-" * 90)
    
    metrics = [
        ('avg_sharpe', 'Sharpe比率', '.3f', 'max'),
        ('avg_annual_return', '年化收益%', '.2f', 'max'),
        ('avg_max_drawdown', '最大回撤%', '.2f', 'min'),
        ('avg_win_rate', '胜率%', '.1f', 'max'),
        ('avg_trades', '平均交易次数', '.1f', None),
        ('positive_sharpe_pct', '正Sharpe占比%', '.1f', 'max'),
        ('positive_return_pct', '正收益占比%', '.1f', 'max'),
    ]
    
    for key, label, fmt, best_type in metrics:
        values = []
        for config in configs:
            if config in summary:
                val = summary[config].get(key, 0)
                values.append(val)
            else:
                values.append(0)
        
        # 找出最优值
        if best_type == 'max':
            best_idx = values.index(max(values))
        elif best_type == 'min':
            best_idx = values.index(min(values))
        else:
            best_idx = -1
        
        # 打印
        row = f"{label:<20}"
        for i, val in enumerate(values):
            marker = " ⭐" if i == best_idx else "   "
            row += f" {val:>15{fmt}}{marker}"
        p(row)
    
    p("-" * 90)
    
    # 结论
    p("\n📈 验证结论:")
    
    sharpe_values = [summary[c]['avg_sharpe'] for c in configs if c in summary]
    best_config_idx = sharpe_values.index(max(sharpe_values))
    best_config = configs[best_config_idx]
    
    # 对比配置B与配置A
    if len(sharpe_values) >= 2:
        improvement_b_vs_a = ((sharpe_values[1] - sharpe_values[0]) / abs(sharpe_values[0]) * 100) if sharpe_values[0] != 0 else 0
        p(f"  配置B vs 配置A: Sharpe {sharpe_values[1]:.3f} vs {sharpe_values[0]:.3f} (差异 {improvement_b_vs_a:+.1f}%)")
    
    # 对比配置B与配置C
    if len(sharpe_values) >= 3:
        improvement_b_vs_c = ((sharpe_values[1] - sharpe_values[2]) / abs(sharpe_values[2]) * 100) if sharpe_values[2] != 0 else 0
        p(f"  配置B vs 配置C: Sharpe {sharpe_values[1]:.3f} vs {sharpe_values[2]:.3f} (差异 {improvement_b_vs_c:+.1f}%)")
    
    p(f"\n  🏆 最优配置: {config_names[best_config]} (Sharpe={sharpe_values[best_config_idx]:.3f})")
    
    if best_config == 'config_b_low_ma_macd':
        p("\n  ✅ 结论：配置B（降权MA/MACD）表现最优！")
        p("     - MA/MACD作为技术确认因子，以低权重参与mr_score是合理的")
        p("     - 建议保持当前配置（MA=0.3, MACD=0.5）")
    elif best_config == 'config_a_no_ma_macd':
        p("\n  ⚠️ 结论：配置A（排除MA/MACD）表现最优！")
        p("     - MA/MACD的技术确认作用未体现")
        p("     - 建议回退到方案1（完全排除MA/MACD）")
    else:
        p("\n  ⚠️ 结论：配置C（原权重MA/MACD）表现最优！")
        p("     - 降权可能过度，MA/MACD需要更高权重")
        p("     - 建议调整为方案2（MA=0.88, MACD=1.13）或中间值")


def fetch_online_data(codes, datalen=800, workers=8):
    """在线拉取股票数据"""
    p(f"📡 开始拉取 {len(codes)} 只股票的最新数据...")
    
    stock_data = {}
    success = 0
    failed = 0
    
    def fetch_one(code):
        try:
            df = fetch_stock_daily(code=code, datalen=datalen, min_bars=100)
            if df is not None and not df.empty and len(df) >= 100:
                return (code, df, True)
            return (code, None, False)
        except Exception as e:
            return (code, None, False)
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_one, code): code for code in codes}
        for i, future in enumerate(as_completed(futures)):
            code, df, ok = future.result()
            if ok:
                stock_data[code] = df
                success += 1
                if (i + 1) % 50 == 0 or i < 5:
                    p(f"  [{i+1}/{len(codes)}] {code} ✓ ({len(df)}条)")
            else:
                failed += 1
    
    p(f"✅ 数据拉取完成: 成功 {success}, 失败 {failed}")
    return stock_data


def main():
    parser = argparse.ArgumentParser(description='双引擎调度架构回测验证')
    parser.add_argument('--stocks', type=int, default=0, help='回测股票数量（0=全部）')
    parser.add_argument('--quick', action='store_true', help='快速测试（前50只）')
    parser.add_argument('--online', action='store_true', help='使用在线数据（实时拉取）')
    parser.add_argument('--pool', type=str, help='股票池文件（在线模式必需）')
    parser.add_argument('--workers', type=int, default=8, help='并发数（在线模式）')
    args = parser.parse_args()
    
    # 在线模式
    if args.online:
        if not args.pool:
            p("❌ 在线模式需要指定 --pool 参数")
            return
        
        # 加载股票池
        max_count = 50 if args.quick else (args.stocks if args.stocks > 0 else 99999)
        stocks = load_pool(args.pool, max_count=max_count, include_etf=False)
        codes = [s['code'] for s in stocks]
        
        p(f"📊 股票池: {args.pool}")
        p(f"📈 股票数: {len(codes)}")
        p()
        
        # 拉取数据
        t0 = time.time()
        stock_data = fetch_online_data(codes, datalen=800, workers=args.workers)
        fetch_time = time.time() - t0
        p(f"⏱️  拉取耗时: {fetch_time:.1f}秒\n")
        
        if len(stock_data) == 0:
            p("❌ 未获取到任何数据")
            return
        
        # 运行回测（直接使用DataFrame）
        t0 = time.time()
        results = run_backtest_comparison_online(stock_data)
        elapsed = time.time() - t0
    
    # 本地模式
    else:
        # 加载股票列表
        if not os.path.exists(BACKTEST_DIR):
            p(f"❌ 回测数据目录不存在: {BACKTEST_DIR}")
            p("   请先运行: python3 tools/data/backtest_prefetch.py")
            return
        
        stock_files = sorted([f for f in os.listdir(BACKTEST_DIR) if f.endswith('.parquet')])
        if len(stock_files) == 0:
            p("❌ 回测数据为空")
            return
        
        max_stocks = 50 if args.quick else (args.stocks if args.stocks > 0 else 0)
        
        p(f"回测数据目录: {BACKTEST_DIR}")
        p(f"可用股票数: {len(stock_files)}")
        p(f"本次回测: {max_stocks if max_stocks > 0 else len(stock_files)} 只")
        p()
        
        # 运行回测
        t0 = time.time()
        results = run_backtest_comparison(stock_files, max_stocks)
        elapsed = time.time() - t0
    
    # 汇总统计
    summary = summarize_results(results)
    
    # 打印对比表格
    print_comparison_table(summary)
    
    # 保存结果
    output_file = os.path.join(RESULT_DIR, f"comparison_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'summary': summary,
            'config': {
                'weights_no_ma_macd': WEIGHTS_NO_MA_MACD,
                'weights_low_ma_macd': WEIGHTS_LOW_MA_MACD,
                'weights_full_ma_macd': WEIGHTS_FULL_MA_MACD,
                'trend_weight_base': TREND_WEIGHT_BASE,
                'trend_weight_range': TREND_WEIGHT_RANGE,
            },
            'elapsed_seconds': elapsed,
        }, f, indent=2, ensure_ascii=False)
    
    p(f"\n💾 结果已保存: {output_file}")
    p(f"⏱️  总耗时: {elapsed:.1f}秒")


if __name__ == '__main__':
    main()
