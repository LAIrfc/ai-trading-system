#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查缓存覆盖率"""

import json
import os

# 加载股票池
with open('mydate/stock_pool_all.json', 'r', encoding='utf-8') as f:
    pool = json.load(f)

pool_codes = set()
for sector_stocks in pool.get('stocks', {}).values():
    for stock in sector_stocks:
        code = stock.get('code') or stock.get('symbol', '')
        if code:
            pool_codes.add(code)

print(f"股票池: {len(pool_codes)}只")

# 检查K线缓存
kline_dir = 'mydate/backtest_kline'
if os.path.exists(kline_dir):
    cached_kline = {f[:-8] for f in os.listdir(kline_dir) if f.endswith('.parquet')}
    print(f"K线缓存: {len(cached_kline)}只")
    
    missing_kline = pool_codes - cached_kline
    print(f"缺少K线缓存: {len(missing_kline)}只")
    if len(missing_kline) <= 20:
        print(f"  缺少的: {sorted(missing_kline)}")
else:
    print("K线缓存目录不存在")

# 检查基本面缓存
fund_file = 'mydate/market_fundamental_cache.json'
if os.path.exists(fund_file):
    with open(fund_file, 'r', encoding='utf-8') as f:
        fund_data = json.load(f)
    cached_fund = set(fund_data.get('all_data', {}).keys())
    print(f"基本面缓存: {len(cached_fund)}只")
    
    missing_fund = pool_codes - cached_fund
    print(f"缺少基本面缓存: {len(missing_fund)}只")
    if len(missing_fund) <= 20:
        print(f"  缺少的: {sorted(missing_fund)}")
else:
    print("基本面缓存不存在")
