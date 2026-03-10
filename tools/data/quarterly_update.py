#!/usr/bin/env python3
"""
股票池季度更新工具

每季度同步指数成分调整，更新综合股票池。
建议在每季度第一个交易日的开盘前运行（9:00-9:15）。

功能:
  1. 从baostock拉取最新沪深300+中证500成分股
  2. 刷新7大赛道龙头（东方财富）
  3. 更新基本面数据缓存
  4. 重新生成综合股票池

用法:
  python3 tools/data/quarterly_update.py               # 全量更新
  python3 tools/data/quarterly_update.py --index-only   # 仅更新指数成分
  python3 tools/data/quarterly_update.py --check        # 检查是否需要更新
  python3 tools/data/quarterly_update.py --force        # 强制更新（忽略日期检查）

定期执行（crontab）:
  # 每季度第一个周一早上8:30自动更新
  30 8 1-7 1,4,7,10 1 cd /home/wangxinghan/codetree/ai-trading-system && python3 tools/data/quarterly_update.py >> logs/quarterly_update.log 2>&1
"""

import sys
import os
import json
import time
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# 优先使用 mydate 和 mylog 目录
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(base_dir, 'mydate')
LOG_DIR = os.path.join(base_dir, 'mylog')
POOL_ALL_FILE = os.path.join(DATA_DIR, 'stock_pool_all.json')
UPDATE_LOG_FILE = os.path.join(DATA_DIR, 'update_history.json')

# 季度调整月份（3/6/9/12月的第二个周五后生效）
QUARTERLY_MONTHS = [1, 4, 7, 10]


def check_need_update() -> bool:
    """检查是否需要更新（上次更新距今超过85天）"""
    if not os.path.exists(UPDATE_LOG_FILE):
        print("  ⚠️ 无更新记录，需要更新")
        return True

    with open(UPDATE_LOG_FILE, 'r', encoding='utf-8') as f:
        history = json.load(f)

    last_update = history.get('last_update', '')
    if not last_update:
        return True

    last_date = datetime.strptime(last_update, '%Y-%m-%d')
    days_since = (datetime.now() - last_date).days

    print(f"  上次更新: {last_update} ({days_since}天前)")

    if days_since >= 85:  # 约一个季度
        print(f"  ⚠️ 距上次更新超过85天，建议更新")
        return True

    # 检查是否跨越了季度
    current_month = datetime.now().month
    last_month = last_date.month
    if current_month in QUARTERLY_MONTHS and last_month not in QUARTERLY_MONTHS:
        print(f"  ⚠️ 已进入新季度({current_month}月)，建议更新")
        return True

    print(f"  ✅ 暂不需要更新")
    return False


def update_index_constituents():
    """从baostock更新沪深300+中证500成分股"""
    print("\n📡 从baostock更新指数成分股...")

    try:
        import baostock as bs
    except ImportError:
        print("  ⚠️ baostock未安装，跳过指数更新")
        return False

    bs.login()

    today = datetime.now().strftime('%Y-%m-%d')
    all_stocks = {}

    # 沪深300
    print("  获取沪深300成分股...")
    rs = bs.query_hs300_stocks(date=today)
    hs300_count = 0
    while rs.error_code == '0' and rs.next():
        row = rs.get_row_data()
        code = row[1].split('.')[1] if '.' in row[1] else row[1]
        name = row[2]
        if code not in all_stocks:
            all_stocks[code] = {'code': code, 'name': name, 'index': 'HS300'}
            hs300_count += 1
    print(f"    沪深300: {hs300_count} 只")

    # 中证500
    print("  获取中证500成分股...")
    rs = bs.query_zz500_stocks(date=today)
    zz500_count = 0
    while rs.error_code == '0' and rs.next():
        row = rs.get_row_data()
        code = row[1].split('.')[1] if '.' in row[1] else row[1]
        name = row[2]
        if code not in all_stocks:
            all_stocks[code] = {'code': code, 'name': name, 'index': 'ZZ500'}
            zz500_count += 1
    print(f"    中证500: {zz500_count} 只 (去重后)")

    bs.logout()

    # 获取行业分类
    print("  获取行业分类...")
    bs.login()
    industry_map = {}
    for code in list(all_stocks.keys()):
        prefix = 'sh' if code.startswith(('5', '6')) else 'sz'
        full_code = f'{prefix}.{code}'
        rs = bs.query_stock_industry(code=full_code)
        if rs.error_code == '0' and rs.next():
            row = rs.get_row_data()
            industry = row[3] if len(row) > 3 else '未知'
            industry_map[code] = industry
    bs.logout()

    # 按行业分组
    sectors = {}
    for code, info in all_stocks.items():
        industry = industry_map.get(code, '未知')
        if industry not in sectors:
            sectors[industry] = []
        sectors[industry].append({
            'code': info['code'],
            'name': info['name'],
        })

    # 保存
    pool = {
        'description': f'沪深300+中证500成分股（{hs300_count}+{zz500_count}）',
        'source': 'baostock',
        'date': today,
        'sectors': sectors,
    }
    with open(POOL_ALL_FILE, 'w', encoding='utf-8') as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)

    total = sum(len(v) for v in sectors.values())
    print(f"  ✅ 指数成分股已更新: {total} 只, {len(sectors)} 个行业")
    return True


