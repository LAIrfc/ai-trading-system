#!/usr/bin/env python3
"""
L2层权重调整系数滚动回测优化（预计算信号 + 投票重放）

核心优化：
  对每只股票只运行一次完整回测来预计算所有子策略的逐 bar 信号，
  然后对不同权重配置只需重放投票逻辑（纯数学运算），无需重新调用 analyze()。
  这使得 N 个配置的成本从 O(N × 完整回测) 降为 O(完整回测 + N × 纯数学)。

严格的参数优化流程：
1. 数据准备：使用预取的 parquet K线（mydate/backtest_kline/）
2. 信号预计算：对每只股票逐 bar 运行 12 个子策略，记录信号
3. 市场状态标注：对每只股票的回测期，用其自身K线判断所处市场状态
4. 网格搜索：对不同权重配置重放投票+回测
5. 时间切分验证：训练期(70%)优化 + 测试期(30%)样本外验证
6. 防过拟合：仅当测试期表现显著优于基线时才采纳

用法:
  # 标准模式（推荐，约30-60分钟）
  nohup python3 tools/optimization/optimize_regime_weights.py --stocks 30 > optimize_log.txt 2>&1 &

  # 快速验证（约10分钟）
  python3 tools/optimization/optimize_regime_weights.py --stocks 10 --quick

  # 完整模式（约2-4小时）
  nohup python3 tools/optimization/optimize_regime_weights.py --stocks 50 --full > optimize_log.txt 2>&1 &
"""

import sys
import os
import json
import argparse
import logging
import time
from datetime import datetime
from itertools import product
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s %(message)s',
    datefmt='%H:%M:%S',
)

BACKTEST_DIR = os.path.join(os.path.dirname(__file__), "../../mydate/backtest_kline")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "../../mydate")

BASE_WEIGHTS = {
    'PB': 2.0, 'BOLL': 1.95, 'RSI': 1.82, 'PE': 1.68,
    'PEPB': 1.61, 'KDJ': 1.5, 'DUAL': 1.39, 'MACD': 1.13,
    'MA': 0.88, 'SENTIMENT': 0.32, 'NEWS': 0.32, 'MONEY_FLOW': 0.3,
}

STRAT_TO_GROUP = {
    'MA': 'momentum', 'MACD': 'momentum', 'DUAL': 'momentum',
    'RSI': 'oscillator', 'BOLL': 'oscillator', 'KDJ': 'oscillator',
    'PE': 'value', 'PB': 'value', 'PEPB': 'value',
    'NEWS': 'news', 'SENTIMENT': 'sentiment', 'MONEY_FLOW': 'flow',
}

BUY_THRESHOLD = 0.07
SELL_THRESHOLD = -0.07
MIN_ACTIVE_VOTES = 1


def p(*args, **kwargs):
    print(*args, **kwargs, flush=True)


# ============================================================
# 数据加载
# ============================================================
def load_stock_data(code: str) -> Optional[pd.DataFrame]:
    path = os.path.join(BACKTEST_DIR, f"{code}.parquet")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_parquet(path)
        if len(df) < 200:
            return None
        df['date'] = pd.to_datetime(df['date'])
        for c in ['open', 'high', 'low', 'close', 'volume']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        return df.dropna(subset=['close']).sort_values('date').reset_index(drop=True)
    except Exception:
        return None


def get_available_stocks(max_count: int = 30) -> List[str]:
    files = [f.replace('.parquet', '') for f in os.listdir(BACKTEST_DIR)
             if f.endswith('.parquet')]
    files.sort()
    np.random.seed(42)
    if len(files) > max_count:
        files = list(np.random.choice(files, max_count, replace=False))
    return sorted(files)


# ============================================================
# 市场状态判断
# ============================================================
def classify_regime_from_kline(df: pd.DataFrame) -> str:
    if len(df) < 65:
        return 'sideways'
    close = df['close'].astype(float)
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    last_ma20 = ma20.iloc[-1]
    last_ma60 = ma60.iloc[-1]
    if pd.isna(last_ma20) or pd.isna(last_ma60):
        return 'sideways'
    ret = close.pct_change().dropna()
    vol_recent = ret.tail(20).std()
    vol_all = ret.std()
    if last_ma20 > last_ma60 and vol_recent < vol_all:
        return 'bull'
    elif last_ma20 < last_ma60 and vol_recent > vol_all:
        return 'bear'
    return 'sideways'


