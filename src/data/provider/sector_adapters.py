"""
板块数据适配器：统一各数据源的板块成分股获取接口
"""

import logging
import time
from typing import List, Dict, Optional
import requests

from .base import SectorAdapter

logger = logging.getLogger(__name__)


class AkshareSectorAdapter(SectorAdapter):
    """akshare 板块数据适配器"""

    @property
    def source_id(self) -> str:
        return "akshare"

    def get_sector_stocks(
        self,
        sector_code: str,
        limit: Optional[int] = None,
        **kwargs,
    ) -> List[Dict[str, any]]:
        """
        从akshare获取概念板块成分股
        
        Args:
            sector_code: 概念名称，如 "光伏概念"、"机器人概念"
            limit: 返回数量限制
        """
        try:
            import akshare as ak
            
            # 获取概念板块成分股
            df = ak.stock_board_concept_cons_em(symbol=sector_code)
            if df is None or len(df) == 0:
                return []
            
            stocks = []
            for _, row in df.iterrows():
                code = str(row.get('代码', ''))
                name = str(row.get('名称', ''))
                market_cap = row.get('市值', 0)
                
                if name and 'ST' not in name and '*' not in name:
                    stocks.append({
                        'code': code,
                        'name': name,
                        'market_cap_yi': round(market_cap / 1e8, 1) if market_cap else 0,
                    })
            
            # 按市值排序
            stocks.sort(key=lambda x: x['market_cap_yi'], reverse=True)
            
            if limit:
                stocks = stocks[:limit]
            
            logger.info(f"[akshare] 获取 {sector_code} 成功: {len(stocks)}只")
            return stocks
        
        except Exception as e:
            logger.warning(f"[akshare] 获取 {sector_code} 失败: {e}")
            return []