def update_fundamental_cache():
    """更新基本面数据缓存（PE/市值）"""
    import requests

    print("\n📡 更新基本面数据缓存...")

    # 加载所有股票代码
    all_codes = set()
    for pool_file in [
        os.path.join(DATA_DIR, 'stock_pool.json'),
        os.path.join(DATA_DIR, 'stock_pool_all.json'),
    ]:
        if os.path.exists(pool_file):
            with open(pool_file, 'r', encoding='utf-8') as f:
                pool = json.load(f)
            for sector, stocks in pool.get('sectors', {}).items():
                for s in stocks:
                    all_codes.add(s['code'])

    codes = sorted(all_codes)
    print(f"  需要获取 {len(codes)} 只股票的基本面数据")

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        'Referer': 'http://quote.eastmoney.com/',
    })

    results = {}
    batch_size = 30
    pause = 6

    for batch_start in range(0, len(codes), batch_size):
        batch = codes[batch_start:batch_start + batch_size]
        for code in batch:
            market = '1' if code.startswith(('5', '6')) else '0'
            try:
                url = 'http://push2.eastmoney.com/api/qt/stock/get'
                params = {
                    'secid': f'{market}.{code}',
                    'fields': 'f57,f58,f162,f116',
                    'fltt': '2',
                }
                r = session.get(url, params=params, timeout=8)
                d = r.json().get('data', {})
                if d:
                    name = str(d.get('f58', ''))
                    pe_raw = d.get('f162', '-')
                    cap_raw = d.get('f116', 0)

                    pe_val = None
                    try:
                        pe_val = float(pe_raw) if pe_raw and pe_raw != '-' else None
                    except:
                        pass
                    cap_yi = None
                    try:
                        cap_yi = round(float(cap_raw) / 1e8, 1) if cap_raw and cap_raw not in ['-', 0] else None
                    except:
                        pass

                    results[code] = {
                        'name': name,
                        'pe_ttm': pe_val,
                        'market_cap_yi': cap_yi,
                        'is_st': 'ST' in name or '*ST' in name or '退' in name,
                    }
            except:
                pass
            time.sleep(0.15)

        batch_end = min(batch_start + batch_size, len(codes))
        print(f"    进度: {batch_end}/{len(codes)}, 已获取 {len(results)}")
        time.sleep(pause)

    session.close()

    # 保存缓存
    cache_file = os.path.join(DATA_DIR, 'market_fundamental_cache.json')
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'total_fetched': len(results),
            'all_data': results,
        }, f, ensure_ascii=False)

    print(f"  ✅ 基本面缓存已更新: {len(results)}/{len(codes)} 只")
    return len(results)


def record_update(details: dict):
    """记录更新历史"""
    history = {'updates': []}
    if os.path.exists(UPDATE_LOG_FILE):
        with open(UPDATE_LOG_FILE, 'r', encoding='utf-8') as f:
            history = json.load(f)

    entry = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        **details,
    }
    history['updates'].append(entry)
    history['last_update'] = datetime.now().strftime('%Y-%m-%d')

    # 只保留最近20条记录
    history['updates'] = history['updates'][-20:]

    with open(UPDATE_LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"\n📝 更新记录已保存")


def main():
    parser = argparse.ArgumentParser(description='股票池季度更新工具')
    parser.add_argument('--check', action='store_true', help='仅检查是否需要更新')
    parser.add_argument('--index-only', action='store_true', help='仅更新指数成分')
    parser.add_argument('--force', action='store_true', help='强制更新')
    parser.add_argument('--skip-fundamental', action='store_true',
                        help='跳过基本面缓存更新（API不稳定时使用）')
    args = parser.parse_args()

    os.makedirs(LOG_DIR, exist_ok=True)

    print(f"{'='*60}")
    print(f"  📅 股票池季度更新工具")
    print(f"  📆 当前日期: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    # 检查是否需要更新
    need_update = check_need_update()

    if args.check:
        return

    if not need_update and not args.force:
        print("\n暂不需要更新。使用 --force 强制更新。")
        return

    details = {'type': 'quarterly_update'}

    # 1. 更新指数成分
    if update_index_constituents():
        details['index_updated'] = True

    # 2. 刷新赛道龙头
    if not args.index_only:
        try:
            from tools.data.refresh_stock_pool import refresh_sector_pool
            refresh_sector_pool()
            details['sectors_updated'] = True
        except Exception as e:
            print(f"  ⚠️ 赛道龙头更新失败: {e}")

    # 3. 更新基本面缓存
    if not args.skip_fundamental and not args.index_only:
        count = update_fundamental_cache()
        details['fundamental_count'] = count

    # 4. 重新生成综合池
    if not args.index_only:
        try:
            from tools.data.refresh_stock_pool import merge_all_pools
            merge_all_pools(do_filter=True, min_pe=0, max_pe=100, min_cap=30)
            details['merged'] = True
        except Exception as e:
            print(f"  ⚠️ 合并生成失败: {e}")

    # 记录更新
    record_update(details)

    print(f"\n{'='*60}")
    print(f"  ✅ 季度更新完成!")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
