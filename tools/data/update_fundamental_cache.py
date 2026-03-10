#!/usr/bin/env python3
"""
基本面数据缓存更新工具 - 多数据源版本

使用多个数据源获取PE/PB/市值等基本面数据：
1. 新浪财经接口（主力，稳定快速）
2. 东方财富接口（备用）
3. akshare接口（备用）
4. baostock接口（最后备用）

用法:
  python3 tools/data/update_fundamental_cache.py                # 更新所有股票池股票
  python3 tools/data/update_fundamental_cache.py --codes 600030,000001  # 更新指定股票
  python3 tools/data/update_fundamental_cache.py --test         # 测试模式（仅10只）
"""

import sys
import os
import json
import time
import argparse
import requests
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(base_dir, 'mydate')
CACHE_FILE = os.path.join(DATA_DIR, 'market_fundamental_cache.json')
POOL_FILE = os.path.join(DATA_DIR, 'stock_pool_all.json')


def fetch_fundamental_sina(codes: List[str], timeout: int = 10) -> Dict[str, dict]:
    """
    使用新浪财经接口批量获取基本面数据
    接口: http://hq.sinajs.cn/list=sh600000,sz000001
    返回: {code: {name, pe_ttm, pb, market_cap_yi, is_st}}
    """
    if not codes:
        return {}
    
    results = {}
    batch_size = 50  # 新浪接口支持批量，每次50只
    
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        symbols = []
        for code in batch:
            prefix = 'sh' if code.startswith(('5', '6')) else 'sz'
            symbols.append(f'{prefix}{code}')
        
        try:
            list_param = ",".join(symbols)
            url = f"http://hq.sinajs.cn/list={list_param}"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
            
            if not resp.text:
                continue
            
            # 解析新浪返回的数据
            lines = resp.text.strip().split('\n')
            for line in lines:
                if 'hq_str_' not in line:
                    continue
                
                # 格式: var hq_str_sh600000="浦发银行,9.12,9.13,...";
                parts = line.split('"')
                if len(parts) < 2:
                    continue
                
                symbol = line.split('_')[-1].split('=')[0]
                code = symbol[2:]  # 去掉sh/sz前缀
                
                data_str = parts[1]
                fields = data_str.split(',')
                
                if len(fields) < 10:
                    continue
                
                try:
                    name = fields[0]
                    price = float(fields[3]) if fields[3] else 0  # 当前价
                    
                    # 新浪接口不直接提供PE/PB，需要从其他字段计算或使用备用接口
                    # 这里先标记为需要从其他源获取
                    results[code] = {
                        'name': name,
                        'price': price,
                        'pe_ttm': None,
                        'pb': None,
                        'market_cap_yi': None,
                        'is_st': 'ST' in name or '*ST' in name or '退' in name,
                        'source': 'sina_partial',
                    }
                except (ValueError, IndexError):
                    continue
        
        except Exception as e:
            print(f"  ⚠️ 新浪接口批量请求失败: {e}")
            continue
        
        time.sleep(0.2)  # 批量请求间隔
    
    return results


def fetch_fundamental_eastmoney_single(code: str, timeout: int = 8) -> Optional[dict]:
    """
    使用东方财富接口获取单只股票基本面数据
    接口: http://push2.eastmoney.com/api/qt/stock/get
    返回: {name, pe_ttm, pb, market_cap_yi, is_st}
    """
    market = '1' if code.startswith(('5', '6')) else '0'
    try:
        url = 'http://push2.eastmoney.com/api/qt/stock/get'
        params = {
            'secid': f'{market}.{code}',
            'fields': 'f57,f58,f162,f167,f116,f170',  # f162=PE, f167=PB, f116=总市值
            'fltt': '2',
        }
        resp = requests.get(url, params=params, timeout=timeout)
        d = resp.json().get('data', {})
        
        if not d:
            return None
        
        name = str(d.get('f58', ''))
        pe_raw = d.get('f162', '-')
        pb_raw = d.get('f167', '-')
        cap_raw = d.get('f116', 0)
        
        is_st = 'ST' in name or '*ST' in name or '退' in name
        
        try:
            pe_val = float(pe_raw) if pe_raw and pe_raw != '-' else None
        except (ValueError, TypeError):
            pe_val = None
        
        try:
            pb_val = float(pb_raw) if pb_raw and pb_raw != '-' else None
        except (ValueError, TypeError):
            pb_val = None
        
        try:
            cap_yi = round(float(cap_raw) / 1e8, 1) if cap_raw and cap_raw != '-' and cap_raw != 0 else None
        except (ValueError, TypeError):
            cap_yi = None
        
        return {
            'name': name,
            'pe_ttm': pe_val,
            'pb': pb_val,
            'market_cap_yi': cap_yi,
            'is_st': is_st,
            'source': 'eastmoney',
        }
    except Exception as e:
        return None


