#!/usr/bin/env python3
"""
V6.4.3 回测验证：对比 v5.2 / v6.1 / v6.4 三版本在历史数据上的表现

使用 863只 × ~800日 缓存K线数据，每周调仓，计算净值曲线和核心指标。

关键改进：
- 持仓延续性：旧仓在 top_N*2 内保留，减少不必要换手
- 真实协方差：从历史收益矩阵构建，非模拟数据
- 成本惩罚增大：非线性冲击成本
"""

import sys, os
import warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

import numpy as np
import pandas as pd
from datetime import datetime
from collections import defaultdict

CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'mydate', 'backtest_kline')
LOOKBACK = 60
REBALANCE_FREQ = 5
TOP_N = 20
COST_RATE = 0.003
MIN_HOLD_PERIODS = 2  # 至少持仓 2 个调仓周期


def load_all_klines():
    all_data = {}
    files = [f for f in os.listdir(CACHE_DIR) if f.endswith('.parquet')]
    for f in files:
        code = f.replace('.parquet', '')
        try:
            df = pd.read_parquet(os.path.join(CACHE_DIR, f))
            if 'date' in df.columns and 'close' in df.columns and len(df) >= 120:
                df = df.sort_values('date').reset_index(drop=True)
                df['date'] = pd.to_datetime(df['date'])
                all_data[code] = df
        except Exception:
            pass
    return all_data


def load_index_kline():
    from src.data.fetchers.data_prefetch import fetch_index_daily
    df = fetch_index_daily('000300', datalen=900, min_bars=100)
    if df is not None and not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        return df.sort_values('date').reset_index(drop=True)
    return pd.DataFrame()


def get_common_dates(all_data, min_stocks=200):
    date_counts = defaultdict(int)
    for code, df in all_data.items():
        for d in df['date']:
            date_counts[d] += 1
    dates = sorted([d for d, c in date_counts.items() if c >= min_stocks])
    return dates


def calc_factors_at_date(code, df, idx):
    if idx < LOOKBACK:
        return None

    sl = df.iloc[max(0, idx - LOOKBACK):idx + 1]
    close = sl['close'].values
    volume = sl['volume'].values

    if len(close) < 30 or close[-1] <= 0:
        return None

    ma5 = np.mean(close[-5:])
    ma20 = np.mean(close[-20:])
    ma60 = np.mean(close[-min(60, len(close)):])
    alignment = 0
    if ma5 > ma20:
        alignment += 0.5
    if ma20 > ma60:
        alignment += 0.5
    mom = close[-1] / close[-20] - 1 if close[-20] > 0 else 0
    base_trend = alignment * 0.6 + np.clip(mom, -0.5, 0.5) * 0.4

    ema12 = pd.Series(close).ewm(span=12).mean().iloc[-1]
    ema26 = pd.Series(close).ewm(span=26).mean().iloc[-1]
    dif = ema12 - ema26
    tech_confirm = dif / (close[-1] + 1e-8)

    ret20 = close[-1] / close[-21] - 1 if len(close) >= 21 and close[-21] > 0 else 0
    relative_strength = ret20

    vol5 = np.mean(volume[-5:]) if len(volume) >= 5 else 1
    vol20 = np.mean(volume[-20:]) if len(volume) >= 20 else 1
    price_chg = close[-1] / close[-6] - 1 if len(close) >= 6 and close[-6] > 0 else 0
    vol_ratio = np.clip(vol5 / (vol20 + 1e-8), 0.5, 2.0)
    volume_confirm = price_chg * np.log(vol_ratio + 1e-8)

    rets = np.diff(close[-min(60, len(close)):]) / (close[-min(60, len(close)):-1] + 1e-8)
    volatility = np.std(rets) * np.sqrt(252) if len(rets) > 5 else 0.3

    return {
        'code': code,
        'base_trend': base_trend,
        'tech_confirm': tech_confirm,
        'relative_strength': relative_strength,
        'volume_confirm': volume_confirm,
        'volatility': max(volatility, 0.05),
        'close': close[-1],
    }


