#!/usr/bin/env python3
"""
回测辅助数据预取：新闻（按标的）、政策（单文件）、龙虎榜（按标的）写入指定目录 Parquet。
回测时通过 --local-aux DIR 指定该目录，并设置 BACKTEST_PREFETCH_DIR=DIR，策略从本地读。
与 docs/data/API_INTERFACES_AND_FETCHERS.md 2.3 一致。
"""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pandas as pd

try:
    from src.data.news.news_fetcher import fetch_stock_news
except ImportError:
    fetch_stock_news = None
try:
    from src.data.policy.policy_news import fetch_policy_news
except ImportError:
    fetch_policy_news = None
try:
    from src.data.money_flow.lhb import fetch_stock_lhb
except ImportError:
    fetch_stock_lhb = None


def load_stock_pool(pool_file: str, max_count: int = 200) -> list:
    try:
        from src.utils.pool_loader import load_pool
        return load_pool(pool_file, max_count=max_count, include_etf=False)
    except ImportError:
        pass
    with open(pool_file, "r", encoding="utf-8") as f:
        pool = json.load(f)
    sectors = pool.get("stocks", pool.get("sectors", {}))
    if not sectors:
        return []
    stocks = []
    for sector_name, sector_stocks in sectors.items():
        for s in sector_stocks[: max(1, max_count // len(sectors))]:
            stocks.append(s.get("code", s) if isinstance(s, dict) else s)
    return list({c for c in stocks if c})[:max_count]


def prefetch_news_one(code: str, out_dir: str, max_items: int = 30) -> tuple:
    path = os.path.join(out_dir, "news", f"{code}.parquet")
    try:
        if fetch_stock_news is None:
            return (code, False, "news_fetcher 未可用")
        df = fetch_stock_news(str(code), max_items=max_items)
        if df is None or df.empty:
            return (code, False, "无数据")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_parquet(path, index=False)
        return (code, True, f"{len(df)}条")
    except Exception as e:
        return (code, False, str(e))


def prefetch_policy(out_dir: str, max_items: int = 30) -> tuple:
    path = os.path.join(out_dir, "policy.parquet")
    try:
        if fetch_policy_news is None:
            return (False, "policy_news 未可用")
        df = fetch_policy_news(max_items=max_items)
        if df is None or df.empty:
            return (False, "无数据")
        os.makedirs(out_dir, exist_ok=True)
        df.to_parquet(path, index=False)
        return (True, f"{len(df)}条")
    except Exception as e:
        return (False, str(e))


def prefetch_lhb_one(code: str, out_dir: str, days_back: int = 10) -> tuple:
    path = os.path.join(out_dir, "lhb", f"{code}.parquet")
    try:
        if fetch_stock_lhb is None:
            return (code, False, "lhb 未可用")
        df = fetch_stock_lhb(str(code), days_back=days_back)
        if df is None or df.empty:
            return (code, False, "无数据")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_parquet(path, index=False)
        return (code, True, f"{len(df)}条")
    except Exception as e:
        return (code, False, str(e))


def main():
    parser = argparse.ArgumentParser(description="回测辅助数据预取：新闻/政策/龙虎榜 → Parquet")
    parser.add_argument("--pool", default="mydate/stock_pool.json", help="股票池 JSON")
    parser.add_argument("--count", type=int, default=50, help="预取标的数量")
    parser.add_argument("--out-dir", default="mydate/backtest_aux", help="输出目录（含 news/, lhb/ 子目录与 policy.parquet）")
    parser.add_argument("--workers", type=int, default=2, help="并发数")
    parser.add_argument("--news", action="store_true", help="预取新闻")
    parser.add_argument("--policy", action="store_true", help="预取政策")
    parser.add_argument("--lhb", action="store_true", help="预取龙虎榜")
    args = parser.parse_args()
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pool_path = os.path.join(base_dir, args.pool) if not os.path.isabs(args.pool) else args.pool
    out_dir = os.path.join(base_dir, args.out_dir) if not os.path.isabs(args.out_dir) else args.out_dir
    if not os.path.isfile(pool_path):
        print(f"股票池不存在: {pool_path}")
        sys.exit(1)
    os.makedirs(out_dir, exist_ok=True)
    stocks = load_stock_pool(pool_path, args.count)
    if not stocks:
        stocks = []
    do_all = not (args.news or args.policy or args.lhb)
    ok, fail = 0, 0
    if args.policy or do_all:
        success, msg = prefetch_policy(out_dir)
        if success:
            print(f"政策: 已写入 {msg}")
            ok += 1
        else:
            print(f"政策: 失败 {msg}")
            fail += 1
    if args.news or do_all:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(prefetch_news_one, c, out_dir): c for c in stocks}
            for fut in as_completed(futures):
                c, success, reason = fut.result()
                if success:
                    ok += 1
                    print(f"  新闻 {c} {reason}")
                else:
                    fail += 1
    if args.lhb or do_all:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(prefetch_lhb_one, c, out_dir): c for c in stocks}
            for fut in as_completed(futures):
                c, success, reason = fut.result()
                if success:
                    ok += 1
                    print(f"  龙虎榜 {c} {reason}")
                else:
                    fail += 1
    print(f"\n回测时使用: --local-aux {out_dir} 并设置 BACKTEST_PREFETCH_DIR={out_dir}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
