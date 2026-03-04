"""
龙虎榜/大宗交易策略（MoneyFlow）V3.3

- 龙虎榜：连续 2 日同席位净买/卖、占比>0.1%、机构权重>1.2；置信度 = min(占比/0.2%,1)×席位权重均值；有效期 3 日。
- 大宗：折价<3%、买方长线机构、额>1 亿→买入(0.5)；折价>5%、卖方控股股东/董监高、额>0.5 亿→卖出(0.8)；有效期 5 日。
- 信号时点：T 日交易 T+1 披露，信号 T+2 开盘执行（见 config/signal_timing.yaml）。
- 接口异常时尝试备用数据源，并可使用近 7 日本地缓存。
"""

import logging
import time
from typing import Optional, Tuple

import pandas as pd

from .base import Strategy, StrategySignal

logger = logging.getLogger(__name__)

# 近 7 日缓存：symbol -> (action, confidence, position, timestamp)，接口异常时使用
_MONEY_FLOW_CACHE: dict = {}
_MONEY_FLOW_CACHE_DAYS = 7


def _get_money_flow_signal(symbol: str) -> Tuple[Optional[str], Optional[float], Optional[float]]:
    """(action, confidence, position) 或 (None, None, None)。龙虎榜优先，其次大宗；成功时写入缓存。"""
    try:
        from src.data.money_flow import get_lhb_signal, get_dzjy_signal
    except ImportError:
        try:
            from data.money_flow import get_lhb_signal, get_dzjy_signal
        except ImportError:
            return None, None, None
    try:
        s = get_lhb_signal(symbol)
        if s is not None:
            _MONEY_FLOW_CACHE[symbol] = (s[0], s[1], s[2], time.time())
            return s[0], s[1], s[2]
        s = get_dzjy_signal(symbol)
        if s is not None:
            _MONEY_FLOW_CACHE[symbol] = (s[0], s[1], s[2], time.time())
            return s[0], s[1], s[2]
    except Exception as e:
        logger.debug("MoneyFlow 信号获取失败 %s: %s", symbol, e)
    return None, None, None


def _get_money_flow_from_cache(symbol: str) -> Tuple[Optional[str], Optional[float], Optional[float]]:
    """接口异常时使用近 7 日缓存。"""
    entry = _MONEY_FLOW_CACHE.get(symbol)
    if not entry:
        return None, None, None
    _, _, _, ts = entry
    if time.time() - ts > _MONEY_FLOW_CACHE_DAYS * 86400:
        return None, None, None
    return entry[0], entry[1], entry[2]


class MoneyFlowStrategy(Strategy):
    """龙虎榜/大宗交易策略 V3.3：同席位连续 2 日、占比与机构权重；大宗折价与买卖方。"""

    name = "MoneyFlow"
    description = "龙虎榜连续2日同席位净买/卖+大宗折价与买卖方(V3.3)，T+2开盘执行"

    param_ranges = {}
    min_bars = 0

    def __init__(self, symbol: Optional[str] = None, **kwargs):
        self.symbol = symbol

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        from .base import _BACKTEST_ACTIVE
        symbol = self.symbol
        if not symbol:
            return StrategySignal(
                action="HOLD",
                confidence=0.0,
                position=0.5,
                reason="未指定标的，无法获取龙虎榜/大宗数据",
                indicators={"money_flow": None},
            )
        # 回测时仅用本地预取/缓存，不实时拉取，避免每 bar I/O
        if _BACKTEST_ACTIVE:
            action, confidence, position = _get_money_flow_from_cache(symbol)
            if action is None:
                return StrategySignal("HOLD", 0.0, "回测中无预取龙虎榜/大宗数据", 0.5, {"money_flow": "no_prefetch"})
            return StrategySignal(
                action=action,
                confidence=round(confidence, 2),
                position=round(position, 2),
                reason=f"资金异动(回测预取)({action})",
                indicators={"money_flow": action},
            )
        try:
            action, confidence, position = _get_money_flow_signal(symbol)
            if action is not None:
                return StrategySignal(
                    action=action,
                    confidence=round(confidence, 2),
                    position=round(position, 2),
                    reason=f"资金异动({action}): 龙虎榜/大宗条件满足",
                    indicators={"money_flow": action},
                )
            action, confidence, position = _get_money_flow_from_cache(symbol)
            if action is not None:
                logger.info("[MoneyFlow] 标的=%s 主接口无数据，使用近7日缓存", symbol)
                return StrategySignal(
                    action=action,
                    confidence=round(confidence, 2),
                    position=round(position, 2),
                    reason=f"资金异动(缓存)({action})",
                    indicators={"money_flow": action},
                )
        except Exception as e:
            logger.warning(
                "[MoneyFlow] 策略=%s 标的=%s 时间=%s 主接口异常: %s",
                self.name, symbol, pd.Timestamp.now().isoformat(), e,
            )
            action, confidence, position = _get_money_flow_from_cache(symbol)
            if action is not None:
                logger.info("[MoneyFlow] 备用使用近7日缓存 标的=%s", symbol)
                return StrategySignal(
                    action=action,
                    confidence=round(confidence, 2),
                    position=round(position, 2),
                    reason=f"资金异动(缓存)({action})",
                    indicators={"money_flow": action},
                )
        return StrategySignal(
            action="HOLD",
            confidence=0.0,
            position=0.5,
            reason="龙虎榜/大宗接口异常且无有效缓存，暂观望",
            indicators={"money_flow": None},
        )