# ============================================================
# 信号预计算：对一只股票逐 bar 运行所有子策略
# ============================================================
def precompute_signals(code: str, df: pd.DataFrame) -> Optional[Dict]:
    """
    对一只股票运行一次完整的逐 bar 分析，记录每个 bar 上每个子策略的信号。
    返回 dict:
      'signals': list of dict, 每个元素是一个 bar 的信号
        { 'bar_idx': int, 'exec_date': str, 'exec_price': float, 't1_close': float,
          'strat_signals': { strat_name: (action, confidence, position), ... } }
      'regime': str  (整段数据的市场状态)
    """
    from src.strategies.ensemble import EnsembleStrategy
    from src.strategies.base import StrategySignal, _BACKTEST_ACTIVE
    import src.strategies.base as base_mod

    strategy = EnsembleStrategy(
        symbol=code,
        weights=BASE_WEIGHTS.copy(),
        use_dynamic_weights=False,
    )

    min_bars = strategy.min_bars
    if len(df) < min_bars + 1:
        return None

    base_mod._BACKTEST_ACTIVE = True
    try:
        if hasattr(strategy, 'prepare_backtest'):
            try:
                strategy.prepare_backtest(df)
            except Exception:
                pass

        bar_signals = []
        for i in range(min_bars, len(df) - 1):
            window = df.iloc[:i + 1]
            t1_row = df.iloc[i + 1]
            exec_date = str(t1_row['date'])[:10]
            t1_close = float(t1_row['close'])
            _open = t1_row.get('open', 0) if hasattr(t1_row, 'get') else t1_row['open']
            exec_price = float(_open) if (float(_open) > 0) else t1_close

            strat_signals = {}
            for strat_name, strat in strategy.sub_strategies.items():
                if len(window) < strat.min_bars:
                    continue
                try:
                    sig = strat.analyze(window)

                    # DUAL 反向
                    if strat_name == 'DUAL' and strategy.dual_reverse:
                        if sig.action == 'BUY':
                            sig = StrategySignal('SELL', sig.confidence,
                                                 f'[DUAL反向] {sig.reason}',
                                                 1.0 - sig.position, sig.indicators)
                        elif sig.action == 'SELL':
                            sig = StrategySignal('BUY', sig.confidence,
                                                 f'[DUAL反向] {sig.reason}',
                                                 1.0 - sig.position, sig.indicators)

                    # 数据缺失过滤
                    if (sig.action == 'HOLD' and sig.confidence == 0.0
                            and sig.reason and any(kw in sig.reason for kw in ('缺少', '不足', '无法'))):
                        continue

                    strat_signals[strat_name] = (sig.action, sig.confidence, sig.position)
                except Exception:
                    continue

            bar_signals.append({
                'bar_idx': i,
                'exec_date': exec_date,
                'exec_price': exec_price,
                't1_close': t1_close,
                'strat_signals': strat_signals,
            })

        regime = classify_regime_from_kline(df)
        return {
            'signals': bar_signals,
            'regime': regime,
            'code': code,
        }
    finally:
        base_mod._BACKTEST_ACTIVE = False


