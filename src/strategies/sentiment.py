"""
市场情绪策略（Sentiment）V3.3

- 情绪指数 S 为多指标 Z-score 合成（见 sentiment_index.py），S_low/S_high 为 60 日 20/80 分位。
- 买入：当日 S < S_low 且次日 S 回升；卖出：当日 S > S_high 且次日 S 回落。
- 趋势过滤（个股）：仅当【情绪极端+次日确认】与【趋势加速度衰竭】同时满足才输出买卖；
  买入端：MACD 柱 3 日斜率<0、股价创 5 日新低、ADX>25；卖出端：MACD 柱 3 日斜率<0、股价创 5 日新高、ADX>25。
- 无 V3.3 数据时回退为旧版单指标 0~100 情绪逻辑（无趋势过滤）。
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from .base import Strategy, StrategySignal

logger = logging.getLogger(__name__)

# 回测预取缓存：同一日期范围只拉一次（市场级数据），避免单策略回测+组合回测重复拉取
_backtest_sentiment_cache: dict = {}

# 趋势过滤参数（V3.3）
MACD_SLOPE_WINDOW = 3
PRICE_LOOKBACK = 5
ADX_PERIOD = 14
ADX_TREND_THRESHOLD = 25


def _macd_hist_slope(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9, slope_n: int = 3) -> Optional[float]:
    """MACD 柱（红绿柱）最近 slope_n 日的线性回归斜率。"""
    if len(close) < slow + signal + slope_n:
        return None
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    dif = ema_f - ema_s
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea).values
    last = hist[-slope_n:]
    if np.any(np.isnan(last)):
        return None
    x = np.arange(slope_n, dtype=float)
    slope = np.polyfit(x, last, 1)[0]
    return float(slope)


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> Optional[float]:
    """ADX(period)，返回最后一根 K 线的 ADX 值。"""
    if len(close) < period + 10:
        return None
    high = high.astype(float)
    low = low.astype(float)
    close = close.astype(float)
    tr = pd.Series(index=close.index, dtype=float)
    tr.iloc[0] = high.iloc[0] - low.iloc[0]
    for i in range(1, len(close)):
        tr.iloc[i] = max(
            high.iloc[i] - low.iloc[i],
            abs(high.iloc[i] - close.iloc[i - 1]),
            abs(low.iloc[i] - close.iloc[i - 1]),
        )
    plus_dm = pd.Series(0.0, index=close.index)
    minus_dm = pd.Series(0.0, index=close.index)
    for i in range(1, len(close)):
        up = high.iloc[i] - high.iloc[i - 1]
        down = low.iloc[i - 1] - low.iloc[i]
        if up > down and up > 0:
            plus_dm.iloc[i] = up
        if down > up and down > 0:
            minus_dm.iloc[i] = down
    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100.0 * (plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, np.nan))
    minus_di = 100.0 * (minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, np.nan))
    dx = 100.0 * (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan))
    adx = dx.ewm(alpha=alpha, adjust=False).mean()
    return float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else None


def _trend_filter_buy(df: pd.DataFrame) -> bool:
    """买入端趋势过滤：MACD 柱 3 日斜率<0、股价创 5 日新低、ADX>25。"""
    close = df["close"].astype(float)
    high = df["high"].astype(float) if "high" in df.columns else close
    low = df["low"].astype(float) if "low" in df.columns else close
    if len(close) < PRICE_LOOKBACK + 30:
        return False
    slope = _macd_hist_slope(close, slope_n=MACD_SLOPE_WINDOW)
    if slope is None or slope >= 0:
        return False
    five_low = close.iloc[-PRICE_LOOKBACK:].min()
    if close.iloc[-1] > five_low:
        return False
    adx = _adx(high, low, close, ADX_PERIOD)
    if adx is None or adx <= ADX_TREND_THRESHOLD:
        return False
    return True


def _trend_filter_sell(df: pd.DataFrame) -> bool:
    """卖出端趋势过滤：MACD 柱 3 日斜率<0、股价创 5 日新高、ADX>25。"""
    close = df["close"].astype(float)
    high = df["high"].astype(float) if "high" in df.columns else close
    low = df["low"].astype(float) if "low" in df.columns else close
    if len(close) < PRICE_LOOKBACK + 30:
        return False
    slope = _macd_hist_slope(close, slope_n=MACD_SLOPE_WINDOW)
    if slope is None or slope >= 0:
        return False
    five_high = close.iloc[-PRICE_LOOKBACK:].max()
    if close.iloc[-1] < five_high:
        return False
    adx = _adx(high, low, close, ADX_PERIOD)
    if adx is None or adx <= ADX_TREND_THRESHOLD:
        return False
    return True


def _get_sentiment_v2_last_two(lookback_days: int = 80) -> Optional[pd.DataFrame]:
    """获取最近两个交易日的 S、S_low、S_high（V3.3 多指标）。"""
    try:
        from src.data.sentiment.sentiment_index import get_sentiment_series_v2
        end = datetime.now()
        start = (end - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
        df = get_sentiment_series_v2(start, end_str)
        if df is None or len(df) < 2:
            return None
        return df.tail(2).copy()
    except Exception as e:
        logger.debug("获取情绪 V2 失败: %s", e)
        return None


def _get_sentiment_v2_for_date(start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """按日期范围获取情绪序列（供回测预取用）。"""
    try:
        from src.data.sentiment.sentiment_index import get_sentiment_series_v2
        df = get_sentiment_series_v2(start_date, end_date)
        if df is None or df.empty:
            return None
        return df
    except Exception as e:
        logger.debug("获取情绪 V2 失败: %s", e)
        return None


def _get_latest_sentiment_legacy(lookback_days: int = 80) -> Optional[float]:
    """旧版：最近一日情绪指数 0~100。"""
    try:
        from src.data.sentiment import get_sentiment_series
        end = datetime.now()
        start = (end - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
        df = get_sentiment_series(start, end_str)
        if df.empty or pd.isna(df["sentiment_index"].iloc[-1]):
            return None
        return float(df["sentiment_index"].iloc[-1])
    except Exception as e:
        logger.debug("获取情绪指数失败: %s", e)
        return None


class SentimentStrategy(Strategy):
    """市场情绪策略 V3.3：多指标 S、20/80 分位、次日确认、个股趋势过滤。"""

    name = "Sentiment"
    description = "市场情绪指数(V3.3)：多指标Z-score合成，极端+次日确认+趋势过滤"

    param_ranges = {
        "low_threshold": (10, 20, 35, 5),
        "high_threshold": (65, 80, 90, 5),
    }

    min_bars = 65  # 满足趋势过滤（MACD+ADX）所需

    def __init__(self, low_threshold: float = 20.0, high_threshold: float = 80.0, **kwargs):
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold
        self._backtest_sentiment_df: Optional[pd.DataFrame] = None  # 回测时预取的情绪序列，避免逐 bar 拉取

    def prepare_backtest(self, df: pd.DataFrame) -> None:
        """回测前预取整段情绪数据，避免逐 bar 调用接口；同日期范围用缓存；拉取超时则跳过（该策略回测多为 HOLD）。"""
        if df.empty or "date" not in df.columns:
            return
        start = (pd.Timestamp(df["date"].iloc[0]) - timedelta(days=80)).strftime("%Y-%m-%d")
        end = pd.Timestamp(df["date"].iloc[-1]).strftime("%Y-%m-%d")
        key = (start, end)
        if key not in _backtest_sentiment_cache:
            _backtest_sentiment_cache[key] = None
            for retry in range(3):
                try:
                    with ThreadPoolExecutor(max_workers=1) as ex:
                        fut = ex.submit(_get_sentiment_v2_for_date, start, end)
                        _backtest_sentiment_cache[key] = fut.result(timeout=15)
                    if _backtest_sentiment_cache[key] is not None and not _backtest_sentiment_cache[key].empty:
                        break
                except (FuturesTimeoutError, Exception) as e:
                    logger.debug("情绪预取第%d次失败: %s", retry + 1, e)
                if retry < 2:
                    time.sleep(2)
        self._backtest_sentiment_df = _backtest_sentiment_cache[key]

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        # 1) 优先 V3.3：最近两日 S、S_low、S_high
        sent_df = None
        if self._backtest_sentiment_df is not None and not self._backtest_sentiment_df.empty and "date" in df.columns:
            bar_date = pd.Timestamp(df["date"].iloc[-1])
            subset = self._backtest_sentiment_df[self._backtest_sentiment_df["date"] <= bar_date].tail(2)
            if len(subset) >= 2:
                sent_df = subset.reset_index(drop=True)
        if sent_df is None:
            from .base import _BACKTEST_ACTIVE
            if _BACKTEST_ACTIVE:
                return StrategySignal("HOLD", 0.0, "回测中无预取情绪数据", 0.5, {})
            sent_df = _get_sentiment_v2_last_two()
        if sent_df is not None and len(sent_df) >= 2:
            prev = sent_df.iloc[-2]
            curr = sent_df.iloc[-1]
            s_prev = prev["S"]
            s_curr = curr["S"]
            s_low_prev = prev["S_low"]
            s_high_prev = prev["S_high"]
            if pd.isna(s_prev) or pd.isna(s_curr):
                pass
            else:
                # 买入：前日 S < S_low 且当日 S 回升
                if s_prev < s_low_prev and s_curr > s_prev:
                    if _trend_filter_buy(df):
                        conf = 0.5 + 0.35 * min(abs(s_curr - s_prev) / 2.0, 1.0)
                        return StrategySignal(
                            action="BUY",
                            confidence=min(conf, 0.9),
                            position=0.75,
                            reason=f"情绪恐慌(S={s_prev:.2f}<S_low)且次日回升(S={s_curr:.2f})+趋势过滤",
                            indicators={"S": round(s_curr, 3), "S_low": round(s_low_prev, 3)},
                        )
                    return StrategySignal(
                        action="HOLD",
                        confidence=0.5,
                        position=0.5,
                        reason=f"情绪恐慌且次日回升(S={s_curr:.2f})，但趋势过滤未过",
                        indicators={"S": round(s_curr, 3)},
                    )
                # 卖出：前日 S > S_high 且当日 S 回落
                if s_prev > s_high_prev and s_curr < s_prev:
                    if _trend_filter_sell(df):
                        conf = 0.5 + 0.35 * min(abs(s_curr - s_prev) / 2.0, 1.0)
                        return StrategySignal(
                            action="SELL",
                            confidence=min(conf, 0.9),
                            position=0.15,
                            reason=f"情绪贪婪(S={s_prev:.2f}>S_high)且次日回落(S={s_curr:.2f})+趋势过滤",
                            indicators={"S": round(s_curr, 3), "S_high": round(s_high_prev, 3)},
                        )
                    return StrategySignal(
                        action="HOLD",
                        confidence=0.5,
                        position=0.5,
                        reason=f"情绪贪婪且次日回落(S={s_curr:.2f})，但趋势过滤未过",
                        indicators={"S": round(s_curr, 3)},
                    )
                # 未触发买卖
                return StrategySignal(
                    action="HOLD",
                    confidence=0.5,
                    position=0.5,
                    reason=f"情绪中性(S={s_curr:.2f}，未满足极端+次日确认)",
                    indicators={"S": round(s_curr, 3)},
                )

        # 2) 回退旧版：0~100 单指标，无趋势过滤
        sentiment = _get_latest_sentiment_legacy()
        if sentiment is None:
            return StrategySignal(
                action="HOLD",
                confidence=0.0,
                position=0.5,
                reason="无市场情绪数据",
                indicators={"sentiment_index": None},
            )
        deviation = abs(sentiment - 50.0) / 50.0
        confidence = 0.5 + 0.35 * deviation
        if sentiment <= self.low_threshold:
            pos = min(0.95, max(0.5, 0.5 + 0.4 * (1.0 - sentiment / max(1, self.low_threshold))))
            return StrategySignal(
                action="BUY",
                confidence=confidence,
                position=pos,
                reason=f"市场情绪恐慌(指数{sentiment:.1f}≤{self.low_threshold})，反向买入(旧版)",
                indicators={"sentiment_index": round(sentiment, 2)},
            )
        if sentiment >= self.high_threshold:
            pos = max(0.05, min(0.5, 0.5 * (1.0 - (sentiment - self.high_threshold) / max(1, 100 - self.high_threshold))))
            return StrategySignal(
                action="SELL",
                confidence=confidence,
                position=pos,
                reason=f"市场情绪贪婪(指数{sentiment:.1f}≥{self.high_threshold})，反向卖出(旧版)",
                indicators={"sentiment_index": round(sentiment, 2)},
            )
        return StrategySignal(
            action="HOLD",
            confidence=0.5,
            position=0.5,
            reason=f"市场情绪中性(指数{sentiment:.1f})(旧版)",
            indicators={"sentiment_index": round(sentiment, 2)},
        )
