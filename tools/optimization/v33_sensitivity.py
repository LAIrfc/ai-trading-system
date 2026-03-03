#!/usr/bin/env python3
"""
V3.3 参数敏感性分析（Phase 6.2）

对新闻情感阈值、情绪分位、ADX 阈值等做网格扫描，筛选「收益/回撤比」变异系数最小的参数组。
用法:
  python3 tools/optimization/v33_sensitivity.py
  python3 tools/optimization/v33_sensitivity.py --stocks 20 --strategy news
"""

import sys
import os
import argparse
from itertools import product

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

# 敏感性区间（±20% 或文档约定）
NEWS_BUY_THRESHOLD = [0.24, 0.3, 0.36]
NEWS_SELL_THRESHOLD = [-0.36, -0.3, -0.24]
# ADX 阈值（情绪趋势过滤）：25 → [20, 30]
ADX_THRESHOLD_RANGE = [20, 25, 30]


def fetch_sina(code: str, datalen: int = 600) -> pd.DataFrame:
    """从新浪获取日线（与 batch_backtest 一致）。"""
    import json
    import requests
    prefix = "sh" if code.startswith(("5", "6")) else "sz"
    symbol = f"{prefix}{code}"
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    try:
        r = requests.get(
            url,
            params={"symbol": symbol, "scale": "240", "ma": "no", "datalen": str(datalen)},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        data = json.loads(r.text) if r.text.strip() else None
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["day"])
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df.get(c, 0), errors="coerce")
        return df
    except Exception:
        return pd.DataFrame()


def run_news_sensitivity(stocks_data: dict, initial_cash: float = 100000.0) -> pd.DataFrame:
    """
    新闻情感策略：buy_threshold in [0.24, 0.3, 0.36], sell_threshold in [-0.36, -0.3, -0.24]。
    对每组参数在所有股票上回测，计算收益/回撤比的均值和变异系数 CV，选 CV 最小。
    """
    from src.strategies.news_sentiment import NewsSentimentStrategy

    combos = list(product(NEWS_BUY_THRESHOLD, NEWS_SELL_THRESHOLD))
    combos = [(b, s) for b, s in combos if b > 0 and s < 0]
    results = []
    for buy_t, sell_t in combos:
        ratios = []
        for code, df in stocks_data.items():
            strat = NewsSentimentStrategy(symbol=code, buy_threshold=buy_t, sell_threshold=sell_t)
            if len(df) < strat.min_bars:
                continue
            try:
                bt = strat.backtest(df, initial_cash=initial_cash)
                ann = bt.get("annualized_return", 0) or 0
                dd = max(abs(bt.get("max_drawdown", 0) or 0), 0.01)
                ratios.append(ann / dd)
            except Exception:
                pass
        if not ratios:
            continue
        ratios = np.array(ratios)
        mean_r = float(np.mean(ratios))
        std_r = float(np.std(ratios))
        cv = (std_r / mean_r) if mean_r != 0 else 999.0
        results.append({
            "buy_threshold": buy_t,
            "sell_threshold": sell_t,
            "mean_ratio": mean_r,
            "std_ratio": std_r,
            "cv": cv,
            "stocks": len(ratios),
        })
    return pd.DataFrame(results)


def main():
    parser = argparse.ArgumentParser(description="V3.3 参数敏感性：收益/回撤比变异系数最小")
    parser.add_argument("--stocks", type=int, default=15, help="参与回测的股票数量")
    parser.add_argument("--strategy", type=str, default="news", choices=["news"], help="策略：news")
    parser.add_argument("--top", type=int, default=5, help="输出最优参数组数量")
    args = parser.parse_args()

    # 默认股票列表（沪深300 部分成分或固定列表）
    default_codes = [
        "000001", "000002", "600000", "600519", "000858",
        "601318", "600036", "000333", "601888", "002594",
        "600030", "000725", "601166", "002415", "300059",
    ]
    codes = default_codes[: max(args.stocks, 1)]

    print("加载行情...")
    stocks_data = {}
    for code in codes:
        df = fetch_sina(code, 600)
        if df is not None and len(df) >= 100:
            stocks_data[code] = df
    print(f"有效股票: {len(stocks_data)}")

    if args.strategy == "news":
        df_res = run_news_sensitivity(stocks_data)
    else:
        df_res = pd.DataFrame()

    if df_res.empty:
        print("无有效结果")
        return

    df_res = df_res.sort_values("cv").reset_index(drop=True)
    print("\n按收益/回撤比变异系数 CV 升序（越小越稳）：")
    print(df_res.head(args.top).to_string(index=False))
    best = df_res.iloc[0]
    print(f"\n推荐参数: buy_threshold={best['buy_threshold']}, sell_threshold={best['sell_threshold']} (CV={best['cv']:.4f})")


if __name__ == "__main__":
    main()