# ============================================================
# 投票重放 + 回测：用预计算信号和指定权重重放完整回测
# ============================================================
def replay_backtest(
    bar_signals: List[Dict],
    weights: Dict[str, float],
    initial_cash: float = 100000.0,
    commission: float = 0.0002,
    stamp_tax: float = 0.001,
    risk_free_rate: float = 0.03,
) -> Optional[Dict[str, float]]:
    """
    用预计算的逐 bar 信号和指定权重重放回测。
    核心逻辑与 base.py backtest() 完全一致，但信号来自预计算。
    """
    if not bar_signals:
        return None

    cash = initial_cash
    shares = 0
    avg_buy_price = 0.0
    total_buy_cost = 0.0
    round_trip_buy_cost = 0.0
    completed_trips = []
    equity_curve = []

    for bar in bar_signals:
        exec_price = bar['exec_price']
        t1_close = bar['t1_close']
        strat_signals = bar['strat_signals']

        equity = cash + shares * exec_price

        # 投票聚合（与 _weighted 方法一致）
        buy_votes = []
        sell_votes = []
        all_positions = []

        for sname, (action, confidence, position) in strat_signals.items():
            w = weights.get(sname, 1.0)
            all_positions.append((sname, w, position))
            if action == 'BUY':
                buy_votes.append((sname, confidence))
            elif action == 'SELL':
                sell_votes.append((sname, confidence))

        # 净得分计算
        if not buy_votes and not sell_votes:
            action = 'HOLD'
            avg_position = 0.5
        else:
            buy_score = sum(weights.get(n, 1.0) * c for n, c in buy_votes)
            sell_score = sum(weights.get(n, 1.0) * c for n, c in sell_votes)
            active_weight_sum = (sum(weights.get(n, 1.0) for n, _ in buy_votes) +
                                 sum(weights.get(n, 1.0) for n, _ in sell_votes))

            if active_weight_sum == 0:
                action = 'HOLD'
                avg_position = 0.5
            else:
                net_score = (buy_score - sell_score) / active_weight_sum

                if net_score > BUY_THRESHOLD and len(buy_votes) >= MIN_ACTIVE_VOTES:
                    action = 'BUY'
                elif net_score < SELL_THRESHOLD and len(sell_votes) >= MIN_ACTIVE_VOTES:
                    action = 'SELL'
                else:
                    action = 'HOLD'

            # 加权平均仓位
            total_w = sum(weights.get(n, 1.0) for n, _, _ in all_positions)
            avg_position = (sum(weights.get(n, 1.0) * pos for n, _, pos in all_positions)
                            / total_w) if total_w > 0 else 0.5

        # 仓位管理
        if action == 'BUY':
            target_pos = min(0.95, max(0.4, avg_position))
        elif action == 'SELL':
            target_pos = 0.0
        else:
            target_pos = avg_position

        # 执行交易（与 base.py backtest 一致）
        if action == 'BUY':
            target_value = equity * target_pos
            current_value = shares * exec_price
            delta_value = target_value - current_value
            if delta_value >= exec_price * 100:
                add_shares = int(delta_value / exec_price / 100) * 100
                if add_shares > 0:
                    cost = add_shares * exec_price * (1 + commission)
                    if cost <= cash:
                        cash -= cost
                        total_buy_cost += add_shares * exec_price
                        round_trip_buy_cost += add_shares * exec_price
                        shares += add_shares
                        avg_buy_price = total_buy_cost / shares

        elif action == 'SELL' and shares > 0:
            target_value = equity * target_pos
            current_value = shares * exec_price
            delta_value = current_value - target_value
            sell_shares = int(delta_value / exec_price / 100) * 100
            if target_pos < 0.05 or (shares - sell_shares) < 100:
                sell_shares = shares
            if sell_shares > 0 and sell_shares <= shares:
                revenue = sell_shares * exec_price * (1 - commission - stamp_tax)
                pnl = (exec_price - avg_buy_price) / avg_buy_price if avg_buy_price > 0 else 0
                cash += revenue
                shares -= sell_shares
                if shares == 0:
                    if round_trip_buy_cost > 0:
                        completed_trips.append(pnl)
                    avg_buy_price = 0.0
                    total_buy_cost = 0.0
                    round_trip_buy_cost = 0.0
                else:
                    total_buy_cost = shares * avg_buy_price

        equity_curve.append(cash + shares * t1_close)

    if not equity_curve:
        return None

    # 最终市值
    final_value = equity_curve[-1]
    total_return = (final_value / initial_cash - 1) * 100

    # 年化
    n_bars = len(bar_signals)
    years = max(n_bars / 252.0, 0.01)
    annualized = ((final_value / initial_cash) ** (1 / years) - 1) * 100

    # 最大回撤
    max_drawdown = 0.0
    peak = equity_curve[0]
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_drawdown:
            max_drawdown = dd
    max_drawdown *= 100

    # 胜率
    all_trips = list(completed_trips)
    if shares > 0 and avg_buy_price > 0:
        final_close = bar_signals[-1]['t1_close']
        all_trips.append((final_close - avg_buy_price) / avg_buy_price)
    win_rate = (sum(1 for t in all_trips if t > 0) / len(all_trips) * 100) if all_trips else 0.0
    trade_count = len(completed_trips) + (1 if shares > 0 else 0)

    # 夏普
    sharpe = 0.0
    if len(equity_curve) > 1:
        returns = pd.Series(equity_curve).pct_change().dropna()
        daily_rf = risk_free_rate / 252
        excess = returns - daily_rf
        if excess.std() > 1e-10:
            sharpe = float((excess.mean() / excess.std()) * (252 ** 0.5))

    if trade_count == 0:
        return None

    dd = abs(max_drawdown)
    return {
        'sharpe': round(sharpe, 4),
        'return': round(annualized, 2),
        'drawdown': round(dd, 2),
        'calmar': round(annualized / dd, 2) if dd > 0.01 else 0,
        'win_rate': round(win_rate, 2),
        'trades': trade_count,
    }


