#!/usr/bin/env python3
"""快速对比：旧权重+旧阈值 vs 新权重+旧阈值 vs 新权重+新阈值"""
import pickle, sys, os, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

RESULT_DIR = os.path.join(os.path.dirname(__file__), "../../results/calibration")

with open(os.path.join(RESULT_DIR, "threshold_precompute.pkl"), "rb") as f:
    all_sig = pickle.load(f)
print(f"预计算信号: {len(all_sig)} 只股票")


def replay(bar_signals, weights, buy_th, sell_th,
           initial_cash=100000.0, commission=0.0002, stamp_tax=0.001, rf=0.03):
    cash, shares, abp, tbc, rtbc = initial_cash, 0, 0.0, 0.0, 0.0
    trips, eq = [], []
    for bar in bar_signals:
        ep, tc = bar["exec_price"], bar["t1_close"]
        ss = bar["strat_signals"]
        equity = cash + shares * ep
        bv, sv, ap = [], [], []
        for sn, (a, c, p) in ss.items():
            ap.append((sn, weights.get(sn, 1.0), p))
            if a == "BUY": bv.append((sn, c))
            elif a == "SELL": sv.append((sn, c))
        if not bv and not sv:
            action, avg_pos = "HOLD", 0.5
        else:
            bs = sum(weights.get(n, 1.0) * c for n, c in bv)
            ssc = sum(weights.get(n, 1.0) * c for n, c in sv)
            aws = sum(weights.get(n, 1.0) for n, _ in bv) + sum(weights.get(n, 1.0) for n, _ in sv)
            if aws == 0:
                action, avg_pos = "HOLD", 0.5
            else:
                ns = (bs - ssc) / aws
                if ns > buy_th and len(bv) >= 1: action = "BUY"
                elif ns < sell_th and len(sv) >= 1: action = "SELL"
                else: action = "HOLD"
            tw = sum(weights.get(n, 1.0) for n, _, _ in ap)
            avg_pos = sum(weights.get(n, 1.0) * p for n, _, p in ap) / tw if tw > 0 else 0.5
        if action == "BUY": tp = min(0.95, max(0.4, avg_pos))
        elif action == "SELL": tp = 0.0
        else: tp = avg_pos
        if action == "BUY":
            dv = equity * tp - shares * ep
            if dv >= ep * 100:
                add = int(dv / ep / 100) * 100
                if add > 0:
                    cost = add * ep * (1 + commission)
                    if cost <= cash:
                        cash -= cost; tbc += add * ep; rtbc += add * ep; shares += add; abp = tbc / shares
        elif action == "SELL" and shares > 0:
            dv = shares * ep - equity * tp
            ss2 = int(dv / ep / 100) * 100
            if tp < 0.05 or (shares - ss2) < 100: ss2 = shares
            if 0 < ss2 <= shares:
                rev = ss2 * ep * (1 - commission - stamp_tax)
                pnl = (ep - abp) / abp if abp > 0 else 0
                cash += rev; shares -= ss2
                if shares == 0:
                    if rtbc > 0: trips.append(pnl)
                    abp = tbc = rtbc = 0.0
                else:
                    tbc = shares * abp
        eq.append(cash + shares * tc)
    if not eq: return None
    fv = eq[-1]; tr = (fv / initial_cash - 1) * 100
    sharpe = 0.0
    if len(eq) > 1:
        rets = pd.Series(eq).pct_change().dropna()
        exc = rets - rf / 252
        if exc.std() > 1e-10:
            sharpe = float((exc.mean() / exc.std()) * (252 ** 0.5))
    tc2 = len(trips) + (1 if shares > 0 else 0)
    if tc2 == 0: return None
    return {"sharpe": sharpe, "total_return": tr, "trade_count": tc2}


configs = {
    "旧权重+旧阈值(0.07/-0.07)": {
        "weights": {"BOLL": 1.5, "MACD": 1.3, "KDJ": 1.1, "MA": 1.0,
                     "DUAL": 0.9, "RSI": 0.8, "PEPB": 0.8, "PE": 0.6,
                     "PB": 0.6, "NEWS": 0.5, "SENTIMENT": 0.5, "MONEY_FLOW": 0.4},
        "buy_th": 0.07, "sell_th": -0.07,
    },
    "新权重+旧阈值(0.07/-0.07)": {
        "weights": {"PB": 2.0, "BOLL": 1.95, "RSI": 1.82, "PE": 1.68,
                     "PEPB": 1.61, "KDJ": 1.5, "DUAL": 1.39, "MACD": 1.13,
                     "MA": 0.88, "SENTIMENT": 0.32, "NEWS": 0.32, "MONEY_FLOW": 0.3},
        "buy_th": 0.07, "sell_th": -0.07,
    },
    "新权重+新阈值(0.07/-0.15)": {
        "weights": {"PB": 2.0, "BOLL": 1.95, "RSI": 1.82, "PE": 1.68,
                     "PEPB": 1.61, "KDJ": 1.5, "DUAL": 1.39, "MACD": 1.13,
                     "MA": 0.88, "SENTIMENT": 0.32, "NEWS": 0.32, "MONEY_FLOW": 0.3},
        "buy_th": 0.07, "sell_th": -0.15,
    },
}

print()
print("=" * 100)
hdr = f"{'配置':<32} {'股票':>5} {'avgSharpe':>10} {'medSharpe':>10} {'avg收益%':>10} {'正收益%':>8} {'avg交易':>8}"
print(hdr)
print("-" * 100)

for name, cfg in configs.items():
    sharpes, rets, trades = [], [], []
    for code, sd in all_sig.items():
        r = replay(sd["signals"], cfg["weights"], cfg["buy_th"], cfg["sell_th"])
        if r:
            sharpes.append(r["sharpe"])
            rets.append(r["total_return"])
            trades.append(r["trade_count"])
    sa, ra = np.array(sharpes), np.array(rets)
    pos_pct = float((ra > 0).mean()) if len(ra) > 0 else 0
    print(f"{name:<32} {len(sharpes):>5} {np.mean(sa):>10.4f} {np.median(sa):>10.4f} "
          f"{np.mean(ra):>9.1f}% {pos_pct:>7.1%} {np.mean(trades):>8.1f}")

print("=" * 100)
