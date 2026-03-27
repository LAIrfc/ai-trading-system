"""
统一数据预取与主备接口封装（对齐 docs/data/API_INTERFACES_AND_FETCHERS.md）

- 基础日线：主 Sina → 备1 东方财富(akshare) → 备2 腾讯 → 备3 tushare；token 取自 config 或 TUSHARE_TOKEN；timeout=10，异常不中断。
- 实时快照：Sina hq.sinajs.cn/list=、东方财富 push2.eastmoney.com/api/qt/stock/get（预留）。
- 所有请求统一超时/重试/日志，便于回测预取与实盘熔断扩展。
"""

import json
import logging
import time
from datetime import date, datetime, timedelta
from typing import Callable, List, Optional, Tuple

import pandas as pd
import requests

logger = logging.getLogger(__name__)

try:
    from src.data.monitor import record_fetch
except ImportError:
    def record_fetch(source: str, success: bool, elapsed_seconds: float = 0.0, used_backup: bool = False) -> None:
        pass

# 与文档一致：基础行情 timeout=10
STOCK_DAILY_TIMEOUT = 10
STOCK_DAILY_RETRIES = 3
# 熔断：连续失败次数阈值、熔断时长（秒），与文档 3.1 一致
CIRCUIT_FAIL_THRESHOLD = 3
CIRCUIT_OPEN_SECONDS = 300
# ETF 源单独设置更宽松的阈值（ETF 数据源少，单个标的失败不代表源不可用）
_ETF_SOURCES = {"akshare_etf", "push2his_etf", "baostock_etf"}
CIRCUIT_FAIL_THRESHOLD_ETF = 10
CIRCUIT_OPEN_SECONDS_ETF = 60
# 各数据源熔断状态：(连续失败次数, 最后失败时间戳)
_circuit_state = {
    "sina": [0, 0.0], 
    "eastmoney": [0, 0.0], 
    "tencent": [0, 0.0], 
    "tushare": [0, 0.0],
    "akshare_etf": [0, 0.0],
    "push2his_etf": [0, 0.0],
    "baostock_etf": [0, 0.0],
    "local_cache": [0, 0.0],
}
# 日线内存缓存：key=(code, datalen), value=(df, ts)；与文档 3.3 一致，日频可短期复用
DAILY_CACHE_TTL_SECONDS = 300
_daily_cache: dict = {}  # (code, datalen) -> (pd.DataFrame, float)
# 文档 2.1：腾讯连续 3 个自然日失败则暂时移除并告警
_tencent_fail_dates: List[date] = []  # 腾讯失败过的日期，仅保留最近 7 天
TENCENT_3DAY_ALERT_CALLBACK: Optional[Callable[[str], None]] = None  # 告警回调，参数为消息


def _tencent_allow_by_3day() -> bool:
    """若最近 3 个自然日均失败则不允许使用腾讯并触发告警。"""
    global _tencent_fail_dates
    today = date.today()
    recent = [today - timedelta(days=i) for i in range(1, 4)]  # 昨天、前天、大前天
    if all(d in _tencent_fail_dates for d in recent):
        msg = "[data_prefetch] 腾讯日线连续 3 自然日失败，暂时移除备用并告警"
        logger.warning(msg)
        if TENCENT_3DAY_ALERT_CALLBACK:
            try:
                TENCENT_3DAY_ALERT_CALLBACK(msg)
            except Exception as e:
                logger.debug("告警回调异常: %s", e)
        return False
    return True


def _tencent_record_fail() -> None:
    """记录今日腾讯失败，用于 3 日连续失败判断。"""
    global _tencent_fail_dates
    _tencent_fail_dates = [d for d in _tencent_fail_dates if (date.today() - d).days <= 7]
    _tencent_fail_dates.append(date.today())


