#!/usr/bin/env python3
"""
刷新股票池数据
从东方财富获取各板块龙头股票，更新 data/stock_pool.json

用法:
  python3 tools/refresh_stock_pool.py              # 更新股票池
  python3 tools/refresh_stock_pool.py --verify     # 验证现有股票池
"""

import sys
import os
import json
import time
import argparse
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

POOL_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'stock_pool.json')

# 板块代码映射 (东方财富)
SECTOR_BOARDS = {
    '光伏':     {'concept': 'BK1031', 'industry': 'BK1315', 'target': 15},
    '机器人':   {'concept': 'BK1090', 'industry': 'BK1408', 'target': 15},
    '半导体':   {'concept': 'BK0917', 'industry': 'BK1325', 'target': 15},
    '有色金属': {'concept': None,     'industry': 'BK0478', 'target': 14},
    '证券':     {'concept': 'BK0711', 'industry': 'BK0473', 'target': 14},
    '创新药':   {'concept': 'BK1106', 'industry': None,     'target': 14},
    '商业航天': {'concept': 'BK0963', 'industry': 'BK1232', 'target': 13},
}


def fetch_board_stocks(board_code, limit=30):
    """从东方财富获取板块成分股"""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        'Referer': 'http://quote.eastmoney.com/',
    })
    try:
        url = 'http://push2.eastmoney.com/api/qt/clist/get'
        params = {
            'pn': 1, 'pz': limit, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2,
            'fid': 'f20', 'fs': f'b:{board_code}',
            'fields': 'f12,f14,f2,f3,f20,f6',
        }
        resp = session.get(url, params=params, timeout=15)
        data = resp.json()
        stocks = []
        if data.get('data') and data['data'].get('diff'):
            for item in data['data']['diff']:
                code = item.get('f12', '')
                name = item.get('f14', '')
                price = item.get('f2', 0)
                cap = item.get('f20', 0)
                if name and 'ST' not in name and '*' not in name \
                   and price and price != '-' and cap and cap > 1e9:
                    stocks.append({
                        'code': code, 'name': name,
                        'market_cap_yi': round(cap / 1e8, 1),
                    })
        return stocks
    except Exception as e:
        print(f"  ⚠️ 请求 {board_code} 失败: {e}")
        return []
    finally:
        session.close()


def refresh():
    """从东方财富刷新股票池"""
    print("📡 从东方财富获取板块成分股...")
    pool = {'created_at': time.strftime('%Y-%m-%d'), 'sectors': {}, 'stocks': []}
    seen = set()

    for sector, info in SECTOR_BOARDS.items():
        stocks = []
        for key in ['concept', 'industry']:
            if info[key]:
                s = fetch_board_stocks(info[key], info['target'] * 2)
                stocks.extend(s)
                time.sleep(3)

        # 去重，取前N只
        selected = []
        for s in stocks:
            if s['code'] not in seen and len(selected) < info['target']:
                selected.append(s)
                seen.add(s['code'])

        pool['sectors'][sector] = selected
        print(f"  {sector}: {len(selected)} 只")

    pool['total'] = sum(len(v) for v in pool['sectors'].values())
    pool['description'] = '7大热门赛道精选股票池'

    with open(POOL_FILE, 'w', encoding='utf-8') as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 已更新 {POOL_FILE}，共 {pool['total']} 只")


def verify():
    """验证现有股票池中的股票数据是否可获取"""
    with open(POOL_FILE, 'r', encoding='utf-8') as f:
        pool = json.load(f)

    total = 0
    ok = 0
    fail = 0

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        'Referer': 'http://quote.eastmoney.com/',
    })

    for sector, stocks in pool['sectors'].items():
        print(f"\n【{sector}】 {len(stocks)} 只")
        for s in stocks:
            code = s['code']
            market = 1 if code.startswith(('5', '6')) else 0
            total += 1
            try:
                url = 'http://push2his.eastmoney.com/api/qt/stock/kline/get'
                params = {
                    'secid': f'{market}.{code}',
                    'fields1': 'f1,f2,f3,f4,f5,f6',
                    'fields2': 'f51,f52,f53,f54,f55,f56,f57',
                    'klt': '101', 'fqt': '1', 'lmt': '1', 'end': '20500101',
                }
                resp = session.get(url, params=params, timeout=10)
                data = resp.json()
                if data.get('data') and data['data'].get('klines'):
                    last = data['data']['klines'][-1].split(',')
                    print(f"  ✅ {code} {s['name']:8s} 最新:{last[0]} ¥{last[2]}")
                    ok += 1
                else:
                    print(f"  ❌ {code} {s['name']:8s} 无数据")
                    fail += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"  ⚠️ {code} {s['name']:8s} 请求失败: {e}")
                fail += 1
                time.sleep(2)

    print(f"\n{'='*40}")
    print(f"总计: {total} 只, 成功: {ok}, 失败: {fail}")
    session.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', action='store_true', help='验证股票池')
    args = parser.parse_args()

    if args.verify:
        verify()
    else:
        refresh()
