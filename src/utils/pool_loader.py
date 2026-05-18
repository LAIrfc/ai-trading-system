#!/usr/bin/env python3
"""
通用股票池加载器

支持两种格式:
  1. 综合格式 (stock_pool_all.json): stocks 分区（沪深300+中证500+科创50+创业板300+创业板活跃）
  2. ETF格式 (etf_pool.json): categories分区

用法:
  from src.utils.pool_loader import load_pool
  stocks = load_pool('mydate/stock_pool_all.json')
  stocks = load_pool('mydate/stock_pool_all.json', max_count=500)
"""

import json
import logging
import os
import random

logger = logging.getLogger(__name__)

# 科创50成分股（000688指数），动态获取失败时的硬编码回退
_KC50_FALLBACK = frozenset([
    '688008', '688009', '688012', '688027', '688036', '688041', '688047',
    '688065', '688072', '688082', '688099', '688111', '688114', '688120',
    '688122', '688126', '688169', '688183', '688187', '688188', '688213',
    '688220', '688223', '688234', '688249', '688256', '688271', '688278',
    '688297', '688303', '688349', '688361', '688375', '688396', '688469',
    '688472', '688506', '688521', '688525', '688538', '688568', '688578',
    '688599', '688608', '688617', '688702', '688728', '688777', '688981',
    '689009',
])


def _get_kc50_codes() -> frozenset:
    """获取科创50成分股代码集合，失败时用硬编码回退"""
    try:
        import akshare as ak
        df = ak.index_stock_cons(symbol='000688')
        col = '品种代码' if '品种代码' in df.columns else df.columns[0]
        codes = frozenset(df[col].astype(str).tolist())
        if len(codes) >= 40:
            return codes
    except Exception:
        pass
    return _KC50_FALLBACK


def load_pool(pool_file: str,
              max_count: int = 0,
              sector: str = None,
              include_etf: bool = False,
              star_filter: str = 'all') -> list:
    """
    通用股票池加载器，自动识别格式
    
    Args:
        pool_file: 股票池JSON文件路径
        max_count: 最大股票数量（0=不限制）
        sector: 筛选特定板块（模糊匹配）
        include_etf: 是否包含ETF（仅对综合格式有效）
        star_filter: 科创板过滤策略: 'kc50'=只保留科创50成分股, 'all'=全部保留, 'none'=完全排除
                     注：新版池子(v2)已在构建时只纳入科创50，默认'all'即可
    
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

    # 格式2: sectors格式 (兼容旧格式)
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

    # 科创板过滤：默认只保留科创50成分股
    if star_filter != 'all':
        before_count = len(stocks)
        if star_filter == 'none':
            stocks = [s for s in stocks if not s['code'].startswith('688')]
        elif star_filter == 'kc50':
            kc50_codes = _get_kc50_codes()
            stocks = [s for s in stocks if not s['code'].startswith('688') or s['code'] in kc50_codes]
        filtered = before_count - len(stocks)
        if filtered > 0:
            logger.info(f"科创板过滤({star_filter}): 移除{filtered}只, 保留{len([s for s in stocks if s['code'].startswith('688')])}只科创板股票")

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

    # 先在板块内做可复现打散，避免长期固定命中“每个板块前几只”的顺序偏置
    rng = random.Random(20260423)
    selected = []
    for sector_name, sector_stocks in sector_groups.items():
        sector_stocks = list(sector_stocks)
        rng.shuffle(sector_stocks)
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
