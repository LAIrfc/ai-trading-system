#!/usr/bin/env python3
"""
股票池刷新工具 —— 生成综合股票池（个股 + ETF）

功能:
  1. 从baostock获取沪深300+中证500成分股
  2. 从东方财富获取7大热门赛道龙头
  3. 整合ETF池
  4. 基本面前置过滤（PE 0-100、市值>30亿、排除ST）
  5. 合并去重，输出 data/stock_pool_all.json

用法:
  python3 tools/data/refresh_stock_pool.py                # 全量刷新
  python3 tools/data/refresh_stock_pool.py --verify       # 验证现有池
  python3 tools/data/refresh_stock_pool.py --filter-only  # 仅对现有池做基本面过滤
  python3 tools/data/refresh_stock_pool.py --etf-only     # 仅更新ETF池
"""

import sys
import os
import json
import time
import argparse
import requests
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# 优先使用 mydate 目录
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(base_dir, 'mydate')
POOL_100_FILE = os.path.join(DATA_DIR, 'stock_pool.json')
POOL_600_FILE = os.path.join(DATA_DIR, 'stock_pool_600.json')
ETF_POOL_FILE = os.path.join(DATA_DIR, 'etf_pool.json')
OUTPUT_FILE = os.path.join(DATA_DIR, 'stock_pool_all.json')

# ============================================================
# 东方财富API工具
# ============================================================

def _eastmoney_session():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        'Referer': 'http://quote.eastmoney.com/',
    })
    return s


def fetch_realtime_info(codes: list, session=None) -> dict:
    """
    逐只获取股票实时信息（PE/市值/名称/是否ST）
    使用东财单只接口，稳定可靠
    返回 {code: {name, pe_ttm, market_cap_yi, is_st}} 
    """
    if session is None:
        session = _eastmoney_session()

    results = {}
    total = len(codes)

    for idx, code in enumerate(codes):
        if (idx + 1) % 100 == 0:
            print(f"    进度: {idx+1}/{total}...")

        market = '1' if code.startswith(('5', '6')) else '0'
        try:
            url = 'http://push2.eastmoney.com/api/qt/stock/get'
            params = {
                'secid': f'{market}.{code}',
                'fields': 'f57,f58,f162,f116,f170',
                'fltt': '2',
            }
            resp = session.get(url, params=params, timeout=8)
            d = resp.json().get('data', {})

            if not d:
                continue

            name = str(d.get('f58', ''))
            pe_raw = d.get('f162', '-')
            cap_raw = d.get('f116', 0)

            is_st = 'ST' in name or '*ST' in name or '退' in name

            try:
                pe_val = float(pe_raw) if pe_raw and pe_raw != '-' else None
            except (ValueError, TypeError):
                pe_val = None

            try:
                cap_yi = round(float(cap_raw) / 1e8, 1) if cap_raw and cap_raw != '-' and cap_raw != 0 else None
            except (ValueError, TypeError):
                cap_yi = None

            results[code] = {
                'name': name,
                'pe_ttm': pe_val,
                'market_cap_yi': cap_yi,
                'is_st': is_st,
            }
        except Exception as e:
            pass  # 静默跳过失败的

        time.sleep(0.1)

    return results


# ============================================================
# 板块成分股获取（东方财富）
# ============================================================

SECTOR_BOARDS = {
    '光伏':     {'concept': 'BK1031', 'industry': 'BK1315', 'target': 15},
    '机器人':   {'concept': 'BK1090', 'industry': 'BK1408', 'target': 15},
    '半导体':   {'concept': 'BK0917', 'industry': 'BK1325', 'target': 15},
    '有色金属': {'concept': None,     'industry': 'BK0478', 'target': 15},
    '证券':     {'concept': 'BK0711', 'industry': 'BK0473', 'target': 14},
    '创新药':   {'concept': 'BK1106', 'industry': None,     'target': 14},
    '商业航天': {'concept': 'BK0963', 'industry': 'BK1232', 'target': 13},
}


