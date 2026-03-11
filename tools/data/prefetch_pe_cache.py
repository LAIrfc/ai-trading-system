"""
批量预取/增量更新历史 PE/PB 数据，存为本地 parquet 缓存。

策略：
  - 首次运行：全量拉取（从 K 线最早日期到今天）
  - 再次运行：增量更新（只拉缓存最后日期之后的新数据，追加合并）
  - --refresh：强制全量重拉，覆盖已有缓存

用法:
    python tools/data/prefetch_pe_cache.py              # 增量更新（默认）
    python tools/data/prefetch_pe_cache.py --count 50   # 只处理前50只
    python tools/data/prefetch_pe_cache.py --refresh    # 强制全量重拉

输出目录: mydate/pe_cache/{code}.parquet
每个文件列: date, pe_ttm, pb, turnover_rate
"""

import os
import sys
import glob
import argparse
import time
from typing import Optional
import pandas as pd
import baostock as bs
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

KLINE_DIR   = os.path.join(os.path.dirname(__file__), '../../mydate/backtest_kline')
PE_CACHE_DIR = os.path.join(os.path.dirname(__file__), '../../mydate/pe_cache')

_BS_LOGGED_IN = False


def bs_login():
    global _BS_LOGGED_IN
    if not _BS_LOGGED_IN:
        lg = bs.login()
        if lg.error_code != '0':
            raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")
        _BS_LOGGED_IN = True


def bs_logout():
    global _BS_LOGGED_IN
    if _BS_LOGGED_IN:
        bs.logout()
        _BS_LOGGED_IN = False


def code_to_bs(code: str) -> str:
    code = code.zfill(6)
    if code.startswith(('60', '68')):
        return f'sh.{code}'
    return f'sz.{code}'


def fetch_pe_range(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """从 baostock 拉取指定日期区间的 PE/PB 数据。"""
    bs_code = code_to_bs(code)
    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,peTTM,pbMRQ,turn",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="3"
        )
        rows = []
        while rs.error_code == '0' and rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=['date', 'pe_ttm', 'pb', 'turnover_rate'])
        df['date'] = pd.to_datetime(df['date'])
        df['pe_ttm'] = pd.to_numeric(df['pe_ttm'], errors='coerce')
        df['pb'] = pd.to_numeric(df['pb'], errors='coerce')
        df['turnover_rate'] = pd.to_numeric(df['turnover_rate'], errors='coerce')
        return df.sort_values('date').reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def get_kline_date_range(code: str) -> tuple:
    """从 K 线缓存读取日期范围（用于首次全量拉取的起始日期）。"""
    kline_path = os.path.join(KLINE_DIR, f'{code}.parquet')
    if not os.path.exists(kline_path):
        end = datetime.now()
        start = end - timedelta(days=1200)
        return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')
    try:
        df = pd.read_parquet(kline_path, columns=['date'])
        start = pd.to_datetime(df['date'].min()).strftime('%Y-%m-%d')
        end   = datetime.now().strftime('%Y-%m-%d')
        return start, end
    except Exception:
        end = datetime.now()
        start = end - timedelta(days=1200)
        return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')


def get_cache_last_date(code: str) -> Optional[str]:
    """读取已有缓存的最后日期，用于增量更新的起点。"""
    cache_path = os.path.join(PE_CACHE_DIR, f'{code}.parquet')
    if not os.path.exists(cache_path):
        return None
    try:
        df = pd.read_parquet(cache_path, columns=['date'])
        return pd.to_datetime(df['date'].max()).strftime('%Y-%m-%d')
    except Exception:
        return None