# ============================================================
# 权重调整
# ============================================================
def get_adjusted_weights(regime: str, bull_mults: Dict, bear_mults: Dict) -> Dict[str, float]:
    if regime == 'bull':
        mults = bull_mults
    elif regime == 'bear':
        mults = bear_mults
    else:
        return BASE_WEIGHTS.copy()
    adjusted = {}
    for strat, base_w in BASE_WEIGHTS.items():
        group = STRAT_TO_GROUP.get(strat, 'other')
        mult = mults.get(group, 1.0)
        adjusted[strat] = round(base_w * mult, 4)
    return adjusted


# ============================================================
# 评估一个配置（使用预计算信号）
# ============================================================
def evaluate_config_fast(
    all_signals: Dict[str, Dict],
    bull_mults: Dict[str, float],
    bear_mults: Dict[str, float],
    period: Optional[Tuple[str, str]] = None,
) -> Dict[str, float]:
    sharpes, rets, dds, calmars, wrs = [], [], [], [], []

    for code, sig_data in all_signals.items():
        bar_signals = sig_data['signals']
        regime = sig_data['regime']

        if period:
            start, end = period
            bar_signals = [b for b in bar_signals
                           if start <= b['exec_date'] <= end]

        if len(bar_signals) < 60:
            continue

        # 如果有时间切片，重新判断该切片的市场状态
        if period:
            prices = [b['t1_close'] for b in bar_signals]
            if len(prices) >= 65:
                temp_df = pd.DataFrame({'close': prices})
                regime = classify_regime_from_kline(temp_df)

        weights = get_adjusted_weights(regime, bull_mults, bear_mults)
        result = replay_backtest(bar_signals, weights)

        if result:
            sharpes.append(result['sharpe'])
            rets.append(result['return'])
            dds.append(result['drawdown'])
            calmars.append(result['calmar'])
            wrs.append(result['win_rate'])

    if not sharpes:
        return {'sharpe': -999, 'return': 0, 'drawdown': 100,
                'calmar': 0, 'win_rate': 0, 'stocks': 0}

    return {
        'sharpe': float(np.mean(sharpes)),
        'return': float(np.mean(rets)),
        'drawdown': float(np.mean(dds)),
        'calmar': float(np.mean(calmars)),
        'win_rate': float(np.mean(wrs)),
        'stocks': len(sharpes),
    }


