#!/usr/bin/env python3
"""
回测日线数据预取与更新：存股票池内数据到本地，并支持定期更新拉取新数据，用于策略验证与回测。

- 存：按股票池预取日线落盘为 Parquet，供 batch_backtest 读本地。
- 更新：在已有缓存基础上重新拉取最新数据并覆盖，更新后再跑回测即可用最新数据验证策略。

用法:
  # 首次：预取股票池内全部标的
  python3 tools/data/backtest_prefetch.py --pool mydate/stock_pool_all.json --all --out-dir mydate/backtest_kline --workers 4
  # 之后：定期更新，拉取新数据（覆盖本地，再用最新数据跑回测验证策略）
  python3 tools/data/backtest_prefetch.py --update --out-dir mydate/backtest_kline --datalen 800 --workers 4
  # 或只预取前 N 只
  python3 tools/data/backtest_prefetch.py --pool mydate/stock_pool.json --count 300 --out-dir mydate/backtest_kline --workers 4

预取/更新完成后会在 out-dir 下写入 manifest.json（记录所用股票池、标的列表、最后更新时间）。
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


def get_codes_to_update(out_dir: str) -> tuple:
    """
    获取需要更新的标的列表（用于 --update）。
    若存在 manifest.json 则用其中的 codes 与 pool；否则扫描 out_dir 下 *.parquet 得到 codes。
    返回 (codes, pool_rel 或 None)。
    """
    manifest_path = os.path.join(out_dir, "manifest.json")
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                m = json.load(f)
            codes = m.get("codes", [])
            pool_rel = m.get("pool")
            if codes:
                return (codes, pool_rel)
        except Exception:
            pass
    if not os.path.isdir(out_dir):
        return ([], None)
    codes = [f[:-8] for f in os.listdir(out_dir) if f.endswith(".parquet")]
    return (codes, None)


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
    parser = argparse.ArgumentParser(description="回测日线数据预取与更新（存+更新股票池内数据，供策略验证与回测）")
    parser.add_argument("--pool", default="mydate/stock_pool.json", help="股票池 JSON（预取时用；--update 时可选，用于补全 manifest）")
    parser.add_argument("--count", type=int, default=50, help="预取数量（与 --all 二选一）")
    parser.add_argument("--all", action="store_true", dest="prefetch_all",
                        help="预取股票池内全部标的（用于存池子数据做回测验证）")
    parser.add_argument("--update", action="store_true",
                        help="更新模式：对已有缓存逐只拉取最新数据并覆盖，便于用最新数据验证策略")
    parser.add_argument("--retry-failed", action="store_true",
                        help="仅重试 manifest 中 failed_codes 的标的（请求少，不易触发熔断）")
    parser.add_argument("--datalen", type=int, default=800, help="每只 K 线根数（预取与更新共用）")
    parser.add_argument("--out-dir", default="mydate/backtest_kline", help="输出目录（每只 code.parquet，并写 manifest.json）")
    parser.add_argument("--workers", type=int, default=2, help="并发数")
    parser.add_argument("--check", type=int, metavar="DAYS", default=0,
                        help="仅检查本地数据是否在 DAYS 天内更新；缺失或过期则退出码 1，便于 cron 触发重跑")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pool_path = os.path.join(base_dir, args.pool) if not os.path.isabs(args.pool) else args.pool
    out_dir = os.path.join(base_dir, args.out_dir) if not os.path.isabs(args.out_dir) else args.out_dir

    # 仅重试失败标的（从 manifest.failed_codes 读取，请求次数少）
    if getattr(args, "retry_failed", False):
        manifest_path = os.path.join(out_dir, "manifest.json")
        if not os.path.isfile(manifest_path):
            print(f"未找到 {manifest_path}，请先运行预取或更新。")
            sys.exit(1)
        with open(manifest_path, "r", encoding="utf-8") as f:
            m = json.load(f)
        codes = m.get("failed_codes", [])
        if not codes:
            print("无失败标的需重试（failed_codes 为空）。")
            sys.exit(0)
        os.makedirs(out_dir, exist_ok=True)
        print(f"仅重试失败标的：共 {len(codes)} 只，拉取最新 {args.datalen} 条 → {out_dir}")

        start = time.time()
        ok, fail = 0, 0
        still_failed = []
        for i, code in enumerate(codes):
            _, success, reason = prefetch_one(code, args.datalen, out_dir)
            if success:
                ok += 1
                print(f"  [{i+1}/{len(codes)}] {code} 已拉取 {reason}")
            else:
                fail += 1
                still_failed.append(code)
                print(f"  [{i+1}/{len(codes)}] {code} 失败: {reason}")
        elapsed = time.time() - start

        # 更新 manifest：只改 failed_codes 与统计
        all_codes = m.get("codes", [])
        m["failed_codes"] = sorted(still_failed)
        m["last_update"] = datetime.now().isoformat(timespec="seconds")
        m["success_count"] = len(all_codes) - len(still_failed)
        m["fail_count"] = len(still_failed)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
        print(f"\n重试完成: 本次成功 {ok}, 仍失败 {fail}, 耗时 {elapsed:.0f}s。manifest 已更新。")
        return 0 if fail == 0 else 1

    # 更新模式：按已有缓存拉取新数据并覆盖
    if getattr(args, "update", False):
        codes, pool_rel = get_codes_to_update(out_dir)
        if not codes:
            print("无已有数据可更新（out-dir 为空或无 manifest/parquet），请先运行预取：")
            print("  python3 tools/data/backtest_prefetch.py --pool mydate/stock_pool_all.json --all --out-dir mydate/backtest_kline --workers 4")
            sys.exit(1)
        os.makedirs(out_dir, exist_ok=True)
        print(f"更新模式：对已有 {len(codes)} 只拉取最新 {args.datalen} 条日线并覆盖 → {out_dir}")

        start = time.time()
        ok, fail = 0, 0
        failed_codes = []
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(prefetch_one, code, args.datalen, out_dir): code for code in codes}
            for i, fut in enumerate(as_completed(futures)):
                code, success, reason = fut.result()
                if success:
                    ok += 1
                    if (i + 1) % 50 == 0 or i < 3:
                        print(f"  [{i+1}/{len(codes)}] {code} 已更新 {reason}")
                else:
                    fail += 1
                    failed_codes.append(code)
                    print(f"  [{i+1}/{len(codes)}] {code} 失败: {reason}")
        elapsed = time.time() - start

        try:
            manifest_path = os.path.join(out_dir, "manifest.json")
            rel_pool = pool_rel or (args.pool if not os.path.isabs(args.pool) else os.path.relpath(pool_path, base_dir))
            manifest = {
                "pool": rel_pool,
                "codes": codes,
                "prefetch_time": datetime.now().isoformat(timespec="seconds"),
                "last_update": datetime.now().isoformat(timespec="seconds"),
                "datalen": args.datalen,
                "success_count": ok,
                "fail_count": fail,
                "failed_codes": sorted(failed_codes),
            }
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            print(f"已写入 {manifest_path}")
        except Exception as e:
            print(f"写入 manifest 失败: {e}")

        print(f"\n更新完成: 成功 {ok}, 失败 {fail}, 耗时 {elapsed:.0f}s。可运行回测验证策略: batch_backtest --local-kline {out_dir}")
        return 0 if fail == 0 else 1

    max_count = 99999 if getattr(args, 'prefetch_all', False) else args.count
    if args.check:
        need = check_freshness(out_dir, pool_path, max_count, args.check)
        sys.exit(0 if need <= 0 else 1)

    if not os.path.isfile(pool_path):
        print(f"股票池不存在: {pool_path}")
        sys.exit(1)
    os.makedirs(out_dir, exist_ok=True)

    stocks = load_stock_pool(pool_path, max_count)
    if not stocks:
        print("股票池为空或格式不支持")
        sys.exit(1)
    print(f"已加载股票池 {len(stocks)} 只，预取日线 {args.datalen} 条 → {out_dir}")

    start = time.time()
    ok, fail = 0, 0
    failed_codes = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(prefetch_one, s["code"], args.datalen, out_dir): s["code"] for s in stocks}
        for i, fut in enumerate(as_completed(futures)):
            code, success, reason = fut.result()
            if success:
                ok += 1
                print(f"  [{i+1}/{len(stocks)}] {code} 已写入 {reason}")
            else:
                fail += 1
                failed_codes.append(code)
                print(f"  [{i+1}/{len(stocks)}] {code} 失败: {reason}")
    elapsed = time.time() - start
    # 写入 manifest，记录所用股票池与标的列表、未拉取成功的代码，便于策略验证与回测复现
    try:
        manifest_path = os.path.join(out_dir, "manifest.json")
        rel_pool = args.pool if not os.path.isabs(args.pool) else os.path.relpath(pool_path, base_dir)
        manifest = {
            "pool": rel_pool,
            "codes": [s["code"] for s in stocks],
            "prefetch_time": datetime.now().isoformat(timespec="seconds"),
            "datalen": args.datalen,
            "success_count": ok,
            "fail_count": fail,
            "failed_codes": sorted(failed_codes),
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(f"已写入 {manifest_path}")
    except Exception as e:
        print(f"写入 manifest 失败: {e}")

    print(f"\n预取完成: 成功 {ok}, 失败 {fail}, 耗时 {elapsed:.0f}s。之后可 --update 拉取新数据，回测时使用: --local-kline {out_dir}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
