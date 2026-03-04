"""
ETF数据获取模块

支持多种数据源:
1. baostock（免费，Python 3.8 兼容）
2. 模拟数据（用于离线测试策略逻辑）

使用方法:
    fetcher = ETFDataFetcher()
    data = fetcher.get_etf_pool_data(codes)
    
如果网络不可用，自动降级使用模拟数据。
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from loguru import logger
import time


# ETF名称映射
ETF_NAME_MAP = {
    '510300': '沪深300ETF',
    '159949': '创业板50ETF',
    '513100': '纳指ETF',
    '518880': '黄金ETF',
    '511520': '国债ETF',
    '510050': '上证50ETF',
    '510500': '中证500ETF',
    '159915': '创业板ETF',
    '510880': '红利ETF',
    '512000': '券商ETF',
}

# ETF模拟参数（基于真实历史特征）
ETF_SIM_PARAMS = {
    '510300': {'base_price': 3.8, 'annual_return': 0.05, 'volatility': 0.20, 'name': '沪深300'},
    '159949': {'base_price': 0.8, 'annual_return': -0.02, 'volatility': 0.28, 'name': '创业板50'},
    '513100': {'base_price': 1.5, 'annual_return': 0.15, 'volatility': 0.22, 'name': '纳指ETF'},
    '518880': {'base_price': 5.0, 'annual_return': 0.12, 'volatility': 0.15, 'name': '黄金ETF'},
    '511520': {'base_price': 102.0, 'annual_return': 0.03, 'volatility': 0.03, 'name': '国债ETF'},
}

# 交易所映射（baostock用）
ETF_EXCHANGE_MAP = {
    '510300': 'sh', '510500': 'sh', '510050': 'sh', '513100': 'sh',
    '518880': 'sh', '511520': 'sh', '511010': 'sh', '510880': 'sh',
    '512000': 'sh', '512880': 'sh',
    '159949': 'sz', '159915': 'sz', '159919': 'sz', '159901': 'sz', '159922': 'sz',
}


def get_baostock_code(code: str) -> str:
    """将ETF代码转换为baostock格式"""
    exchange = ETF_EXCHANGE_MAP.get(code)
    if exchange:
        return f"{exchange}.{code}"
    if code.startswith('15') or code.startswith('16'):
        return f"sz.{code}"
    return f"sh.{code}"


def generate_simulated_etf_data(code: str, start_date: str, end_date: str,
                                 seed: int = None) -> pd.DataFrame:
    """
    生成模拟ETF数据（基于几何布朗运动，参数参考真实市场特征）
    
    Args:
        code: ETF代码
        start_date: 开始日期 YYYYMMDD
        end_date: 结束日期 YYYYMMDD
        seed: 随机种子
    
    Returns:
        DataFrame with columns: open, high, low, close, volume
    """
    params = ETF_SIM_PARAMS.get(code, {
        'base_price': 3.0,
        'annual_return': 0.08,
        'volatility': 0.20,
        'name': f'ETF{code}'
    })
    
    start = pd.Timestamp(f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}")
    end = pd.Timestamp(f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}")
    
    # 生成交易日序列（去掉周末）
    all_days = pd.bdate_range(start, end, freq='B')
    n_days = len(all_days)
    
    if n_days == 0:
        return pd.DataFrame()
    
    # 设置随机种子（保证相同代码生成相同数据）
    if seed is None:
        seed = sum(ord(c) for c in code)
    rng = np.random.RandomState(seed)
    
    # 几何布朗运动参数
    dt = 1 / 252
    mu = params['annual_return']
    sigma = params['volatility']
    
    # 添加趋势周期（模拟牛熊交替）
    days_from_start = np.arange(n_days)
    # 牛熊周期（约250天一个周期）
    cycle = 0.08 * np.sin(2 * np.pi * days_from_start / 500)
    # 中期波动（约60天一个周期）
    medium_cycle = 0.03 * np.sin(2 * np.pi * days_from_start / 120 + rng.rand() * 2 * np.pi)
    
    # 每日收益率
    daily_returns = (mu + cycle + medium_cycle) * dt + sigma * np.sqrt(dt) * rng.randn(n_days)
    
    # 累积价格
    price_series = params['base_price'] * np.exp(np.cumsum(daily_returns))
    
    # 生成OHLCV
    data = []
    for i in range(n_days):
        close = price_series[i]
        daily_range = close * sigma / np.sqrt(252) * abs(rng.randn())
        
        open_price = close * (1 + 0.002 * rng.randn())
        high = max(open_price, close) + daily_range * abs(rng.randn()) * 0.5
        low = min(open_price, close) - daily_range * abs(rng.randn()) * 0.5
        
        # 成交量（基础量 + 随机波动）
        base_volume = 50000000 + 30000000 * abs(rng.randn())
        volume = int(base_volume)
        
        data.append({
            'open': round(open_price, 4),
            'high': round(high, 4),
            'low': round(low, 4),
            'close': round(close, 4),
            'volume': volume,
            'amount': round(close * volume, 2),
        })
    
    df = pd.DataFrame(data, index=all_days)
    df.index.name = 'date'
    
    return df


class ETFDataFetcher:
    """ETF数据获取器（支持baostock + 模拟数据降级）"""
    
    def __init__(self, use_simulation: bool = False):
        """
        初始化
        
        Args:
            use_simulation: 是否强制使用模拟数据
        """
        self.cache = {}
        self._connected = False
        self.use_simulation = use_simulation
        self._bs_available = False
        
        if not use_simulation:
            try:
                import baostock
                self._bs_available = True
            except ImportError:
                logger.warning("baostock 未安装，将使用模拟数据")
                self.use_simulation = True
    
    def _connect(self):
        """连接baostock"""
        if self.use_simulation or not self._bs_available:
            return
        
        if not self._connected:
            import baostock as bs
            lg = bs.login()
            if lg.error_code != '0':
                logger.warning(f"baostock登录失败: {lg.error_msg}，降级使用模拟数据")
                self.use_simulation = True
                return
            self._connected = True
            logger.info("baostock连接成功")
    
    def _disconnect(self):
        """断开baostock"""
        if self._connected and self._bs_available:
            import baostock as bs
            bs.logout()
            self._connected = False
    
    def fetch_etf_history(self, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        获取单个ETF的历史数据
        
        优先使用baostock，失败则降级使用模拟数据
        """
        name = ETF_NAME_MAP.get(code, code)
        logger.info(f"获取 {code} ({name}) 数据: {start_date} -> {end_date}")
        
        # 尝试使用 baostock
        if not self.use_simulation and self._bs_available:
            df = self._fetch_from_baostock(code, start_date, end_date)
            if df is not None and len(df) > 50:  # 至少50条数据才认为有效
                return df
            else:
                logger.warning(f"baostock数据不足({len(df) if df is not None else 0}条)，使用模拟数据")
        
        # 降级：使用模拟数据
        logger.info(f"使用模拟数据: {code} ({name})")
        df = generate_simulated_etf_data(code, start_date, end_date)
        
        if df is not None and len(df) > 0:
            logger.info(f"{code} ({name}) 模拟数据生成: {len(df)} 条")
        
        return df
    
    def _fetch_from_baostock(self, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """从baostock获取数据"""
        try:
            import baostock as bs
            self._connect()
            
            if self.use_simulation:
                return None
            
            bs_code = get_baostock_code(code)
            start_str = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
            end_str = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
            
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount",
                start_date=start_str,
                end_date=end_str,
                frequency="d",
                adjustflag="2"
            )
            
            if rs.error_code != '0':
                return None
            
            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())
            
            if len(data_list) == 0:
                return None
            
            df = pd.DataFrame(data_list, columns=['date', 'open', 'high', 'low', 'close', 'volume', 'amount'])
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            
            for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df = df[(df['close'] > 0) & df['close'].notna()]
            
            return df
            
        except Exception as e:
            logger.error(f"baostock获取 {code} 失败: {e}")
            return None
    
    def fetch_multiple_etfs(self, codes: List[str], start_date: str, end_date: str,
                           delay: float = 0.1) -> Dict[str, pd.DataFrame]:
        """批量获取多个ETF的历史数据"""
        results = {}
        
        if not self.use_simulation:
            self._connect()
        
        for i, code in enumerate(codes):
            name = ETF_NAME_MAP.get(code, code)
            logger.info(f"正在获取 {i+1}/{len(codes)}: {code} ({name})")
            
            df = self.fetch_etf_history(code, start_date, end_date)
            
            if df is not None and len(df) > 0:
                results[code] = df
            
            if i < len(codes) - 1 and not self.use_simulation:
                time.sleep(delay)
        
        logger.info(f"批量获取完成: {len(results)}/{len(codes)} 个ETF成功")
        
        return results
    
    def merge_to_multiindex(self, data_dict: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """将多个ETF的数据合并成 MultiIndex DataFrame"""
        if len(data_dict) == 0:
            return pd.DataFrame()
        
        result = pd.concat(data_dict.values(), axis=1, keys=data_dict.keys())
        result = result.sort_index()
        
        logger.info(f"数据合并完成: {result.shape[0]} 行 x {len(data_dict)} 个ETF")
        
        return result
    
    def get_etf_pool_data(self, codes: List[str], start_date: str = None, 
                         end_date: str = None, use_cache: bool = True) -> pd.DataFrame:
        """
        一键获取ETF池的完整数据
        
        Args:
            codes: ETF代码列表
            start_date: 开始日期，默认3年前
            end_date: 结束日期，默认今天
            use_cache: 是否使用缓存
        """
        if end_date is None:
            end_date = datetime.now().strftime('%Y%m%d')
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=365*3)).strftime('%Y%m%d')
        
        cache_key = f"{'-'.join(codes)}_{start_date}_{end_date}"
        
        if use_cache and cache_key in self.cache:
            logger.info("使用缓存数据")
            return self.cache[cache_key]
        
        logger.info(f"开始获取 {len(codes)} 个ETF的数据")
        data_dict = self.fetch_multiple_etfs(codes, start_date, end_date)
        
        merged = self.merge_to_multiindex(data_dict)
        
        if use_cache and not merged.empty:
            self.cache[cache_key] = merged
        
        self._disconnect()
        
        return merged
    
    def validate_data(self, data: pd.DataFrame, min_length: int = 250) -> bool:
        """验证数据是否足够"""
        if data.empty:
            logger.error("数据为空")
            return False
        
        if len(data) < min_length:
            logger.error(f"数据长度不足: {len(data)} < {min_length}")
            return False
        
        logger.info(f"数据验证通过: {len(data)} 条记录")
        return True
    
    def fill_missing_data(self, data: pd.DataFrame, method: str = 'ffill') -> pd.DataFrame:
        """填充缺失数据"""
        if method == 'ffill':
            return data.fillna(method='ffill')
        elif method == 'bfill':
            return data.fillna(method='bfill')
        elif method == 'interpolate':
            return data.interpolate(method='linear')
        return data
    
    def __del__(self):
        try:
            self._disconnect()
        except Exception:
            pass


def quick_fetch_etf_data(codes: List[str] = None, years: int = 3) -> pd.DataFrame:
    """快速获取ETF数据"""
    if codes is None:
        codes = ['510300', '159949', '513100', '518880', '511520']
    
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=365*years)).strftime('%Y%m%d')
    
    fetcher = ETFDataFetcher()
    return fetcher.get_etf_pool_data(codes, start_date, end_date)


if __name__ == '__main__':
    # 测试模拟数据
    print("="*50)
    print("ETF数据获取模块测试")
    print("="*50)
    
    fetcher = ETFDataFetcher()
    codes = ['510300', '159949', '513100', '518880', '511520']
    data = fetcher.get_etf_pool_data(codes, '20200101', '20260224')
    
    print(f"\n数据形状: {data.shape}")
    print(f"\n沪深300 最近5天:")
    print(data['510300'][['close']].tail())
    print(f"\n黄金ETF 最近5天:")
    print(data['518880'][['close']].tail())