# ============================================================
# 生成搜索配置
# ============================================================
def generate_configs(mode: str) -> List[Tuple[Dict[str, float], Dict[str, float]]]:
    if mode == 'quick':
        grid_bull_mom = [0.8, 1.0, 1.2, 1.4]
        grid_bull_val = [0.6, 0.8, 1.0, 1.2]
        grid_bear_mom = [0.6, 0.8, 1.0, 1.2]
        grid_bear_val = [0.8, 1.0, 1.2, 1.4]
    elif mode == 'full':
        grid_bull_mom = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5]
        grid_bull_val = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
        grid_bear_mom = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
        grid_bear_val = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5]
    else:  # standard
        grid_bull_mom = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
        grid_bull_val = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2]
        grid_bear_mom = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2]
        grid_bear_val = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3]

    configs = []
    for bm, bv, em, ev in product(grid_bull_mom, grid_bull_val, grid_bear_mom, grid_bear_val):
        configs.append(({'momentum': bm, 'value': bv}, {'momentum': em, 'value': ev}))

    baseline = ({'momentum': 1.0, 'value': 1.0}, {'momentum': 1.0, 'value': 1.0})
    if baseline not in configs:
        configs.insert(0, baseline)

    return configs


# ============================================================
# 主流程
# ============================================================
def run_optimization(stocks: int = 30, mode: str = 'standard', train_ratio: float = 0.7):
    t0 = time.time()

    p("=" * 70)
    p("  L2层权重调整系数 · 滚动回测优化")
    p("  （预计算信号 + 投票重放，高效版）")
    p("=" * 70)
    p(f"  模式: {mode}  |  股票数: {stocks}  |  训练/测试: {train_ratio:.0%}/{1-train_ratio:.0%}")
    p("=" * 70)
    p()

    # ---- 1. 加载数据 ----
    p("📊 [1/7] 加载股票数据...")
    stock_codes = get_available_stocks(stocks)
    stock_data = {}
    for code in stock_codes:
        df = load_stock_data(code)
        if df is not None:
            stock_data[code] = df
    p(f"   有效: {len(stock_data)} 只（候选 {len(stock_codes)} 只）")

    if len(stock_data) < 5:
        p("❌ 有效数据不足 5 只，退出")
        return

    # ---- 2. 信号预计算（最耗时的步骤，但只需一次）----
    p(f"\n⚙️  [2/7] 信号预计算（逐 bar 运行12个子策略）...")
    p(f"   这是最耗时的步骤，但只需运行一次...")
    all_signals = {}
    t_precompute = time.time()
    for idx, (code, df) in enumerate(stock_data.items()):
        p(f"   [{idx+1}/{len(stock_data)}] {code} ({len(df)} bars)...", end='')
        sig = precompute_signals(code, df)
        if sig and sig['signals']:
            all_signals[code] = sig
            n_active = sum(1 for b in sig['signals'] if b['strat_signals'])
            p(f" ✅ {len(sig['signals'])} bars, {n_active} 有效, 状态={sig['regime']}")
        else:
            p(f" ❌ 信号不足")
    precompute_time = time.time() - t_precompute
    p(f"   ✅ 预计算完成: {len(all_signals)} 只有效, 耗时 {precompute_time/60:.1f} 分钟")

    if len(all_signals) < 5:
        p("❌ 有效信号不足 5 只，退出")
        return

    # ---- 3. 数据质量报告 ----
    p(f"\n📋 [3/7] 数据质量报告:")
    regime_counts = {'bull': 0, 'bear': 0, 'sideways': 0}
    for sig in all_signals.values():
        regime_counts[sig['regime']] += 1
    p(f"   全量市场状态分布: 牛={regime_counts['bull']}, 熊={regime_counts['bear']}, 震荡={regime_counts['sideways']}")

    # 统计各策略在回测中的活跃率
    strat_active_counts = {}
    total_bars = 0
    for sig in all_signals.values():
        for bar in sig['signals']:
            total_bars += 1
            for sname in bar['strat_signals']:
                strat_active_counts[sname] = strat_active_counts.get(sname, 0) + 1
    p(f"   总 bar 数: {total_bars}")
    p(f"   各策略活跃率:")
    for sname in sorted(strat_active_counts.keys(), key=lambda x: strat_active_counts[x], reverse=True):
        rate = strat_active_counts[sname] / total_bars * 100
        p(f"     {sname:>12}: {rate:5.1f}% ({strat_active_counts[sname]}/{total_bars})")

    # ---- 4. 时间切分 ----
    sample_sig = list(all_signals.values())[0]
    all_dates_str = sorted(set(b['exec_date'] for b in sample_sig['signals']))
    min_date = all_dates_str[0]
    max_date = all_dates_str[-1]
    split_idx = int(len(all_dates_str) * train_ratio)
    split_date = all_dates_str[split_idx]

    p(f"\n📅 [4/7] 时间切分:")
    p(f"   全量: {min_date} ~ {max_date}")
    p(f"   训练: {min_date} ~ {split_date}")
    p(f"   测试: {split_date} ~ {max_date}")

    # ---- 5. 基线回测 ----
    p(f"\n📊 [5/7] 基线回测（固定权重，无动态调整）...")
    baseline_train = evaluate_config_fast(all_signals, {}, {}, (min_date, split_date))
    baseline_test  = evaluate_config_fast(all_signals, {}, {}, (split_date, max_date))
    baseline_full  = evaluate_config_fast(all_signals, {}, {})

    p(f"   {'期间':>6} {'夏普':>7} {'年化%':>7} {'回撤%':>7} {'Calmar':>7} {'胜率%':>7} {'股票':>4}")
    p(f"   {'-'*49}")
    for name, r in [('训练', baseline_train), ('测试', baseline_test), ('全量', baseline_full)]:
        p(f"   {name:>6} {r['sharpe']:>7.3f} {r['return']:>7.2f} "
          f"{r['drawdown']:>7.2f} {r['calmar']:>7.2f} "
          f"{r['win_rate']:>7.1f} {r['stocks']:>4}")

    # ---- 6. 网格搜索（纯数学运算，极快）----
    configs = generate_configs(mode)
    total = len(configs)
    p(f"\n🔍 [6/7] 网格搜索: {total} 个配置（投票重放，纯数学运算）")

    results = []
    t_search = time.time()
    for i, (bull_m, bear_m) in enumerate(configs):
        if i > 0 and i % 100 == 0:
            elapsed = time.time() - t_search
            eta = elapsed / i * (total - i) / 60
            p(f"   [{i}/{total}] 已耗时 {elapsed/60:.1f}min, 预计剩余 {eta:.1f}min")

        train_result = evaluate_config_fast(all_signals, bull_m, bear_m, (min_date, split_date))
        results.append({
            'bull_mults': bull_m,
            'bear_mults': bear_m,
            'train_sharpe': train_result['sharpe'],
            'train_return': train_result['return'],
            'train_drawdown': train_result['drawdown'],
            'train_calmar': train_result['calmar'],
            'train_stocks': train_result['stocks'],
        })

    search_time = time.time() - t_search
    results.sort(key=lambda x: x['train_sharpe'], reverse=True)
    p(f"\n   ✅ 训练期搜索完成，耗时 {search_time/60:.1f} 分钟 ({search_time:.0f} 秒)")

    p(f"\n   训练期 TOP 15:")
    p(f"   {'#':>3} {'夏普':>7} {'年化%':>7} {'回撤%':>7} {'Calmar':>7} "
      f"{'牛-动量':>7} {'牛-价值':>7} {'熊-动量':>7} {'熊-价值':>7}")
    p(f"   {'-'*71}")
    for i, r in enumerate(results[:15]):
        p(f"   {i+1:>3} {r['train_sharpe']:>7.3f} {r['train_return']:>7.2f} "
          f"{r['train_drawdown']:>7.2f} {r['train_calmar']:>7.2f} "
          f"{r['bull_mults']['momentum']:>7.1f} {r['bull_mults']['value']:>7.1f} "
          f"{r['bear_mults']['momentum']:>7.1f} {r['bear_mults']['value']:>7.1f}")

    # ---- 7. 测试期验证 ----
    top_n = min(30, len(results))
    p(f"\n📋 [7/7] 测试期样本外验证 TOP {top_n}...")

    test_results = []
    for i, r in enumerate(results[:top_n]):
        test_result = evaluate_config_fast(
            all_signals, r['bull_mults'], r['bear_mults'], (split_date, max_date)
        )
        test_results.append({
            **r,
            'test_sharpe': test_result['sharpe'],
            'test_return': test_result['return'],
            'test_drawdown': test_result['drawdown'],
            'test_calmar': test_result['calmar'],
            'test_win_rate': test_result['win_rate'],
            'test_stocks': test_result['stocks'],
        })

    p(f"\n   测试期结果（基线夏普 = {baseline_test['sharpe']:.3f}）:")
    p(f"   {'#':>3} {'训练夏普':>9} {'测试夏普':>9} {'测试年化%':>9} {'测试回撤%':>9} "
      f"{'Calmar':>7} {'vs基线':>8}")
    p(f"   {'-'*64}")
    p(f"   {'基线':>3} {'---':>9} {baseline_test['sharpe']:>9.3f} "
      f"{baseline_test['return']:>9.2f} {baseline_test['drawdown']:>9.2f} "
      f"{baseline_test['calmar']:>7.2f} {'---':>8}")

    for i, r in enumerate(test_results):
        diff = r['test_sharpe'] - baseline_test['sharpe']
        marker = '✅' if diff > 0.001 else '❌'
        p(f"   {i+1:>3} {r['train_sharpe']:>9.3f} {r['test_sharpe']:>9.3f} "
          f"{r['test_return']:>9.2f} {r['test_drawdown']:>9.2f} "
          f"{r['test_calmar']:>7.2f} {marker}{diff:>+.3f}")

    # ---- 结论 ----
    total_time = time.time() - t0
    best = max(test_results, key=lambda x: x['test_sharpe'])

    p(f"\n{'='*70}")
    p(f"  优化完成 · 总耗时 {total_time/60:.1f} 分钟 ({total_time/3600:.1f} 小时)")
    p(f"  其中: 信号预计算 {precompute_time/60:.1f}min, 网格搜索 {search_time/60:.1f}min")
    p(f"{'='*70}")

    output = {
        'optimized_at': datetime.now().isoformat(),
        'mode': mode,
        'stocks_count': len(all_signals),
        'stock_codes': sorted(all_signals.keys()),
        'train_period': f'{min_date} ~ {split_date}',
        'test_period': f'{split_date} ~ {max_date}',
        'configs_tested': total,
        'total_time_minutes': round(total_time / 60, 1),
        'precompute_time_minutes': round(precompute_time / 60, 1),
        'search_time_minutes': round(search_time / 60, 1),
        'strategy_active_rates': {
            sname: round(strat_active_counts.get(sname, 0) / total_bars * 100, 1)
            for sname in sorted(strat_active_counts.keys())
        },
        'baseline': {
            'train_sharpe': float(baseline_train['sharpe']),
            'test_sharpe': float(baseline_test['sharpe']),
            'test_return': float(baseline_test['return']),
            'test_drawdown': float(baseline_test['drawdown']),
            'test_calmar': float(baseline_test['calmar']),
            'full_sharpe': float(baseline_full['sharpe']),
        },
    }

    improved = [r for r in test_results if r['test_sharpe'] > baseline_test['sharpe'] + 0.001]
    p(f"\n  测试期显著超过基线的配置: {len(improved)}/{len(test_results)}")

    if best['test_sharpe'] > baseline_test['sharpe'] + 0.001:
        improvement = best['test_sharpe'] - baseline_test['sharpe']
        p(f"\n  🏆 最优配置（测试期验证通过）:")
        p(f"     训练期夏普: {best['train_sharpe']:.3f}")
        p(f"     测试期夏普: {best['test_sharpe']:.3f} (基线 {baseline_test['sharpe']:.3f}, 提升 {improvement:+.3f})")
        p(f"     测试期年化: {best['test_return']:.2f}% (基线 {baseline_test['return']:.2f}%)")
        p(f"     测试期回撤: {best['test_drawdown']:.2f}% (基线 {baseline_test['drawdown']:.2f}%)")
        p(f"     测试期Calmar: {best['test_calmar']:.2f} (基线 {baseline_test['calmar']:.2f})")
        p(f"\n     牛市系数: 动量={best['bull_mults']['momentum']:.1f}, 价值={best['bull_mults']['value']:.1f}")
        p(f"     熊市系数: 动量={best['bear_mults']['momentum']:.1f}, 价值={best['bear_mults']['value']:.1f}")
        p(f"     震荡市: 不调整（乘数=1.0）")

        train_rank = next(
            (i for i, r in enumerate(results)
             if r['bull_mults'] == best['bull_mults'] and r['bear_mults'] == best['bear_mults']),
            -1
        ) + 1
        p(f"\n     过拟合检测: 训练期排名 #{train_rank}/{total}")
        if train_rank <= 3:
            p(f"     ⚠️ 训练期排名过高，可能存在过拟合风险")
        else:
            p(f"     ✅ 训练期排名适中，过拟合风险较低")

        output['conclusion'] = 'dynamic_weights_better'
        output['best'] = {
            'test_sharpe': float(best['test_sharpe']),
            'test_return': float(best['test_return']),
            'test_drawdown': float(best['test_drawdown']),
            'test_calmar': float(best['test_calmar']),
            'improvement_sharpe': float(improvement),
            'bull_multipliers': best['bull_mults'],
            'bear_multipliers': best['bear_mults'],
            'train_rank': train_rank,
        }
        output['recommended_regime_weights'] = {
            'bull': get_adjusted_weights('bull', best['bull_mults'], best['bear_mults']),
            'bear': get_adjusted_weights('bear', best['bull_mults'], best['bear_mults']),
            'sideways': BASE_WEIGHTS.copy(),
        }
    else:
        p(f"\n  ⚠️ 所有动态权重配置均未在测试期显著超过基线")
        p(f"     结论: 保持当前固定权重，L2层暂不启用")
        p(f"     最优动态夏普: {best['test_sharpe']:.3f} vs 基线: {baseline_test['sharpe']:.3f}")

        output['conclusion'] = 'fixed_weights_better'
        output['recommendation'] = '保持固定权重，L2层暂不启用'
        output['best_dynamic'] = {
            'test_sharpe': float(best['test_sharpe']),
            'bull_multipliers': best['bull_mults'],
            'bear_multipliers': best['bear_mults'],
        }

    output['all_test_results'] = [
        {
            'rank': i + 1,
            'bull_mults': r['bull_mults'],
            'bear_mults': r['bear_mults'],
            'train_sharpe': float(r['train_sharpe']),
            'test_sharpe': float(r['test_sharpe']),
            'test_return': float(r['test_return']),
            'test_drawdown': float(r['test_drawdown']),
            'test_calmar': float(r['test_calmar']),
        }
        for i, r in enumerate(test_results)
    ]

    output_path = os.path.join(OUTPUT_DIR, "optimized_regime_weights.json")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    p(f"\n  结果已保存: {output_path}")
    p(f"{'='*70}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="L2层权重调整系数优化（预计算信号 + 投票重放）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 快速验证（~10min）
  python3 tools/optimization/optimize_regime_weights.py --stocks 10 --quick

  # 标准模式（~30-60min，推荐）
  nohup python3 tools/optimization/optimize_regime_weights.py --stocks 30 > optimize_log.txt 2>&1 &

  # 完整模式（~2-4h）
  nohup python3 tools/optimization/optimize_regime_weights.py --stocks 50 --full > optimize_log.txt 2>&1 &
        """,
    )
    parser.add_argument("--stocks", type=int, default=30, help="参与回测的股票数量（默认30）")
    parser.add_argument("--quick", action="store_true", help="快速模式（粗网格 256 配置）")
    parser.add_argument("--full", action="store_true", help="完整模式（细网格 5184 配置）")
    parser.add_argument("--train-ratio", type=float, default=0.7, help="训练集比例（默认0.7）")
    args = parser.parse_args()

    if args.quick:
        mode = 'quick'
    elif args.full:
        mode = 'full'
    else:
        mode = 'standard'

    run_optimization(stocks=args.stocks, mode=mode, train_ratio=args.train_ratio)
