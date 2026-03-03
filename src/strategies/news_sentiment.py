"""
新闻情感策略（NewsSentiment）V3.3

- 24h 内同向新闻最多 3 篇，加权平均得 S_news；新闻源权重参与最终置信度。
- 预期差（日频近似）：买入要求当日涨幅<3%，卖出要求当日跌幅<2%；无 K 线时不校验。
- 置信度：基础 = min(1, |S_news|×2 + 0.1×(N-1))；最终 = min(基础×新闻源权重, 1)。
- 无 V3.3 数据时回退为旧版近期 N 篇情感均值。
"""

import logging
from typing import Optional

import pandas as pd

from .base import Strategy, StrategySignal

logger = logging.getLogger(__name__)

# 预期差阈值（日频近似：1h 涨幅/跌幅 → 当日收益率）
BUY_MAX_DAILY_RETURN = 0.03   # 买入：当日涨幅 < 3%
SELL_MIN_DAILY_RETURN = -0.02  # 卖出：当日跌幅 < 2%（即 return > -2%）


def _daily_return_from_df(df: pd.DataFrame) -> Optional[float]:
    """最近一日收益率（日频近似预期差用）。"""
    if df is None or len(df) < 2:
        return None
    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if len(close) < 2:
        return None
    return float(close.iloc[-1] / close.iloc[-2] - 1.0)


def _get_news_sentiment_v33(symbol: str) -> Optional[tuple]:
    """(S_news, N, mean_source_weight)。无数据返回 None。"""
    try:
        from src.data.news import get_news_sentiment_v33
        return get_news_sentiment_v33(symbol, max_same_direction=3)
    except ImportError:
        try:
            from data.news import get_news_sentiment_v33
            return get_news_sentiment_v33(symbol, max_same_direction=3)
        except ImportError:
            return None


def _get_news_sentiment_legacy(symbol: str, max_news: int = 10) -> Optional[float]:
    """旧版：近期 N 篇情感均值（-1~1）。"""
    try:
        from src.data.news import fetch_stock_news, score_news_sentiment
        from src.data.news.sentiment import aggregate_sentiment
    except ImportError:
        try:
            from data.news import fetch_stock_news, score_news_sentiment
            from data.news.sentiment import aggregate_sentiment
        except ImportError:
            return None
    try:
        df = fetch_stock_news(symbol, max_items=max_news)
        if df is None or df.empty:
            return None
        scores = score_news_sentiment(df)
        return aggregate_sentiment(scores, method="mean")
    except Exception as e:
        logger.debug("获取新闻情感失败 %s: %s", symbol, e)
        return None