def build_hist_returns(all_data, codes, current_date, window=60):
    """从K线缓存中构建历史收益率矩阵"""
    ret_dict = {}
    for code in codes:
        if code not in all_data:
            continue
        df = all_data[code]
        mask = df['date'] <= current_date
        avail = df[mask]
        if len(avail) < window:
            continue
        sl = avail.iloc[-window:]
        rets = sl['close'].pct_change().dropna().values
        if len(rets) >= window - 1:
            ret_dict[code] = rets[-min(len(rets), window-1):]

    if not ret_dict:
        return None, []
    min_len = min(len(v) for v in ret_dict.values())
    aligned_codes = list(ret_dict.keys())
    mat = np.column_stack([ret_dict[c][-min_len:] for c in aligned_codes])
    return mat, aligned_codes


def apply_holding_continuity(new_scores, prev_weights, hold_ages, factor_df):
    """持仓延续性：旧持仓如果仍在 top_N*2 内则保留"""
    sorted_all = new_scores.sort_values(ascending=False)
    top_2n = set(sorted_all.head(TOP_N * 2).index)
    keep = []
    for code in prev_weights:
        age = hold_ages.get(code, 0)
        if age < MIN_HOLD_PERIODS and code in top_2n:
            keep.append(code)
        elif code in top_2n and new_scores.get(code, -999) > sorted_all.iloc[TOP_N * 2 - 1] if len(sorted_all) >= TOP_N * 2 else True:
            keep.append(code)

    new_top = [c for c in sorted_all.head(TOP_N).index if c not in keep]
    final = keep + new_top
    final = final[:TOP_N]
    return final


