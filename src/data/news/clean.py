"""
新闻清洗与去重（V3.3）

- 去重：同一自然日（或时间窗 5 分钟内）+ 标题相似度>threshold 只保留最早一条（文档 2.3）。
- 可选 SimHash 加速；当前使用编辑距离。
- 时间戳校准：剔除发布时间晚于 ref_time 的异常数据。
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# 文档 2.3：时间窗 5 分钟内同标题视为同事件
DEDUP_TIME_WINDOW_MINUTES = 5


def _title_similarity(a: str, b: str) -> float:
    """标题相似度 [0,1]，用编辑距离比。"""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    try:
        from difflib import SequenceMatcher
        return SequenceMatcher(None, a.strip(), b.strip()).ratio()
    except Exception:
        return 0.0


def _parse_date(x: Any) -> Optional[datetime]:
    """解析日期为 datetime，用于比较先后。"""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if isinstance(x, datetime):
        return x
    try:
        return pd.to_datetime(x)
    except Exception:
        return None


def dedup_news(
    df: pd.DataFrame,
    symbol: Optional[str] = None,
    date_col: str = "date",
    title_col: str = "title",
    same_natural_day: bool = True,
    title_similarity_threshold: float = 0.85,
    time_window_minutes: Optional[float] = None,
) -> pd.DataFrame:
    """
    同事件去重：同一自然日（或 time_window_minutes 内）+ 标题相似度>threshold 只保留最早一条。
    文档 2.3：时间 5 分钟内 + 标题相似视为同事件。

    Parameters
    ----------
    time_window_minutes : float, optional
        若设置，则仅当两条记录时间差 <= 此分钟数且标题相似时才视为重复；默认用 DEDUP_TIME_WINDOW_MINUTES（5）。
    """
    if df is None or df.empty or title_col not in df.columns:
        return df.copy() if df is not None else pd.DataFrame()
    out = df.copy()
    if date_col not in out.columns:
        out = out.sort_index().reset_index(drop=True)
        return out

    window = time_window_minutes if time_window_minutes is not None else DEDUP_TIME_WINDOW_MINUTES
    out["_parsed_date"] = out[date_col].map(_parse_date)
    out = out.dropna(subset=["_parsed_date"])
    if out.empty:
        return out.drop(columns=["_parsed_date"], errors="ignore")

    out["_natural_day"] = out["_parsed_date"].dt.normalize()
    out = out.sort_values("_parsed_date").reset_index(drop=True)

    keep = []
    for _, g in out.groupby("_natural_day", sort=False):
        g_sorted = g.sort_values("_parsed_date")
        chosen_in_day = []
        for i, row in g_sorted.iterrows():
            title = str(row.get(title_col, ""))
            t = row["_parsed_date"]
            dup = any(
                _title_similarity(title, str(out.loc[j, title_col])) >= title_similarity_threshold
                and (window is None or abs((t - out.loc[j, "_parsed_date"]).total_seconds()) <= (window or 0) * 60)
                for j in chosen_in_day
            )
            if not dup:
                chosen_in_day.append(i)
        keep.extend(chosen_in_day)

    result = out.loc[sorted(keep)].drop(columns=["_parsed_date", "_natural_day"], errors="ignore")
    return result.sort_values(date_col).reset_index(drop=True)


def filter_future_time(df: pd.DataFrame, ref_time: Optional[datetime] = None, date_col: str = "date") -> pd.DataFrame:
    """剔除发布时间晚于 ref_time 的异常数据。ref_time 默认当前时间。"""
    if df is None or df.empty or date_col not in df.columns:
        return df.copy() if df is not None else pd.DataFrame()
    ref = ref_time or datetime.now()
    parsed = df[date_col].map(_parse_date)
    mask = parsed.notna() & (parsed <= ref)
    return df.loc[mask].reset_index(drop=True)
