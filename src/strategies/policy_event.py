"""
政策事件驱动策略（PolicyEvent）V3.3

- 买入：重大利好 + 当前情绪 S < S_high + 标的行业指数当日涨幅 < 2%（暂无行业映射时用沪深300 1 日涨幅）；置信度 = 影响力 × (1 + 情绪强化)，恐慌乘 1.3、贪婪乘 0.7。
- 卖出：重大利空（影响力≥1.0 + 关键词：监管加强/反垄断/集采降价/出口管制）→ 无条件优先卖出，置信度 = 影响力 × 1.2；否则按普通利空参与投票。
- 行业市值占全市场≥5% 条件暂不实现，见文档。
"""

import logging
from typing import Optional

import pandas as pd

from .base import Strategy, StrategySignal

logger = logging.getLogger(__name__)

# 买入时要求：行业/指数当日涨幅 < 2%（无行业映射时用沪深300）
MAX_INDEX_RETURN_FOR_BUY = 0.02


def _get_recent_index_return(lookback_days: int = 5) -> Optional[float]:
    """近期指数涨跌幅（如 1 日或 5 日）。无数据返回 None。"""
    try:
        import akshare as ak
        from datetime import datetime, timedelta
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=lookback_days + 15)).strftime("%Y%m%d")
        df = ak.stock_zh_index_hist_csindex(symbol="000300", start_date=start, end_date=end)
        if df is None or len(df) < lookback_days + 1:
            return None
        df = df.rename(columns={"日期": "date", "收盘": "close"})
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        close = pd.to_numeric(df["close"], errors="coerce")
        if len(close) < lookback_days + 1:
            return None
        return float(close.iloc[-1] / close.iloc[-1 - lookback_days] - 1.0)
    except Exception as e:
        logger.debug("获取近期指数涨幅失败: %s", e)
        return None


def _get_market_sentiment_s_high() -> Optional[tuple]:
    """(S, S_low, S_high) 或 None。用于买入条件 S < S_high 与情绪强化（恐慌/贪婪）。"""
    try:
        from src.data.sentiment.sentiment_index import get_s_low_s_high_latest
        return get_s_low_s_high_latest(80)
    except ImportError:
        try:
            from data.sentiment.sentiment_index import get_s_low_s_high_latest
            return get_s_low_s_high_latest(80)
        except ImportError:
            return None


def _get_policy_v33(max_news: int = 15) -> Optional[tuple]:
    """(agg_score, has_major_negative, avg_influence)。"""
    try:
        from src.data.policy import get_policy_sentiment_v33
        return get_policy_sentiment_v33(max_news=max_news)
    except ImportError:
        try:
            from data.policy import get_policy_sentiment_v33
            return get_policy_sentiment_v33(max_news=max_news)
        except ImportError:
            return None


def _get_policy_legacy(max_news: int = 15) -> Optional[float]:
    """旧版：仅政策情感聚合。"""
    try:
        from src.data.policy import get_policy_sentiment as _get
        return _get(max_news=max_news)
    except ImportError:
        try:
            from data.policy import get_policy_sentiment as _get
            return _get(max_news=max_news)
        except ImportError:
            return None


def _get_policy_prefetch_for_backtest(df: pd.DataFrame):
    """回测时从本地预取数据读取（预留 parquet 等）。无预取返回 None。"""
    return None


def _analyze_from_prefetched_policy(prefetched: dict, buy_threshold: float, sell_threshold: float) -> StrategySignal:
    """用预取政策数据计算信号。"""
    agg = prefetched.get("agg")
    if agg is None:
        return StrategySignal("HOLD", 0.0, 0.5, "预取政策数据无效", {})
    confidence = 0.5 + 0.35 * min(abs(agg), 1.0)
    if prefetched.get("has_major_negative") and agg <= 0:
        return StrategySignal("SELL", min(1.0, prefetched.get("avg_influence", 1) * 1.2), 0.15, "预取重大利空", {"policy_agg": agg})
    if agg >= buy_threshold:
        return StrategySignal("BUY", confidence, min(0.9, 0.5 + 0.4 * (agg - buy_threshold) / (1 - buy_threshold)), f"预取政策利好{agg:.2f}", {"policy_agg": agg})
    if agg <= sell_threshold:
        return StrategySignal("SELL", confidence, max(0.05, 0.5 - 0.4 * (sell_threshold - agg) / abs(sell_threshold)), f"预取政策利空{agg:.2f}", {"policy_agg": agg})
    return StrategySignal("HOLD", 0.5, 0.5, f"预取政策中性{agg:.2f}", {"policy_agg": agg})