def fetch_fundamental_akshare(code: str) -> Optional[dict]:
    """
    使用akshare获取基本面数据
    """
    try:
        import akshare as ak
        
        # akshare的实时行情接口
        df = ak.stock_zh_a_spot_em()
        stock_data = df[df['代码'] == code]
        
        if stock_data.empty:
            return None
        
        row = stock_data.iloc[0]
        name = row['名称']
        pe = row.get('市盈率-动态', None)
        pb = row.get('市净率', None)
        cap = row.get('总市值', None)
        
        return {
            'name': name,
            'pe_ttm': float(pe) if pe and pe != '-' else None,
            'pb': float(pb) if pb and pb != '-' else None,
            'market_cap_yi': round(float(cap) / 1e8, 1) if cap and cap != '-' else None,
            'is_st': 'ST' in name or '*ST' in name or '退' in name,
            'source': 'akshare',
        }
    except Exception as e:
        return None


def fetch_fundamental_baostock(code: str, bs_session=None) -> Optional[dict]:
    """
    使用baostock获取基本面数据
    返回: {name, pe_ttm, pb, market_cap_yi, is_st}
    """
    try:
        import baostock as bs
        
        # 如果没有传入session，自己登录
        need_logout = False
        if bs_session is None:
            bs.login()
            need_logout = True
        
        prefix = 'sh' if code.startswith(('5', '6')) else 'sz'
        bs_code = f'{prefix}.{code}'
        
        # 获取最近5天的数据（包含PE/PB/PS）
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,code,close,peTTM,pbMRQ,psTTM",
            start_date='2026-03-01',
            end_date='2026-03-06',
            frequency="d",
            adjustflag="3"
        )
        
        data_list = []
        while (rs.error_code == '0') and rs.next():
            data_list.append(rs.get_row_data())
        
        if need_logout:
            bs.logout()
        
        if not data_list:
            return None
        
        # 取最后一条有效数据
        last_row = data_list[-1]
        close_price = last_row[2]
        pe = last_row[3]
        pb = last_row[4]
        ps = last_row[5]
        
        # 尝试估算市值（用PS和收盘价粗略估算）
        market_cap_yi = None
        try:
            if ps and ps != '' and close_price and close_price != '':
                # 这是一个粗略估算，实际需要总股本数据
                # 暂时返回None，后续可以补充
                pass
        except:
            pass
        
        return {
            'name': '',  # baostock不提供名称，需要从其他源补充
            'pe_ttm': float(pe) if pe and pe != '' else None,
            'pb': float(pb) if pb and pb != '' else None,
            'market_cap_yi': market_cap_yi,
            'is_st': False,  # baostock不提供ST标记
            'source': 'baostock',
        }
    except Exception as e:
        return None


