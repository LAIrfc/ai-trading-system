"""
实时行情数据获取
支持多个数据源：akshare、tushare、新浪财经等
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger
import time


class RealtimeDataFetcher:
    """实时行情数据获取器"""
    
    def __init__(self, data_source='akshare'):
        """
        初始化
        
        Args:
            data_source: 数据源 ('akshare', 'tushare', 'sina')
        """
        self.data_source = data_source
        self._init_data_source()
    
    def _init_data_source(self):
        """初始化数据源"""
        if self.data_source == 'akshare':
            try:
                import akshare as ak
                self.ak = ak
                logger.info("✅ AKShare数据源已初始化")
            except ImportError:
                logger.warning("⚠️  AKShare未安装，请运行: pip install akshare")
                self.ak = None
        
        elif self.data_source == 'tushare':
            try:
                import tushare as ts
                self.ts = ts
                logger.info("✅ Tushare数据源已初始化")
            except ImportError:
                logger.warning("⚠️  Tushare未安装，请运行: pip install tushare")
                self.ts = None
    
    def get_realtime_price(self, stock_code: str) -> Optional[float]:
        """
        获取实时价格
        
        Args:
            stock_code: 股票代码（如'600519'）
            
        Returns:
            当前价格，失败返回None
        """
        try:
            if self.data_source == 'akshare' and self.ak:
                # 使用akshare获取实时行情
                df = self.ak.stock_zh_a_spot_em()
                
                # 查找股票
                stock_data = df[df['代码'] == stock_code]
                
                if not stock_data.empty:
                    price = float(stock_data['最新价'].iloc[0])
                    return price
            
            logger.warning(f"无法获取{stock_code}的实时价格")
            return None
            
        except Exception as e:
            logger.error(f"获取实时价格失败: {e}")
            return None
    
    def get_realtime_quotes(self, stock_codes: List[str]) -> Dict[str, Dict]:
        """
        批量获取实时行情
        
        Args:
            stock_codes: 股票代码列表
            
        Returns:
            股票代码 -> 行情数据的字典
        """
        quotes = {}
        
        try:
            if self.data_source == 'akshare' and self.ak:
                # 获取所有A股实时数据
                df = self.ak.stock_zh_a_spot_em()
                
                for code in stock_codes:
                    stock_data = df[df['代码'] == code]
                    
                    if not stock_data.empty:
                        row = stock_data.iloc[0]
                        quotes[code] = {
                            'code': code,
                            'name': row['名称'],
                            'price': float(row['最新价']),
                            'change_pct': float(row['涨跌幅']),
                            'change_amount': float(row['涨跌额']),
                            'volume': float(row['成交量']),
                            'amount': float(row['成交额']),
                            'open': float(row['今开']),
                            'high': float(row['最高']),
                            'low': float(row['最低']),
                            'pre_close': float(row['昨收']),
                            'timestamp': datetime.now(),
                        }
        
        except Exception as e:
            logger.error(f"批量获取行情失败: {e}")
        
        return quotes
    
    def get_historical_data(self, stock_code: str, 
                           start_date: Optional[str] = None,
                           end_date: Optional[str] = None,
                           period: str = 'daily') -> Optional[pd.DataFrame]:
        """
        获取历史数据。日线走统一 DataProvider（主备由 config 决定），周/月线仍用 akshare。
        
        Args:
            stock_code: 股票代码
            start_date: 开始日期 ('YYYYMMDD')
            end_date: 结束日期 ('YYYYMMDD')
            period: 周期 ('daily', 'weekly', 'monthly')
            
        Returns:
            DataFrame 含 date/open/high/low/close/volume，日线时 index=date
        """
        try:
            if period == 'daily':
                if not start_date:
                    start_date = (datetime.now() - timedelta(days=150)).strftime('%Y%m%d')
                if not end_date:
                    end_date = datetime.now().strftime('%Y%m%d')
                from src.data.provider.data_provider import get_default_kline_provider
                code = stock_code.replace('SH', '').replace('SZ', '').replace('sh', '').replace('sz', '').strip()
                df = get_default_kline_provider().get_kline(
                    symbol=code, start_date=start_date, end_date=end_date, min_bars=1
                )
                if df is not None and not df.empty:
                    df = df.copy()
                    if 'date' in df.columns:
                        df['date'] = pd.to_datetime(df['date'])
                        df.set_index('date', inplace=True)
                    return df
                return None
            if self.data_source == 'akshare' and self.ak:
                if not start_date:
                    start_date = (datetime.now() - timedelta(days=150)).strftime('%Y%m%d')
                if not end_date:
                    end_date = datetime.now().strftime('%Y%m%d')
                df = self.ak.stock_zh_a_hist(
                    symbol=stock_code,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    adjust='qfq'
                )
                if df is not None and not df.empty:
                    df.columns = ['date', 'open', 'close', 'high', 'low', 'volume',
                                 'amount', 'amplitude', 'change_pct', 'change_amount', 'turnover']
                    for col in ['open', 'close', 'high', 'low', 'volume', 'amount']:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                    df['date'] = pd.to_datetime(df['date'])
                    df.set_index('date', inplace=True)
                    return df
            return None
        except Exception as e:
            logger.error(f"获取历史数据失败 {stock_code}: {e}")
            return None
    
    def get_market_overview(self) -> Dict:
        """
        获取市场概览
        
        Returns:
            市场统计信息
        """
        try:
            if self.data_source == 'akshare' and self.ak:
                # 获取市场概况
                df = self.ak.stock_zh_a_spot_em()
                
                return {
                    'total_stocks': len(df),
                    'rising': len(df[df['涨跌幅'] > 0]),
                    'falling': len(df[df['涨跌幅'] < 0]),
                    'flat': len(df[df['涨跌幅'] == 0]),
                    'limit_up': len(df[df['涨跌幅'] >= 9.9]),
                    'limit_down': len(df[df['涨跌幅'] <= -9.9]),
                    'avg_change_pct': float(df['涨跌幅'].mean()),
                    'total_volume': float(df['成交量'].sum()),
                    'total_amount': float(df['成交额'].sum()),
                    'timestamp': datetime.now(),
                }
        
        except Exception as e:
            logger.error(f"获取市场概览失败: {e}")
            return {}
    
    def search_stock(self, keyword: str) -> List[Dict]:
        """
        搜索股票
        
        Args:
            keyword: 股票代码或名称关键词
            
        Returns:
            匹配的股票列表
        """
        try:
            if self.data_source == 'akshare' and self.ak:
                df = self.ak.stock_zh_a_spot_em()
                
                # 按代码或名称搜索
                mask = df['代码'].str.contains(keyword) | df['名称'].str.contains(keyword)
                results = df[mask]
                
                return [
                    {
                        'code': row['代码'],
                        'name': row['名称'],
                        'price': float(row['最新价']),
                        'change_pct': float(row['涨跌幅']),
                    }
                    for _, row in results.head(10).iterrows()
                ]
        
        except Exception as e:
            logger.error(f"搜索股票失败: {e}")
            return []


class MarketDataManager:
    """市场数据管理器 - 缓存和更新实时数据"""
    
    def __init__(self, data_source='akshare', update_interval=3):
        """
        初始化
        
        Args:
            data_source: 数据源
            update_interval: 更新间隔（秒）
        """
        self.fetcher = RealtimeDataFetcher(data_source)
        self.update_interval = update_interval
        
        self.realtime_cache = {}  # 实时数据缓存
        self.historical_cache = {}  # 历史数据缓存
        
        self.last_update_time = {}
    
    def get_realtime_data(self, stock_codes: List[str], force_update=False) -> Dict:
        """
        获取实时数据（带缓存）
        
        Args:
            stock_codes: 股票代码列表
            force_update: 是否强制更新
            
        Returns:
            实时行情数据
        """
        now = time.time()
        
        # 检查是否需要更新
        need_update = force_update
        if not need_update:
            for code in stock_codes:
                if code not in self.last_update_time:
                    need_update = True
                    break
                if now - self.last_update_time[code] > self.update_interval:
                    need_update = True
                    break
        
        # 更新数据
        if need_update:
            logger.debug(f"更新实时数据: {stock_codes}")
            quotes = self.fetcher.get_realtime_quotes(stock_codes)
            
            for code, data in quotes.items():
                self.realtime_cache[code] = data
                self.last_update_time[code] = now
        
        # 返回缓存数据
        return {code: self.realtime_cache.get(code) for code in stock_codes}
    
    def get_historical_data(self, stock_code: str, days=100, use_cache=True) -> Optional[pd.DataFrame]:
        """
        获取历史数据（带缓存）
        
        Args:
            stock_code: 股票代码
            days: 获取天数
            use_cache: 是否使用缓存
            
        Returns:
            历史数据DataFrame
        """
        cache_key = f"{stock_code}_{days}"
        
        # 检查缓存
        if use_cache and cache_key in self.historical_cache:
            cached_data, cached_time = self.historical_cache[cache_key]
            
            # 缓存有效期：1小时
            if time.time() - cached_time < 3600:
                logger.debug(f"使用缓存的历史数据: {stock_code}")
                return cached_data
        
        # 获取新数据
        logger.debug(f"获取历史数据: {stock_code}, {days}天")
        start_date = (datetime.now() - timedelta(days=days + 50)).strftime('%Y%m%d')
        end_date = datetime.now().strftime('%Y%m%d')
        
        df = self.fetcher.get_historical_data(stock_code, start_date, end_date)
        
        if df is not None and not df.empty:
            # 只保留最近N天
            df = df.tail(days)
            
            # 缓存
            self.historical_cache[cache_key] = (df, time.time())
        
        return df
    
    def prepare_strategy_data(self, stock_codes: List[str], historical_days=100) -> Dict:
        """
        为策略准备数据（实时+历史）
        
        Args:
            stock_codes: 股票代码列表
            historical_days: 历史数据天数
            
        Returns:
            股票代码 -> DataFrame的字典
        """
        data = {}
        
        for code in stock_codes:
            # 获取历史数据
            df = self.get_historical_data(code, historical_days)
            
            if df is not None and not df.empty:
                # 获取实时数据
                realtime = self.get_realtime_data([code])
                
                if code in realtime and realtime[code]:
                    # 将实时数据追加到历史数据
                    rt_data = realtime[code]
                    
                    # 创建今天的数据行
                    today = pd.DataFrame({
                        'open': [rt_data['open']],
                        'close': [rt_data['price']],
                        'high': [rt_data['high']],
                        'low': [rt_data['low']],
                        'volume': [rt_data['volume']],
                    }, index=[pd.Timestamp.now().normalize()])
                    
                    # 合并数据
                    df = pd.concat([df, today])
                    df = df[~df.index.duplicated(keep='last')]
                
                data[code] = df
        
        return data