def _get_policy_backup(
    max_news: int,
    buy_threshold: float,
    sell_threshold: float,
    max_index_return_for_buy: float,
) -> Optional[StrategySignal]:
    """备用：主流财经媒体政策专栏（预留），失败返回 None。"""
    agg = _get_policy_legacy(max_news=max_news)
    if agg is None:
        return None
    confidence = 0.5 + 0.35 * min(abs(agg), 1.0)
    if agg >= buy_threshold:
        pos = min(0.9, max(0.5, 0.5 + 0.4 * min((agg - buy_threshold) / (1.0 - buy_threshold), 1.0)))
        return StrategySignal("BUY", confidence, pos, f"备用政策利好({agg:.2f})", {"policy_agg": round(agg, 3)})
    if agg <= sell_threshold:
        pos = max(0.05, min(0.5, 0.5 * (1.0 - (agg - sell_threshold) / max(0.01, sell_threshold))))
        return StrategySignal("SELL", confidence, pos, f"备用政策利空({agg:.2f})", {"policy_agg": round(agg, 3)})
    return StrategySignal("HOLD", 0.5, 0.5, f"备用政策中性({agg:.2f})", {"policy_agg": round(agg, 3)})


class PolicyEventStrategy(Strategy):
    """政策事件驱动 V3.3：重大利好 + S<S_high + 指数涨幅<2% 买入；重大利空无条件卖出。"""

    name = "PolicyEvent"
    description = "政策面V3.3：利好+S<S_high+涨幅<2%买入，重大利空无条件卖出，置信度×情绪强化"

    param_ranges = {
        "buy_threshold": (0.2, 0.3, 0.6, 0.1),
        "sell_threshold": (-0.6, -0.3, -0.2, 0.1),
        "max_news": (5, 15, 30, 5),
        "max_index_return_for_buy": (0.01, 0.02, 0.05, 0.01),
    }

    min_bars = 0

    def __init__(
        self,
        buy_threshold: float = 0.3,
        sell_threshold: float = -0.3,
        max_news: int = 15,
        max_index_return_for_buy: float = 0.02,
        **kwargs,
    ):
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.max_news = max_news
        self.max_index_return_for_buy = max_index_return_for_buy

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        from .base import _BACKTEST_ACTIVE
        if _BACKTEST_ACTIVE:
            prefetched = _get_policy_prefetch_for_backtest(df)
            if prefetched is None:
                return StrategySignal("HOLD", 0.0, "回测中无预取政策数据", 0.5, {"policy": "no_prefetch"})
            return _analyze_from_prefetched_policy(prefetched, self.buy_threshold, self.sell_threshold)
        try:
            return self._analyze_impl(df)
        except Exception as e:
            logger.warning(
                "[PolicyEvent] 策略=%s 时间=%s 主接口异常: %s",
                self.name, pd.Timestamp.now().isoformat(), e,
            )
            try:
                out = _get_policy_backup(self.max_news, self.buy_threshold, self.sell_threshold, self.max_index_return_for_buy)
                if out is not None:
                    return out
            except Exception as e2:
                logger.debug("[PolicyEvent] 备用接口(财经媒体政策专栏)异常: %s", e2)
            return StrategySignal(
                action="HOLD",
                confidence=0.0,
                position=0.5,
                reason="政策接口异常及备用均失败，暂观望",
                indicators={"policy": None},
            )

    def _analyze_impl(self, df: pd.DataFrame) -> StrategySignal:
        v33 = _get_policy_v33(max_news=self.max_news)
        if v33 is not None:
            agg, has_major_negative, avg_influence = v33
            sent = _get_market_sentiment_s_high()
            S, S_low, S_high = (sent if sent and len(sent) == 3 else (None, None, None))
            index_1d = _get_recent_index_return(1)

            # 重大利空 → 无条件卖出优先
            if has_major_negative and agg <= 0:
                conf = min(1.0, avg_influence * 1.2)
                return StrategySignal(
                    action="SELL",
                    confidence=round(conf, 2),
                    position=0.15,
                    reason="重大利空(影响力≥1.0+监管/反垄断/集采/出口管制)，无条件卖出",
                    indicators={"policy_agg": round(agg, 3), "influence": round(avg_influence, 2)},
                )

            # 买入：重大利好 + S < S_high + 指数当日涨幅 < 2%
            if agg >= self.buy_threshold:
                if S is not None and S_high is not None and S >= S_high:
                    return StrategySignal(
                        action="HOLD",
                        confidence=0.5,
                        position=0.5,
                        reason=f"政策偏利好({agg:.2f})但情绪S({S:.2f})≥S_high({S_high:.2f})，不追高",
                        indicators={"policy_agg": round(agg, 3)},
                    )
                if index_1d is not None and index_1d >= self.max_index_return_for_buy:
                    return StrategySignal(
                        action="HOLD",
                        confidence=0.5,
                        position=0.5,
                        reason=f"政策偏利好({agg:.2f})但指数当日已涨{index_1d:.2%}≥{self.max_index_return_for_buy:.0%}",
                        indicators={"policy_agg": round(agg, 3)},
                    )
                # 情绪强化：恐慌乘 1.3、贪婪乘 0.7 => boost 0.3 / -0.3
                sentiment_boost = 0.0
                if S is not None and S_low is not None and S_high is not None:
                    if S <= S_low:
                        sentiment_boost = 0.3
                    elif S >= S_high:
                        sentiment_boost = -0.3
                conf = min(1.0, avg_influence * (1.0 + sentiment_boost))
                pos = 0.5 + 0.4 * min((agg - self.buy_threshold) / (1.0 - self.buy_threshold), 1.0)
                pos = min(0.9, max(0.5, pos))
                return StrategySignal(
                    action="BUY",
                    confidence=round(conf, 2),
                    position=round(pos, 2),
                    reason=f"政策面利好({agg:.2f})+S<S_high+涨幅<2%，影响力×情绪强化",
                    indicators={"policy_agg": round(agg, 3), "influence": round(avg_influence, 2)},
                )

            # 普通利空
            if agg <= self.sell_threshold:
                conf = min(1.0, avg_influence * 1.2)
                pos = max(0.05, 0.5 - 0.4 * min((self.sell_threshold - agg) / max(0.01, abs(self.sell_threshold)), 1.0))
                return StrategySignal(
                    action="SELL",
                    confidence=round(conf, 2),
                    position=round(pos, 2),
                    reason=f"政策面偏利空(情感{agg:.2f}≤{self.sell_threshold})",
                    indicators={"policy_agg": round(agg, 3), "influence": round(avg_influence, 2)},
                )

            return StrategySignal(
                action="HOLD",
                confidence=0.5,
                position=0.5,
                reason=f"政策面中性(情感{agg:.2f})",
                indicators={"policy_agg": round(agg, 3)},
            )

        # 回退旧版
        agg = _get_policy_legacy(max_news=self.max_news)
        if agg is None:
            return StrategySignal(
                action="HOLD",
                confidence=0.0,
                position=0.5,
                reason="无政策面数据或获取失败",
                indicators={"policy_sentiment": None},
            )
        confidence = 0.5 + 0.35 * min(abs(agg), 1.0)
        if agg >= self.buy_threshold:
            index_ret = _get_recent_index_return(5)
            if index_ret is not None and index_ret > self.max_index_return_for_buy:
                return StrategySignal(
                    action="HOLD",
                    confidence=0.5,
                    position=0.5,
                    reason=f"政策偏利好({agg:.2f})但近期指数已涨{index_ret:.2%}，暂不追高(旧版)",
                    indicators={"policy_sentiment": round(agg, 3)},
                )
            pos = min(0.9, max(0.5, 0.5 + 0.4 * min((agg - self.buy_threshold) / (1.0 - self.buy_threshold), 1.0)))
            return StrategySignal(
                action="BUY",
                confidence=confidence,
                position=pos,
                reason=f"政策面偏利好(情感{agg:.2f}≥{self.buy_threshold})(旧版)",
                indicators={"policy_sentiment": round(agg, 3)},
            )
        if agg <= self.sell_threshold:
            pos = max(0.05, min(0.5, 0.5 * (1.0 - (agg - self.sell_threshold) / max(0.01, abs(self.sell_threshold)))))
            return StrategySignal(
                action="SELL",
                confidence=confidence,
                position=pos,
                reason=f"政策面偏利空(情感{agg:.2f}≤{self.sell_threshold})(旧版)",
                indicators={"policy_sentiment": round(agg, 3)},
            )
        return StrategySignal(
            action="HOLD",
            confidence=0.5,
            position=0.5,
            reason=f"政策面中性(情感{agg:.2f})(旧版)",
            indicators={"policy_sentiment": round(agg, 3)},
        )