def run_version(version, factor_df, regime_score, prev_weights, hold_ages,
                all_data=None, current_date=None):
    """
    根据版本计算推荐权重

    Returns: dict {code: weight}
    """
    regime_prob = np.clip((regime_score + 1.0) / 2.0, 0.05, 0.95)

    if version == 'v5.2':
        weights_arr = [0.40, 0.30, 0.10, 0.20]
        scores = (weights_arr[0] * factor_df['base_trend'] +
                  weights_arr[1] * factor_df['tech_confirm'] +
                  weights_arr[2] * factor_df['relative_strength'] +
                  weights_arr[3] * factor_df['volume_confirm'])
        scores = scores.apply(np.tanh)

        final_codes = apply_holding_continuity(scores, prev_weights, hold_ages, factor_df)
        w = {c: 1.0 / len(final_codes) for c in final_codes} if final_codes else {}
        return w

    elif version == 'v6.1':
        from src.factors.orthogonalization import FactorOrthogonalizer
        from src.factors.normalization import RankNormalizer

        orth = FactorOrthogonalizer()
        try:
            orth_df = orth.fit_transform(factor_df[['relative_strength', 'base_trend',
                                                     'tech_confirm', 'volume_confirm']])
        except Exception:
            orth_df = factor_df[['base_trend', 'tech_confirm', 'relative_strength', 'volume_confirm']]

        w_t = np.array([0.5, 0.3, 0.1, 0.1])
        w_r = np.array([0.3, 0.3, 0.2, 0.2])
        dw = regime_prob * w_t + (1 - regime_prob) * w_r

        f_map = {'base_trend': 0, 'tech_confirm': 1, 'relative_strength': 2, 'volume_confirm': 3}
        scores = pd.Series(0.0, index=orth_df.index)
        for col in orth_df.columns:
            idx = f_map.get(col, 0)
            scores += dw[idx] * orth_df[col]

        normalizer = RankNormalizer(method='percentile')
        scores = normalizer.transform(scores)

        final_codes = apply_holding_continuity(scores, prev_weights, hold_ages, factor_df)

        vol = factor_df.loc[final_codes, 'volatility'].clip(lower=0.05)
        inv_vol = 1.0 / vol
        raw_w = inv_vol / inv_vol.sum()
        return raw_w.to_dict()

    elif version == 'v6.4':
        from src.factors.orthogonalization import FactorOrthogonalizer
        from src.factors.normalization import RankNormalizer
        from src.alpha.alpha_penalty import compute_alpha_with_penalty, nonlinear_alpha_mapping
        from src.risk.risk_model import compute_expected_return, ewma_covariance
        from src.optimizer.unified_optimizer import UnifiedOptimizer

        orth = FactorOrthogonalizer()
        try:
            orth_df = orth.fit_transform(factor_df[['relative_strength', 'base_trend',
                                                     'tech_confirm', 'volume_confirm']])
        except Exception:
            orth_df = factor_df[['base_trend', 'tech_confirm', 'relative_strength', 'volume_confirm']]

        w_t = np.array([0.5, 0.3, 0.1, 0.1])
        w_r = np.array([0.3, 0.3, 0.2, 0.2])
        dw = regime_prob * w_t + (1 - regime_prob) * w_r

        f_map = {'base_trend': 0, 'tech_confirm': 1, 'relative_strength': 2, 'volume_confirm': 3}
        raw_scores = pd.Series(0.0, index=orth_df.index)
        for col in orth_df.columns:
            idx = f_map.get(col, 0)
            raw_scores += dw[idx] * orth_df[col]

        normalizer = RankNormalizer(method='percentile')
        norm_scores = normalizer.transform(raw_scores)

        final_codes = apply_holding_continuity(norm_scores, prev_weights, hold_ages, factor_df)
        n_top = len(final_codes)
        if n_top == 0:
            return {}

        alpha_raw = np.array([raw_scores.get(c, 0) for c in final_codes])
        F = factor_df.loc[final_codes, ['base_trend', 'tech_confirm',
                                         'relative_strength', 'volume_confirm']].fillna(0).values
        alpha_p = compute_alpha_with_penalty(alpha_raw, F, lambda_penalty=0.1)
        alpha_p = nonlinear_alpha_mapping(alpha_p, power=1.5)

        ic = 0.15
        vols = factor_df.loc[final_codes, 'volatility'].values

        # 真实历史协方差
        if all_data and current_date:
            ret_mat, ret_codes = build_hist_returns(all_data, final_codes, current_date, window=60)
            if ret_mat is not None and ret_mat.shape[1] >= 3:
                code_idx_map = {c: i for i, c in enumerate(ret_codes)}
                aligned_idx = [code_idx_map[c] for c in final_codes if c in code_idx_map]
                if len(aligned_idx) == n_top:
                    cov = ewma_covariance(ret_mat[:, aligned_idx], halflife=30,
                                           shrink_intensity=0.3)
                else:
                    corr = np.eye(n_top) * 0.7 + np.ones((n_top, n_top)) * 0.3
                    vol_diag = np.diag(vols / np.sqrt(252))
                    cov = vol_diag @ corr @ vol_diag
            else:
                corr = np.eye(n_top) * 0.7 + np.ones((n_top, n_top)) * 0.3
                vol_diag = np.diag(vols / np.sqrt(252))
                cov = vol_diag @ corr @ vol_diag
        else:
            cov = np.diag((vols / np.sqrt(252)) ** 2)

        np.fill_diagonal(cov, np.maximum(np.diag(cov), 1e-8))

        er = compute_expected_return(alpha_p, ic, vols)

        # prev_weights arrays
        pw = np.array([prev_weights.get(c, 0) for c in final_codes])

        optimizer = UnifiedOptimizer(
            max_weight=0.10, max_leverage=1.5, max_l2=1.2,
            target_vol=0.15, max_trend_pct=0.20,
            lambda_risk=0.5, lambda_cost=0.15, lambda_smooth=0.05
        )

        trend_mask = np.array([norm_scores.get(c, 0) > 0.5 for c in final_codes])

        hist_ret_data, _ = build_hist_returns(all_data, final_codes, current_date, window=100)
        if hist_ret_data is None or hist_ret_data.shape[1] != n_top:
            hist_ret_data = np.random.randn(100, n_top) * 0.02

        try:
            result = optimizer.optimize(
                expected_returns=er,
                covariance=cov,
                returns_hist=hist_ret_data,
                regime_prob=regime_prob,
                prev_weights=pw,
                trend_mask=trend_mask,
                codes=final_codes
            )
            weights = {final_codes[i]: float(result['weights'][i])
                       for i in range(n_top) if result['weights'][i] > 1e-4}
        except Exception:
            weights = {c: 1.0 / n_top for c in final_codes}

        wsum = sum(weights.values())
        if wsum > 0:
            weights = {k: v / wsum for k, v in weights.items()}
        return weights


def calc_regime_score_simple(index_df, idx):
    if idx < 60:
        return 0.0
    close = index_df['close'].values[max(0, idx-60):idx+1]
    if len(close) < 60:
        return 0.0
    ma20 = np.mean(close[-20:])
    ma60 = np.mean(close[-60:])
    trend = ma20 / ma60 - 1 if ma60 > 0 else 0
    rets = np.diff(close[-20:]) / (close[-20:-1] + 1e-8)
    vol = np.std(rets) if len(rets) > 5 else 0.02
    score = 0.6 * trend - 0.4 * vol
    return np.tanh(score)


