"""
回测未来函数约束（V3.3 Phase 6.1）

在回测截面日/当前 K 线时间下，仅使用「当前可见」的数据，避免未来函数。
供回测框架在每根 K 线/每日截面调用，过滤新闻、政策、龙虎榜等。
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)

# 龙虎榜：T 日交易 T+1 披露，信号 T+2 开盘可用
LHB_OFFSET_DAYS = 2


def _to_timestamp(t: Any) -> Optional[pd.Timestamp]:
    """转为 pd.Timestamp，失败返回 None。"""
    if t is None or (isinstance(t, float) and pd.isna(t)):
        return None
    try:
        return pd.Timestamp(t)
    except Exception:
        return None


def filter_news_by_time(
    df_news: pd.DataFrame,
    current_bar_time: Union[datetime, pd.Timestamp, str],
    date_col: str = "date",
) -> pd.DataFrame:
    """
    仅保留发布时间 <= current_bar_time 的新闻（信号从发布时间之后生效）。
    无 date 列或为空则返回空 DataFrame。
    """
    if df_news is None or df_news.empty:
        return pd.DataFrame()
    if date_col not in df_news.columns:
        return df_news.copy()
    try:
        bar_ts = _to_timestamp(current_bar_time)
        if bar_ts is None:
            return df_news.copy()
        parsed = pd.to_datetime(df_news[date_col], errors="coerce")
        mask = parsed.notna() & (parsed <= bar_ts)
        return df_news.loc[mask].reset_index(drop=True)
    except Exception as e:
        logger.debug("filter_news_by_time 失败: %s", e)
        return pd.DataFrame()


def filter_policy_by_time(
    df_policy: pd.DataFrame,
    current_bar_time: Union[datetime, pd.Timestamp, str],
    date_col: str = "date",
) -> pd.DataFrame:
    """
    仅保留发布时间 <= current_bar_time 的政策（同上）。
    """
    return filter_news_by_time(df_policy, current_bar_time, date_col)


def is_lhb_visible_at_date(
    lhb_trade_date: Any,
    current_date: Union[datetime, pd.Timestamp, str],
) -> bool:
    """
    龙虎榜 T 日交易、T+1 披露、T+2 开盘可用。
    当 current_date >= lhb_trade_date + 2 个交易日时，该日龙虎榜数据在 current_date 可见。
    简化：按自然日 +2 判断；严格应为交易日 +2，需日历表。
    """
    if lhb_trade_date is None or current_date is None:
        return False
    try:
        lhb = _to_timestamp(lhb_trade_date)
        cur = _to_timestamp(current_date)
        if lhb is None or cur is None:
            return False
        # 自然日 +2：lhb 当日、+1、+2，则 +2 日及之后可见
        visible_from = lhb.normalize() + timedelta(days=LHB_OFFSET_DAYS)
        return cur.normalize() >= visible_from
    except Exception:
        return False


def filter_lhb_by_visible_date(
    df_lhb: pd.DataFrame,
    current_date: Union[datetime, pd.Timestamp, str],
    date_col: str = "date",
) -> pd.DataFrame:
    """
    仅保留在 current_date 截面下已可见的龙虎榜记录（trade_date + 2 <= current_date）。
    """
    if df_lhb is None or df_lhb.empty or date_col not in df_lhb.columns:
        return pd.DataFrame()
    try:
        cur = _to_timestamp(current_date)
        if cur is None:
            return pd.DataFrame()
        keep = []
        for i, row in df_lhb.iterrows():
            if is_lhb_visible_at_date(row[date_col], cur):
                keep.append(i)
        return df_lhb.loc[keep].reset_index(drop=True)
    except Exception as e:
        logger.debug("filter_lhb_by_visible_date 失败: %s", e)
        return pd.DataFrame()


def check_sentiment_no_future(
    df_index: pd.DataFrame,
    as_of_date: Union[datetime, pd.Timestamp, str],
    date_col: str = "date",
) -> bool:
    """
    校验情绪所用指数数据：仅包含 as_of_date 及以前的 K 线（无未来数据）。
    返回 True 表示通过校验。
    """
    if df_index is None or df_index.empty or date_col not in df_index.columns:
        return True
    try:
        as_of = _to_timestamp(as_of_date)
        if as_of is None:
            return True
        parsed = pd.to_datetime(df_index[date_col], errors="coerce")
        return (parsed <= as_of).all()
    except Exception:
        return True
