"""
策略库 - 所有策略统一接口，支持交叉验证

每个策略接收单只股票的 DataFrame，返回标准化的 StrategySignal:
  - action:     BUY / SELL / HOLD
  - confidence: 0.0~1.0  信号强度
  - position:   0.0~1.0  建议目标仓位
  - reason:     人类可读决策理由
  - indicators: 指标快照

每个策略可选定义 param_ranges 类属性，格式:
  { 'param_name': (min, default, max, step) }
  用于后续参数扫描优化。
"""

from .base import Strategy, StrategySignal
from .ma_cross import MACrossStrategy
from .macd_cross import MACDStrategy
from .rsi_signal import RSIStrategy
from .bollinger_band import BollingerBandStrategy
from .kdj_signal import KDJStrategy
from .dual_momentum import DualMomentumSingleStrategy
from .sentiment import SentimentStrategy
from .news_sentiment import NewsSentimentStrategy
from .policy_event import PolicyEventStrategy
from .money_flow import MoneyFlowStrategy
from .ensemble import (EnsembleStrategy, ConservativeEnsemble,
                       BalancedEnsemble, AggressiveEnsemble,
                       V33EnsembleStrategy)

# 所有可用策略的注册表（含单策略 + 组合策略）
STRATEGY_REGISTRY = {
    # 单策略
    'MA':   MACrossStrategy,
    'MACD': MACDStrategy,
    'RSI':  RSIStrategy,
    'BOLL': BollingerBandStrategy,
    'KDJ':  KDJStrategy,
    'DUAL': DualMomentumSingleStrategy,
    'Sentiment': SentimentStrategy,
    'NewsSentiment': NewsSentimentStrategy,
    'PolicyEvent': PolicyEventStrategy,
    'MoneyFlow': MoneyFlowStrategy,
    # 组合策略
    '保守组合': ConservativeEnsemble,
    '均衡组合': BalancedEnsemble,
    '激进组合': AggressiveEnsemble,
    'V33组合': V33EnsembleStrategy,
}


def get_all_strategies(**override_params) -> dict:
    """获取所有策略实例（使用默认参数）"""
    return {name: cls(**override_params) for name, cls in STRATEGY_REGISTRY.items()}


def list_strategies() -> list:
    """
    列出所有可用策略的详细信息

    Returns:
        list of dict, 每个包含:
        - name, description, min_bars
        - param_ranges: { 'param': (min, default, max, step) }
    """
    result = []
    for name, cls in STRATEGY_REGISTRY.items():
        inst = cls()
        result.append({
            'name': name,
            'description': inst.description,
            'min_bars': inst.min_bars,
            'param_ranges': getattr(inst, 'param_ranges', {}),
        })
    return result
