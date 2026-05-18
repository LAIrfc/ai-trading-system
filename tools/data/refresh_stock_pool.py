#!/usr/bin/env python3
"""
股票池刷新工具 v2 — 4源构建综合池

综合大池 stock_pool_all.json 是每日选股的唯一数据源。

5个来源:
  1. 沪深300 成分股     ≈ 300只   (baostock 动态获取)
  2. 中证500 成分股     ≈ 500只   (baostock 动态获取)
  3. 科创50 成分股      ≈ 50只    (akshare 动态获取)
  4. 创业板300          = 300只   (创业板指399006[100只] + 创业板200指数399019[200只])
  5. 创业板活跃补充      ≈ 100只   (非指数成分, 按日均成交额排序)

合并去重后约 1100只。

用法:
  python3 tools/data/refresh_stock_pool.py              # 全量刷新
  python3 tools/data/refresh_stock_pool.py --verify     # 验证现有池
  python3 tools/data/refresh_stock_pool.py --dry-run    # 只显示统计不保存
"""

import sys
import os
import json
import time
import argparse
import requests
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(base_dir, 'mydate')
OUTPUT_FILE = os.path.join(DATA_DIR, 'stock_pool_all.json')
ETF_POOL_FILE = os.path.join(DATA_DIR, 'etf_pool.json')


def _eastmoney_session():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        'Referer': 'http://quote.eastmoney.com/',
    })
    return s


# ============================================================
# 来源1+2: 沪深300 + 中证500 (baostock)
# ============================================================

def fetch_index_constituents_bs():
    """从baostock获取沪深300+中证500成分股（含行业分类）"""
    print("\n📡 来源1+2: 从baostock获取沪深300+中证500成分股...")
    try:
        import baostock as bs
    except ImportError:
        print("  ❌ baostock未安装")
        return {}

    bs.login()
    today = datetime.now().strftime('%Y-%m-%d')
    all_stocks = {}

    for index_name, query_fn in [
        ('沪深300', lambda d: bs.query_hs300_stocks(date=d)),
        ('中证500', lambda d: bs.query_zz500_stocks(date=d)),
    ]:
        rs = query_fn(today)
        count = 0
        while rs.error_code == '0' and rs.next():
            row = rs.get_row_data()
            code = row[1].split('.')[1] if '.' in row[1] else row[1]
            name = row[2]
            if code not in all_stocks:
                all_stocks[code] = {'code': code, 'name': name}
                count += 1
        print(f"  {index_name}: {count}只 (去重后)")

    # 获取行业分类（批量）
    print("  获取行业分类...")
    industry_map = {}
    codes_list = list(all_stocks.keys())
    for i, code in enumerate(codes_list):
        prefix = 'sh' if code.startswith(('5', '6')) else 'sz'
        try:
            rs = bs.query_stock_industry(code=f'{prefix}.{code}')
            if rs.error_code == '0' and rs.next():
                row = rs.get_row_data()
                industry = row[3] if len(row) > 3 else '未知'
                industry_map[code] = industry
        except Exception:
            pass
        if (i + 1) % 200 == 0:
            print(f"    进度: {i+1}/{len(codes_list)}")

    bs.logout()

    sectors = {}
    for code, info in all_stocks.items():
        industry = industry_map.get(code, '未知')
        sectors.setdefault(industry, []).append({
            'code': info['code'],
            'name': info['name'],
        })

    total = sum(len(v) for v in sectors.values())
    print(f"  ✅ 沪深300+中证500: {total}只, {len(sectors)}个行业")
    return sectors


# ============================================================
# 来源3: 科创50 (akshare)
# ============================================================

