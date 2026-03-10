"""
情绪指数多指标合成（V3.3）

对多个代理指标做 60 日 Z-score 标准化，按方向性（正向/反向）与权重加权合成 S；
缺项权重置 0 并对其余权重归一化。S_low / S_high 为 60 日滚动 20/80 分位。
"""

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 指数日线预取超时（秒），超时或失败时尝试备用数据源
INDEX_FETCH_TIMEOUT = 15

# 默认权重（与 V3.3 文档一致；缺项置 0 后归一化）
DEFAULT_WEIGHTS = {
    "advance_decline_ratio": (0.25, 1),   # (weight, direction: 1=正向 -1=反向)
    "turnover_rate": (0.19, 1),
    "margin_buy_ratio": (0.12, 1),
    "option_pcr": (0.15, -1),
    "new_high_low_ratio": (0.22, 1),
    "volatility_index": (0.07, -1),
}
SENTIMENT_WINDOW = 60
LOW_PERCENTILE = 20
HIGH_PERCENTILE = 80


def _zscore_rolling(series: pd.Series, window: int) -> pd.Series:
    """滚动 Z-score，(x - mean) / std，窗口内 std=0 时返回 0。"""
    mean = series.rolling(window, min_periods=1).mean()
    std = series.rolling(window, min_periods=1).std()
    out = (series - mean) / np.where(std > 1e-12, std, np.nan)
    return out.fillna(0.0)


def _rolling_percentile(series: pd.Series, window: int, pct: float) -> pd.Series:
    """滚动 window 日内的 pct 分位数（0~100）。"""
    return series.rolling(window, min_periods=1).apply(
        lambda x: np.nanpercentile(x, pct),
        raw=True
    )


def composite_sentiment(
    indicators: pd.DataFrame,
    weights: Optional[Dict[str, Tuple[float, int]]] = None,
    window: int = SENTIMENT_WINDOW,
) -> pd.DataFrame:
    """
    多指标 Z-score 加权合成情绪指数 S，并计算 S_low / S_high。

    Parameters
    ----------
    indicators : pd.DataFrame
        列名为指标名，索引为 date；仅使用 weights 中出现的列，缺列则该权重置 0 并归一化。
    weights : dict, optional
        { indicator_name: (weight, direction) }，direction 1=正向 -1=反向。默认用 DEFAULT_WEIGHTS。
    window : int
        滚动窗口（Z-score 与分位数）。

    Returns
    -------
    pd.DataFrame
        列：date (index), S, S_low, S_high；按 date 升序。
    """
    weights = weights or DEFAULT_WEIGHTS
    # 只保留存在的列，缺项权重 0
    available = [k for k in weights if k in indicators.columns]
    if not available:
        return pd.DataFrame()

    total_w = sum(weights[k][0] for k in available)
    if total_w <= 0:
        return pd.DataFrame()
    # 归一化权重
    w_norm = {k: (weights[k][0] / total_w, weights[k][1]) for k in available}

    df = indicators.copy()
    comp = pd.Series(0.0, index=df.index)
    for name in available:
        w, direction = w_norm[name]
        z = _zscore_rolling(df[name].astype(float), window)
        comp = comp + z * direction * w

    out = pd.DataFrame({"S": comp}, index=df.index)
    out["S_low"] = _rolling_percentile(comp, window, LOW_PERCENTILE)
    out["S_high"] = _rolling_percentile(comp, window, HIGH_PERCENTILE)
    out = out.reset_index()
    if "index" in out.columns:
        out = out.rename(columns={"index": "date"})
    return out.sort_values("date").reset_index(drop=True)


