"""
龙虎榜/大宗交易策略（MoneyFlow）V3.3

- 龙虎榜：连续 2 日同席位净买/卖、占比>0.1%、机构权重>1.2；置信度 = min(占比/0.2%,1)×席位权重均值；有效期 3 日。
- 大宗：折价<3%、买方长线机构、额>1 亿→买入(0.5)；折价>5%、卖方控股股东/董监高、额>0.5 亿→卖出(0.8)；有效期 5 日。
- 信号时点：T 日交易 T+1 披露，信号 T+2 开盘执行（见 config/signal_timing.yaml）。
"""

import logging
from typing import Optional

import pandas as pd

from .base import Strategy, StrategySignal

logger = logging.getLogger(__name__)


def _get_money_flow_signal(symbol: str):
    """(action, confidence, position) 或 (None, None, None)。龙虎榜优先，其次大宗。"""
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
            return s[0], s[1], s[2]
        s = get_dzjy_signal(symbol)
        if s is not None:
            return s[0], s[1], s[2]
    except Exception as e:
        logger.debug("MoneyFlow 信号获取失败 %s: %s", symbol, e)
    return None, None, None


class MoneyFlowStrategy(Strategy):
    """龙虎榜/大宗交易策略 V3.3：同席位连续 2 日、占比与机构权重；大宗折价与买卖方。"""

    name = "MoneyFlow"
    description = "龙虎榜连续2日同席位净买/卖+大宗折价与买卖方(V3.3)，T+2开盘执行"

    param_ranges = {}
    min_bars = 0

    def __init__(self, symbol: Optional[str] = None, **kwargs):
        self.symbol = symbol

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        symbol = self.symbol
        if not symbol:
            return StrategySignal(
                action="HOLD",
                confidence=0.0,
                position=0.5,
                reason="未指定标的，无法获取龙虎榜/大宗数据",
                indicators={"money_flow": None},
            )
        action, confidence, position = _get_money_flow_signal(symbol)
        if action is None:
            return StrategySignal(
                action="HOLD",
                confidence=0.0,
                position=0.5,
                reason="无龙虎榜/大宗信号或数据不可用",
                indicators={"money_flow": None},
            )
        return StrategySignal(
            action=action,
            confidence=round(confidence, 2),
            position=round(position, 2),
            reason=f"资金异动({action}): 龙虎榜/大宗条件满足",
            indicators={"money_flow": action},
        )