def fetch_kc50_constituents():
    """获取科创50成分股"""
    print("\n📡 来源3: 获取科创50成分股...")
    try:
        import akshare as ak
        df = ak.index_stock_cons(symbol='000688')
        col = '品种代码' if '品种代码' in df.columns else df.columns[0]
        name_col = '品种名称' if '品种名称' in df.columns else (df.columns[1] if len(df.columns) > 1 else None)

        stocks = []
        for _, row in df.iterrows():
            code = str(row[col]).zfill(6)
            name = str(row[name_col]) if name_col else ''
            stocks.append({'code': code, 'name': name})

        print(f"  ✅ 科创50: {len(stocks)}只")
        return stocks
    except Exception as e:
        print(f"  ⚠️ akshare获取失败: {e}, 使用硬编码回退")
        from src.utils.pool_loader import _KC50_FALLBACK
        return [{'code': c, 'name': ''} for c in sorted(_KC50_FALLBACK)]


# ============================================================
# 来源4: 创业板300 = 创业板指(399006, 100只) + 创业板200(399019, 200只)
# ============================================================

def fetch_chinext300():
    """获取创业板指(100只) + 创业板200(200只) = 300只，两指数不重叠"""
    print(f"\n📡 来源4: 创业板指(399006)+创业板200(399019) = 300只...")
    import akshare as ak

    all_stocks = []
    seen = set()

    for idx_code, idx_name in [('399006', '创业板指'), ('399019', '创业板200')]:
        try:
            df = ak.index_stock_cons(symbol=idx_code)
            if df is not None and not df.empty:
                col_code = '品种代码' if '品种代码' in df.columns else df.columns[0]
                col_name = '品种名称' if '品种名称' in df.columns else df.columns[1]
                count = 0
                for _, row in df.iterrows():
                    code = str(row[col_code]).strip().zfill(6)
                    if code not in seen:
                        name = str(row[col_name]).strip()
                        all_stocks.append({'code': code, 'name': name})
                        seen.add(code)
                        count += 1
                print(f"  {idx_name}({idx_code}): {count}只")
        except Exception as e:
            print(f"  ⚠️ {idx_name}({idx_code})获取失败: {e}")

    if all_stocks:
        print(f"  ✅ 创业板合计: {len(all_stocks)}只")
        return all_stocks

    # 回退: 从现有池子中保留创业板数据
    print("  尝试从现有池子中保留创业板...")
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                old_pool = json.load(f)
            old_stocks = old_pool.get('stocks', {})
            fallback = []
            for group, stock_list in old_stocks.items():
                for s in stock_list:
                    code = s.get('code', '')
                    if code.startswith('300') or code.startswith('301') or code.startswith('302'):
                        name = s.get('name', '')
                        if 'ST' not in name.upper() and '退' not in name:
                            fallback.append({'code': code, 'name': name})
            if fallback:
                print(f"  ✅ 从旧池子回退: {len(fallback)}只创业板")
                return fallback
        except Exception:
            pass
    print("  ⚠️ 创业板获取失败，无回退可用")
    return []


# ============================================================
# 来源5: 创业板活跃补充（未入指数的新股/活跃股）
# ============================================================