def _fetch_index_series_akshare(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """主数据源：akshare 指数日线，返回 date, close。"""
    try:
        import akshare as ak
        start_str = start_date.replace("-", "")[:8]
        end_str = end_date.replace("-", "")[:8]
        df = ak.stock_zh_index_hist_csindex(symbol=symbol, start_date=start_str, end_date=end_str)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(columns={"日期": "date", "收盘": "close"})
        df["date"] = pd.to_datetime(df["date"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["close"]).sort_values("date").set_index("date")
        return df[["close"]]
    except Exception as e:
        logger.debug("akshare 指数日线失败: %s", e)
        return pd.DataFrame()


def _fetch_index_series_tushare(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """备用数据源：tushare 指数日线。需配置 TUSHARE_TOKEN。返回 date, close。"""
    try:
        import tushare as ts
        start_str = start_date.replace("-", "")[:8]
        end_str = end_date.replace("-", "")[:8]
        # 沪深300: tushare 为 399300.SZ；其它指数按 0/3/6 开头用 .SH
        ts_code = "399300.SZ" if symbol == "000300" else (f"{symbol}.SH" if symbol.startswith(("0", "6")) else f"{symbol}.SZ")
        pro = getattr(ts, "pro_api", None)
        if pro is None:
            token = getattr(ts, "token", None) or __import__("os").environ.get("TUSHARE_TOKEN")
            if not token:
                return pd.DataFrame()
            pro = ts.pro_api(token)
        df = pro.index_daily(ts_code=ts_code, start_date=start_str, end_date=end_str)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(columns={"trade_date": "date", "close": "close"})
        df["date"] = pd.to_datetime(df["date"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["close"]).sort_values("date").set_index("date")
        return df[["close"]]
    except Exception as e:
        logger.debug("tushare 指数日线失败: %s", e)
        return pd.DataFrame()


# ---------- 文档 1.2：6 大情绪指标独立获取（主 akshare / 备 tushare）----------

def get_advance_decline_ratio_series(
    start_date: str,
    end_date: str,
    index_symbol: str = "000300",
) -> pd.Series:
    """
    涨跌家数比序列。无直接历史接口时用指数日线收益符号的 5 日平滑比代理（涨日数/跌日数）。
    主 akshare 截面/备 tushare；缺则用 index 代理。
    """
    idx_df = _fetch_index_series(index_symbol, start_date, end_date)
    if idx_df.empty or len(idx_df) < 5:
        return pd.Series(dtype=float)
    ret = idx_df["close"].astype(float).pct_change()
    # 代理：涨日=1 跌日=0，再 rolling 5 日 sum 得到涨日数，比值 (涨日数+1)/(跌日数+1)
    up = (ret > 0).astype(float)
    roll_up = up.rolling(5, min_periods=1).sum()
    roll_down = (1 - up).rolling(5, min_periods=1).sum()
    ratio = (roll_up + 0.5) / (roll_down + 0.5)
    return ratio


def get_turnover_rate_series(
    start_date: str,
    end_date: str,
    index_symbol: str = "000300",
) -> pd.Series:
    """
    换手率序列。用指数日线成交量 5 日变化率代理（无全市场换手时）；若有 akshare/tushare 全市场换手则优先。
    """
    idx_df = _fetch_index_series(index_symbol, start_date, end_date)
    if idx_df.empty or "volume" not in idx_df.columns:
        # 部分指数接口无 volume，尝试用 close 的波动代理
        if idx_df.empty or len(idx_df) < 5:
            return pd.Series(dtype=float)
        vol = idx_df["close"].astype(float).pct_change().abs()
    else:
        vol = idx_df["volume"].astype(float)
    roll = vol.rolling(5, min_periods=1).mean()
    # 代理：换手与前期均值比，归一化到 0~5 区间
    turnover_proxy = (roll / (roll.shift(5).replace(0, np.nan) + 1e-8)).fillna(1.0).clip(0.2, 5.0)
    return turnover_proxy


def get_margin_buy_ratio_series(start_date: str, end_date: str) -> pd.Series:
    """
    融资买入占比序列。主 akshare stock_margin_trade_summary（沪+深）。
    返回日频序列，值为融资买入额归一化（0~1）作为情绪代理。
    """
    try:
        import akshare as ak
        out = []
        for symbol in ["sh", "sz"]:
            try:
                df = ak.stock_margin_trade_summary(symbol=symbol)
                if df is None or df.empty:
                    continue
                date_col = [c for c in df.columns if "日期" in str(c)][:1] or ["date"]
                df["date"] = pd.to_datetime(df[date_col[0]], errors="coerce")
                buy_col = [c for c in df.columns if "融资" in str(c) and "买" in str(c)][:1]
                if not buy_col:
                    buy_col = [c for c in df.columns if "买入" in str(c)][:1]
                if buy_col:
                    df["margin_buy"] = pd.to_numeric(df[buy_col[0]], errors="coerce").fillna(0)
                    out.append(df[["date", "margin_buy"]].dropna(subset=["date"]))
            except Exception as e:
                logger.debug("融资融券 %s 失败: %s", symbol, e)
        if not out:
            return pd.Series(dtype=float)
        merged = pd.concat(out, ignore_index=True)
        merged = merged.groupby("date")["margin_buy"].sum().reset_index().set_index("date").sort_index()
        start_ts, end_ts = pd.Timestamp(start_date), pd.Timestamp(end_date)
        merged = merged[(merged.index >= start_ts) & (merged.index <= end_ts)]
        if merged.empty:
            return pd.Series(dtype=float)
        s = merged["margin_buy"] / (merged["margin_buy"].max() + 1e-8)
        return s.squeeze()
    except Exception as e:
        logger.debug("get_margin_buy_ratio_series 失败: %s", e)
        return pd.Series(dtype=float)


def get_option_pcr_series(start_date: str, end_date: str) -> pd.Series:
    """
    期权 PCR 序列。主 akshare 期权日数据，备 tushare opt_daily；缺数据返回空 Series。
    当前若无 50ETF/沪深300 期权日频接口则返回空，权重在合成时置 0。
    """
    try:
        import akshare as ak
        # 50ETF 期权日统计（若有）；接口名可能为 option_50etf_daily 等
        for name in ["option_sse_daily", "option_50etf_daily", "option_sz_daily"]:
            func = getattr(ak, name, None)
            if func is None:
                continue
            try:
                df = func()
                if df is None or df.empty:
                    continue
                date_col = [c for c in df.columns if "日期" in str(c) or "date" in c.lower()][:1]
                if not date_col:
                    continue
                df["date"] = pd.to_datetime(df[date_col[0]], errors="coerce")
                pcr_col = [c for c in df.columns if "pcr" in c.lower() or "PCR" in c or "认沽" in str(c) and "认购" in str(c)][:1]
                if pcr_col:
                    s = df.groupby("date")[pcr_col[0]].mean()
                else:
                    s = pd.Series(dtype=float)
                if s.empty:
                    continue
                start_ts, end_ts = pd.Timestamp(start_date), pd.Timestamp(end_date)
                s = s[(s.index >= start_ts) & (s.index <= end_ts)]
                return s
            except Exception:
                continue
        return pd.Series(dtype=float)
    except Exception as e:
        logger.debug("get_option_pcr_series 失败: %s", e)
        return pd.Series(dtype=float)


def get_new_high_low_ratio_series(
    start_date: str,
    end_date: str,
    index_symbol: str = "000300",
) -> pd.Series:
    """
    新高新低比序列。无直接接口时用指数 20 日最高/最低位代理（close 在 20 日 high 的分位）。
    """
    idx_df = _fetch_index_series(index_symbol, start_date, end_date)
    if idx_df.empty or len(idx_df) < 21:
        return pd.Series(dtype=float)
    close = idx_df["close"].astype(float)
    high20 = close.rolling(20, min_periods=5).max()
    low20 = close.rolling(20, min_periods=5).min()
    # 分位 (close - low20)/(high20 - low20)，比值代理
    pos = (close - low20) / (high20 - low20 + 1e-8)
    return pos.clip(0, 1)


def get_volatility_index_series(
    start_date: str,
    end_date: str,
    index_symbol: str = "000300",
) -> pd.Series:
    """
    波动率指数序列。指数日线 20 日年化波动率 HV20（%）。
    """
    idx_df = _fetch_index_series(index_symbol, start_date, end_date)
    if idx_df.empty or len(idx_df) < 21:
        return pd.Series(dtype=float)
    close = idx_df["close"].astype(float)
    ret = close.pct_change()
    hv20 = ret.rolling(20, min_periods=5).std() * np.sqrt(252) * 100
    return hv20.fillna(0)


def _fetch_index_series_joinquant(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    文档 1.2.3 备2：JoinQuant 指数日线。需配置 JQ_USER/JQ_PASSWORD 或 JQ_ACCESS_TOKEN。
    返回 date, close；未配置或失败返回空 DataFrame。
    """
    import os
    user = os.environ.get("JQ_USER", "").strip()
    pwd = os.environ.get("JQ_PASSWORD", "").strip()
    token = os.environ.get("JQ_ACCESS_TOKEN", "").strip()
    if not token and not (user and pwd):
        return pd.DataFrame()
    try:
        from jqdatasdk import auth, get_price
        if token:
            auth(token, token)
        else:
            auth(user, pwd)
        # 沪深300 在 JoinQuant 为 000300.XSHG 或 399300.XSHE
        jq_code = "000300.XSHG" if symbol == "000300" else (f"{symbol}.XSHG" if symbol.startswith(("5", "6")) else f"{symbol}.XSHE")
        df = get_price(jq_code, start_date=start_date[:10], end_date=end_date[:10], frequency="daily", fields=["close"])
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.reset_index()
        df = df.rename(columns={"time": "date", "close": "close"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")[["close"]]
        return df
    except ImportError:
        logger.debug("jqdatasdk 未安装，跳过 JoinQuant")
        return pd.DataFrame()
    except Exception as e:
        logger.debug("JoinQuant 指数日线失败: %s", e)
        return pd.DataFrame()


def _fetch_index_series(symbol: str, start_date: str, end_date: str, timeout: int = INDEX_FETCH_TIMEOUT) -> pd.DataFrame:
    """
    获取指数日线：主源 akshare（带 timeout）→ 备 tushare → 备2 JoinQuant（文档 1.2.3）。
    返回 date, close；均失败返回空 DataFrame。
    """
    def _do_akshare():
        return _fetch_index_series_akshare(symbol, start_date, end_date)

    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_do_akshare)
            df = fut.result(timeout=timeout)
        if df is not None and not df.empty:
            return df
    except (FuturesTimeoutError, Exception) as e:
        logger.warning("指数日线主源 akshare 超时或异常(%s)，尝试备用 tushare", e)
    df = _fetch_index_series_tushare(symbol, start_date, end_date)
    if df is not None and not df.empty:
        logger.info("指数日线已用备用 tushare 成功")
        return df
    df = _fetch_index_series_joinquant(symbol, start_date, end_date)
    if df is not None and not df.empty:
        logger.info("指数日线已用备用 JoinQuant 成功")
        return df
    return pd.DataFrame()


def get_sentiment_series_v2(
    start_date: str,
    end_date: str,
    index_symbol: str = "000300",
    window: int = SENTIMENT_WINDOW,
) -> pd.DataFrame:
    """
    获取情绪指数序列（V3.3 多指标版）。

    优先使用文档 1.2 的 6 大指标：涨跌家数比、换手率、融资买入比、期权 PCR、新高新低比、波动率；
    主 akshare/备 tushare，缺项权重置 0 并归一化。若无任一指标则回退为指数动量+波动率两指标合成。

    Returns
    -------
    pd.DataFrame
        列：date, S, S_low, S_high；无数据时返回空。
    """
    from datetime import timedelta
    start_early = (pd.Timestamp(start_date) - timedelta(days=window + 60)).strftime("%Y-%m-%d")
    end_str = end_date.replace("-", "")[:8]

    idx_df = _fetch_index_series(index_symbol, start_early, end_str)
    if idx_df.empty or len(idx_df) < window + 20:
        return pd.DataFrame()

    common_index = idx_df.index
    indicators = pd.DataFrame(index=common_index)

    # 6 大指标独立获取，对齐到 common_index
    for name, getter in [
        ("advance_decline_ratio", lambda: get_advance_decline_ratio_series(start_early, end_str, index_symbol)),
        ("turnover_rate", lambda: get_turnover_rate_series(start_early, end_str, index_symbol)),
        ("margin_buy_ratio", lambda: get_margin_buy_ratio_series(start_early, end_str)),
        ("option_pcr", lambda: get_option_pcr_series(start_early, end_str)),
        ("new_high_low_ratio", lambda: get_new_high_low_ratio_series(start_early, end_str, index_symbol)),
        ("volatility_index", lambda: get_volatility_index_series(start_early, end_str, index_symbol)),
    ]:
        try:
            s = getter()
            if s is not None and not s.empty:
                indicators[name] = s.reindex(common_index).ffill().fillna(0)
        except Exception as e:
            logger.debug("情绪指标 %s 获取失败: %s", name, e)

    if indicators.dropna(axis=1, how="all").empty or not any(indicators.columns.isin(DEFAULT_WEIGHTS)):
        # 回退：仅用指数动量 + 波动率
        close = idx_df["close"].astype(float)
        indicators = pd.DataFrame(index=common_index)
        indicators["advance_decline_ratio"] = (close.pct_change(5) > 0).astype(float).rolling(5, min_periods=1).mean()
        indicators["volatility_index"] = get_volatility_index_series(start_early, end_str, index_symbol).reindex(common_index).fillna(0)
        indicators = indicators.dropna(axis=1, how="all")

    if indicators.empty:
        return pd.DataFrame()
    out = composite_sentiment(indicators, weights=DEFAULT_WEIGHTS, window=window)
    out = out[(out["date"] >= pd.Timestamp(start_date)) & (out["date"] <= pd.Timestamp(end_date))]
    return out


def get_sentiment_series(
    start_date: str,
    end_date: str,
    index_symbol: str = "000300",
    momentum_days: int = 20,
    lookback_days: int = 60,
) -> pd.DataFrame:
    """
    向后兼容接口：返回旧版格式（date, sentiment_index, momentum_pct）。

    内部调用 get_sentiment_series_v2，将 S 线性映射到 0~100 的 sentiment_index。
    原 market_sentiment.py 的调用方可直接切换到此函数。
    """
    df = get_sentiment_series_v2(start_date, end_date, index_symbol=index_symbol, window=lookback_days)
    if df.empty:
        return pd.DataFrame()
    # S 是 Z-score 合成值，通过 S_low/S_high 分位映射到 0~100
    s_min = df["S"].min()
    s_max = df["S"].max()
    span = s_max - s_min
    if span < 1e-8:
        df["sentiment_index"] = 50.0
    else:
        df["sentiment_index"] = ((df["S"] - s_min) / span * 100).clip(0, 100)
    df["momentum_pct"] = float("nan")
    return df[["date", "sentiment_index", "momentum_pct"]].copy()


def get_s_low_s_high_latest(lookback_days: int = 80) -> Optional[Tuple[float, float, float]]:
    """
    获取最近一日的 S、S_low、S_high，供策略使用。

    Returns
    -------
    (S, S_low, S_high) 或 None
    """
    from datetime import datetime, timedelta
    end = datetime.now()
    start = (end - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")
    df = get_sentiment_series_v2(start, end_str)
    if df.empty or df["S"].iloc[-1] != df["S"].iloc[-1]:
        return None
    row = df.iloc[-1]
    return float(row["S"]), float(row["S_low"]), float(row["S_high"])