def update_pe_cache(code: str, refresh: bool = False) -> tuple:
    """
    更新单只股票的 PE 缓存。

    Returns:
        (status_str, new_rows_count)
        status: 'full' | 'incremental' | 'up_to_date' | 'fail'
    """
    cache_path = os.path.join(PE_CACHE_DIR, f'{code}.parquet')
    today = datetime.now().strftime('%Y-%m-%d')

    if refresh or not os.path.exists(cache_path):
        # 全量拉取
        start_date, end_date = get_kline_date_range(code)
        new_df = fetch_pe_range(code, start_date, end_date)
        if new_df.empty:
            return 'fail', 0
        new_df.to_parquet(cache_path, index=False)
        return 'full', len(new_df)

    # 增量更新：从缓存最后日期的次日开始拉
    last_date = get_cache_last_date(code)
    if last_date is None:
        # 缓存损坏，全量重拉
        start_date, _ = get_kline_date_range(code)
        new_df = fetch_pe_range(code, start_date, today)
        if new_df.empty:
            return 'fail', 0
        new_df.to_parquet(cache_path, index=False)
        return 'full', len(new_df)

    # 判断是否已是最新（最后日期是今天或昨天的交易日）
    last_dt = datetime.strptime(last_date, '%Y-%m-%d')
    days_behind = (datetime.now() - last_dt).days
    if days_behind <= 1:
        return 'up_to_date', 0

    # 拉增量数据（从最后日期次日到今天）
    inc_start = (last_dt + timedelta(days=1)).strftime('%Y-%m-%d')
    new_df = fetch_pe_range(code, inc_start, today)
    if new_df.empty:
        return 'up_to_date', 0

    # 读取旧缓存，合并去重，按日期排序后写回
    try:
        old_df = pd.read_parquet(cache_path)
        old_df['date'] = pd.to_datetime(old_df['date'])
        merged = pd.concat([old_df, new_df], ignore_index=True)
        merged = merged.drop_duplicates(subset='date').sort_values('date').reset_index(drop=True)
        merged.to_parquet(cache_path, index=False)
        return 'incremental', len(new_df)
    except Exception:
        # 旧缓存读取失败，直接覆盖
        new_df.to_parquet(cache_path, index=False)
        return 'incremental', len(new_df)


def main():
    parser = argparse.ArgumentParser(description='批量预取/增量更新历史PE/PB数据')
    parser.add_argument('--count',   type=int,  default=0,     help='最多处理N只，0=全量')
    parser.add_argument('--refresh', action='store_true',      help='强制全量重拉，覆盖已有缓存')
    args = parser.parse_args()

    os.makedirs(PE_CACHE_DIR, exist_ok=True)

    # 从 K 线缓存目录获取所有股票代码（跳过 ETF）
    kline_files = sorted(glob.glob(os.path.join(KLINE_DIR, '*.parquet')))
    codes = [os.path.basename(f).replace('.parquet', '') for f in kline_files]
    codes = [c for c in codes if not c.startswith('5')]

    if args.count > 0:
        codes = codes[:args.count]

    mode = '强制全量重拉' if args.refresh else '增量更新'
    print(f'PE/PB 缓存{mode}，共 {len(codes)} 只股票')
    print(f'缓存目录: {PE_CACHE_DIR}')
    print()

    bs_login()

    ok_full = ok_inc = ok_skip = fail_count = 0
    start_time = time.time()

    for i, code in enumerate(codes, 1):
        status, new_rows = update_pe_cache(code, refresh=args.refresh)

        if status == 'full':
            ok_full += 1
            status_str = f'全量({new_rows}条)'
        elif status == 'incremental':
            ok_inc += 1
            status_str = f'增量+{new_rows}条'
        elif status == 'up_to_date':
            ok_skip += 1
            status_str = '已最新'
        else:
            fail_count += 1
            status_str = 'FAIL'

        elapsed = time.time() - start_time
        eta = elapsed / i * (len(codes) - i)
        print(f'  [{i:4d}/{len(codes)}] {code}  {status_str:<14}  | 已用{elapsed:.0f}s 预计剩余{eta:.0f}s')

        time.sleep(0.05)

    bs_logout()

    print()
    print(f'完成！全量={ok_full} 增量={ok_inc} 已最新={ok_skip} 失败={fail_count}  总耗时: {time.time()-start_time:.0f}s')


if __name__ == '__main__':
    main()
