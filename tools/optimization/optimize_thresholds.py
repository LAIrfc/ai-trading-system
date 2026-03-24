#!/usr/bin/env python3
"""
信号阈值优化（预计算子策略信号 + 重放投票与成交）

与旧版不同：每只股票只预计算一次逐 bar 的 12 子策略信号，
再对 36 组 (BUY/SELL 净分阈值) 纯数学重放，总耗时 ≈ 1×预计算 + 36×轻量循环。

默认权重：results/calibration/best_weights.json（composite），若无则用 ensemble 默认。

用法:
  python3 tools/optimization/optimize_thresholds.py --stocks 100
  python3 tools/optimization/optimize_thresholds.py --stocks 839 --cache results/calibration/threshold_precompute.pkl
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pickle
import sys
import time
from itertools import product
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

BACKTEST_DIR = os.path.join(os.path.dirname(__file__), "../../mydate/backtest_kline")
RESULT_DIR = os.path.join(os.path.dirname(__file__), "../../results/calibration")
os.makedirs(RESULT_DIR, exist_ok=True)

MIN_ACTIVE_VOTES = 1


def p(*a, **kw):
    print(*a, **kw, flush=True)


def _load_regime_module():
    path = os.path.join(os.path.dirname(__file__), "optimize_regime_weights.py")
    spec = importlib.util.spec_from_file_location("optimize_regime_weights", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_weights() -> Dict[str, float]:
    from src.strategies.ensemble import EnsembleStrategy

    path = os.path.join(RESULT_DIR, "best_weights.json")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data.get("weights"), dict):
                return dict(data["weights"])
    ens = EnsembleStrategy()
    return dict(ens.weights)


def replay_backtest_threshold(
    bar_signals: List[Dict],
    weights: Dict[str, float],
    buy_th: float,
    sell_th: float,
    initial_cash: float = 100000.0,
    commission: float = 0.0002,
    stamp_tax: float = 0.001,
    risk_free_rate: float = 0.03,
) -> Optional[Dict]:
    """与 optimize_regime_weights.replay_backtest 一致，仅阈值可参量化。"""
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
        exec_price = bar["exec_price"]
        t1_close = bar["t1_close"]
        strat_signals = bar["strat_signals"]

        equity = cash + shares * exec_price

        buy_votes = []
        sell_votes = []
        all_positions = []

        for sname, (action, confidence, position) in strat_signals.items():
            w = weights.get(sname, 1.0)
            all_positions.append((sname, w, position))
            if action == "BUY":
                buy_votes.append((sname, confidence))
            elif action == "SELL":
                sell_votes.append((sname, confidence))

        if not buy_votes and not sell_votes:
            action = "HOLD"
            avg_position = 0.5
        else:
            buy_score = sum(weights.get(n, 1.0) * c for n, c in buy_votes)
            sell_score = sum(weights.get(n, 1.0) * c for n, c in sell_votes)
            active_weight_sum = (
                sum(weights.get(n, 1.0) for n, _ in buy_votes)
                + sum(weights.get(n, 1.0) for n, _ in sell_votes)
            )

            if active_weight_sum == 0:
                action = "HOLD"
                avg_position = 0.5
            else:
                net_score = (buy_score - sell_score) / active_weight_sum
                if net_score > buy_th and len(buy_votes) >= MIN_ACTIVE_VOTES:
                    action = "BUY"
                elif net_score < sell_th and len(sell_votes) >= MIN_ACTIVE_VOTES:
                    action = "SELL"
                else:
                    action = "HOLD"

            total_w = sum(weights.get(n, 1.0) for n, _, _ in all_positions)
            avg_position = (
                sum(weights.get(n, 1.0) * pos for n, _, pos in all_positions) / total_w
                if total_w > 0
                else 0.5
            )

        if action == "BUY":
            target_pos = min(0.95, max(0.4, avg_position))
        elif action == "SELL":
            target_pos = 0.0
        else:
            target_pos = avg_position

        if action == "BUY":
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

        elif action == "SELL" and shares > 0:
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

    final_value = equity_curve[-1]
    total_return = (final_value / initial_cash - 1) * 100

    n_bars = len(bar_signals)
    years = max(n_bars / 252.0, 0.01)
    annualized = ((final_value / initial_cash) ** (1 / years) - 1) * 100

    max_drawdown = 0.0
    peak = equity_curve[0]
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_drawdown:
            max_drawdown = dd
    max_drawdown *= 100

    all_trips = list(completed_trips)
    if shares > 0 and avg_buy_price > 0:
        final_close = bar_signals[-1]["t1_close"]
        all_trips.append((final_close - avg_buy_price) / avg_buy_price)
    win_rate = (sum(1 for t in all_trips if t > 0) / len(all_trips) * 100) if all_trips else 0.0
    trade_count = len(completed_trips) + (1 if shares > 0 else 0)

    sharpe = 0.0
    if len(equity_curve) > 1:
        rets = pd.Series(equity_curve).pct_change().dropna()
        daily_rf = risk_free_rate / 252
        excess = rets - daily_rf
        if excess.std() > 1e-10:
            sharpe = float((excess.mean() / excess.std()) * (252**0.5))

    if trade_count == 0:
        return None

    dd = abs(max_drawdown)
    return {
        "sharpe": round(sharpe, 4),
        "total_return_pct": round(total_return, 2),
        "annualized_return": round(annualized, 2),
        "max_drawdown": round(dd, 2),
        "win_rate": round(win_rate, 2),
        "trade_count": trade_count,
    }


def precompute_all(
    codes: List[str],
    orw_mod,
    cache_path: Optional[str],
) -> Dict[str, Dict]:
    if cache_path and os.path.isfile(cache_path):
        try:
            with open(cache_path, "rb") as f:
                cached = pickle.load(f)
            if set(cached.keys()) >= set(codes):
                p(f"  预计算缓存命中: {cache_path} ({len(cached)} 条)")
                return {c: cached[c] for c in codes if c in cached}
        except Exception:
            pass

    out = {}
    t0 = time.time()
    for i, code in enumerate(codes):
        path = os.path.join(BACKTEST_DIR, f"{code}.parquet")
        if not os.path.isfile(path):
            continue
        try:
            df = pd.read_parquet(path)
            if len(df) < 200:
                continue
            df["date"] = pd.to_datetime(df["date"])
            for c in ["open", "high", "low", "close", "volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
        except Exception:
            continue
        sig = orw_mod.precompute_signals(code, df)
        if sig and sig.get("signals"):
            out[code] = sig
        if (i + 1) % 50 == 0:
            p(f"  预计算 [{i+1}/{len(codes)}] 有效 {len(out)} 只 · {time.time()-t0:.0f}s")

    if cache_path:
        try:
            with open(cache_path, "wb") as f:
                pickle.dump(out, f)
            p(f"  预计算已写入: {cache_path}")
        except Exception as e:
            p(f"  缓存写入失败: {e}")

    p(f"  预计算完成: {len(out)} 只股票, 耗时 {(time.time()-t0)/60:.1f} min")
    return out


def main():
    ap = argparse.ArgumentParser(description="净分阈值优化（预计算+重放）")
    ap.add_argument("--stocks", type=int, default=0, help="0=全部 parquet")
    ap.add_argument(
        "--cache",
        type=str,
        default="",
        help="预计算 pickle 路径（可复用）。默认 results/calibration/threshold_precompute.pkl",
    )
    args = ap.parse_args()

    files = sorted(f for f in os.listdir(BACKTEST_DIR) if f.endswith(".parquet"))
    if args.stocks > 0:
        files = files[: args.stocks]
    codes = [f.replace(".parquet", "") for f in files]

    cache_path = args.cache or os.path.join(RESULT_DIR, "threshold_precompute.pkl")

    weights = load_weights()
    p("使用权重:")
    p(json.dumps(weights, indent=2, ensure_ascii=False))

    p("\n加载 optimize_regime_weights.precompute_signals …")
    orw = _load_regime_module()

    all_sig = precompute_all(codes, orw, cache_path)

    buy_thresholds = [0.03, 0.05, 0.07, 0.10, 0.12, 0.15]
    sell_thresholds = [-0.03, -0.05, -0.07, -0.10, -0.12, -0.15]
    configs = list(product(buy_thresholds, sell_thresholds))

    p(f"\n重放 {len(configs)} 组阈值 × {len(all_sig)} 只股票 …")
    results = {}
    t0 = time.time()
    for idx, (buy_th, sell_th) in enumerate(configs):
        key = f"buy{buy_th:.2f}_sell{sell_th:.2f}"
        sharpes, rets, trades = [], [], []
        for code, sig_data in all_sig.items():
            bar_signals = sig_data["signals"]
            r = replay_backtest_threshold(bar_signals, weights, buy_th, sell_th)
            if r:
                sharpes.append(r["sharpe"])
                rets.append(r["total_return_pct"])
                trades.append(r["trade_count"])
        if sharpes:
            arr_s = np.array(sharpes)
            arr_r = np.array(rets)
            results[key] = {
                "buy_threshold": buy_th,
                "sell_threshold": sell_th,
                "stock_count": len(sharpes),
                "avg_sharpe": float(np.mean(arr_s)),
                "median_sharpe": float(np.median(arr_s)),
                "avg_total_return_pct": float(np.mean(arr_r)),
                "positive_return_pct": float((arr_r > 0).mean()),
                "avg_trades": float(np.mean(trades)),
            }
        p(
            f"  [{idx+1}/{len(configs)}] {key} "
            f"avg_Sharpe={results[key]['avg_sharpe']:.4f} "
            f"n={results[key]['stock_count']}"
        )

    p(f"\n重放总耗时 {(time.time()-t0):.1f}s")

    ranked = sorted(results.items(), key=lambda x: x[1]["avg_sharpe"], reverse=True)
    baseline_key = "buy0.07_sell-0.07"
    baseline = results.get(baseline_key, {})

    p("\n" + "=" * 100)
    p("Top 10（按平均 Sharpe）")
    p("=" * 100)
    for name, r in ranked[:10]:
        mark = "  [当前默认]" if name == baseline_key else ""
        p(
            f"{name:<22} buy={r['buy_threshold']:.2f} sell={r['sell_threshold']:.2f} "
            f"avg_Sharpe={r['avg_sharpe']:.4f} med={r['median_sharpe']:.4f} "
            f"pos_ret%={r['positive_return_pct']:.1%} avg_trades={r['avg_trades']:.1f}{mark}"
        )

    out_json = os.path.join(RESULT_DIR, "threshold_optimization.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    p(f"\n完整结果: {out_json}")

    best_name, best = ranked[0]
    best_file = os.path.join(RESULT_DIR, "best_thresholds.json")
    with open(best_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "buy_threshold": best["buy_threshold"],
                "sell_threshold": best["sell_threshold"],
                "metrics": best,
                "baseline_avg_sharpe": baseline.get("avg_sharpe"),
                "delta_vs_baseline": (
                    best["avg_sharpe"] - baseline["avg_sharpe"] if baseline else None
                ),
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    p(f"最优阈值: {best_file}  ->  {best_name}")
    if baseline:
        p(
            f"相对默认(0.07/-0.07) Sharpe 变化: "
            f"{best['avg_sharpe'] - baseline['avg_sharpe']:+.4f}"
        )


if __name__ == "__main__":
    main()