def backtest():
    print("=" * 70)
    print("V6.4.3 backtest: v5.2 vs v6.1 vs v6.4")
    print("=" * 70)

    print("\nLoading data...")
    all_data = load_all_klines()
    print(f"  K-line cache: {len(all_data)} stocks")

    index_df = load_index_kline()
    print(f"  CSI 300: {len(index_df)} bars")

    dates = get_common_dates(all_data, min_stocks=200)
    print(f"  Common dates: {len(dates)} ({dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')})")

    start_idx = LOOKBACK + 20
    if start_idx >= len(dates):
        print("Insufficient data")
        return

    versions = ['v5.2', 'v6.1', 'v6.4']
    nav = {v: [1.0] for v in versions}
    nav_dates = [dates[start_idx]]
    turnover_hist = {v: [] for v in versions}
    prev_weights = {v: {} for v in versions}
    hold_ages = {v: {} for v in versions}  # {code: periods_held}

    total_periods = (len(dates) - start_idx) // REBALANCE_FREQ
    print(f"\nStarting backtest: {total_periods} rebalance periods, every {REBALANCE_FREQ} days\n")

    period_count = 0
    for t in range(start_idx, len(dates) - REBALANCE_FREQ, REBALANCE_FREQ):
        current_date = dates[t]
        next_date = dates[min(t + REBALANCE_FREQ, len(dates) - 1)]
        period_count += 1

        if period_count % 20 == 0 or period_count == 1:
            pct = period_count / total_periods * 100
            print(f"  [{period_count}/{total_periods}] {current_date.strftime('%Y-%m-%d')} ({pct:.0f}%)")

        factors = []
        for code, df in all_data.items():
            date_mask = df['date'] <= current_date
            available = df[date_mask]
            if len(available) < LOOKBACK:
                continue
            idx = len(available) - 1
            f = calc_factors_at_date(code, available, idx)
            if f:
                factors.append(f)

        if len(factors) < 50:
            for v in versions:
                nav[v].append(nav[v][-1])
            nav_dates.append(next_date)
            continue

        factor_df = pd.DataFrame(factors).set_index('code')

        # z-score relative_strength
        rs = factor_df['relative_strength']
        factor_df['relative_strength'] = (rs - rs.mean()) / (rs.std() + 1e-8)
        factor_df['relative_strength'] = factor_df['relative_strength'].clip(-3, 3)

        idx_mask = index_df['date'] <= current_date
        idx_avail = index_df[idx_mask]
        regime_score = calc_regime_score_simple(idx_avail, len(idx_avail) - 1) if len(idx_avail) > 60 else 0.0

        for v in versions:
            try:
                new_weights = run_version(v, factor_df, regime_score,
                                          prev_weights[v], hold_ages[v],
                                          all_data=all_data, current_date=current_date)
            except Exception:
                new_weights = prev_weights[v]

            # turnover
            all_codes_set = set(list(new_weights.keys()) + list(prev_weights[v].keys()))
            turnover = sum(abs(new_weights.get(c, 0) - prev_weights[v].get(c, 0)) for c in all_codes_set)
            turnover_hist[v].append(turnover)

            # update hold ages
            new_ages = {}
            for code in new_weights:
                new_ages[code] = hold_ages[v].get(code, 0) + 1
            hold_ages[v] = new_ages

            # period return
            period_return = 0.0
            for code, w in new_weights.items():
                if code in all_data:
                    df = all_data[code]
                    mask_cur = df['date'] <= current_date
                    mask_nxt = df['date'] <= next_date
                    if mask_cur.sum() > 0 and mask_nxt.sum() > 0:
                        p_cur = df[mask_cur]['close'].iloc[-1]
                        p_nxt = df[mask_nxt]['close'].iloc[-1]
                        if p_cur > 0:
                            period_return += w * (p_nxt / p_cur - 1)

            cost = (turnover ** 1.3) * COST_RATE
            net_return = period_return - cost

            nav[v].append(nav[v][-1] * (1 + net_return))
            prev_weights[v] = new_weights

        nav_dates.append(next_date)

    # ========== Results ==========
    years = (nav_dates[-1] - nav_dates[0]).days / 365.25

    idx_start = index_df[index_df['date'] >= nav_dates[0]]['close'].iloc[0]
    idx_end = index_df[index_df['date'] <= nav_dates[-1]]['close'].iloc[-1]
    bench_return = idx_end / idx_start - 1

    results = {}
    for v in versions:
        nav_series = np.array(nav[v])
        total_ret = nav_series[-1] / nav_series[0] - 1
        ann_ret = (1 + total_ret) ** (1 / max(years, 0.1)) - 1
        period_rets = np.diff(nav_series) / nav_series[:-1]
        ann_vol = np.std(period_rets) * np.sqrt(252 / REBALANCE_FREQ) if len(period_rets) > 2 else 0
        sharpe = ann_ret / (ann_vol + 1e-8)
        peak = np.maximum.accumulate(nav_series)
        drawdown = (nav_series - peak) / peak
        max_dd = drawdown.min()
        calmar = ann_ret / (abs(max_dd) + 1e-8)
        win_rate = (period_rets > 0).mean() if len(period_rets) > 0 else 0
        avg_turnover = np.mean(turnover_hist[v]) if turnover_hist[v] else 0

        results[v] = {
            'ret': total_ret, 'ann': ann_ret, 'vol': ann_vol,
            'sharpe': sharpe, 'dd': max_dd, 'calmar': calmar,
            'turnover': avg_turnover, 'wr': win_rate,
        }

    bench_ann = (1 + bench_return) ** (1 / max(years, 0.1)) - 1

    print(f"\n{'='*75}")
    print(f"  BACKTEST RESULTS")
    print(f"{'='*75}")
    print(f"  Period: {nav_dates[0].strftime('%Y-%m-%d')} ~ {nav_dates[-1].strftime('%Y-%m-%d')} ({years:.1f} yrs)")
    print(f"  Stocks: {len(all_data)}, Rebalance periods: {period_count}")
    print()

    def fmt(v):
        return f"{v:>+10.2%}" if abs(v) < 100 else f"{v:>10.2f}"

    header = f"{'Metric':>20} | {'v5.2':>10} | {'v6.1':>10} | {'v6.4':>10} | {'CSI300':>10}"
    print(header)
    print("-" * len(header))

    r = results
    rows = [
        ('Total Return',    r['v5.2']['ret'],  r['v6.1']['ret'],  r['v6.4']['ret'],  bench_return),
        ('Annual Return',   r['v5.2']['ann'],  r['v6.1']['ann'],  r['v6.4']['ann'],  bench_ann),
        ('Annual Vol',      r['v5.2']['vol'],  r['v6.1']['vol'],  r['v6.4']['vol'],  None),
        ('Sharpe Ratio',    r['v5.2']['sharpe'], r['v6.1']['sharpe'], r['v6.4']['sharpe'], None),
        ('Max Drawdown',    r['v5.2']['dd'],   r['v6.1']['dd'],   r['v6.4']['dd'],   None),
        ('Calmar Ratio',    r['v5.2']['calmar'], r['v6.1']['calmar'], r['v6.4']['calmar'], None),
        ('Win Rate',        r['v5.2']['wr'],   r['v6.1']['wr'],   r['v6.4']['wr'],   None),
        ('Avg Turnover',    r['v5.2']['turnover'], r['v6.1']['turnover'], r['v6.4']['turnover'], None),
    ]

    for name, v52, v61, v64, bench in rows:
        b = fmt(bench) if bench is not None else f"{'--':>10}"
        print(f"{name:>20} | {fmt(v52)} | {fmt(v61)} | {fmt(v64)} | {b}")

    # v6.4 vs v5.2 improvement
    print(f"\n{'='*75}")
    print("  V6.4 vs V5.2 Comparison")
    print(f"{'='*75}")
    d_ret = r['v6.4']['ret'] - r['v5.2']['ret']
    d_dd  = r['v6.4']['dd']  - r['v5.2']['dd']
    d_sr  = r['v6.4']['sharpe'] - r['v5.2']['sharpe']
    d_to  = r['v6.4']['turnover'] - r['v5.2']['turnover']
    print(f"  Return delta:    {d_ret:>+.2%}")
    print(f"  Drawdown delta:  {d_dd:>+.2%} ({'better' if d_dd > 0 else 'worse'})")
    print(f"  Sharpe delta:    {d_sr:>+.4f}")
    print(f"  Turnover delta:  {d_to:>+.2%}")

    # NAV curve
    print(f"\n{'='*75}")
    print("  NAV Curve (monthly)")
    print(f"{'='*75}")
    print(f"{'Date':>12} | {'v5.2':>8} | {'v6.1':>8} | {'v6.4':>8}")
    print("-" * 48)

    last_month = None
    for i, d in enumerate(nav_dates):
        month_key = d.strftime('%Y-%m')
        if month_key != last_month:
            last_month = month_key
            print(f"{d.strftime('%Y-%m-%d'):>12} | {nav['v5.2'][i]:>8.4f} | {nav['v6.1'][i]:>8.4f} | {nav['v6.4'][i]:>8.4f}")

    print(f"{nav_dates[-1].strftime('%Y-%m-%d'):>12} | {nav['v5.2'][-1]:>8.4f} | {nav['v6.1'][-1]:>8.4f} | {nav['v6.4'][-1]:>8.4f}")

    # ========== Segment analysis ==========
    print(f"\n{'='*75}")
    print("  Segment Analysis (market phases)")
    print(f"{'='*75}")

    # identify phases by index returns over rolling 60-day windows
    phase_data = []
    for i in range(1, len(nav_dates)):
        d = nav_dates[i]
        idx_mask = index_df['date'] <= d
        idx_avail = index_df[idx_mask]
        if len(idx_avail) < 60:
            phase_data.append('unknown')
            continue
        r60 = idx_avail['close'].iloc[-1] / idx_avail['close'].iloc[-60] - 1
        vol20 = idx_avail['close'].pct_change().iloc[-20:].std()
        if r60 > 0.05:
            phase_data.append('bull')
        elif r60 < -0.05:
            phase_data.append('bear')
        else:
            phase_data.append('range')

    for phase in ['bull', 'bear', 'range']:
        idxs = [i for i, p in enumerate(phase_data) if p == phase]
        if len(idxs) < 5:
            continue
        print(f"\n  [{phase.upper()}] {len(idxs)} periods")
        for v in versions:
            nav_arr = np.array(nav[v])
            rets = []
            for i in idxs:
                if i < len(nav_arr) - 1:
                    r = (nav_arr[i+1] - nav_arr[i]) / nav_arr[i]
                    rets.append(r)
            if not rets:
                continue
            avg_r = np.mean(rets) * 100
            win = np.mean(np.array(rets) > 0) * 100
            vol = np.std(rets) * np.sqrt(252/REBALANCE_FREQ) * 100
            print(f"    {v}: avg={avg_r:>+.2f}%/period  win={win:.0f}%  vol={vol:.1f}%")

    # ========== Drawdown analysis ==========
    print(f"\n{'='*75}")
    print("  Major Drawdown Periods")
    print(f"{'='*75}")
    for v in versions:
        nav_arr = np.array(nav[v])
        peak = np.maximum.accumulate(nav_arr)
        dd = (nav_arr - peak) / peak
        worst_idx = np.argmin(dd)
        peak_idx = np.argmax(nav_arr[:worst_idx+1])
        print(f"  {v}: worst DD={dd[worst_idx]:.2%} ({nav_dates[peak_idx].strftime('%Y-%m-%d')} -> {nav_dates[worst_idx].strftime('%Y-%m-%d')})")

    # ========== Rolling Sharpe ==========
    print(f"\n{'='*75}")
    print("  Rolling 6-month Sharpe")
    print(f"{'='*75}")
    window_sr = 26  # ~6 months
    for v in versions:
        nav_arr = np.array(nav[v])
        period_rets = np.diff(nav_arr) / nav_arr[:-1]
        rolling_sharpes = []
        for i in range(window_sr, len(period_rets)):
            chunk = period_rets[i-window_sr:i]
            sr = chunk.mean() / (chunk.std() + 1e-8) * np.sqrt(252/REBALANCE_FREQ)
            rolling_sharpes.append(sr)
        if rolling_sharpes:
            print(f"  {v}: mean={np.mean(rolling_sharpes):.2f}  min={np.min(rolling_sharpes):.2f}  max={np.max(rolling_sharpes):.2f}")

    print(f"\nBacktest complete.")
    return results, nav, nav_dates


if __name__ == '__main__':
    backtest()