# 文档 3.1：数据加时间戳与源标识
def _tag_df_source(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """为 DataFrame 添加 data_source、fetched_at 列（文档 3.1）。"""
    if df is None or df.empty:
        return df
    d = df.copy()
    d["data_source"] = source
    d["fetched_at"] = datetime.now().isoformat()
    return d


def _market_prefix(code: str) -> Tuple[str, str]:
    """沪市 6/5 → sh；深市 0/3/2 → sz。北交所 8/4 暂不处理。"""
    code = code.strip()
    if code.startswith(("5", "6")):
        return "sh", code
    if code.startswith(("0", "3", "2")):
        return "sz", code
    return "sz", code


def _eastmoney_secid(code: str) -> str:
    """东方财富 secid：0=深市，1=沪市，后接代码。文档：secid=0.000001"""
    if code.startswith(("5", "6")):
        return f"1.{code}"
    return f"0.{code}"


# ------ 主数据源：Sina 日线 K 线（与文档 money.finance.sina KLine 一致）------
def _fetch_sina_kline(code: str, datalen: int, timeout: int = STOCK_DAILY_TIMEOUT) -> pd.DataFrame:
    """Sina 日线 K 线：CN_MarketData.getKLineData。"""
    prefix, sym = _market_prefix(code)
    symbol = f"{prefix}{sym}"
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    
    # 添加完整的请求头以避免403错误
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.sina.com.cn/",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    
    try:
        r = requests.get(
            url,
            params={"symbol": symbol, "scale": "240", "ma": "no", "datalen": str(datalen)},
            headers=headers,
            timeout=timeout,
        )
        r.raise_for_status()  # 检查HTTP状态码
        data = json.loads(r.text) if r.text and r.text.strip() else None
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["day"])
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df
    except Exception as e:
        logger.debug(f"新浪K线获取失败 {code}: {e}")
        return pd.DataFrame()


