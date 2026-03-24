#!/usr/bin/env python3
"""
批量补全 parquet 回测数据中的 PE/PB 字段

从 baostock 获取每只股票的日频 peTTM 和 pbMRQ，
合并到现有的 mydate/backtest_kline/*.parquet 文件中。

用法:
  python3 tools/data/backfill_pe_pb.py              # 全量补全
  python3 tools/data/backfill_pe_pb.py --limit 10   # 只处理前10只（测试用）
  python3 tools/data/backfill_pe_pb.py --force       # 强制覆盖已有PE/PB数据
"""

import sys
import os
import time
import argparse
import logging

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')

BACKTEST_DIR = os.path.join(os.path.dirname(__file__), "../../mydate/backtest_kline")


def p(*args, **kwargs):
    print(*args, **kwargs, flush=True)


def code_to_bs(code: str) -> str:
    prefix = 'sh' if code.startswith(('5', '6', '9')) else 'sz'
    return f'{prefix}.{code}'


def fetch_pe_pb_from_baostock(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """从 baostock 获取日频 PE(TTM) 和 PB(MRQ)"""
    import baostock as bs

    bs_code = code_to_bs(code)
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,peTTM,pbMRQ",
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag="3",
    )

    rows = []
    while rs.error_code == '0' and rs.next():
        rows.append(rs.get_row_data())

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=['date', 'pe_ttm', 'pb'])
    df['date'] = pd.to_datetime(df['date'])
    df['pe_ttm'] = pd.to_numeric(df['pe_ttm'], errors='coerce')
    df['pb'] = pd.to_numeric(df['pb'], errors='coerce')

    # 过滤异常值：PE <= 0 或 > 10000 视为无效，PB <= 0 或 > 100 视为无效
    df.loc[(df['pe_ttm'] <= 0) | (df['pe_ttm'] > 10000), 'pe_ttm'] = np.nan
    df.loc[(df['pb'] <= 0) | (df['pb'] > 100), 'pb'] = np.nan

    return df.sort_values('date').reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description="批量补全 PE/PB 数据")
    parser.add_argument("--limit", type=int, default=0, help="只处理前N只（0=全部）")
    parser.add_argument("--force", action="store_true", help="强制覆盖已有PE/PB数据")
    args = parser.parse_args()

    import baostock as bs
    lg = bs.login()
    if lg.error_code != '0':
        p(f"❌ baostock 登录失败: {lg.error_msg}")
        return
    p("✅ baostock 登录成功")

    try:
        files = sorted([f for f in os.listdir(BACKTEST_DIR) if f.endswith('.parquet')])
        if args.limit > 0:
            files = files[:args.limit]

        total = len(files)
        p(f"\n📊 待处理: {total} 只股票")
        p(f"   目录: {BACKTEST_DIR}")
        p(f"   模式: {'强制覆盖' if args.force else '跳过已有'}")
        p()

        success = 0
        skipped = 0
        failed = 0
        no_data = 0

        t0 = time.time()
        for i, fname in enumerate(files):
            code = fname.replace('.parquet', '')
            path = os.path.join(BACKTEST_DIR, fname)

            df = pd.read_parquet(path)

            # 检查是否已有 PE/PB 数据
            if not args.force and 'pe_ttm' in df.columns and 'pb' in df.columns:
                pe_valid = df['pe_ttm'].notna().sum()
                pb_valid = df['pb'].notna().sum()
                if pe_valid > len(df) * 0.3:
                    skipped += 1
                    if (i + 1) % 100 == 0:
                        elapsed = time.time() - t0
                        p(f"   [{i+1}/{total}] 进度 {(i+1)/total*100:.0f}% "
                          f"(成功={success}, 跳过={skipped}, 无数据={no_data}, 失败={failed}) "
                          f"耗时 {elapsed/60:.1f}min")
                    continue

            df['date'] = pd.to_datetime(df['date'])
            start_date = df['date'].min().strftime('%Y-%m-%d')
            end_date = df['date'].max().strftime('%Y-%m-%d')

            try:
                pe_pb_df = fetch_pe_pb_from_baostock(code, start_date, end_date)

                if pe_pb_df.empty:
                    no_data += 1
                    if (i + 1) % 50 == 0 or i < 5:
                        p(f"   [{i+1}/{total}] {code}: 无PE/PB数据")
                    continue

                # 合并：按日期左连接
                if 'pe_ttm' in df.columns:
                    df = df.drop(columns=['pe_ttm'], errors='ignore')
                if 'pb' in df.columns:
                    df = df.drop(columns=['pb'], errors='ignore')

                merged = pd.merge(df, pe_pb_df[['date', 'pe_ttm', 'pb']],
                                  on='date', how='left')

                # 前向填充（非交易日的PE/PB用前一个交易日的值）
                merged['pe_ttm'] = merged['pe_ttm'].ffill()
                merged['pb'] = merged['pb'].ffill()

                merged = merged.sort_values('date').reset_index(drop=True)

                pe_valid = merged['pe_ttm'].notna().sum()
                pb_valid = merged['pb'].notna().sum()
                pe_rate = pe_valid / len(merged) * 100
                pb_rate = pb_valid / len(merged) * 100

                merged.to_parquet(path, index=False)
                success += 1

                if (i + 1) % 50 == 0 or i < 5:
                    elapsed = time.time() - t0
                    eta = elapsed / (i + 1) * (total - i - 1) / 60
                    p(f"   [{i+1}/{total}] {code}: PE覆盖{pe_rate:.0f}% PB覆盖{pb_rate:.0f}% "
                      f"(成功={success}, 跳过={skipped}, 无数据={no_data}) "
                      f"ETA {eta:.1f}min")

            except Exception as e:
                failed += 1
                if failed <= 5:
                    p(f"   [{i+1}/{total}] {code}: ❌ {e}")

            # baostock 限流
            if (i + 1) % 100 == 0:
                time.sleep(1)

        elapsed = time.time() - t0
        p(f"\n{'='*60}")
        p(f"  补全完成 · 耗时 {elapsed/60:.1f} 分钟")
        p(f"{'='*60}")
        p(f"  成功: {success}")
        p(f"  跳过（已有数据）: {skipped}")
        p(f"  无PE/PB数据: {no_data}")
        p(f"  失败: {failed}")
        p(f"  总计: {total}")
        p(f"{'='*60}")

    finally:
        bs.logout()
        p("baostock 已登出")


if __name__ == '__main__':
    main()