def fetch_board_stocks(board_code, limit=30):
    """从东方财富获取板块成分股（按市值排序）"""
    session = _eastmoney_session()
    try:
        url = 'http://push2.eastmoney.com/api/qt/clist/get'
        params = {
            'pn': 1, 'pz': limit, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2,
            'fid': 'f20', 'fs': f'b:{board_code}',
            'fields': 'f12,f14,f2,f3,f20,f6,f9',
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
                pe = item.get('f9', '-')
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


def refresh_sector_pool():
    """刷新7大赛道龙头池"""
    print("📡 从东方财富获取7大赛道龙头...")
    pool = {
        'created_at': time.strftime('%Y-%m-%d'),
        'description': '7大热门赛道精选龙头股票池',
        'total': 0,
        'sectors': {},
    }
    seen = set()

    for sector, info in SECTOR_BOARDS.items():
        stocks = []
        for key in ['concept', 'industry']:
            if info[key]:
                s = fetch_board_stocks(info[key], info['target'] * 2)
                stocks.extend(s)
                time.sleep(2)

        selected = []
        for s in stocks:
            if s['code'] not in seen and len(selected) < info['target']:
                selected.append({'code': s['code'], 'name': s['name']})
                seen.add(s['code'])

        pool['sectors'][sector] = selected
        print(f"  {sector}: {len(selected)} 只")

    pool['total'] = sum(len(v) for v in pool['sectors'].values())

    with open(POOL_100_FILE, 'w', encoding='utf-8') as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)
    print(f"  ✅ 已更新 {POOL_100_FILE}，共 {pool['total']} 只")
    return pool


# ============================================================
# 基本面过滤
# ============================================================

def fundamental_filter(stocks: list,
                       min_pe: float = 0,
                       max_pe: float = 100,
                       min_market_cap_yi: float = 30,
                       exclude_st: bool = True) -> list:
    """
    基本面前置过滤
    - PE TTM: 0 < PE < 100（排除亏损股和泡沫股）
    - 市值 > 30亿
    - 排除ST/*ST/退市预警
    
    返回过滤后的股票列表和过滤统计
    """
    print(f"\n🔍 基本面过滤 (PE: {min_pe}-{max_pe}, 市值>{min_market_cap_yi}亿, 排除ST={exclude_st})")

    codes = [s['code'] for s in stocks]
    session = _eastmoney_session()

    # 批量获取基本面数据
    print(f"  📡 获取 {len(codes)} 只股票的基本面数据...")
    info_map = fetch_realtime_info(codes, session)
    session.close()

    passed = []
    filtered_st = 0
    filtered_pe = 0
    filtered_cap = 0
    filtered_no_data = 0

    for s in stocks:
        code = s['code']
        info = info_map.get(code)

        if not info:
            filtered_no_data += 1
            continue

        # ST过滤
        if exclude_st and info['is_st']:
            filtered_st += 1
            continue

        # PE过滤（允许PE为None的通过，因为ETF/银行等可能没有PE）
        if info['pe_ttm'] is not None:
            if info['pe_ttm'] <= min_pe or info['pe_ttm'] > max_pe:
                filtered_pe += 1
                continue

        # 市值过滤
        if info['market_cap_yi'] is not None:
            if info['market_cap_yi'] < min_market_cap_yi:
                filtered_cap += 1
                continue

        # 通过过滤
        s_copy = dict(s)
        s_copy['pe_ttm'] = info['pe_ttm']
        s_copy['market_cap_yi'] = info['market_cap_yi']
        if info['name']:
            s_copy['name'] = info['name']
        passed.append(s_copy)

    print(f"  📊 过滤结果:")
    print(f"    原始: {len(stocks)} 只")
    print(f"    ST过滤: -{filtered_st}")
    print(f"    PE过滤(0-{max_pe}): -{filtered_pe}")
    print(f"    市值过滤(>{min_market_cap_yi}亿): -{filtered_cap}")
    print(f"    无数据: -{filtered_no_data}")
    print(f"    ✅ 通过: {len(passed)} 只")

    return passed


# ============================================================
# 合并生成综合股票池
# ============================================================