def fetch_chinext_active_supplement(exclude_codes: set, max_count: int = 100):
    """获取未入指数但活跃的创业板股票，按日均成交额排序。多源降级。"""
    print(f"\n📡 来源5: 创业板活跃补充 (非指数成分, 日均成交额活跃, TOP{max_count})...")
    import akshare as ak

    df = None

    # 方案1: 东方财富创业板实时行情（交易日最佳）
    for attempt in range(3):
        try:
            df = ak.stock_cy_a_spot_em()
            if df is not None and not df.empty:
                print(f"  东方财富创业板行情: {len(df)}只")
                break
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                print(f"  ⚠️ 东方财富接口失败: {e}")

    # 方案2: 全市场行情中筛选创业板
    if df is None or df.empty:
        try:
            all_spot = ak.stock_zh_a_spot_em()
            if all_spot is not None and not all_spot.empty:
                col = '代码' if '代码' in all_spot.columns else all_spot.columns[0]
                df = all_spot[all_spot[col].astype(str).str.match(r'^30[0-9]')]
                if not df.empty:
                    print(f"  全市场筛选创业板: {len(df)}只")
        except Exception as e:
            print(f"  ⚠️ 全市场行情也失败: {e}")

    # 方案3: 从K线缓存推断活跃股（读取已有parquet缓存）
    if df is None or df.empty:
        cache_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'mydate', 'kline_cache')
        if os.path.exists(cache_dir):
            import glob
            parquet_files = glob.glob(os.path.join(cache_dir, '30*.parquet'))
            active_from_cache = []
            for pf in parquet_files:
                try:
                    import pandas as pd
                    code = os.path.basename(pf).replace('.parquet', '').split('_')[0]
                    if code in exclude_codes:
                        continue
                    kdf = pd.read_parquet(pf)
                    if len(kdf) >= 5 and 'amount' in kdf.columns:
                        avg_amount = kdf['amount'].tail(5).mean()
                        active_from_cache.append({'code': code, 'name': '', 'amount': avg_amount})
                except Exception:
                    pass
            if active_from_cache:
                active_from_cache.sort(key=lambda x: x['amount'], reverse=True)
                result = active_from_cache[:max_count]
                print(f"  ✅ 从K线缓存推断: {len(result)}只活跃创业板")
                return result
        print("  ⚠️ 所有数据源不可用, 跳过活跃补充")
        return []

    col_code = '代码' if '代码' in df.columns else df.columns[0]
    col_name = '名称' if '名称' in df.columns else df.columns[1]
    col_amount = '成交额' if '成交额' in df.columns else None

    stocks = []
    for _, row in df.iterrows():
        code = str(row[col_code]).strip().zfill(6)
        if code in exclude_codes:
            continue
        name = str(row[col_name]).strip()
        if 'ST' in name.upper() or '退' in name:
            continue
        amount = 0
        if col_amount:
            try:
                amount = float(row[col_amount])
            except (ValueError, TypeError):
                amount = 0
        stocks.append({'code': code, 'name': name, 'amount': amount})

    stocks.sort(key=lambda x: x['amount'], reverse=True)
    result = stocks[:max_count]
    print(f"  ✅ 创业板活跃补充: {len(result)}只 (从{len(stocks)}只非指数成分中按成交额选取)")
    return result


# ============================================================
# 合并构建综合池
# ============================================================

