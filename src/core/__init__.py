"""
核心交易模块

包含：
- dual_momentum_strategy.py DualMomentumStrategy（MultiIndex DataFrame接口，ETF回测用）
- momentum_math.py          动量计算共用函数
- backtest_constraints.py   回测防未来函数工具
- risk/                     多层风控管理
- simulator/                模拟交易账户
"""

from .momentum_math import (
    calc_absolute_momentum,
    calc_relative_momentum,
    check_stop_loss,
    check_market_crash,
    calc_liquidity,
)
from .dual_momentum_strategy import DualMomentumStrategy
from src.strategies.v33_weights import compute_v33_weights, get_market_state
from .backtest_constraints import (
    filter_news_by_time,
    filter_policy_by_time,
    is_lhb_visible_at_date,
    filter_lhb_by_visible_date,
    check_sentiment_no_future,
)