def fetch_fundamental_multi_source(codes: List[str], show_progress: bool = True) -> Dict[str, dict]:
    """
    使用多数据源fallback机制获取基本面数据
    
    策略（网络接口不稳定时优先使用本地库）:
    1. 主力：baostock获取PE/PB（稳定可靠）
    2. 备用：东方财富补充市值和名称
    3. 备用：akshare补充缺失数据
    """
    print(f"\n📡 多数据源获取基本面数据 ({len(codes)}只)...")
    
    results = {}
    
    # 第一步：baostock批量获取PE/PB（主力数据源）
    print("  [1/3] baostock获取PE/PB数据...")
    
    try:
        import baostock as bs
        bs.login()
        
        bs_success = 0
        for idx, code in enumerate(codes):
            if show_progress and (idx + 1) % 100 == 0:
                print(f"    进度: {idx+1}/{len(codes)}, 成功{bs_success}")
            
            bs_data = fetch_fundamental_baostock(code, bs_session=bs)
            if bs_data and bs_data.get('pe_ttm') is not None:
                results[code] = bs_data
                bs_success += 1
            
            # baostock比较稳定，不需要sleep
        
        bs.logout()
        print(f"    ✅ baostock成功 {bs_success}/{len(codes)} 只 ({bs_success*100//len(codes)}%)")
    
    except Exception as e:
        print(f"    ⚠️ baostock失败: {e}")
    
    # 第二步：东方财富补充名称和市值
    print("  [2/3] 东方财富补充名称和市值...")
    em_success = 0
    
    for idx, code in enumerate(codes):
        if show_progress and (idx + 1) % 100 == 0:
            print(f"    进度: {idx+1}/{len(codes)}, 成功{em_success}")
        
        # 如果没有数据或缺少名称/市值，尝试东财
        if code not in results or not results[code].get('name') or not results[code].get('market_cap_yi'):
            em_data = fetch_fundamental_eastmoney_single(code, timeout=8)
            if em_data:
                if code in results:
                    # 保留baostock的PE/PB，补充东财的名称和市值
                    if em_data.get('name'):
                        results[code]['name'] = em_data['name']
                    if em_data.get('market_cap_yi'):
                        results[code]['market_cap_yi'] = em_data['market_cap_yi']
                    if em_data.get('is_st'):
                        results[code]['is_st'] = em_data['is_st']
                    # 如果baostock的PE/PB为空，用东财的
                    if not results[code].get('pe_ttm') and em_data.get('pe_ttm'):
                        results[code]['pe_ttm'] = em_data['pe_ttm']
                    if not results[code].get('pb') and em_data.get('pb'):
                        results[code]['pb'] = em_data['pb']
                else:
                    results[code] = em_data
                em_success += 1
            
            time.sleep(0.1)
    
    print(f"    ✅ 东方财富补充 {em_success} 只")
    
    # 第三步：akshare补充仍然缺失的
    missing_codes = [c for c in codes if c not in results or not results[c].get('pe_ttm')]
    if missing_codes and len(missing_codes) <= 50:  # akshare较慢，只处理少量缺失
        print(f"  [3/3] akshare补充剩余 {len(missing_codes)} 只...")
        ak_success = 0
        
        try:
            import akshare
            has_akshare = True
        except ImportError:
            has_akshare = False
            print("    ⚠️ akshare未安装，跳过")
        
        if has_akshare:
            for code in missing_codes:
                ak_data = fetch_fundamental_akshare(code)
                if ak_data and ak_data.get('pe_ttm') is not None:
                    if code in results:
                        results[code].update(ak_data)
                    else:
                        results[code] = ak_data
                    ak_success += 1
                time.sleep(0.2)
            
            print(f"    ✅ akshare成功 {ak_success} 只")
    else:
        print(f"  [3/3] 跳过akshare（缺失数据过多或为0）")
    
    # 统计最终结果
    complete = sum(1 for v in results.values() if v.get('pe_ttm') is not None)
    complete_with_name = sum(1 for v in results.values() if v.get('pe_ttm') is not None and v.get('name'))
    print(f"\n  📊 最终结果:")
    print(f"    PE/PB完整: {complete}/{len(codes)} 只 ({complete*100//len(codes) if len(codes)>0 else 0}%)")
    print(f"    含名称: {complete_with_name}/{len(codes)} 只 ({complete_with_name*100//len(codes) if len(codes)>0 else 0}%)")
    
    return results


def update_cache(codes: List[str] = None, test_mode: bool = False):
    """更新基本面数据缓存"""
    print(f"{'='*60}")
    print(f"  📦 基本面数据缓存更新")
    print(f"{'='*60}")
    
    # 获取股票列表
    if codes:
        stock_codes = codes
        print(f"  指定股票: {len(stock_codes)} 只")
    else:
        # 从股票池加载
        if not os.path.exists(POOL_FILE):
            print(f"  ⚠️ 股票池文件不存在: {POOL_FILE}")
            return
        
        with open(POOL_FILE, 'r', encoding='utf-8') as f:
            pool = json.load(f)
        
        stock_codes = []
        for sector, stocks in pool.get('sectors', {}).items():
            for s in stocks:
                stock_codes.append(s['code'])
        
        print(f"  股票池: {len(stock_codes)} 只")
    
    if test_mode:
        stock_codes = stock_codes[:10]
        print(f"  测试模式: 仅处理前 {len(stock_codes)} 只")
    
    # 多数据源获取
    fundamental_data = fetch_fundamental_multi_source(stock_codes, show_progress=True)
    
    # 保存缓存
    cache = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'total': len(stock_codes),
        'success': len(fundamental_data),
        'all_data': fundamental_data,
    }
    
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"  ✅ 缓存已更新: {CACHE_FILE}")
    print(f"  📊 成功: {len(fundamental_data)}/{len(stock_codes)} 只")
    print(f"  📅 日期: {cache['date']}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description='基本面数据缓存更新工具')
    parser.add_argument('--codes', type=str, help='指定股票代码（逗号分隔）')
    parser.add_argument('--test', action='store_true', help='测试模式（仅10只）')
    args = parser.parse_args()
    
    codes = args.codes.split(',') if args.codes else None
    update_cache(codes=codes, test_mode=args.test)


if __name__ == '__main__':
    main()
