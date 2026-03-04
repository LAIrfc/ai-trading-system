"""
市场数据获取模块
使用东方财富 HTTP 接口获取 A 股 ETF 的历史和最新行情数据
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger
import os
import json


# ETF 观察池定义
ETF_POOL = {
    '510300': {'name': '沪深300ETF', 'short': '沪深300', 'market': 1},
    '159949': {'name': '创业板50ETF', 'short': '创业板50', 'market': 0},
    '513100': {'name': '纳指ETF',     'short': '纳指',     'market': 1},
    '518880': {'name': '黄金ETF',     'short': '黄金',     'market': 1},
    '511520': {'name': '国债ETF',     'short': '国债',     'market': 1},
}

# 缓存目录（使用 mycache 目录）
CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'mycache', 'market_data')


class MarketData:
    """市场数据管理器（东方财富数据源）"""

    def __init__(self, use_cache: bool = True):
        self.use_cache = use_cache
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
            'Referer': 'http://quote.eastmoney.com/',
        })
        os.makedirs(CACHE_DIR, exist_ok=True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._session.close()

    def _fetch_from_eastmoney(self, code: str, limit: int = 500) -> pd.DataFrame:
        """
        从东方财富获取 ETF 日线数据

        Args:
            code: ETF 代码，如 '510300'
            limit: 获取的数据条数

        Returns:
            DataFrame: columns=[date, open, high, low, close, volume, amount]
        """
        info = ETF_POOL.get(code)
        if info is None:
            # 猜测市场
            market = 1 if code.startswith(('5', '6')) else 0
        else:
            market = info['market']

        url = 'http://push2his.eastmoney.com/api/qt/stock/kline/get'
        params = {
            'secid': f'{market}.{code}',
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '101',          # 日线
            'fqt': '1',            # 前复权
            'lmt': str(limit),
            'end': '20500101',
            '_': '1',
        }

        try:
            resp = self._session.get(url, params=params, timeout=10)
            data = resp.json()
        except Exception as e:
            logger.error(f"请求东方财富失败 ({code}): {e}")
            return pd.DataFrame()

        if not data.get('data') or not data['data'].get('klines'):
            logger.warning(f"{code} 无数据返回")
            return pd.DataFrame()

        records = []
        for line in data['data']['klines']:
            parts = line.split(',')
            records.append({
                'date': parts[0],
                'open': float(parts[1]),
                'close': float(parts[2]),
                'high': float(parts[3]),
                'low': float(parts[4]),
                'volume': float(parts[5]),
                'amount': float(parts[6]),
            })

        df = pd.DataFrame(records)
        df['date'] = pd.to_datetime(df['date'])
        return df

    def get_history(self, code: str, days: int = 500) -> pd.DataFrame:
        """
        获取历史日线数据

        Args:
            code: ETF代码，如 '510300'
            days: 获取的交易日数量

        Returns:
            DataFrame: columns=[date, open, high, low, close, volume, amount]
        """
        # 检查缓存
        today_str = datetime.now().strftime('%Y%m%d')
        cache_file = os.path.join(CACHE_DIR, f"{code}_{days}_{today_str}.csv")

        if self.use_cache and os.path.exists(cache_file):
            mtime = os.path.getmtime(cache_file)
            # 缓存有效期: 交易时间内1小时，非交易时间12小时
            hour = datetime.now().hour
            ttl = 3600 if 9 <= hour <= 16 else 43200
            if (datetime.now().timestamp() - mtime) < ttl:
                try:
                    df = pd.read_csv(cache_file, parse_dates=['date'])
                    if len(df) > 0:
                        logger.debug(f"使用缓存: {code} ({len(df)} 条)")
                        return df
                except Exception:
                    pass

        # 从东方财富获取
        df = self._fetch_from_eastmoney(code, limit=days)

        if len(df) > 0:
            # 保存缓存
            if self.use_cache:
                df.to_csv(cache_file, index=False)
            logger.info(f"获取 {code} 日线: {len(df)} 条 "
                        f"({df['date'].min().strftime('%Y-%m-%d')} ~ "
                        f"{df['date'].max().strftime('%Y-%m-%d')})")
        else:
            logger.warning(f"{code} 无数据")

        return df

    def get_all_etf_history(self, days: int = 500) -> Dict[str, pd.DataFrame]:
        """获取观察池中所有 ETF 的历史数据"""
        result = {}
        for code in ETF_POOL:
            df = self.get_history(code, days=days)
            if len(df) > 0:
                result[code] = df
        return result

    def get_latest_prices(self) -> Dict[str, dict]:
        """获取所有 ETF 的最新价格"""
        result = {}
        for code, info in ETF_POOL.items():
            df = self.get_history(code, days=5)
            if len(df) > 0:
                latest = df.iloc[-1]
                result[code] = {
                    'name': info['name'],
                    'short': info['short'],
                    'date': latest['date'].strftime('%Y-%m-%d') if isinstance(latest['date'], pd.Timestamp) else str(latest['date']),
                    'close': float(latest['close']),
                    'volume': float(latest['volume']),
                    'amount': float(latest['amount']),
                }
        return result

    def get_market_overview(self) -> str:
        """获取市场概览文本"""
        prices = self.get_latest_prices()
        lines = ["📊 市场概览", "=" * 50]
        for code, p in prices.items():
            lines.append(
                f"  {p['short']:6s} ({code})  "
                f"收盘: {p['close']:>10.4f}  "
                f"成交额: {p['amount']/1e8:>8.2f}亿  "
                f"日期: {p['date']}"
            )
        lines.append("=" * 50)
        return '\n'.join(lines)