def build_pool(dry_run: bool = False, **kwargs):
    """构建综合股票池"""
    print(f"\n{'='*60}")
    print(f"  🔄 构建综合股票池 (5源)")
    print(f"{'='*60}")

    all_stocks = []
    seen_codes = set()

    # 来源1+2: 沪深300 + 中证500
    index_sectors = fetch_index_constituents_bs()
    for sector, stocks in index_sectors.items():
        for s in stocks:
            if s['code'] not in seen_codes:
                all_stocks.append({
                    'code': s['code'],
                    'name': s['name'],
                    'sector': sector,
                    'source': 'hs300_zz500',
                })
                seen_codes.add(s['code'])
    hs_count = len(all_stocks)
    print(f"  来源1+2 (沪深300+中证500): {hs_count}只")

    # 来源3: 科创50
    kc50_stocks = fetch_kc50_constituents()
    kc50_count = 0
    for s in kc50_stocks:
        if s['code'] not in seen_codes:
            all_stocks.append({
                'code': s['code'],
                'name': s['name'],
                'sector': '科创50',
                'source': 'kc50',
            })
            seen_codes.add(s['code'])
            kc50_count += 1
    print(f"  来源3 (科创50): +{kc50_count}只 (去重后)")

    # 来源4: 创业板300 = 创业板指(100) + 创业板200(200)
    chinext_stocks = fetch_chinext300()
    chinext_count = 0
    for s in chinext_stocks:
        if s['code'] not in seen_codes:
            all_stocks.append({
                'code': s['code'],
                'name': s['name'],
                'sector': '创业板300',
                'source': 'chinext300',
            })
            seen_codes.add(s['code'])
            chinext_count += 1
    print(f"  来源4 (创业板300): +{chinext_count}只 (去重后)")

    # 来源5: 创业板活跃补充（未入指数的新股/活跃股）
    chinext_active = fetch_chinext_active_supplement(exclude_codes=seen_codes, max_count=100)
    chinext_active_count = 0
    for s in chinext_active:
        if s['code'] not in seen_codes:
            all_stocks.append({
                'code': s['code'],
                'name': s['name'],
                'sector': '创业板活跃',
                'source': 'chinext_active',
            })
            seen_codes.add(s['code'])
            chinext_active_count += 1
    print(f"  来源5 (创业板活跃补充): +{chinext_active_count}只 (去重后)")

    total_stocks = len(all_stocks)
    print(f"\n  📊 合计个股: {total_stocks}只")

    etf_list = []  # ETF不参与每日推荐，独立存放在etf_pool.json

    # 构建输出
    output = {
        'description': '综合股票池(沪深300+中证500+科创50+创业板300+创业板活跃补充)',
        'created_at': datetime.now().strftime('%Y-%m-%d'),
        'filter_rules': {
            'sources': '沪深300 + 中证500 + 科创50 + 创业板指(399006) + 创业板200(399019) + 创业板活跃补充(成交额TOP100)',
            'exclude_st': True,
        },
        'stats': {
            'total_stocks': total_stocks,
            'total_etf': len(etf_list),
            'total': total_stocks + len(etf_list),
            'breakdown': {
                'hs300_zz500': hs_count,
                'kc50': kc50_count,
                'chinext': chinext_count,
            },
        },
        'stocks': {},
        'etf': {},
    }

    # 按板块分组
    for s in all_stocks:
        sector = s['sector']
        output['stocks'].setdefault(sector, [])
        entry = {'code': s['code'], 'name': s['name']}
        output['stocks'][sector].append(entry)

    # ETF分组
    for e in etf_list:
        cat = e['sector']
        output['etf'].setdefault(cat, [])
        output['etf'][cat].append({
            'code': e['code'],
            'name': e['name'],
            'track': e.get('track', ''),
        })

    # 统计输出
    print(f"\n{'='*60}")
    print(f"  📊 最终结果:")
    print(f"    个股: {total_stocks}只 ({len(output['stocks'])}个板块)")
    print(f"    ETF:  {len(etf_list)}只")
    print(f"    合计: {total_stocks + len(etf_list)}只")
    print(f"\n  板块分布 (前15):")
    sector_counts = sorted(
        [(k, len(v)) for k, v in output['stocks'].items()],
        key=lambda x: x[1], reverse=True
    )
    for sector, count in sector_counts[:15]:
        print(f"    {sector[:25]:25s}: {count:>3}只")
    if len(sector_counts) > 15:
        print(f"    ... 还有{len(sector_counts)-15}个板块")
    print(f"{'='*60}")

    if dry_run:
        print("\n  ⚠️ dry-run模式，不保存文件")
        return output

    # 保存
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  ✅ 已保存: {OUTPUT_FILE}")

    return output


# ============================================================
# 验证
# ============================================================

def verify():
    """验证综合股票池"""
    if not os.path.exists(OUTPUT_FILE):
        print("❌ 股票池文件不存在")
        return

    with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
        pool = json.load(f)

    all_codes = []
    for sector, stocks in pool.get('stocks', {}).items():
        for s in stocks:
            all_codes.append((s['code'], s.get('name', ''), sector))

    print(f"验证 {len(all_codes)} 只标的...")
    session = _eastmoney_session()
    ok = fail = 0

    for i, (code, name, sector) in enumerate(all_codes):
        market = '1' if code.startswith(('5', '6')) else '0'
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
            time.sleep(0.15)
        except Exception:
            fail += 1

        if (i + 1) % 100 == 0:
            print(f"  ... {i+1}/{len(all_codes)}, 成功{ok}, 失败{fail}")

    print(f"\n总计: {len(all_codes)}, 成功: {ok}, 失败: {fail}")
    session.close()


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='股票池刷新工具 v2')
    parser.add_argument('--verify', action='store_true', help='验证股票池数据')
    parser.add_argument('--dry-run', action='store_true', help='只显示统计不保存')
    args = parser.parse_args()

    if args.verify:
        verify()
    else:
        build_pool(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