# ------ 备用1：东方财富（akshare 日线，文档推荐）------
def _fetch_eastmoney_akshare(code: str, datalen: int, max_retries: int = 2) -> pd.DataFrame:
    """东方财富源：通过 akshare stock_zh_a_hist 获取日线，带重试机制。"""
    try:
        import akshare as ak
    except ImportError:
        return pd.DataFrame()
    
    for attempt in range(max_retries):
        try:
            end_d = datetime.now()
            start_d = end_d - timedelta(days=min(datalen + 60, 800))
            start_str = start_d.strftime("%Y%m%d")
            end_str = end_d.strftime("%Y%m%d")
            symbol = code if len(code) <= 6 else code[-6:] if code.isdigit() else code
            
            # 添加超时和重试
            import time
            if attempt > 0:
                time.sleep(1)  # 重试前等待1秒
            
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_str, end_date=end_str, adjust="")
            if df is None or df.empty:
                if attempt < max_retries - 1:
                    continue
                return pd.DataFrame()
            
            col_map = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume"}
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            if "date" not in df.columns:
                if attempt < max_retries - 1:
                    continue
                return pd.DataFrame()
            
            df["date"] = pd.to_datetime(df["date"])
            for c in ["open", "high", "low", "close", "volume"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            return df[["date", "open", "high", "low", "close", "volume"]].dropna(subset=["close"]).tail(datalen).reset_index(drop=True)
        except Exception as e:
            if attempt < max_retries - 1:
                logger.debug(f"东方财富 akshare 日线 {code} 失败 (尝试 {attempt+1}/{max_retries}): {e}")
                continue
            else:
                logger.debug(f"东方财富 akshare 日线 {code} 最终失败: {e}")
                return pd.DataFrame()
    
    return pd.DataFrame()


# ------ 备用3：tushare 个股日线（与情绪一致：config 或 TUSHARE_TOKEN）------
def _get_tushare_token() -> Optional[str]:
    """与 sentiment_index 一致：先 config.data.tushare_token，再环境变量 TUSHARE_TOKEN，再 ts.token。"""
    try:
        import yaml
        from pathlib import Path
        for base in [Path(__file__).resolve().parents[3], Path.cwd()]:
            cfg = base / "config" / "trading_config.yaml"
            if cfg.is_file():
                with open(cfg, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict) and isinstance(data.get("data"), dict):
                    tok = (data["data"].get("tushare_token") or "").strip()
                    if tok:
                        return tok
    except Exception:
        pass
    return __import__("os").environ.get("TUSHARE_TOKEN") or None


def _fetch_tushare_kline(code: str, datalen: int, timeout: int = STOCK_DAILY_TIMEOUT) -> pd.DataFrame:
    """tushare 个股日线：pro.daily。token 取自 config 或 TUSHARE_TOKEN（与 akshare/tushare 配置一致）。"""
    try:
        import tushare as ts
        code = code.strip()
        ts_code = f"{code}.SH" if code.startswith(("5", "6")) else f"{code}.SZ"
        end_d = datetime.now()
        start_d = end_d - timedelta(days=min(datalen + 60, 800))
        start_str = start_d.strftime("%Y%m%d")
        end_str = end_d.strftime("%Y%m%d")
        pro = getattr(ts, "pro_api", None)
        if pro is None:
            token = getattr(ts, "token", None) or _get_tushare_token()
            if not token:
                return pd.DataFrame()
            pro = ts.pro_api(token)
        df = pro.daily(ts_code=ts_code, start_date=start_str, end_date=end_str)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(columns={"trade_date": "date", "vol": "volume"})
        df["date"] = pd.to_datetime(df["date"])
        for c in ["open", "high", "low", "close", "volume"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df[["date", "open", "high", "low", "close", "volume"]].dropna(subset=["close"]).sort_values("date").tail(datalen).reset_index(drop=True)
        return df
    except Exception as e:
        logger.debug("tushare 日线 %s 失败: %s", code, e)
        return pd.DataFrame()


# ------ 备用2：腾讯财经日线（文档 qt.gtimg.cn 日线）------
def _fetch_tencent_kline(code: str, datalen: int, timeout: int = STOCK_DAILY_TIMEOUT) -> pd.DataFrame:
    """腾讯日线：web.ifzq.gtimg.cn kline。"""
    try:
        prefix, sym = _market_prefix(code)
        symbol = f"{prefix}{sym}"
        url = (
            f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?"
            f"param={symbol},day,,,{datalen}&_var=kline_day&r=0.{int(time.time())}"
        )
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        if not r.text or "kline_day=" not in r.text:
            return pd.DataFrame()
        raw = r.text.replace("kline_day=", "").strip()
        data = json.loads(raw)
        kkey = "day" if "day" in data.get("data", {}).get(symbol, {}) else list((data.get("data") or {}).get(symbol) or {}).pop(0, None)
        if not kkey:
            return pd.DataFrame()
        rows = (data.get("data") or {}).get(symbol) or {}
        if isinstance(rows, dict):
            rows = rows.get(kkey) or []
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume", "_"])[:datalen]
        df = df[["date", "open", "high", "low", "close", "volume"]]
        df["date"] = pd.to_datetime(df["date"])
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.dropna(subset=["close"])
    except Exception as e:
        logger.debug("腾讯日线 %s 失败: %s", code, e)
        return pd.DataFrame()


def _circuit_allow(source: str) -> bool:
    """熔断检查：连续失败>=阈值且在开窗期内则不允许请求该源。local_cache不受熔断限制。"""
    if source == "local_cache":
        return True

    cnt, t0 = _circuit_state.get(source, [0, 0.0])
    threshold = CIRCUIT_FAIL_THRESHOLD_ETF if source in _ETF_SOURCES else CIRCUIT_FAIL_THRESHOLD
    open_secs = CIRCUIT_OPEN_SECONDS_ETF if source in _ETF_SOURCES else CIRCUIT_OPEN_SECONDS
    if cnt < threshold:
        return True
    if time.time() - t0 >= open_secs:
        _circuit_state[source][0] = 0
        return True
    return False


def _circuit_record(source: str, success: bool) -> None:
    """记录成功/失败，失败时增加计数并刷新时间。local_cache不记录失败（不触发熔断）。"""
    if source == "local_cache" and not success:
        return

    if source not in _circuit_state:
        _circuit_state[source] = [0, 0.0]

    if success:
        _circuit_state[source][0] = 0
    else:
        _circuit_state[source][0] = _circuit_state[source][0] + 1
        _circuit_state[source][1] = time.time()
        threshold = CIRCUIT_FAIL_THRESHOLD_ETF if source in _ETF_SOURCES else CIRCUIT_FAIL_THRESHOLD
        open_secs = CIRCUIT_OPEN_SECONDS_ETF if source in _ETF_SOURCES else CIRCUIT_OPEN_SECONDS
        if _circuit_state[source][0] >= threshold:
            logger.warning("[data_prefetch] 数据源 %s 连续失败达 %d 次，熔断 %d 秒", source, threshold, open_secs)


def fetch_index_daily(
    code: str = "000300",
    datalen: int = 800,
    timeout: int = 15,
    min_bars: int = 20,
) -> pd.DataFrame:
    """
    指数日线获取（独立于股票数据源，不受熔断影响）。
    指数和股票的API完全不同，必须用专门的接口：
      - akshare: stock_zh_index_daily_em（指数专用）
      - sina: 指数代码前缀固定为 sh（沪）或 sz（深）
      - 腾讯: 同上
    失败后逐源降级，不计入全局熔断状态。
    """
    key = (f"_idx_{code}", datalen)
    now = time.time()
    if key in _daily_cache:
        cached_df, ts = _daily_cache[key]
        if now - ts <= DAILY_CACHE_TTL_SECONDS and cached_df is not None and len(cached_df) >= min_bars:
            return cached_df.copy()
        del _daily_cache[key]

    # 指数代码映射：确定正确的市场前缀
    INDEX_PREFIX = {
        "000001": "sh", "000300": "sh", "000016": "sh", "000905": "sh",
        "000688": "sh", "000852": "sh", "399001": "sz", "399006": "sz",
        "399005": "sz", "399673": "sz",
    }
    pure_code = code.replace("sh", "").replace("sz", "").strip()
    prefix = INDEX_PREFIX.get(pure_code, "sh" if pure_code.startswith("000") else "sz")

    last_err = None

    # 数据源1: akshare 指数日线（最可靠）
    try:
        import akshare as ak
        end_d = datetime.now()
        start_d = end_d - timedelta(days=min(datalen + 60, 1200))
        df = ak.stock_zh_index_daily_em(symbol=f"{prefix}{pure_code}")
        if df is not None and not df.empty:
            col_map = {"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume"}
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                for c in ["open", "high", "low", "close", "volume"]:
                    if c in df.columns:
                        df[c] = pd.to_numeric(df[c], errors="coerce")
                df = df[["date", "open", "high", "low", "close", "volume"]].dropna(subset=["close"]).tail(datalen).reset_index(drop=True)
                if len(df) >= min_bars:
                    logger.info("[fetch_index_daily] akshare 获取 %s 成功: %d 条", pure_code, len(df))
                    _daily_cache[key] = (df.copy(), time.time())
                    return df
    except Exception as e:
        last_err = f"akshare: {e}"
        logger.debug("[fetch_index_daily] akshare %s 失败: %s", pure_code, e)

    # 数据源2: sina 指数日线
    try:
        symbol = f"{prefix}{pure_code}"
        url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://finance.sina.com.cn/",
        }
        r = requests.get(url, params={"symbol": symbol, "scale": "240", "ma": "no", "datalen": str(datalen)}, headers=headers, timeout=timeout)
        data = json.loads(r.text) if r.text and r.text.strip() else None
        if data:
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["day"])
            for c in ["open", "high", "low", "close", "volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df[["date", "open", "high", "low", "close", "volume"]].dropna(subset=["close"])
            if len(df) >= min_bars:
                logger.info("[fetch_index_daily] sina 获取 %s 成功: %d 条", pure_code, len(df))
                _daily_cache[key] = (df.copy(), time.time())
                return df
    except Exception as e:
        last_err = f"sina: {e}"
        logger.debug("[fetch_index_daily] sina %s 失败: %s", pure_code, e)

    # 数据源3: 腾讯日线
    try:
        symbol = f"{prefix}{pure_code}"
        url = (f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?"
               f"param={symbol},day,,,{datalen}&_var=kline_day&r=0.{int(time.time())}")
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        if r.text and "kline_day=" in r.text:
            raw = r.text.replace("kline_day=", "").strip()
            data = json.loads(raw)
            kkey = "day" if "day" in data.get("data", {}).get(symbol, {}) else None
            if kkey:
                rows = data.get("data", {}).get(symbol, {}).get(kkey, [])
                if rows:
                    df = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume", "_"])[:datalen]
                    df = df[["date", "open", "high", "low", "close", "volume"]]
                    df["date"] = pd.to_datetime(df["date"])
                    for c in ["open", "high", "low", "close", "volume"]:
                        df[c] = pd.to_numeric(df[c], errors="coerce")
                    df = df.dropna(subset=["close"])
                    if len(df) >= min_bars:
                        logger.info("[fetch_index_daily] tencent 获取 %s 成功: %d 条", pure_code, len(df))
                        _daily_cache[key] = (df.copy(), time.time())
                        return df
    except Exception as e:
        last_err = f"tencent: {e}"
        logger.debug("[fetch_index_daily] tencent %s 失败: %s", pure_code, e)

    # 数据源4: baostock（需要登录）
    try:
        import baostock as bs
        lg = bs.login()
        ts_code = f"{prefix}.{pure_code}"
        end_d = datetime.now()
        start_d = end_d - timedelta(days=min(datalen + 60, 1200))
        rs = bs.query_history_k_data_plus(
            ts_code, "date,open,high,low,close,volume",
            start_date=start_d.strftime("%Y-%m-%d"), end_date=end_d.strftime("%Y-%m-%d"),
            frequency="d", adjustflag="3"
        )
        rows = []
        while (rs.error_code == '0') and rs.next():
            rows.append(rs.get_row_data())
        bs.logout()
        if rows:
            df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
            df["date"] = pd.to_datetime(df["date"])
            for c in ["open", "high", "low", "close", "volume"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df.dropna(subset=["close"])
            if len(df) >= min_bars:
                logger.info("[fetch_index_daily] baostock 获取 %s 成功: %d 条", pure_code, len(df))
                _daily_cache[key] = (df.copy(), time.time())
                return df
    except Exception as e:
        last_err = f"baostock: {e}"
        logger.debug("[fetch_index_daily] baostock %s 失败: %s", pure_code, e)

    logger.warning("[fetch_index_daily] 指数 %s 全部数据源失败，最后错误: %s", pure_code, last_err)
    return pd.DataFrame()


def fetch_stock_daily(
    code: str,
    datalen: int = 800,
    retries: int = STOCK_DAILY_RETRIES,
    timeout: int = STOCK_DAILY_TIMEOUT,
    min_bars: int = 100,
) -> pd.DataFrame:
    """
    个股日线：统一走 DataProvider，主备顺序由 config/data_sources.yaml kline.sources 决定。
    带 (code,datalen) 内存缓存 TTL=300s；熔断/重试在 provider 内完成。
    与 docs/data/API_INTERFACES_AND_FETCHERS.md 一致。
    """
    key = (code.strip(), datalen)
    now = time.time()
    if key in _daily_cache:
        cached_df, ts = _daily_cache[key]
        if now - ts <= DAILY_CACHE_TTL_SECONDS and cached_df is not None and len(cached_df) >= min_bars:
            return cached_df.copy()  # 已含 data_source、fetched_at
        del _daily_cache[key]

    from src.data.provider.data_provider import get_default_kline_provider

    provider = get_default_kline_provider()
    df = provider.get_kline(
        symbol=code,
        datalen=datalen,
        min_bars=min_bars,
        retries=retries,
        timeout=timeout,
    )
    if df is not None and not df.empty and len(df) >= min_bars:
        _daily_cache[key] = (df.copy(), time.time())
        return df
    return pd.DataFrame()


# ------ 实时快照（文档 1.1.1 / 1.1.2，预留）------
def get_realtime_snapshot_sina(symbols: List[str], timeout: int = 10) -> Optional[dict]:
    """
    文档 1.1.1：Sina 实时行情。
    请求地址：http://hq.sinajs.cn/list=sh600000,sz000001
    返回：解析 JavaScript 字符串为 dict（按需解析 open/close/volume 等）。
    """
    if not symbols:
        return None
    try:
        list_param = ",".join(symbols)
        url = f"http://hq.sinajs.cn/list={list_param}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        if not r.text:
            return None
        # 简单返回原始文本，调用方按 Sina 格式拆分（逗号分隔）
        return {"raw": r.text, "symbols": symbols}
    except Exception as e:
        logger.debug("Sina 实时快照失败: %s", e)
        return None


def get_realtime_snapshot_eastmoney(code: str, timeout: int = 10) -> Optional[dict]:
    """
    文档 1.1.2：东方财富 push2 单只股票快照。
    https://push2.eastmoney.com/api/qt/stock/get
    secid=0.000001（0=深 1=沪）；fields=f43,f57,f58,f60,f169 等。
    """
    try:
        secid = _eastmoney_secid(code)
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        r = requests.get(
            url,
            params={"secid": secid, "fields": "f43,f57,f58,f60,f169"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=timeout,
        )
        data = r.json() if r.text else None
        if not data or "data" not in data:
            return None
        return data.get("data")
    except Exception as e:
        logger.debug("东方财富 实时快照 %s 失败: %s", code, e)
        return None


# ------ 东方财富 龙虎榜/新闻（文档 1.3，供 News/MoneyFlow 策略备用）------
def fetch_eastmoney_lhb(
    pn: int = 1,
    pz: int = 50,
    timeout: int = 10,
) -> List[dict]:
    """
    文档 1.3.2：东方财富龙虎榜列表。
    https://push2.eastmoney.com/api/qt/clist/get
    fid=f62；返回列表项含 f12(代码),f14(名称),f2(最新价),f3(涨跌幅),f18~f26(席位/成交额等)。
    """
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "fid": "f62",
            "po": "1",
            "pz": str(pz),
            "pn": str(pn),
            "np": "1",
            "fields": "f12,f14,f2,f3,f18,f20,f21,f23,f24,f25,f26",
        }
        r = requests.get(
            url,
            params=params,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"},
            timeout=timeout,
        )
        data = r.json() if r.text else None
        if not data or "data" not in data:
            return []
        d = data["data"]
        if not d or "diff" not in d:
            return []
        return d.get("diff") or []
    except Exception as e:
        logger.debug("东方财富龙虎榜请求失败: %s", e)
        return []