def merge_all_pools(do_filter=True, min_pe=0, max_pe=100, min_cap=30):
    """合并所有股票池 + ETF池，去重，输出综合池"""
    print(f"\n{'='*60}")
    print(f"  📦 合并生成综合股票池")
    print(f"{'='*60}")

    all_stocks = []
    seen_codes = set()

    # 1. 加载赛道龙头池
    if os.path.exists(POOL_100_FILE):
        with open(POOL_100_FILE, 'r', encoding='utf-8') as f:
            p1 = json.load(f)
        for sector, stocks in p1.get('sectors', {}).items():
            for s in stocks:
                if s['code'] not in seen_codes:
                    all_stocks.append({
                        'code': s['code'],
                        'name': s.get('name', ''),
                        'sector': sector,
                        'source': 'sector_100',
                    })
                    seen_codes.add(s['code'])
        print(f"  赛道龙头池: +{len([s for s in all_stocks if s['source']=='sector_100'])} 只")

    # 2. 加载指数成分股池
    if os.path.exists(POOL_600_FILE):
        with open(POOL_600_FILE, 'r', encoding='utf-8') as f:
            p2 = json.load(f)
        count_before = len(all_stocks)
        for sector, stocks in p2.get('sectors', {}).items():
            for s in stocks:
                if s['code'] not in seen_codes:
                    all_stocks.append({
                        'code': s['code'],
                        'name': s.get('name', ''),
                        'sector': sector,
                        'source': 'index_800',
                    })
                    seen_codes.add(s['code'])
        print(f"  指数成分股池: +{len(all_stocks) - count_before} 只 (去重后)")

    print(f"  合计个股: {len(all_stocks)} 只")

    # 3. 基本面过滤（仅对个股）
    # 先尝试从缓存获取基本面数据
    cache_file = os.path.join(DATA_DIR, 'market_fundamental_cache.json')
    cache_data = {}
    if do_filter and os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            cache_data = cache.get('all_data', {})
            print(f"  📦 加载缓存基本面数据: {len(cache_data)} 只 (日期: {cache.get('date','未知')})")
        except:
            pass

    if do_filter and cache_data:
        # 使用缓存数据过滤
        filtered = []
        st_cnt = pe_cnt = cap_cnt = no_data_cnt = 0
        for s in all_stocks:
            info = cache_data.get(s['code'])
            if not info:
                # 缓存中无数据的直接放行（宁可多不可少）
                filtered.append(s)
                no_data_cnt += 1
                continue
            if info.get('is_st'):
                st_cnt += 1
                continue
            pe = info.get('pe_ttm')
            if pe is not None and (pe <= min_pe or pe > max_pe):
                pe_cnt += 1
                continue
            cap = info.get('market_cap_yi')
            if cap is not None and cap < min_cap:
                cap_cnt += 1
                continue
            s_copy = dict(s)
            s_copy['pe_ttm'] = pe
            s_copy['market_cap_yi'] = cap
            if info.get('name'):
                s_copy['name'] = info['name']
            filtered.append(s_copy)
        
        print(f"  🔍 基本面过滤 (缓存数据):")
        print(f"    ST过滤: -{st_cnt}, PE过滤: -{pe_cnt}, 市值过滤: -{cap_cnt}, 无缓存(放行): {no_data_cnt}")
        print(f"    ✅ 通过: {len(filtered)} 只")
        all_stocks = filtered
    elif do_filter:
        # 尝试在线获取
        print(f"  📡 尝试在线获取基本面数据...")
        all_stocks = fundamental_filter(
            all_stocks,
            min_pe=min_pe,
            max_pe=max_pe,
            min_market_cap_yi=min_cap,
            exclude_st=True,
        )

    # 4. 加载ETF池
    etf_list = []
    if os.path.exists(ETF_POOL_FILE):
        with open(ETF_POOL_FILE, 'r', encoding='utf-8') as f:
            etf_pool = json.load(f)
        for cat, etfs in etf_pool.get('categories', {}).items():
            for e in etfs:
                if e['code'] not in seen_codes:
                    etf_list.append({
                        'code': e['code'],
                        'name': e['name'],
                        'sector': cat,
                        'track': e.get('track', ''),
                        'type': 'ETF',
                    })
                    seen_codes.add(e['code'])
        print(f"  ETF池: +{len(etf_list)} 只")

    # 5. 构建输出
    output = {
        'description': '综合股票池（个股+ETF），含基本面过滤',
        'created_at': datetime.now().strftime('%Y-%m-%d'),
        'filter_rules': {
            'pe_range': f'{min_pe}-{max_pe}' if do_filter else '未过滤',
            'min_market_cap_yi': min_cap if do_filter else '未过滤',
            'exclude_st': True if do_filter else False,
        },
        'stats': {
            'total_stocks': len(all_stocks),
            'total_etf': len(etf_list),
            'total': len(all_stocks) + len(etf_list),
        },
        'stocks': {},
        'etf': {},
    }

    # 按板块分组（个股）
    for s in all_stocks:
        sector = s['sector']
        if sector not in output['stocks']:
            output['stocks'][sector] = []
        entry = {'code': s['code'], 'name': s['name']}
        if 'pe_ttm' in s and s['pe_ttm'] is not None:
            entry['pe_ttm'] = s['pe_ttm']
        if 'market_cap_yi' in s and s['market_cap_yi'] is not None:
            entry['market_cap_yi'] = s['market_cap_yi']
        output['stocks'][sector].append(entry)

    # 按类别分组（ETF）
    for e in etf_list:
        cat = e['sector']
        if cat not in output['etf']:
            output['etf'][cat] = []
        output['etf'][cat].append({
            'code': e['code'],
            'name': e['name'],
            'track': e.get('track', ''),
        })

    # 保存
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"  ✅ 综合股票池已生成: {OUTPUT_FILE}")
    print(f"  📊 个股: {len(all_stocks)} 只 ({len(output['stocks'])} 个板块)")
    print(f"  📊 ETF:  {len(etf_list)} 只 ({len(output['etf'])} 个类别)")
    print(f"  📊 合计: {len(all_stocks) + len(etf_list)} 只")
    print(f"{'='*60}")

    # 打印各板块统计
    print(f"\n  个股板块分布 (前15):")
    sector_counts = sorted(
        [(k, len(v)) for k, v in output['stocks'].items()],
        key=lambda x: x[1], reverse=True
    )
    for sector, count in sector_counts[:15]:
        print(f"    {sector[:20]:20s}: {count:>3} 只")
    if len(sector_counts) > 15:
        print(f"    ... 还有 {len(sector_counts)-15} 个板块")

    print(f"\n  ETF类别分布:")
    for cat, etfs in output['etf'].items():
        print(f"    {cat:12s}: {len(etfs):>2} 只")

    return output


