#!/usr/bin/env python3
"""
ETF 数据预热缓存工具

功能：
1. 从持仓文件读取所有 ETF
2. 尝试多个数据源获取 ETF 历史数据
3. 保存到本地缓存（mycache/etf_kline/）
4. 供持仓分析和单股分析使用

用法：
    python3 tools/data/prefetch_etf_cache.py
    python3 tools/data/prefetch_etf_cache.py --codes 512480,159770,510300
"""

import sys
import os
import json
import pandas as pd
from datetime import datetime, timedelta
import argparse
import time
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from src.data.fetchers.market_data import MarketData
import akshare as ak

CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'mycache', 'etf_kline')


def _normalize_etf_df(df, min_bars=60):
    """统一 ETF DataFrame 格式"""
    if df is None or df.empty or len(df) < min_bars:
        return None
    col_map = {'日期': 'date', '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume'}
    rename = {k: v for k, v in col_map.items() if k in df.columns}
    df = df.rename(columns=rename)
    if 'date' not in df.columns:
        return None
    required = ['open', 'high', 'low', 'close', 'volume']
    for c in required:
        if c not in df.columns:
            return None
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df[['date'] + required].dropna(subset=['close', 'date'])
    df = df.sort_values('date').reset_index(drop=True)
    return df if len(df) >= min_bars else None


def fetch_etf_multi_source(code, max_retries_per_source=2):
    """
    多源获取 ETF 日线数据
    源顺序：MarketData(push2his) -> akshare新浪 -> akshare网易 -> akshare东方财富
    """
    end_date = pd.Timestamp.now().strftime('%Y%m%d')
    start_date = "20180101"
    common_kw = dict(period="daily", start_date=start_date, end_date=end_date, adjust="")

    # 源1：MarketData (push2his) - 最稳定
    print(f"  尝试 MarketData(push2his)...")
    try:
        md = MarketData(use_cache=False)
        df = md.get_history(code, days=800)
        out = _normalize_etf_df(df, min_bars=60)
        if out is not None:
            print(f"  ✅ MarketData 获取成功: {len(out)} 条")
            return out
    except Exception as e:
        print(f"  ⚠️ MarketData 失败: {str(e)[:60]}")

    # 源2-4：akshare 多源
    sources = [
        ('新浪', getattr(ak, 'fund_etf_hist_sina', None), {'symbol': code}),
        ('网易', getattr(ak, 'fund_etf_hist_163', None), {'symbol': code, **common_kw}),
        ('东方财富', ak.fund_etf_hist_em, {'symbol': code, **common_kw}),
    ]

    for source_name, fetch_func, kwargs in sources:
        if fetch_func is None:
            continue
        print(f"  尝试 akshare {source_name}...")
        for attempt in range(max_retries_per_source):
            try:
                time.sleep(random.uniform(1, 3))
                df = fetch_func(**kwargs)
                out = _normalize_etf_df(df, min_bars=60)
                if out is not None:
                    print(f"  ✅ akshare {source_name} 获取成功: {len(out)} 条")
                    return out
                print(f"  ⚠️ {source_name} 返回空或数据不足")
                break
            except Exception as e:
                print(f"  ⚠️ {source_name} 第 {attempt+1} 次失败: {str(e)[:60]}")
                if attempt < max_retries_per_source - 1:
                    time.sleep(random.uniform(3, 6))

    print(f"  ❌ 所有数据源均失败")
    return None


def save_etf_cache(code, df):
    """保存 ETF 数据到本地缓存"""
    if df is None or len(df) < 60:
        return False
    
    os.makedirs(CACHE_DIR, exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')
    cache_file = os.path.join(CACHE_DIR, f"{code}_{today}.csv")
    
    try:
        df.to_csv(cache_file, index=False)
        print(f"  💾 已保存到: {cache_file}")
        return True
    except Exception as e:
        print(f"  ⚠️ 保存失败: {e}")
        return False


def load_portfolio_etfs():
    """从持仓文件读取所有 ETF 代码"""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    portfolio_path = os.path.join(base_dir, 'mydate', 'my_portfolio.json')
    if not os.path.exists(portfolio_path):
        portfolio_path = os.path.join(base_dir, 'data', 'my_portfolio.json')
    
    if not os.path.exists(portfolio_path):
        return []
    
    with open(portfolio_path, 'r') as f:
        portfolio = json.load(f)
    
    etf_codes = []
    for holding in portfolio.get('holdings', []):
        code = holding.get('code', '')
        shares = holding.get('shares', 0)
        if shares > 0 and 'comment' not in holding:
            # 判断是否为 ETF（5/159 开头且 6 位数）
            if (code.startswith('5') or code.startswith('159')) and len(code) == 6:
                etf_codes.append((code, holding.get('name', code)))
    
    return etf_codes


def main():
    parser = argparse.ArgumentParser(description='ETF 数据预热缓存工具')
    parser.add_argument('--codes', type=str, help='指定 ETF 代码（逗号分隔），如：512480,159770')
    parser.add_argument('--from-portfolio', action='store_true', help='从持仓文件读取 ETF')
    args = parser.parse_args()
    
    print("=" * 80)
    print("📦 ETF 数据预热缓存工具")
    print("=" * 80)
    print(f"缓存目录: {CACHE_DIR}\n")
    
    # 确定要获取的 ETF 列表
    etf_list = []
    if args.codes:
        codes = [c.strip() for c in args.codes.split(',')]
        etf_list = [(code, code) for code in codes]
    elif args.from_portfolio:
        etf_list = load_portfolio_etfs()
        if not etf_list:
            print("❌ 持仓文件中没有找到 ETF")
            return
    else:
        # 默认：从持仓读取
        etf_list = load_portfolio_etfs()
        if not etf_list:
            print("⚠️  持仓文件中没有 ETF，请使用 --codes 指定")
            return
    
    print(f"📋 待获取 ETF 列表（{len(etf_list)} 个）:")
    for code, name in etf_list:
        print(f"  - {code} {name}")
    print()
    
    # 逐个获取并缓存
    success_count = 0
    for i, (code, name) in enumerate(etf_list):
        print(f"[{i+1}/{len(etf_list)}] 正在获取 {code} {name}...")
        
        df = fetch_etf_multi_source(code)
        if df is not None and len(df) >= 60:
            if save_etf_cache(code, df):
                success_count += 1
                print(f"  ✅ 成功: {len(df)} 条数据")
        else:
            print(f"  ❌ 失败: 无法获取数据")
        
        print()
        
        # 避免请求过快
        if i < len(etf_list) - 1:
            time.sleep(random.uniform(2, 5))
    
    print("=" * 80)
    print(f"✅ 预热完成: {success_count}/{len(etf_list)} 个 ETF 成功缓存")
    print("=" * 80)


if __name__ == '__main__':
    main()
