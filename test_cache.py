#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试基本面缓存加载"""

import json
import os

def load_fundamental_cache():
    """加载基本面缓存"""
    cache_file = os.path.join('mydate', 'market_fundamental_cache.json')
    print(f"缓存文件: {cache_file}")
    print(f"是否存在: {os.path.exists(cache_file)}")
    
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            all_data = data.get('all_data', {})
            print(f"✅ 加载成功: {len(all_data)}只股票")
            
            # 测试几只股票
            test_codes = ['000001', '600030', '300750']
            for code in test_codes:
                if code in all_data:
                    print(f"  {code}: PE={all_data[code].get('pe_ttm')}, 市值={all_data[code].get('market_cap_yi')}亿")
            
            return all_data
        except Exception as e:
            print(f"❌ 加载失败: {e}")
    return {}

if __name__ == '__main__':
    cache = load_fundamental_cache()
    print(f"\n总计: {len(cache)}只")
