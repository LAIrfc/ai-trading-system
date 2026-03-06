"""
日线 K 线各数据源适配器实现

每个适配器封装单一数据源，输出统一 schema（date, open, high, low, close, volume）。
内部委托 data_prefetch 现有 _fetch_*，避免重复实现与循环依赖（适配器内按需 import）。
"""

from datetime import datetime, timedelta
from typing import Optional
import os
from pathlib import Path

import pandas as pd

from .base import KlineAdapter, KLINE_COLUMNS


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    """保证输出仅含标准列且类型正确。"""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    for c in KLINE_COLUMNS:
        if c not in out.columns:
            return pd.DataFrame()
    out["date"] = pd.to_datetime(out["date"])
    for c in ["open", "high", "low", "close", "volume"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out[KLINE_COLUMNS].dropna(subset=["close"]).reset_index(drop=True)


def _datalen_from_range(start_date: Optional[str], end_date: Optional[str], default: int = 800) -> int:
    """由 start_date/end_date 估算条数；缺省用 default。"""
    if not start_date or not end_date:
        return default
    try:
        start = datetime.strptime(start_date, "%Y%m%d")
        end = datetime.strptime(end_date, "%Y%m%d")
        return max(1, min(2000, (end - start).days + 60))
    except Exception:
        return default


class SinaKlineAdapter(KlineAdapter):
    """新浪财经日线：money.finance.sina KLine。"""

    @property
    def source_id(self) -> str:
        return "sina"

    def get_kline(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        datalen: Optional[int] = None,
        timeout: int = 10,
        **kwargs,
    ) -> pd.DataFrame:
        if datalen is None:
            datalen = _datalen_from_range(start_date, end_date, 800)
        from src.data.fetchers.data_prefetch import _fetch_sina_kline

        df = _fetch_sina_kline(symbol.strip(), datalen, timeout=timeout)
        return _ensure_columns(df)


class EastMoneyKlineAdapter(KlineAdapter):
    """东方财富日线：akshare stock_zh_a_hist。"""

    @property
    def source_id(self) -> str:
        return "eastmoney"

    def get_kline(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        datalen: Optional[int] = None,
        **kwargs,
    ) -> pd.DataFrame:
        if datalen is None:
            datalen = _datalen_from_range(start_date, end_date, 800)
        from src.data.fetchers.data_prefetch import _fetch_eastmoney_akshare

        df = _fetch_eastmoney_akshare(symbol.strip(), datalen)
        return _ensure_columns(df)


class TencentKlineAdapter(KlineAdapter):
    """腾讯财经日线：web.ifzq.gtimg.cn kline。"""

    @property
    def source_id(self) -> str:
        return "tencent"

    def get_kline(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        datalen: Optional[int] = None,
        timeout: int = 10,
        **kwargs,
    ) -> pd.DataFrame:
        if datalen is None:
            datalen = _datalen_from_range(start_date, end_date, 800)
        from src.data.fetchers.data_prefetch import _fetch_tencent_kline

        df = _fetch_tencent_kline(symbol.strip(), datalen, timeout=timeout)
        return _ensure_columns(df)


class TushareKlineAdapter(KlineAdapter):
    """tushare 日线：pro.daily，需 config/data.tushare_token 或 TUSHARE_TOKEN。"""

    @property
    def source_id(self) -> str:
        return "tushare"

    def get_kline(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        datalen: Optional[int] = None,
        timeout: int = 10,
        **kwargs,
    ) -> pd.DataFrame:
        if datalen is None:
            datalen = _datalen_from_range(start_date, end_date, 800)
        from src.data.fetchers.data_prefetch import _fetch_tushare_kline

        df = _fetch_tushare_kline(symbol.strip(), datalen, timeout=timeout)
        return _ensure_columns(df)


class AkshareETFAdapter(KlineAdapter):
    """akshare ETF 多源适配器：新浪 -> 网易 -> 东方财富，专用于 ETF。"""

    @property
    def source_id(self) -> str:
        return "akshare_etf"

    def get_kline(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        datalen: Optional[int] = None,
        timeout: int = 10,
        **kwargs,
    ) -> pd.DataFrame:
        """
        ETF 专用多源获取：新浪 -> 网易 -> 东方财富
        内部多源切换，只要有一个成功就返回
        """
        import akshare as ak
        import time
        import random
        import logging

        logger = logging.getLogger(__name__)
        code = symbol.strip()
        end_d = end_date or pd.Timestamp.now().strftime('%Y%m%d')
        start_d = start_date or "20180101"
        common_kw = dict(period="daily", start_date=start_d, end_date=end_d, adjust="")

        sources = [
            ('新浪', getattr(ak, 'fund_etf_hist_sina', None), {'symbol': code}),
            ('网易', getattr(ak, 'fund_etf_hist_163', None), {'symbol': code, **common_kw}),
            ('东方财富', ak.fund_etf_hist_em, {'symbol': code, **common_kw}),
        ]

        last_error = None
        for source_name, fetch_func, fetch_kwargs in sources:
            if fetch_func is None:
                continue
            try:
                time.sleep(random.uniform(0.5, 2))
                df = fetch_func(**fetch_kwargs)
                out = self._normalize_etf_df(df)
                if out is not None and len(out) >= 60:
                    logger.debug(f"[AkshareETFAdapter] {code} 从 {source_name} 获取成功")
                    return out
            except Exception as e:
                last_error = e
                logger.debug(f"[AkshareETFAdapter] {code} 从 {source_name} 失败: {e}")
                continue

        if last_error:
            logger.warning(f"[AkshareETFAdapter] {code} 所有子源均失败，最后错误: {last_error}")
        return pd.DataFrame()

    def _normalize_etf_df(self, df):
        """统一 ETF DataFrame 格式"""
        if df is None or df.empty:
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
        return df if len(df) >= 60 else None


class Push2hisETFAdapter(KlineAdapter):
    """东方财富 push2his 直接接口，专用于 ETF，作为 akshare_etf 的备用。"""

    @property
    def source_id(self) -> str:
        return "push2his_etf"

    def get_kline(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        datalen: Optional[int] = None,
        timeout: int = 10,
        **kwargs,
    ) -> pd.DataFrame:
        """
        直接用东方财富 push2his 接口请求 ETF 日 K
        """
        import requests
        import logging

        logger = logging.getLogger(__name__)
        code = symbol.strip()
        secid = f"1.{code}" if code.startswith('5') else f"0.{code}"
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "1",
            "end": "20500101",
            "lmt": str(datalen or 800),
        }
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            data = resp.json()
            if not data.get("data") or not data["data"].get("klines"):
                logger.debug(f"[Push2hisETFAdapter] {code} 返回数据为空")
                return pd.DataFrame()

            rows = []
            for k in data["data"]["klines"]:
                parts = k.split(",")
                rows.append({
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),
                })
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            df = df[KLINE_COLUMNS].sort_values("date").reset_index(drop=True)
            logger.debug(f"[Push2hisETFAdapter] {code} 获取成功: {len(df)} 条")
            return df if len(df) >= 60 else pd.DataFrame()
        except Exception as e:
            logger.debug(f"[Push2hisETFAdapter] {code} 请求失败: {e}")
            return pd.DataFrame()


