"""
双核动量策略共用数学函数（✅ 仍在使用）

被以下模块引用：
- src/strategies/dual_momentum.py（DualMomentumSingleStrategy）
- src/etf_rotation/signal_engine.py（ETF轮动）

三套双核动量实现（DualMomentumEngine / DualMomentumStrategy /
DualMomentumSingleStrategy）共享的纯函数，无副作用，易于单元测试。
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple


def calc_absolute_momentum(
    close: pd.Series,
    period: int,
) -> Tuple[float, float, bool]:
    """
    计算绝对动量：当前价格与 N 日均线的关系。

    Parameters
    ----------
    close : pd.Series
        收盘价序列（按时间升序）
    period : int
        均线周期 N

    Returns
    -------
    (current_price, ma_n, above_ma)
        current_price: 最新收盘价
        ma_n: N 日均线值
        above_ma: 当前价格是否在均线上方
    """
    current_price = float(close.iloc[-1])
    ma_n = float(close.rolling(period, min_periods=period).mean().iloc[-1])
    above_ma = current_price > ma_n
    return current_price, ma_n, above_ma


def calc_relative_momentum(
    close: pd.Series,
    period: int,
) -> Optional[float]:
    """
    计算相对动量：过去 M 日的涨跌幅（百分比）。

    Parameters
    ----------
    close : pd.Series
        收盘价序列（按时间升序）
    period : int
        回看周期 M

    Returns
    -------
    float or None
        动量百分比，如 12.5 表示涨了 12.5%；数据不足时返回 None
    """
    if len(close) < period:
        return None
    current_price = float(close.iloc[-1])
    past_price = float(close.iloc[-period])
    if past_price <= 0:
        return None
    return (current_price / past_price - 1) * 100


def check_stop_loss(
    current_price: float,
    buy_price: float,
    threshold: float = -0.10,
) -> Tuple[bool, float]:
    """
    检查是否触发止损。

    Parameters
    ----------
    current_price : float
        当前价格
    buy_price : float
        买入价格
    threshold : float
        止损阈值，如 -0.10 表示亏损 10% 触发

    Returns
    -------
    (triggered, pnl_pct)
        triggered: 是否触发止损
        pnl_pct: 当前盈亏比例（负数为亏损）
    """
    if buy_price <= 0:
        return False, 0.0
    pnl_pct = (current_price - buy_price) / buy_price
    return pnl_pct <= threshold, pnl_pct


def check_market_crash(
    hs300_close: pd.Series,
    threshold: float = -0.05,
) -> Tuple[bool, float]:
    """
    检查是否发生市场黑天鹅（沪深300单日大跌）。

    Parameters
    ----------
    hs300_close : pd.Series
        沪深300 ETF（510300）收盘价序列
    threshold : float
        触发阈值，如 -0.05 表示单日跌幅超过 5% 触发

    Returns
    -------
    (triggered, daily_return)
        triggered: 是否触发熔断
        daily_return: 最新一日涨跌幅
    """
    if len(hs300_close) < 2:
        return False, 0.0
    last = float(hs300_close.iloc[-1])
    prev = float(hs300_close.iloc[-2])
    if prev <= 0:
        return False, 0.0
    daily_return = (last - prev) / prev
    return daily_return <= threshold, daily_return


def calc_liquidity(
    close: pd.Series,
    volume: pd.Series,
    lookback: int = 20,
) -> float:
    """
    计算近 N 日平均日成交额（元）。

    Parameters
    ----------
    close : pd.Series
        收盘价序列
    volume : pd.Series
        成交量序列（股数）
    lookback : int
        回看天数，默认 20

    Returns
    -------
    float
        平均日成交额（元）
    """
    n = min(lookback, len(close))
    avg_amount = float((close.tail(n) * volume.tail(n)).mean())
    return avg_amount
