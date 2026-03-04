"""
市场情绪指数构建

用市场指数（沪深300）的涨跌幅与波动率等代理指标，标准化后合成 0~100 的情绪指数：
- 0 = 极端恐慌，100 = 极端贪婪
- 低于 20 分位视为恐慌（买入信号），高于 80 分位视为贪婪（卖出信号）

当前实现：
- 以沪深300指数日线为基础，计算 20 日涨跌幅作为动量代理
- 在 60 日滚动窗口内将动量分位数映射到 0~100 作为情绪指数
后续可扩展：换手率、融资买入占比、涨跌家数比、期权 PCR 等，加权合成。
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# 沪深300 指数代码（akshare 东方财富接口用 sh000300）
DEFAULT_INDEX_SYMBOL = "000300"
# 动量周期
MOMENTUM_DAYS = 20
# 情绪分位数滚动窗口
SENTIMENT_LOOKBACK = 60


def _fetch_index_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """获取指数日线。使用 akshare stock_zh_index_hist_csindex，失败则返回空 DataFrame。"""
    try:
        import akshare as ak
        # 日期格式 YYYYMMDD
        start_str = start_date.replace("-", "")[:8]
        end_str = end_date.replace("-", "")[:8]
        df = ak.stock_zh_index_hist_csindex(symbol=symbol, start_date=start_str, end_date=end_str)
        if df is None or df.empty:
            return pd.DataFrame()
        # 统一列名：日期->date, 收盘->close
        df = df.rename(columns={"日期": "date", "收盘": "close", "开盘": "open", "最高": "high", "最低": "low", "成交量": "volume"})
        df["date"] = pd.to_datetime(df["date"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
        return df
    except Exception as e:
        logger.debug("获取指数日线失败: %s", e)
        return pd.DataFrame()


def get_sentiment_series(
    start_date: str,
    end_date: str,
    index_symbol: str = DEFAULT_INDEX_SYMBOL,
    momentum_days: int = MOMENTUM_DAYS,
    lookback_days: int = SENTIMENT_LOOKBACK,
) -> pd.DataFrame:
    """
    获取市场情绪指数时间序列。

    Parameters
    ----------
    start_date : str
        开始日期，如 "2024-01-01"
    end_date : str
        结束日期，如 "2026-03-03"
    index_symbol : str
        指数代码，默认 "000300"（沪深300）
    momentum_days : int
        动量周期（日），用于计算 N 日涨跌幅
    lookback_days : int
        分位数滚动窗口（日），用于将动量分位数映射到 0~100

    Returns
    -------
    pd.DataFrame
        列：date, sentiment_index（0~100）, momentum_pct（20日涨跌幅，可选）
        按 date 升序。无数据时返回空 DataFrame。
    """
    start_str = start_date.replace("-", "")[:8]
    end_str = end_date.replace("-", "")[:8]

    # 多取一些历史用于计算动量与滚动分位数
    try:
        start_early = (pd.Timestamp(start_date) - timedelta(days=lookback_days + momentum_days + 30)).strftime("%Y-%m-%d")
    except Exception:
        start_early = start_date

    df = _fetch_index_daily(index_symbol, start_early.replace("-", ""), end_str)
    if df.empty or len(df) < momentum_days + 10:
        return pd.DataFrame()

    close = df["close"].astype(float)
    # 20 日涨跌幅（动量）
    momentum = close.pct_change(momentum_days)
    df = df.assign(momentum_pct=momentum)

    # 在滚动窗口内计算动量的分位数，映射到 0~100 作为情绪指数
    # 分位数高 = 近期涨得多 = 贪婪(高)；分位数低 = 近期跌得多 = 恐慌(低)
    def _rolling_percentile(series: pd.Series, window: int) -> pd.Series:
        out = pd.Series(index=series.index, dtype=float)
        for i in range(window, len(series) + 1):
            w = series.iloc[i - window:i]
            val = w.iloc[-1]
            if pd.isna(val):
                out.iloc[i - 1] = np.nan
                continue
            out.iloc[i - 1] = (w < val).sum() / max(1, w.notna().sum()) * 100.0
        return out

    df["sentiment_index"] = _rolling_percentile(df["momentum_pct"], lookback_days)

    # 只保留请求的日期范围
    df = df[(df["date"] >= pd.Timestamp(start_date)) & (df["date"] <= pd.Timestamp(end_date))]
    return df[["date", "sentiment_index", "momentum_pct"]].copy()
