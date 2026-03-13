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

策略分类:
  技术面 (technical): MA, MACD, RSI, BOLL, KDJ, DUAL
  基本面 (fundamental): PE, PB, PEPB
  消息面+资金面: NEWS(新闻情感), MONEY_FLOW(龙虎榜/大宗)
  市场级(不入Ensemble): Sentiment(市场情绪), PolicyEvent(政策事件，作选股前大盘过滤)

  组合策略 (ensemble): EnsembleStrategy(11子策略) / 保守/均衡/激进 / V33别名
"""

from .base import Strategy, StrategySignal

# ---- 技术面策略 ----
from .ma_cross import MACrossStrategy
from .macd_cross import MACDStrategy
from .rsi_signal import RSIStrategy
from .bollinger_band import BollingerBandStrategy
from .kdj_signal import KDJStrategy
from .dual_momentum import DualMomentumSingleStrategy
from .turnover_helper import calc_relative_turnover_rate, enhance_signal_with_turnover

# ---- 基本面策略 ----
from .fundamental_base import FundamentalQuantileBase
from .fundamental_pe import PEStrategy
from .fundamental_pb import PBStrategy
from .fundamental_pe_pb import PE_PB_CombinedStrategy

# ---- V3.3 扩展策略 ----
from .v33_weights import compute_v33_weights, get_market_state
from .sentiment import SentimentStrategy
from .news_sentiment import NewsSentimentStrategy
from .policy_event import PolicyEventStrategy
from .money_flow import MoneyFlowStrategy

# ---- 组合策略 ----
from .ensemble import (EnsembleStrategy, ConservativeEnsemble,
                       BalancedEnsemble, AggressiveEnsemble,
                       V33EnsembleStrategy)

# 所有可用策略的注册表（含单策略 + 组合策略）
STRATEGY_REGISTRY = {
    # 技术面单策略
    'MA':   MACrossStrategy,
    'MACD': MACDStrategy,
    'RSI':  RSIStrategy,
    'BOLL': BollingerBandStrategy,
    'KDJ':  KDJStrategy,
    'DUAL': DualMomentumSingleStrategy,
    # 基本面单策略
    'PE':    PEStrategy,
    'PB':    PBStrategy,
    'PE_PB': PE_PB_CombinedStrategy,
    # V3.3 扩展单策略
    'Sentiment':    SentimentStrategy,
    'NewsSentiment': NewsSentimentStrategy,
    'PolicyEvent':  PolicyEventStrategy,
    'MoneyFlow':    MoneyFlowStrategy,
    # 组合策略
    '保守组合': ConservativeEnsemble,
    '均衡组合': BalancedEnsemble,
    '激进组合': AggressiveEnsemble,
    'V33组合':  V33EnsembleStrategy,
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