class LocalCacheAdapter(KlineAdapter):
    """
    本地缓存适配器：从 mycache/etf_kline/ 或 mydate/backtest_kline/ 读取本地缓存的 K 线数据。
    作为所有网络数据源的最后备用方案。
    """

    @property
    def source_id(self) -> str:
        return "local_cache"

    def get_kline(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        datalen: Optional[int] = None,
        timeout: int = 10,
        **kwargs,
    ) -> pd.DataFrame:
        """
        从本地缓存读取 K 线数据
        """
        import logging
        
        logger = logging.getLogger(__name__)
        code = symbol.strip()
        
        # 查找缓存文件的可能位置
        base_paths = [
            Path(__file__).resolve().parents[3],  # 项目根目录
            Path.cwd(),
        ]
        
        cache_dirs = [
            'mycache/etf_kline',
            'mydate/backtest_kline',
            'mycache/stock_kline',
        ]
        
        # 尝试读取最近的缓存文件
        for base in base_paths:
            for cache_dir in cache_dirs:
                cache_path = base / cache_dir
                if not cache_path.exists():
                    continue
                
                # 查找匹配的文件（支持 code.csv, code_YYYYMMDD.csv, code.parquet 等）
                # 优先查找带日期后缀的文件（更新鲜）
                all_matches = []
                all_matches.extend(cache_path.glob(f"{code}_*.csv"))
                all_matches.extend(cache_path.glob(f"{code}_*.parquet"))
                all_matches.extend(cache_path.glob(f"{code}.csv"))
                all_matches.extend(cache_path.glob(f"{code}.parquet"))
                
                if all_matches:
                    # 按修改时间排序，取最新的
                    latest = max(all_matches, key=lambda p: p.stat().st_mtime)
                    try:
                        if latest.suffix == '.parquet':
                            df = pd.read_parquet(latest)
                        else:
                            df = pd.read_csv(latest, parse_dates=['date'])
                        
                        if 'date' in df.columns and len(df) >= 60:
                            # 确保列名正确
                            required = ['date', 'open', 'high', 'low', 'close', 'volume']
                            if all(c in df.columns for c in required):
                                df = df[required].copy()
                                df['date'] = pd.to_datetime(df['date'])
                                df = df.sort_values('date').reset_index(drop=True)
                                logger.info(f"[LocalCacheAdapter] {code} 从本地缓存加载成功: {latest.name}, {len(df)} 条")
                                return df
                    except Exception as e:
                        logger.debug(f"[LocalCacheAdapter] {code} 读取 {latest} 失败: {e}")
                        continue
        
        logger.debug(f"[LocalCacheAdapter] {code} 未找到有效的本地缓存")
        return pd.DataFrame()


