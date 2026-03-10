"""
核心交易模块

包含：
- base_strategy.py          BaseStrategy 抽象基类（ETF回测引擎用）
- dual_momentum_strategy.py DualMomentumStrategy（MultiIndex DataFrame接口，ETF回测用）
- strategy_rule_engine.py   规则引擎（防情绪化交易）
- strategy_executor.py      策略执行器（含审计追踪）
- strategy_document.py      策略文档版本管理
- v33_weights.py            V3.3 组合动态权重计算
- backtest_constraints.py   回测防未来函数工具
- risk/                     多层风控管理
- simulator/                模拟交易账户
"""

from .base_strategy import BaseStrategy
from .momentum_math import (
    calc_absolute_momentum,
    calc_relative_momentum,
    check_stop_loss,
    check_market_crash,
    calc_liquidity,
)
from .dual_momentum_strategy import DualMomentumStrategy
from .strategy_rule_engine import StrategyRuleEngine, StrategyRule, RuleType
from .strategy_executor import StrategyExecutor
from .strategy_document import StrategyDocument
from src.strategies.v33_weights import compute_v33_weights, get_market_state
from .backtest_constraints import (
    filter_news_by_time,
    filter_policy_by_time,
    is_lhb_visible_at_date,
    filter_lhb_by_visible_date,
    check_sentiment_no_future,
)
