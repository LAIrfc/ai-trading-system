"""
Chinese A-share (SSE/SZSE) trading calendar helpers.

Uses a hardcoded holiday set for 2025–2026 (official exchange schedules).
Outside those years, only weekends are treated as non-trading days (no holiday
knowledge).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

__all__ = ["is_cn_trading_day", "get_last_trading_day"]


def _d(y: int, m: int, d: int) -> date:
    return date(y, m, d)


def _add_range(out: set[date], start: date, end: date) -> None:
    cur = start
    while cur <= end:
        out.add(cur)
        cur += timedelta(days=1)


def _build_cn_holidays() -> frozenset[date]:
    """SSE/SZSE-style closed days (calendar dates), 2025 official + 2026 approximate."""
    h: set[date] = set()

    # --- 2025 (沪深交易所公布) ---
    _add_range(h, _d(2025, 1, 1), _d(2025, 1, 1))  # 元旦
    _add_range(h, _d(2025, 1, 28), _d(2025, 2, 4))  # 春节
    _add_range(h, _d(2025, 4, 4), _d(2025, 4, 6))  # 清明
    _add_range(h, _d(2025, 5, 1), _d(2025, 5, 5))  # 劳动节
    _add_range(h, _d(2025, 5, 31), _d(2025, 6, 2))  # 端午节
    _add_range(h, _d(2025, 10, 1), _d(2025, 10, 8))  # 国庆 + 中秋连休

    # --- 2026 (沪深交易所正式公布) ---
    _add_range(h, _d(2026, 1, 1), _d(2026, 1, 3))  # 元旦 1/1-1/3
    _add_range(h, _d(2026, 2, 15), _d(2026, 2, 23))  # 春节 2/15-2/23
    _add_range(h, _d(2026, 4, 4), _d(2026, 4, 6))  # 清明 4/4-4/6
    _add_range(h, _d(2026, 5, 1), _d(2026, 5, 5))  # 劳动节 5/1-5/5
    _add_range(h, _d(2026, 6, 19), _d(2026, 6, 21))  # 端午节 6/19-6/21
    _add_range(h, _d(2026, 9, 25), _d(2026, 9, 27))  # 中秋节 9/25-9/27
    _add_range(h, _d(2026, 10, 1), _d(2026, 10, 7))  # 国庆节 10/1-10/7

    return frozenset(h)


_CN_HOLIDAYS = _build_cn_holidays()


def is_cn_trading_day(dt: date) -> bool:
    """Check if a date is a Chinese A-share trading day (not weekend, not holiday)."""
    if dt.weekday() >= 5:
        return False
    return dt not in _CN_HOLIDAYS


def get_last_trading_day(ref: Optional[date] = None) -> date:
    """Get the most recent trading day on or before ref (default: today)."""
    cur = ref if ref is not None else date.today()
    while not is_cn_trading_day(cur):
        cur -= timedelta(days=1)
    return cur
