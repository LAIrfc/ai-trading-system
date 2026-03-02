#!/usr/bin/env python3
"""
通用股票池加载器

支持三种格式:
  1. sectors格式 (stock_pool.json / stock_pool_600.json)
  2. 综合格式 (stock_pool_all.json): stocks + etf 分区
  3. ETF格式 (etf_pool.json): categories分区

用法:
  from src.utils.pool_loader import load_pool
  stocks = load_pool('data/stock_pool_all.json')
  stocks = load_pool('data/stock_pool_all.json', include_etf=True, max_count=500)
"""

import json
import os


def load_pool(pool_file: str,
              max_count: int = 0,
              sector: str = None,
              include_etf: bool = False) -> list:
    """
    通用股票池加载器，自动识别格式
    
    Args:
        pool_file: 股票池JSON文件路径
        max_count: 最大股票数量（0=不限制）
        sector: 筛选特定板块（模糊匹配）
        include_etf: 是否包含ETF（仅对综合格式有效）
    
    Returns:
        list[dict]: [{'code': '600030', 'name': '中信证券', 'sector': '证券', ...}, ...]
    """
    with open(pool_file, 'r', encoding='utf-8') as f:
        pool = json.load(f)

    stocks = []

    # 格式1: 综合格式 (stock_pool_all.json)
    if 'stocks' in pool and isinstance(pool['stocks'], dict):
        for sec_name, sec_stocks in pool['stocks'].items():
            if sector and sector not in sec_name:
                continue
            for s in sec_stocks:
                stocks.append({
                    'code': s['code'],
                    'name': s.get('name', ''),
                    'sector': sec_name,
                    'pe_ttm': s.get('pe_ttm'),
                    'market_cap_yi': s.get('market_cap_yi'),
                    'type': 'stock',
                })

        # 加载ETF
        if include_etf and 'etf' in pool:
            for cat_name, etfs in pool['etf'].items():
                if sector and sector not in cat_name:
                    continue
                for e in etfs:
                    stocks.append({
                        'code': e['code'],
                        'name': e.get('name', ''),
                        'sector': cat_name,
                        'track': e.get('track', ''),
                        'type': 'ETF',
                    })

    # 格式2: sectors格式 (stock_pool.json / stock_pool_600.json)
    elif 'sectors' in pool:
        for sec_name, sec_stocks in pool['sectors'].items():
            if sector and sector not in sec_name:
                continue
            for s in sec_stocks:
                stocks.append({
                    'code': s['code'],
                    'name': s.get('name', ''),
                    'sector': sec_name,
                    'type': 'stock',
                })

    # 格式3: ETF格式 (etf_pool.json)
    elif 'categories' in pool:
        for cat_name, etfs in pool['categories'].items():
            if sector and sector not in cat_name:
                continue
            for e in etfs:
                stocks.append({
                    'code': e['code'],
                    'name': e.get('name', ''),
                    'sector': cat_name,
                    'track': e.get('track', ''),
                    'type': 'ETF',
                })

    # 限制数量（按板块均匀分配）
    if max_count > 0 and len(stocks) > max_count:
        stocks = _balanced_select(stocks, max_count)

    return stocks


def _balanced_select(stocks: list, max_count: int) -> list:
    """按板块均匀分配选取"""
    from collections import defaultdict
    sector_groups = defaultdict(list)
    for s in stocks:
        sector_groups[s.get('sector', '未知')].append(s)

    num_sectors = len(sector_groups)
    per_sector = max(1, max_count // num_sectors)
    remainder = max_count - per_sector * num_sectors

    selected = []
    for sector_name, sector_stocks in sector_groups.items():
        quota = per_sector + (1 if remainder > 0 else 0)
        if remainder > 0:
            remainder -= 1
        selected.extend(sector_stocks[:quota])

    return selected[:max_count]


def get_pool_info(pool_file: str) -> dict:
    """获取股票池基本信息"""
    with open(pool_file, 'r', encoding='utf-8') as f:
        pool = json.load(f)

    info = {
        'file': pool_file,
        'description': pool.get('description', ''),
        'created_at': pool.get('created_at', pool.get('date', '')),
    }

    if 'stocks' in pool:
        info['stock_count'] = sum(len(v) for v in pool['stocks'].values())
        info['stock_sectors'] = len(pool['stocks'])
    if 'etf' in pool:
        info['etf_count'] = sum(len(v) for v in pool['etf'].values())
        info['etf_categories'] = len(pool['etf'])
    if 'sectors' in pool:
        info['total'] = sum(len(v) for v in pool['sectors'].values())
        info['sectors'] = len(pool['sectors'])
    if 'categories' in pool:
        info['total'] = sum(len(v) for v in pool['categories'].values())
        info['categories'] = len(pool['categories'])
    if 'stats' in pool:
        info.update(pool['stats'])
    if 'filter_rules' in pool:
        info['filter_rules'] = pool['filter_rules']

    return info
