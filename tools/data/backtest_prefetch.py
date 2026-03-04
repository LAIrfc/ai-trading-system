#!/usr/bin/env python3
"""
回测日线数据预取：按股票池批量拉取日线并落盘为 Parquet，供 batch_backtest --local-kline 使用。

用法:
  python3 tools/data/backtest_prefetch.py --pool mydate/stock_pool.json --count 50
  python3 tools/data/backtest_prefetch.py --pool mydate/stock_pool.json --count 100 --datalen 800 --out-dir mydate/backtest_kline --workers 4

与 docs/data/API_INTERFACES_AND_FETCHERS.md 第四阶段「回测数据准备」一致：
回测前预取全量日线存本地，回测时可选 --local-kline 从本地读，避免重复网络请求。
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

import pandas as pd

try:
    from src.data.fetchers.data_prefetch import fetch_stock_daily
except ImportError:
    fetch_stock_daily = None


def load_stock_pool(pool_file: str, max_count: int = 500) -> list:
    """与 batch_backtest 一致的股票池加载逻辑。"""
    try:
        from src.utils.pool_loader import load_pool
        return load_pool(pool_file, max_count=max_count, include_etf=False)
    except ImportError:
        pass
    with open(pool_file, 'r', encoding='utf-8') as f:
        pool = json.load(f)
    sectors = pool.get('stocks', pool.get('sectors', {}))
    if not sectors:
        return []
    per_sector = max(1, max_count // len(sectors))
    remainder = max_count - per_sector * len(sectors)
    stocks = []
    for sector_name, sector_stocks in sectors.items():
        quota = per_sector + (1 if remainder > 0 else 0)
        if remainder > 0:
            remainder -= 1
        for s in sector_stocks[:quota]:
            stocks.append({
                'code': s['code'],
                'name': s.get('name', s['code']),
                'sector': sector_name,
            })
    return stocks[:max_count]


def prefetch_one(code: str, datalen: int, out_dir: str, min_bars: int = 100) -> tuple:
    """拉取一只标的日线并写入 {out_dir}/{code}.parquet。返回 (code, ok, reason)。"""
    path = os.path.join(out_dir, f"{code}.parquet")
    try:
        if fetch_stock_daily is None:
            return (code, False, "data_prefetch 未可用")
        df = fetch_stock_daily(code=code, datalen=datalen, min_bars=min_bars)
        if df is None or df.empty or len(df) < min_bars:
            return (code, False, f"数据不足({len(df) if df is not None else 0}条)")
        df.to_parquet(path, index=False)
        return (code, True, f"{len(df)}条")
    except Exception as e:
        return (code, False, str(e))


def check_freshness(out_dir: str, pool_path: str, max_count: int, max_age_days: int) -> int:
    """
    检查 out_dir 下已有 Parquet 是否在 max_age_days 天内更新；股票池中缺失的视为需更新。
    返回需更新（缺失或过期）的数量；0 表示全部新鲜。
    """
    if not os.path.isdir(out_dir):
        print(f"输出目录不存在: {out_dir}")
        return -1
    stocks = load_stock_pool(pool_path, max_count)
    if not stocks:
        print("股票池为空")
        return 0
    cutoff = datetime.now() - timedelta(days=max_age_days)
    missing = []
    expired = []
    for s in stocks:
        code = s["code"]
        path = os.path.join(out_dir, f"{code}.parquet")
        if not os.path.isfile(path):
            missing.append(code)
            continue
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        if mtime < cutoff:
            expired.append((code, mtime.strftime("%Y-%m-%d %H:%M")))
    if missing:
        print(f"缺失 {len(missing)} 只: {missing[:10]}{'...' if len(missing) > 10 else ''}")
    if expired:
        print(f"过期(>{max_age_days}天) {len(expired)} 只: {[c for c, _ in expired[:10]]}{'...' if len(expired) > 10 else ''}")
    need = len(missing) + len(expired)
    if need == 0:
        print(f"全部 {len(stocks)} 只数据在 {max_age_days} 天内已更新。")
    else:
        print(f"共 {need} 只需更新（缺失 {len(missing)}，过期 {len(expired)}）。建议重新运行预取。")
    return need


def main():
    parser = argparse.ArgumentParser(description="回测日线数据预取（主 Sina → 备东方财富 → 腾讯）")
    parser.add_argument("--pool", default="mydate/stock_pool.json", help="股票池 JSON")
    parser.add_argument("--count", type=int, default=50, help="预取数量")
    parser.add_argument("--datalen", type=int, default=800, help="每只 K 线根数")
    parser.add_argument("--out-dir", default="mydate/backtest_kline", help="输出目录（每只 code.parquet）")
    parser.add_argument("--workers", type=int, default=2, help="并发数")
    parser.add_argument("--check", type=int, metavar="DAYS", default=0,
                        help="仅检查本地数据是否在 DAYS 天内更新；缺失或过期则退出码 1，便于 cron 触发重跑")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pool_path = os.path.join(base_dir, args.pool) if not os.path.isabs(args.pool) else args.pool
    out_dir = os.path.join(base_dir, args.out_dir) if not os.path.isabs(args.out_dir) else args.out_dir

    if args.check:
        need = check_freshness(out_dir, pool_path, args.count, args.check)
        sys.exit(0 if need <= 0 else 1)

    if not os.path.isfile(pool_path):
        print(f"股票池不存在: {pool_path}")
        sys.exit(1)
    os.makedirs(out_dir, exist_ok=True)

    stocks = load_stock_pool(pool_path, args.count)
    print(f"已加载 {len(stocks)} 只股票，预取日线 {args.datalen} 条 → {out_dir}")

    start = time.time()
    ok, fail = 0, 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(prefetch_one, s["code"], args.datalen, out_dir): s["code"] for s in stocks}
        for i, fut in enumerate(as_completed(futures)):
            code, success, reason = fut.result()
            if success:
                ok += 1
                print(f"  [{i+1}/{len(stocks)}] {code} 已写入 {reason}")
            else:
                fail += 1
                print(f"  [{i+1}/{len(stocks)}] {code} 失败: {reason}")
    elapsed = time.time() - start
    print(f"\n预取完成: 成功 {ok}, 失败 {fail}, 耗时 {elapsed:.0f}s。回测时使用: --local-kline {out_dir}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
