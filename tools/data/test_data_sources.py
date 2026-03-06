#!/usr/bin/env python3
"""
数据源测试工具

功能：
1. 测试所有配置的数据源是否可用
2. 测试股票和 ETF 数据获取
3. 显示熔断状态和缓存情况

用法：
    python3 tools/data/test_data_sources.py
    python3 tools/data/test_data_sources.py --stock 600118 --etf 512480
"""

import sys
import os
import argparse
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from src.data.provider.data_provider import get_default_kline_provider, reset_default_kline_provider
from src.data.fetchers.data_prefetch import _circuit_state
import baostock as bs


def reset_circuit():
    """重置熔断状态"""
    for k in _circuit_state:
        _circuit_state[k] = [0, 0.0]
    print("✅ 熔断状态已重置\n")


def show_circuit_status():
    """显示熔断状态"""
    print("=" * 80)
    print("📊 数据源熔断状态")
    print("=" * 80)
    has_circuit = False
    for source, (fail_count, last_fail_time) in _circuit_state.items():
        if fail_count > 0:
            has_circuit = True
            status = "🔴 熔断中" if fail_count >= 3 else f"⚠️  失败 {fail_count} 次"
            if last_fail_time > 0:
                fail_time = datetime.fromtimestamp(last_fail_time).strftime('%H:%M:%S')
                print(f"  {source:15s} {status:15s} (最后失败: {fail_time})")
            else:
                print(f"  {source:15s} {status}")
    
    if not has_circuit:
        print("  ✅ 所有数据源正常")
    print()


def test_stock(code: str):
    """测试股票数据获取"""
    print(f"📈 测试股票 {code}...")
    provider = get_default_kline_provider()
    
    try:
        df = provider.get_kline(code, datalen=800, min_bars=60, is_etf=False)
        if len(df) >= 60:
            source = df['data_source'].iloc[0] if 'data_source' in df.columns else 'unknown'
            date_range = f"{df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')}"
            print(f"  ✅ 成功: {len(df)} 条，来源: {source}")
            print(f"     日期范围: {date_range}")
            return True
        else:
            print(f"  ❌ 失败: 数据不足（{len(df)} 条）")
            return False
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        return False


def test_etf(code: str):
    """测试 ETF 数据获取"""
    print(f"📊 测试 ETF {code}...")
    provider = get_default_kline_provider()
    
    try:
        df = provider.get_kline(code, datalen=800, min_bars=60, is_etf=True)
        if len(df) >= 60:
            source = df['data_source'].iloc[0] if 'data_source' in df.columns else 'unknown'
            date_range = f"{df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')}"
            print(f"  ✅ 成功: {len(df)} 条，来源: {source}")
            print(f"     日期范围: {date_range}")
            return True
        else:
            print(f"  ❌ 失败: 数据不足（{len(df)} 条）")
            return False
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        return False


def check_cache():
    """检查本地缓存情况"""
    import glob
    
    print("=" * 80)
    print("📦 本地缓存情况")
    print("=" * 80)
    
    cache_dirs = [
        'mycache/etf_kline',
        'mydate/backtest_kline',
        'mycache/market_data',
    ]
    
    for cache_dir in cache_dirs:
        if os.path.exists(cache_dir):
            files = glob.glob(f"{cache_dir}/*.csv") + glob.glob(f"{cache_dir}/*.parquet")
            print(f"\n📁 {cache_dir}: {len(files)} 个文件")
            if files:
                # 显示最近的 5 个文件
                files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                for f in files[:5]:
                    mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime('%Y-%m-%d %H:%M')
                    size = os.path.getsize(f) / 1024
                    print(f"  - {os.path.basename(f):30s} {size:6.1f}KB  ({mtime})")
                if len(files) > 5:
                    print(f"  ... 还有 {len(files) - 5} 个文件")
        else:
            print(f"\n📁 {cache_dir}: 目录不存在")
    print()


def main():
    parser = argparse.ArgumentParser(description='数据源测试工具')
    parser.add_argument('--stock', type=str, help='测试股票代码，如：600118')
    parser.add_argument('--etf', type=str, help='测试 ETF 代码，如：512480')
    parser.add_argument('--reset-circuit', action='store_true', help='重置熔断状态')
    parser.add_argument('--check-cache', action='store_true', help='检查本地缓存')
    args = parser.parse_args()
    
    print("=" * 80)
    print("🔧 数据源测试工具")
    print("=" * 80)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # 登录 baostock
    bs.login()
    
    # 重置熔断
    if args.reset_circuit:
        reset_circuit()
        reset_default_kline_provider()
    
    # 检查缓存
    if args.check_cache:
        check_cache()
    
    # 显示熔断状态
    show_circuit_status()
    
    # 测试股票
    stock_codes = []
    if args.stock:
        stock_codes = [args.stock]
    else:
        stock_codes = ['600118', '601099', '002281']  # 默认测试持仓中的股票
    
    print("=" * 80)
    print("📈 股票数据获取测试")
    print("=" * 80)
    success_count = 0
    for code in stock_codes:
        if test_stock(code):
            success_count += 1
        print()
    print(f"股票测试结果: {success_count}/{len(stock_codes)} 成功\n")
    
    # 测试 ETF
    etf_codes = []
    if args.etf:
        etf_codes = [args.etf]
    else:
        etf_codes = ['512480', '159770']  # 默认测试持仓中的 ETF
    
    print("=" * 80)
    print("📊 ETF 数据获取测试")
    print("=" * 80)
    success_count = 0
    for code in etf_codes:
        if test_etf(code):
            success_count += 1
        print()
    print(f"ETF 测试结果: {success_count}/{len(etf_codes)} 成功\n")
    
    # 最终熔断状态
    show_circuit_status()
    
    bs.logout()
    
    print("=" * 80)
    print("✅ 测试完成")
    print("=" * 80)


if __name__ == '__main__':
    main()
