"""
市场数据采集器
支持多个数据源：akshare, tushare, baostock
"""

from abc import ABC, abstractmethod
from typing import List, Optional
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger


class BaseDataCollector(ABC):
    """数据采集器基类"""
    
    def __init__(self, config: dict):
        self.config = config
        
    @abstractmethod
    def get_daily_bars(self, stock_code: str, 
                      start_date: str, 
                      end_date: str) -> pd.DataFrame:
        """获取日线数据"""
        pass
    
    @abstractmethod
    def get_realtime_quote(self, stock_codes: List[str]) -> pd.DataFrame:
        """获取实时行情"""
        pass
    
    @abstractmethod
    def get_stock_list(self, market: str = 'ALL') -> pd.DataFrame:
        """获取股票列表"""
        pass


class AkShareCollector(BaseDataCollector):
    """AkShare数据采集器"""
    
    def __init__(self, config: dict):
        super().__init__(config)
        try:
            import akshare as ak
            self.ak = ak
            logger.info("AkShare数据采集器初始化成功")
        except ImportError:
            logger.error("请安装akshare: pip install akshare")
            raise
    
    def get_daily_bars(self, stock_code: str, 
                      start_date: str, 
                      end_date: str) -> pd.DataFrame:
        """
        获取日线数据（统一走 DataProvider，主备由 config 决定）。
        
        Args:
            stock_code: 股票代码，如 '000001'
            start_date: 开始日期 'YYYYMMDD'
            end_date: 结束日期 'YYYYMMDD'
            
        Returns:
            日线数据 DataFrame，列含 date/open/high/low/close/volume
        """
        try:
            symbol = self._format_stock_code(stock_code)
            from src.data.provider.data_provider import get_default_kline_provider
            df = get_default_kline_provider().get_kline(
                symbol=symbol, start_date=start_date, end_date=end_date, min_bars=1
            )
            if df is not None and not df.empty:
                df = self._standardize_columns(df)
                logger.debug(f"获取{stock_code}日线数据成功，共{len(df)}条")
                return df
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"获取{stock_code}日线数据失败: {e}")
            return pd.DataFrame()
    
    def get_realtime_quote(self, stock_codes: List[str]) -> pd.DataFrame:
        """
        获取实时行情
        
        Args:
            stock_codes: 股票代码列表
            
        Returns:
            实时行情DataFrame
        """
        try:
            df = self.ak.stock_zh_a_spot_em()
            
            # 过滤指定股票
            if stock_codes:
                df = df[df['代码'].isin(stock_codes)]
            
            # 标准化列名
            df = self._standardize_realtime_columns(df)
            
            logger.debug(f"获取实时行情成功，共{len(df)}只股票")
            return df
            
        except Exception as e:
            logger.error(f"获取实时行情失败: {e}")
            return pd.DataFrame()
    
    def get_stock_list(self, market: str = 'ALL') -> pd.DataFrame:
        """
        获取股票列表
        
        Args:
            market: 市场，'ALL'/'SH'/'SZ'
            
        Returns:
            股票列表DataFrame
        """
        try:
            df = self.ak.stock_info_a_code_name()
            
            if market != 'ALL':
                if market == 'SH':
                    df = df[df['code'].str.startswith('6')]
                elif market == 'SZ':
                    df = df[df['code'].str.startswith(('0', '3'))]
            
            logger.info(f"获取股票列表成功，共{len(df)}只股票")
            return df
            
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            return pd.DataFrame()
    
    def get_index_data(self, index_code: str,
                      start_date: str,
                      end_date: str) -> pd.DataFrame:
        """
        获取指数数据
        
        Args:
            index_code: 指数代码，如 '000001'（上证指数）
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            指数数据DataFrame
        """
        try:
            df = self.ak.stock_zh_index_daily(symbol=f"sh{index_code}")
            
            # 过滤日期
            df['date'] = pd.to_datetime(df['date'])
            start = pd.to_datetime(start_date)
            end = pd.to_datetime(end_date)
            df = df[(df['date'] >= start) & (df['date'] <= end)]
            
            logger.debug(f"获取指数{index_code}数据成功，共{len(df)}条")
            return df
            
        except Exception as e:
            logger.error(f"获取指数{index_code}数据失败: {e}")
            return pd.DataFrame()
    
    def _format_stock_code(self, code: str) -> str:
        """格式化股票代码"""
        # 去掉可能的市场前缀
        code = code.replace('SH', '').replace('SZ', '').replace('sh', '').replace('sz', '')
        return code
    
    def _standardize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化列名"""
        column_mapping = {
            '日期': 'date',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
            '成交额': 'amount',
            '涨跌幅': 'pct_change',
            '涨跌额': 'change',
            '换手率': 'turnover',
        }
        
        df = df.rename(columns=column_mapping)
        df['date'] = pd.to_datetime(df['date'])
        
        return df
    
    def _standardize_realtime_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化实时行情列名"""
        column_mapping = {
            '代码': 'code',
            '名称': 'name',
            '最新价': 'price',
            '涨跌幅': 'pct_change',
            '涨跌额': 'change',
            '成交量': 'volume',
            '成交额': 'amount',
            '振幅': 'amplitude',
            '最高': 'high',
            '最低': 'low',
            '今开': 'open',
            '昨收': 'pre_close',
        }
        
        df = df.rename(columns=column_mapping)
        return df