class EastMoneySectorAdapter(SectorAdapter):
    """东方财富板块数据适配器"""

    @property
    def source_id(self) -> str:
        return "eastmoney"

    def get_sector_stocks(
        self,
        sector_code: str,
        limit: Optional[int] = None,
        **kwargs,
    ) -> List[Dict[str, any]]:
        """
        从东方财富获取板块成分股
        
        Args:
            sector_code: 板块代码，如 "BK1031"（光伏）
            limit: 返回数量限制
        """
        max_retries = kwargs.get('max_retries', 2)
        
        for attempt in range(max_retries):
            try:
                session = requests.Session()
                session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                
                url = 'http://push2.eastmoney.com/api/qt/clist/get'
                params = {
                    'pn': 1,
                    'pz': limit or 50,
                    'po': 1,
                    'np': 1,
                    'fltt': 2,
                    'invt': 2,
                    'fid': 'f20',
                    'fs': f'b:{sector_code}',
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
                        
                        if name and 'ST' not in name and '*' not in name \
                           and price and price != '-' and cap and cap > 1e9:
                            stocks.append({
                                'code': code,
                                'name': name,
                                'market_cap_yi': round(cap / 1e8, 1),
                            })
                
                session.close()
                
                if stocks:
                    logger.info(f"[eastmoney] 获取 {sector_code} 成功: {len(stocks)}只")
                return stocks
            
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
                else:
                    logger.warning(f"[eastmoney] 获取 {sector_code} 失败: {e}")
                    return []
        
        return []


class SinaSectorAdapter(SectorAdapter):
    """新浪财经板块数据适配器"""

    @property
    def source_id(self) -> str:
        return "sina"

    def get_sector_stocks(
        self,
        sector_code: str,
        limit: Optional[int] = None,
        **kwargs,
    ) -> List[Dict[str, any]]:
        """
        从新浪财经获取行业板块成分股
        
        Args:
            sector_code: 行业代码，如 "new_ysjs"（有色金属）
            limit: 返回数量限制
        """
        try:
            url = 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
            params = {
                'page': 1,
                'num': limit or 50,
                'sort': 'mktcap',
                'asc': 0,
                'node': sector_code,
            }
            
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                return []
            
            data = resp.json()
            stocks = []
            
            for item in data:
                code = item.get('code', '')
                name = item.get('name', '')
                mktcap = item.get('mktcap', 0)
                
                if name and 'ST' not in name and '*' not in name and mktcap:
                    stocks.append({
                        'code': code,
                        'name': name,
                        'market_cap_yi': round(mktcap / 10000, 1),
                    })
            
            logger.info(f"[sina] 获取 {sector_code} 成功: {len(stocks)}只")
            return stocks
        
        except Exception as e:
            logger.warning(f"[sina] 获取 {sector_code} 失败: {e}")
            return []


class BaostockSectorAdapter(SectorAdapter):
    """baostock 板块数据适配器"""

    @property
    def source_id(self) -> str:
        return "baostock"

    def get_sector_stocks(
        self,
        sector_code: str,
        limit: Optional[int] = None,
        **kwargs,
    ) -> List[Dict[str, any]]:
        """
        从baostock获取行业成分股
        
        Args:
            sector_code: 行业名称，如 "有色"、"证券"
            limit: 返回数量限制
        """
        try:
            import baostock as bs
            
            bs.login()
            
            # 获取行业成分股
            rs = bs.query_stock_industry()
            stocks = []
            
            while rs.error_code == '0' and rs.next():
                row = rs.get_row_data()
                code_full = row[0]  # 格式: sh.600000
                code = code_full.split('.')[1] if '.' in code_full else code_full
                name = row[1]
                industry = row[2]
                
                # 行业匹配
                if sector_code.lower() in industry.lower():
                    if name and 'ST' not in name and '*' not in name:
                        stocks.append({
                            'code': code,
                            'name': name,
                            'market_cap_yi': 0,  # baostock不提供市值
                        })
            
            bs.logout()
            
            if limit:
                stocks = stocks[:limit]
            
            logger.info(f"[baostock] 获取 {sector_code} 成功: {len(stocks)}只")
            return stocks
        
        except Exception as e:
            logger.warning(f"[baostock] 获取 {sector_code} 失败: {e}")
            return []


class LocalSectorAdapter(SectorAdapter):
    """本地数据板块适配器（关键词匹配）"""

    @property
    def source_id(self) -> str:
        return "local"

    def get_sector_stocks(
        self,
        sector_code: str,
        limit: Optional[int] = None,
        **kwargs,
    ) -> List[Dict[str, any]]:
        """
        从本地股票池按关键词匹配
        
        Args:
            sector_code: 关键词列表（JSON字符串）或单个关键词
            limit: 返回数量限制
        """
        try:
            import json
            import os
            from pathlib import Path
            
            # 解析关键词
            keywords = kwargs.get('keywords', [])
            if not keywords:
                # 尝试从sector_code解析
                try:
                    keywords = json.loads(sector_code)
                except:
                    keywords = [sector_code]
            
            # 加载本地股票池
            base_dir = Path(__file__).resolve().parents[3]
            pool_file = base_dir / 'mydate' / 'stock_pool_all.json'
            
            if not pool_file.exists():
                return []
            
            with open(pool_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 加载市值缓存
            cache_file = base_dir / 'mydate' / 'market_fundamental_cache.json'
            market_cap_cache = {}
            if cache_file.exists():
                with open(cache_file, 'r', encoding='utf-8') as f:
                    market_cap_cache = json.load(f)
            
            # 提取所有股票
            all_stocks = []
            if 'stocks' in data and isinstance(data['stocks'], dict):
                for industry, stock_list in data['stocks'].items():
                    if isinstance(stock_list, list):
                        for stock in stock_list:
                            code = stock['code']
                            name = stock['name']
                            market_cap = market_cap_cache.get(code, {}).get('market_cap_yi', 0)
                            all_stocks.append({
                                'code': code,
                                'name': name,
                                'market_cap_yi': market_cap
                            })
            
            # 关键词匹配
            matched = []
            for stock in all_stocks:
                name_lower = stock['name'].lower()
                for kw in keywords:
                    if kw.lower() in name_lower:
                        matched.append(stock)
                        break
            
            # 按市值排序
            matched.sort(key=lambda x: x['market_cap_yi'], reverse=True)
            
            if limit:
                matched = matched[:limit]
            
            logger.info(f"[local] 关键词匹配成功: {len(matched)}只")
            return matched
        
        except Exception as e:
            logger.warning(f"[local] 关键词匹配失败: {e}")
            return []


# 板块适配器注册表
SECTOR_ADAPTER_REGISTRY = {
    'akshare': AkshareSectorAdapter,
    'eastmoney': EastMoneySectorAdapter,
    'sina': SinaSectorAdapter,
    'baostock': BaostockSectorAdapter,
    'local': LocalSectorAdapter,
}
