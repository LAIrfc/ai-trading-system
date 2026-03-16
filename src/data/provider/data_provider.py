"""
统一数据提供层：按配置主备切换，策略层仅调用 get_kline/get_sector_stocks，无需关心底层数据源。

盘中增强：日K线获取成功后，若最新一行不是今天且当前处于交易时段或盘后，
自动调用实时行情接口拼接当日OHLCV，使策略层在盘中也能获取到当天数据。
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple, Dict

import pandas as pd
import yaml

from .base import KlineAdapter, SectorAdapter, KLINE_COLUMNS
from .adapters import KLINE_ADAPTER_REGISTRY, fetch_realtime_bar
from .sector_adapters import SECTOR_ADAPTER_REGISTRY

logger = logging.getLogger(__name__)

try:
    from src.data.monitor import record_fetch
except ImportError:
    def record_fetch(source: str, success: bool, elapsed_seconds: float = 0.0, used_backup: bool = False) -> None:
        pass

# 默认主备顺序，与 docs/data/API_INTERFACES_AND_FETCHERS.md 一致
DEFAULT_KLINE_SOURCES = ["sina", "eastmoney", "tencent", "tushare", "baostock"]


DEFAULT_ETF_SOURCES = ["akshare_etf", "push2his_etf"]
DEFAULT_SECTOR_SOURCES = ["akshare", "eastmoney", "sina", "baostock", "local"]


def _load_sources_config() -> Tuple[List[str], List[str], List[str]]:
    """
    从 config/data_sources.yaml 统一读取三类数据源顺序配置。

    Returns:
        (stock_sources, etf_sources, sector_sources)
    """
    stock_sources = DEFAULT_KLINE_SOURCES
    etf_sources = DEFAULT_ETF_SOURCES
    sector_sources = DEFAULT_SECTOR_SOURCES

    def _parse_list(raw) -> List[str]:
        if isinstance(raw, list) and raw:
            return [str(s).strip().lower() for s in raw]
        return []

    for base in [Path(__file__).resolve().parents[3], Path.cwd()]:
        ds = base / "config" / "data_sources.yaml"
        if ds.is_file():
            try:
                with open(ds, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if not isinstance(data, dict):
                    continue
                kline = data.get("kline", {})
                if isinstance(kline, dict):
                    parsed = _parse_list(kline.get("sources"))
                    if parsed:
                        stock_sources = parsed
                    parsed = _parse_list(kline.get("etf_sources"))
                    if parsed:
                        etf_sources = parsed
                sector = data.get("sector", {})
                if isinstance(sector, dict):
                    parsed = _parse_list(sector.get("sources"))
                    if parsed:
                        sector_sources = parsed
                return stock_sources, etf_sources, sector_sources
            except Exception as e:
                logger.debug("读取 data_sources.yaml 失败: %s", e)
        # 兼容旧版 trading_config.yaml（仅股票 K 线）
        tc = base / "config" / "trading_config.yaml"
        if tc.is_file():
            try:
                with open(tc, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict) and isinstance(data.get("data"), dict):
                    parsed = _parse_list(data["data"].get("kline_sources"))
                    if parsed:
                        stock_sources = parsed
                return stock_sources, etf_sources, sector_sources
            except Exception as e:
                logger.debug("读取 trading_config.yaml 失败: %s", e)
    return stock_sources, etf_sources, sector_sources


class UnifiedDataProvider:
    """
    统一日线数据提供层：按配置顺序尝试各适配器，熔断/腾讯 3 日逻辑委托 data_prefetch，策略层只调 get_kline。
    支持股票和 ETF 分别配置数据源顺序。
    """

    def __init__(
        self,
        sources: Optional[List[str]] = None,
        etf_sources: Optional[List[str]] = None,
        sector_sources: Optional[List[str]] = None,
    ):
        """
        Args:
            sources: 股票 K 线数据源顺序，None 时从 config/data_sources.yaml 读取。
            etf_sources: ETF K 线数据源顺序，None 时从 config/data_sources.yaml 读取。
            sector_sources: 板块成分股数据源顺序，None 时从 config/data_sources.yaml 读取。
        """
        config_stock, config_etf, config_sector = _load_sources_config()
        self._source_order = sources if sources is not None else config_stock
        self._etf_source_order = etf_sources if etf_sources is not None else config_etf
        self._sector_source_order = sector_sources if sector_sources is not None else config_sector

        # 初始化股票 K 线适配器
        self._adapters: List[KlineAdapter] = []
        for name in self._source_order:
            name = name.strip().lower()
            if name in KLINE_ADAPTER_REGISTRY:
                self._adapters.append(KLINE_ADAPTER_REGISTRY[name]())
            else:
                logger.warning("[UnifiedDataProvider] 未知 kline 数据源 %s，已忽略", name)
        if not self._adapters:
            self._adapters = [KLINE_ADAPTER_REGISTRY[n]() for n in DEFAULT_KLINE_SOURCES if n in KLINE_ADAPTER_REGISTRY]
            logger.warning("[UnifiedDataProvider] 无有效配置，使用默认顺序: %s", [a.source_id for a in self._adapters])

        # 初始化 ETF K 线适配器
        self._etf_adapters: List[KlineAdapter] = []
        for name in self._etf_source_order:
            name = name.strip().lower()
            if name in KLINE_ADAPTER_REGISTRY:
                self._etf_adapters.append(KLINE_ADAPTER_REGISTRY[name]())
            else:
                logger.warning("[UnifiedDataProvider] 未知 ETF 数据源 %s，已忽略", name)

        # 初始化板块成分股适配器
        self._sector_adapters: List[SectorAdapter] = []
        for name in self._sector_source_order:
            name = name.strip().lower()
            if name in SECTOR_ADAPTER_REGISTRY:
                self._sector_adapters.append(SECTOR_ADAPTER_REGISTRY[name]())
            else:
                logger.warning("[UnifiedDataProvider] 未知板块数据源 %s，已忽略", name)
        if not self._sector_adapters:
            self._sector_adapters = [SECTOR_ADAPTER_REGISTRY[n]() for n in DEFAULT_SECTOR_SOURCES if n in SECTOR_ADAPTER_REGISTRY]
            logger.warning("[UnifiedDataProvider] 板块数据源无有效配置，使用默认顺序: %s", [a.source_id for a in self._sector_adapters])

    @staticmethod
    def _is_trading_day_today() -> bool:
        """粗略判断今天是否为交易日（周一~周五）。"""
        return datetime.now().weekday() < 5

    @staticmethod
    def _append_realtime(df: pd.DataFrame, code: str) -> pd.DataFrame:
        """
        盘中增强：如果日K线最新日期不是今天，且今天是交易日，
        就用实时行情接口获取当天OHLCV并拼接到末尾。
        这样策略层在盘中也能拿到当天数据。
        """
        if df is None or df.empty:
            return df
        if not UnifiedDataProvider._is_trading_day_today():
            return df

        now = datetime.now()
        # 9:15 之前没有盘中数据
        if now.hour < 9 or (now.hour == 9 and now.minute < 15):
            return df

        today_str = now.strftime('%Y-%m-%d')
        try:
            last_date = pd.Timestamp(df['date'].iloc[-1])
            if last_date.strftime('%Y-%m-%d') >= today_str:
                return df
        except Exception:
            return df

        try:
            rt = fetch_realtime_bar(code)
            if rt is not None and not rt.empty:
                # 保留原始 df 的列（可能含 data_source, fetched_at 等额外列）
                for col in df.columns:
                    if col not in rt.columns:
                        if col == 'data_source':
                            rt[col] = 'realtime'
                        elif col == 'fetched_at':
                            rt[col] = now.isoformat()
                        else:
                            rt[col] = None
                df = pd.concat([df, rt[df.columns]], ignore_index=True)
                logger.debug("[UnifiedDataProvider] 标的=%s 已拼接当日实时数据", code)
        except Exception as e:
            logger.debug("[UnifiedDataProvider] 标的=%s 拼接实时数据失败: %s", code, e)

        return df

    def get_kline(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        datalen: Optional[int] = None,
        min_bars: int = 100,
        retries: int = 3,
        timeout: int = 10,
        is_etf: Optional[bool] = None,
    ) -> pd.DataFrame:
        """
        获取个股/ETF日线，按配置主备尝试，返回统一 schema（含 data_source、fetched_at）。

        Args:
            symbol: 股票/ETF代码。
            start_date: 开始日期 YYYYMMDD。
            end_date: 结束日期 YYYYMMDD。
            datalen: 最近 N 条（与 start/end 二选一）。
            min_bars: 最少条数，不足视为失败并尝试下一源。
            retries: 仅对第一个数据源（主源）重试次数。
            timeout: 请求超时秒数。
            is_etf: 是否为 ETF，None 时自动判断（5/159 开头且 6 位数）。

        Returns:
            标准化 DataFrame；全部失败返回空 DataFrame。
        """
        from src.data.fetchers.data_prefetch import (
            _circuit_allow,
            _circuit_record,
            _tag_df_source,
            _tencent_allow_by_3day,
            _tencent_record_fail,
        )

        code = symbol.strip()
        if datalen is None and (start_date or end_date):
            from datetime import datetime as _dt, timedelta as _td
            end_d = _dt.now()
            start_d = end_d - _td(days=800)
            if end_date:
                try:
                    end_d = _dt.strptime(end_date, "%Y%m%d")
                except Exception:
                    pass
            if start_date:
                try:
                    start_d = _dt.strptime(start_date, "%Y%m%d")
                except Exception:
                    pass
            datalen = max(1, (end_d - start_d).days + 60)
        if datalen is None:
            datalen = 800

        # 自动判断是否为 ETF（5/159 开头且 6 位数）
        if is_etf is None:
            is_etf = (code.startswith('5') or code.startswith('159')) and len(code) == 6

        # ETF 数据源有限（baostock 免费版仅返回近几十条），降低最低条数要求
        if is_etf and min_bars > 20:
            min_bars = 20

        # ETF 使用专用适配器，股票使用普通适配器
        if is_etf and self._etf_adapters:
            adapters_to_use = self._etf_adapters
        else:
            adapters_to_use = self._adapters

        primary_err: Optional[str] = None
        used_backup = False

        for i, adapter in enumerate(adapters_to_use):
            sid = adapter.source_id
            if sid == "tencent" and not _tencent_allow_by_3day():
                continue
            # 本地缓存不受熔断限制（纯本地操作，无网络问题）
            if sid != "local_cache" and not _circuit_allow(sid):
                logger.debug("[UnifiedDataProvider] 跳过 %s（熔断）", sid)
                continue

            t0 = time.time()
            is_primary = i == 0
            # ETF 适配器不重试（内部已有多源切换），股票适配器才重试
            is_etf_adapter = sid in ["akshare_etf", "push2his_etf"]
            retry_count = 1 if is_etf_adapter else retries
            
            try:
                df = adapter.get_kline(
                    symbol=code,
                    start_date=start_date,
                    end_date=end_date,
                    datalen=datalen,
                    timeout=timeout,
                )
                if df is not None and not df.empty and len(df) >= min_bars:
                    _circuit_record(sid, True)
                    record_fetch(sid, True, time.time() - t0, used_backup=used_backup)
                    out = _tag_df_source(df, sid)
                    if used_backup:
                        logger.info(
                            "[UnifiedDataProvider] 标的=%s 主源失败(%s)，已用备用 %s 成功",
                            code, primary_err, sid,
                        )
                    return self._append_realtime(out, code)
                primary_err = "返回空或条数不足"
            except Exception as e:
                primary_err = repr(e)
                if is_primary:
                    logger.warning("[UnifiedDataProvider] 标的=%s 主源 %s 异常: %s", code, sid, primary_err)
                else:
                    logger.debug("[UnifiedDataProvider] 标的=%s 备用 %s 失败: %s", code, sid, primary_err)

            # local_cache失败不记录（避免因缓存缺失触发熔断）
            if sid != "local_cache":
                _circuit_record(sid, False)
            if sid == "tencent":
                _tencent_record_fail()
            record_fetch(sid, False, time.time() - t0, used_backup=used_backup)
            used_backup = True

            # 仅对主源且非 ETF 适配器做重试
            if is_primary and retry_count > 1:
                for attempt in range(1, retry_count):
                    time.sleep(2 ** (attempt - 1))
                    t1 = time.time()
                    try:
                        df = adapter.get_kline(symbol=code, datalen=datalen, timeout=timeout)
                        if df is not None and not df.empty and len(df) >= min_bars:
                            _circuit_record(sid, True)
                            record_fetch(sid, True, time.time() - t1, used_backup=False)
                            return self._append_realtime(_tag_df_source(df, sid), code)
                    except Exception:
                        pass
                    # local_cache失败不记录
                    if sid != "local_cache":
                        _circuit_record(sid, False)
                    record_fetch(sid, False, time.time() - t1, used_backup=False)

        logger.warning(
            "[UnifiedDataProvider] 标的=%s 全部数据源失败或熔断，最后错误: %s",
            code, primary_err,
        )
        return pd.DataFrame()

    def get_sector_stocks(
        self,
        sector_config: Dict[str, any],
        target: int = 15,
    ) -> List[Dict[str, any]]:
        """
        获取板块成分股，按配置的数据源顺序自动切换。
        
        Args:
            sector_config: 板块配置，包含各数据源的板块代码/名称
                {
                    'akshare': ['光伏概念'],
                    'eastmoney': ['BK1031'],
                    'sina': ['new_xxx'],
                    'baostock': ['有色'],
                    'keywords': ['关键词1', '关键词2', ...],
                }
            target: 目标数量
        
        Returns:
            List[Dict]: 成分股列表，每个元素包含 code, name, market_cap_yi
        """
        all_stocks = []
        
        # 所有数据源全部尝试并合并，不因数量达标而提前退出
        for adapter in self._sector_adapters:
            sid = adapter.source_id
            
            # 获取该数据源的配置
            source_codes = sector_config.get(sid, [])
            if not source_codes:
                continue
            
            logger.info(f"[UnifiedDataProvider] 尝试 {sid} 获取板块数据...")
            
            # 尝试该数据源的所有板块代码
            for sector_code in source_codes:
                try:
                    kwargs = {}
                    if sid == 'local':
                        kwargs['keywords'] = sector_config.get('keywords', [])
                    
                    stocks = adapter.get_sector_stocks(
                        sector_code=sector_code,
                        limit=target * 3,
                        **kwargs
                    )
                    
                    if stocks:
                        logger.info(f"[UnifiedDataProvider] {sid} {sector_code} 成功: {len(stocks)}只")
                        all_stocks.extend(stocks)
                    
                except Exception as e:
                    logger.warning(f"[UnifiedDataProvider] {sid} {sector_code} 失败: {e}")
                
                time.sleep(1)
        
        # 去重并按市值排序
        unique_stocks = {}
        for s in all_stocks:
            code = s['code']
            if code not in unique_stocks:
                unique_stocks[code] = s
        
        stocks_list = list(unique_stocks.values())
        stocks_list.sort(key=lambda x: x.get('market_cap_yi', 0), reverse=True)
        
        # 关键词过滤（如果有）
        keywords = sector_config.get('keywords', [])
        if keywords:
            filtered = []
            for s in stocks_list:
                name_lower = s['name'].lower()
                for kw in keywords:
                    if kw.lower() in name_lower:
                        filtered.append(s)
                        break
            stocks_list = filtered
        
        # 返回前N只
        return stocks_list[:target]


_default_provider: Optional[UnifiedDataProvider] = None


def get_default_kline_provider(sources: Optional[List[str]] = None) -> UnifiedDataProvider:
    """获取默认日线数据提供者（单例，首次根据 config 或 sources 构建）。"""
    global _default_provider
    if _default_provider is None:
        _default_provider = UnifiedDataProvider(sources=sources)
    return _default_provider


def reset_default_kline_provider() -> None:
    """重置默认 provider（测试或重载配置时用）。"""
    global _default_provider
    _default_provider = None