class TushareCollector(BaseDataCollector):
    """Tushare数据采集器（需要token）"""
    
    def __init__(self, config: dict):
        super().__init__(config)
        token = config.get('tushare_token')
        
        if not token:
            logger.warning("未配置Tushare token")
            return
        
        try:
            import tushare as ts
            ts.set_token(token)
            self.pro = ts.pro_api()
            logger.info("Tushare数据采集器初始化成功")
        except ImportError:
            logger.error("请安装tushare: pip install tushare")
            raise
    
    def get_daily_bars(self, stock_code: str, 
                      start_date: str, 
                      end_date: str) -> pd.DataFrame:
        """获取日线数据（统一走 DataProvider，主备由 config 决定）。"""
        try:
            # ts_code 如 000001.SZ -> 转成 000001 给 provider
            symbol = stock_code.split(".")[0] if "." in stock_code else stock_code
            from src.data.provider.data_provider import get_default_kline_provider
            df = get_default_kline_provider().get_kline(
                symbol=symbol, start_date=start_date, end_date=end_date, min_bars=1
            )
            if df is not None and not df.empty:
                logger.debug(f"获取{stock_code}日线数据成功，共{len(df)}条")
                return df
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"获取{stock_code}日线数据失败: {e}")
            return pd.DataFrame()
    
    def get_realtime_quote(self, stock_codes: List[str]) -> pd.DataFrame:
        """获取实时行情（Tushare需要高级权限）"""
        logger.warning("Tushare实时行情需要高级权限")
        return pd.DataFrame()
    
    def get_stock_list(self, market: str = 'ALL') -> pd.DataFrame:
        """获取股票列表"""
        try:
            df = self.pro.stock_basic(
                exchange='',
                list_status='L',
                fields='ts_code,symbol,name,area,industry,market,list_date'
            )
            
            logger.info(f"获取股票列表成功，共{len(df)}只股票")
            return df
            
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            return pd.DataFrame()


class DataCollectorFactory:
    """数据采集器工厂"""
    
    @staticmethod
    def create_collector(source: str, config: dict) -> BaseDataCollector:
        """
        创建数据采集器
        
        Args:
            source: 数据源 'akshare'/'tushare'/'baostock'
            config: 配置
            
        Returns:
            数据采集器实例
        """
        if source == 'akshare':
            return AkShareCollector(config)
        elif source == 'tushare':
            return TushareCollector(config)
        else:
            logger.error(f"不支持的数据源: {source}")
            raise ValueError(f"不支持的数据源: {source}")