class NewsSentimentStrategy(Strategy):
    """新闻情感分析策略 V3.3：24h 同向 N、S_news、预期差日频近似、新闻源权重置信度。"""

    name = "NewsSentiment"
    description = "个股新闻情感(V3.3)：24h同向N、S_news、预期差日频近似、新闻源权重置信度"

    param_ranges = {
        "buy_threshold": (0.2, 0.3, 0.6, 0.1),
        "sell_threshold": (-0.6, -0.3, -0.2, 0.1),
        "max_news": (5, 10, 30, 5),
    }

    min_bars = 0

    def __init__(
        self,
        symbol: Optional[str] = None,
        buy_threshold: float = 0.3,
        sell_threshold: float = -0.3,
        max_news: int = 10,
        **kwargs,
    ):
        self.symbol = symbol
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.max_news = max_news

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        symbol = self.symbol
        if not symbol:
            return StrategySignal(
                action="HOLD",
                confidence=0.0,
                position=0.5,
                reason="未指定标的，无法获取新闻情感",
                indicators={"news_sentiment": None},
            )

        # 1) 优先 V3.3：24h 同向 N、S_news、新闻源权重
        v33 = _get_news_sentiment_v33(symbol)
        if v33 is not None:
            S_news, N, mean_weight = v33
            base_conf = min(1.0, abs(S_news) * 2.0 + 0.1 * max(0, N - 1))
            confidence = min(1.0, base_conf * mean_weight)
            daily_ret = _daily_return_from_df(df) if df is not None and not df.empty else None

            # 买入：S_news > 0.3 且 预期差（日频：当日涨幅<3%）
            if S_news >= self.buy_threshold:
                if daily_ret is not None and daily_ret >= BUY_MAX_DAILY_RETURN:
                    return StrategySignal(
                        action="HOLD",
                        confidence=0.5,
                        position=0.5,
                        reason=f"新闻偏利好(S_news={S_news:.2f})但当日已涨{daily_ret:.2%}≥{BUY_MAX_DAILY_RETURN:.0%}，预期差未过",
                        indicators={"S_news": round(S_news, 3), "N": N},
                    )
                pos = 0.5 + 0.4 * min((S_news - self.buy_threshold) / (1.0 - self.buy_threshold), 1.0)
                pos = min(0.9, max(0.5, pos))
                return StrategySignal(
                    action="BUY",
                    confidence=round(confidence, 2),
                    position=round(pos, 2),
                    reason=f"24h同向{N}篇利好(S_news={S_news:.2f})+预期差通过",
                    indicators={"S_news": round(S_news, 3), "N": N, "source_weight": round(mean_weight, 2)},
                )

            # 卖出：S_news < -0.3 且 预期差（日频：当日跌幅<2% 即 return > -2%）
            if S_news <= self.sell_threshold:
                if daily_ret is not None and daily_ret <= SELL_MIN_DAILY_RETURN:
                    return StrategySignal(
                        action="HOLD",
                        confidence=0.5,
                        position=0.5,
                        reason=f"新闻偏利空(S_news={S_news:.2f})但当日已跌{daily_ret:.2%}≤{SELL_MIN_DAILY_RETURN:.0%}，预期差未过",
                        indicators={"S_news": round(S_news, 3), "N": N},
                    )
                pos = max(0.05, 0.5 - 0.4 * min((self.sell_threshold - S_news) / max(0.01, abs(self.sell_threshold)), 1.0))
                return StrategySignal(
                    action="SELL",
                    confidence=round(confidence, 2),
                    position=round(pos, 2),
                    reason=f"24h同向{N}篇利空(S_news={S_news:.2f})+预期差通过",
                    indicators={"S_news": round(S_news, 3), "N": N, "source_weight": round(mean_weight, 2)},
                )

            return StrategySignal(
                action="HOLD",
                confidence=0.5,
                position=0.5,
                reason=f"新闻情感中性(S_news={S_news:.2f}, N={N})",
                indicators={"S_news": round(S_news, 3), "N": N},
            )

        # 2) 回退旧版
        agg = _get_news_sentiment_legacy(symbol, max_news=self.max_news)
        if agg is None:
            return StrategySignal(
                action="HOLD",
                confidence=0.0,
                position=0.5,
                reason="无近期新闻或获取失败",
                indicators={"news_sentiment": None},
            )
        confidence = 0.5 + 0.35 * min(abs(agg), 1.0)
        if agg >= self.buy_threshold:
            pos = min(0.9, max(0.5, 0.5 + 0.4 * min((agg - self.buy_threshold) / (1.0 - self.buy_threshold), 1.0)))
            return StrategySignal(
                action="BUY",
                confidence=confidence,
                position=pos,
                reason=f"近期新闻偏利好(情感{agg:.2f}≥{self.buy_threshold})(旧版)",
                indicators={"news_sentiment": round(agg, 3)},
            )
        if agg <= self.sell_threshold:
            pos = max(0.05, min(0.5, 0.5 * (1.0 - (agg - self.sell_threshold) / max(0.01, self.sell_threshold))))
            return StrategySignal(
                action="SELL",
                confidence=confidence,
                position=pos,
                reason=f"近期新闻偏利空(情感{agg:.2f}≤{self.sell_threshold})(旧版)",
                indicators={"news_sentiment": round(agg, 3)},
            )
        return StrategySignal(
            action="HOLD",
            confidence=0.5,
            position=0.5,
            reason=f"近期新闻情感中性({agg:.2f})(旧版)",
            indicators={"news_sentiment": round(agg, 3)},
        )