# ============================================================
# 验证
# ============================================================

def verify():
    """验证综合股票池中的股票数据是否可获取"""
    pool_file = OUTPUT_FILE if os.path.exists(OUTPUT_FILE) else POOL_100_FILE

    with open(pool_file, 'r', encoding='utf-8') as f:
        pool = json.load(f)

    # 兼容两种格式
    all_codes = []
    if 'stocks' in pool:
        for sector, stocks in pool['stocks'].items():
            for s in stocks:
                all_codes.append((s['code'], s['name'], sector))
    elif 'sectors' in pool:
        for sector, stocks in pool['sectors'].items():
            for s in stocks:
                all_codes.append((s['code'], s.get('name', ''), sector))

    if 'etf' in pool:
        for cat, etfs in pool['etf'].items():
            for e in etfs:
                all_codes.append((e['code'], e['name'], f'ETF-{cat}'))

    print(f"验证 {len(all_codes)} 只标的...")

    session = _eastmoney_session()
    ok = 0
    fail = 0
    total = 0

    for code, name, sector in all_codes:
        market = '1' if code.startswith(('5', '6')) else '0'
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
                ok += 1
            else:
                print(f"  ❌ {code} {name:8s} [{sector[:10]}] 无数据")
                fail += 1
            time.sleep(0.2)
        except Exception as e:
            print(f"  ⚠️ {code} {name:8s} 请求失败: {e}")
            fail += 1
            time.sleep(1)

        if total % 100 == 0:
            print(f"  ... 已验证 {total}/{len(all_codes)}, 成功{ok}, 失败{fail}")

    print(f"\n{'='*40}")
    print(f"总计: {total} 只, 成功: {ok}, 失败: {fail}")
    session.close()


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='股票池刷新工具')
    parser.add_argument('--verify', action='store_true', help='验证股票池数据')
    parser.add_argument('--filter-only', action='store_true',
                        help='仅对现有池做基本面过滤（不重新获取）')
    parser.add_argument('--etf-only', action='store_true',
                        help='仅更新ETF池')
    parser.add_argument('--refresh-sectors', action='store_true',
                        help='重新获取7大赛道龙头')
    parser.add_argument('--no-filter', action='store_true',
                        help='不做基本面过滤')
    parser.add_argument('--min-pe', type=float, default=0, help='PE下限 (默认0)')
    parser.add_argument('--max-pe', type=float, default=100, help='PE上限 (默认100)')
    parser.add_argument('--min-cap', type=float, default=30, help='最小市值(亿) (默认30)')
    args = parser.parse_args()

    if args.verify:
        verify()
    elif args.etf_only:
        print("ETF池已存在，如需更新请直接编辑 data/etf_pool.json")
    elif args.refresh_sectors:
        refresh_sector_pool()
        merge_all_pools(
            do_filter=not args.no_filter,
            min_pe=args.min_pe,
            max_pe=args.max_pe,
            min_cap=args.min_cap,
        )
    else:
        # 默认：合并现有池 + 过滤
        merge_all_pools(
            do_filter=not args.no_filter,
            min_pe=args.min_pe,
            max_pe=args.max_pe,
            min_cap=args.min_cap,
        )


if __name__ == '__main__':
    main()