class BaostockETFAdapter(KlineAdapter):
    """baostock ETF 适配器，作为最后的备用方案。"""

    @property
    def source_id(self) -> str:
        return "baostock_etf"

    def get_kline(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        datalen: Optional[int] = None,
        timeout: int = 10,
        **kwargs,
    ) -> pd.DataFrame:
        """
        使用 baostock 获取 ETF 数据
        """
        import logging
        
        logger = logging.getLogger(__name__)
        code = symbol.strip()
        
        try:
            import baostock as bs
            
            # 判断交易所
            if code.startswith('5') or code.startswith('6'):
                exchange = 'sh'
            elif code.startswith('159') or code.startswith('15'):
                exchange = 'sz'
            else:
                exchange = 'sz'
            
            bs_code = f'{exchange}.{code}'
            
            # 日期范围
            if end_date:
                end_str = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
            else:
                end_str = datetime.now().strftime('%Y-%m-%d')
            
            if start_date:
                start_str = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
            else:
                start_str = (datetime.now() - timedelta(days=1200)).strftime('%Y-%m-%d')
            
            # 查询数据
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume",
                start_date=start_str,
                end_date=end_str,
                frequency="d",
                adjustflag="2"
            )
            
            if rs.error_code != '0':
                logger.debug(f"[BaostockETFAdapter] {code} baostock 查询失败: {rs.error_msg}")
                return pd.DataFrame()
            
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            
            if not rows:
                return pd.DataFrame()
            
            df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
            df['date'] = pd.to_datetime(df['date'])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df = df.dropna(subset=['close']).sort_values('date').reset_index(drop=True)
            
            logger.debug(f"[BaostockETFAdapter] {code} 获取成功: {len(df)} 条")
            return df if len(df) >= 60 else pd.DataFrame()
            
        except Exception as e:
            logger.debug(f"[BaostockETFAdapter] {code} 异常: {e}")
            return pd.DataFrame()


# 注册名 -> 适配器类，供 UnifiedDataProvider 按配置实例化
KLINE_ADAPTER_REGISTRY = {
    "sina": SinaKlineAdapter,
    "eastmoney": EastMoneyKlineAdapter,
    "tencent": TencentKlineAdapter,
    "tushare": TushareKlineAdapter,
    "akshare_etf": AkshareETFAdapter,
    "push2his_etf": Push2hisETFAdapter,
    "baostock_etf": BaostockETFAdapter,
    "local_cache": LocalCacheAdapter,
}
