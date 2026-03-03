"""
多策略组合投票策略 (Ensemble Strategy)

原理:
- 同时运行多个子策略（MA, MACD, RSI, BOLL, KDJ, DUAL）
- 每个策略独立给出 BUY / SELL / HOLD 信号 + confidence + position
- 采用投票机制决策:
  - 多数看多 → 买入
  - 多数看空 → 卖出
  - 信号不一致 → 持有观望

投票模式:
- 'majority':  多数投票（默认，≥阈值才行动）
- 'unanimous': 全票通过才行动（最保守）
- 'any':       任意一个策略发出信号就行动（最激进，卖出优先保护利润）
- 'weighted':  按策略权重加权投票

HOLD 计分规则:
    HOLD 不参与投票分数的计算 — 仅 BUY/SELL 的加权和决定方向。
    HOLD 只影响 "有效策略数" 的分母。

目标仓位:
    最终 position = 所有子策略 position 的加权平均。

参数:
- mode:           投票模式（默认 'majority'）
- buy_threshold:  majority/weighted 模式下，BUY 所需比例（默认 0.5 即过半）
- sell_threshold: majority/weighted 模式下，SELL 所需比例（默认 0.5）
- weights:        各策略权重 dict，可从外部传入（默认基于交叉验证结果）
"""

import logging
from datetime import datetime

import pandas as pd
from typing import Dict, List, Optional
from .base import Strategy, StrategySignal
from .ma_cross import MACrossStrategy
from .macd_cross import MACDStrategy
from .rsi_signal import RSIStrategy
from .bollinger_band import BollingerBandStrategy
from .kdj_signal import KDJStrategy
from .dual_momentum import DualMomentumSingleStrategy
from .fundamental_pe import PEStrategy
from .sentiment import SentimentStrategy
from .news_sentiment import NewsSentimentStrategy
from .policy_event import PolicyEventStrategy
from .money_flow import MoneyFlowStrategy

try:
    from src.core.v33_weights import (
        fetch_index_for_state,
        get_market_state,
        should_trigger_adjustment,
        compute_v33_weights,
        base_weights,
    )
except ImportError:
    fetch_index_for_state = None
    get_market_state = None
    should_trigger_adjustment = None
    compute_v33_weights = None
    base_weights = None

logger = logging.getLogger(__name__)

# V3.3 新策略（情绪+消息+政策）仓位合计上限
V33_NEW_STRATEGY_POSITION_CAP = 0.4
# 重大利空优先：SELL 原因包含此关键词则无条件卖出
MAJOR_NEGATIVE_REASON_KEY = "重大利空"
# 冲突规则：卖出总分 × 此系数 与 买入总分 比较
SELL_SCORE_MULTIPLIER = 1.2


class EnsembleStrategy(Strategy):
    """
    多策略组合投票

    Attributes:
        sub_strategies:  {name: Strategy} 子策略实例
        weights:         {name: float}    策略权重，越高越受信任
        mode:            str              投票模式
        buy_threshold:   float            BUY 阈值
        sell_threshold:  float            SELL 阈值
    """

    name = '多策略组合'
    description = '7大策略投票决策（6技术+1基本面），多数看多/看空才行动'

    param_ranges = {
        'buy_threshold':  (0.3, 0.5, 0.8, 0.05),
        'sell_threshold': (0.3, 0.5, 0.8, 0.05),
    }

    def __init__(self, mode: str = 'majority',
                 buy_threshold: float = 0.5,
                 sell_threshold: float = 0.5,
                 weights: Optional[Dict[str, float]] = None,
                 **kwargs):
        self.mode = mode
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

        # 子策略实例（技术面 + 基本面）
        self.sub_strategies: Dict[str, Strategy] = {
            'MA':   MACrossStrategy(),
            'MACD': MACDStrategy(),
            'RSI':  RSIStrategy(),
            'BOLL': BollingerBandStrategy(),
            'KDJ':  KDJStrategy(),
            'DUAL': DualMomentumSingleStrategy(),
            'PE':   PEStrategy(),  # 基本面策略：PE估值
        }

        # 权重：支持外部传入，否则使用默认值
        # 默认权重依据：夏普高+回撤低 → 权重大
        # 基本面策略初始权重设为1.0（中等），后续可根据回测调整
        self.weights: Dict[str, float] = weights or {
            'DUAL': 1.5,   # 收益最高
            'BOLL': 1.3,   # 夏普最高、回撤最低
            'MA':   1.2,   # 收益第二
            'MACD': 1.1,   # 均衡
            'RSI':  1.0,   # 胜率高
            'PE':   1.0,   # 基本面策略（初始权重，待回测验证）
            'KDJ':  0.9,   # 交易频繁
        }

        # 最小K线数取所有子策略的最大值
        self.min_bars = max(s.min_bars for s in self.sub_strategies.values())

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        """运行所有子策略，投票决策"""

        votes: Dict[str, StrategySignal] = {}
        buy_votes: List[tuple] = []
        sell_votes: List[tuple] = []
        hold_votes: List[tuple] = []

        for strat_name, strat in self.sub_strategies.items():
            if len(df) < strat.min_bars:
                continue
            try:
                sig = strat.analyze(df)
                votes[strat_name] = sig
                if sig.action == 'BUY':
                    buy_votes.append((strat_name, sig))
                elif sig.action == 'SELL':
                    sell_votes.append((strat_name, sig))
                else:
                    hold_votes.append((strat_name, sig))
            except Exception as e:
                logger.warning(f"[{self.name}] 子策略 {strat_name} 异常: {e}")
                continue

        total = len(votes)
        if total == 0:
            return StrategySignal('HOLD', 0.0, '无策略可用', 0.5, {})

        # 投票详情
        vote_detail = {n: f"{s.action}({s.confidence:.0%})" for n, s in votes.items()}

        # 计算加权平均目标仓位
        total_weight = sum(self.weights.get(n, 1.0) for n in votes)
        avg_position = (sum(self.weights.get(n, 1.0) * s.position for n, s in votes.items())
                        / total_weight) if total_weight > 0 else 0.5

        # ========= 投票决策 =========
        if self.mode == 'unanimous':
            action, conf, reason = self._unanimous(buy_votes, sell_votes, total)
        elif self.mode == 'any':
            action, conf, reason = self._any(buy_votes, sell_votes)
        elif self.mode == 'weighted':
            action, conf, reason = self._weighted(buy_votes, sell_votes, total)
        else:  # majority
            action, conf, reason = self._majority(buy_votes, sell_votes, total)

        # 仓位直接使用子策略的加权平均，不施加硬性边界。
        # 子策略的 position 已包含风险考量（死叉平滑、仓位层级等），
        # 组合策略应信任加权平均的结果。如果 SELL 时 avg_position 偏高，
        # 说明部分策略不认为应该卖出——这种分歧信息应被保留，而非被覆盖。
        position = avg_position

        return StrategySignal(
            action=action,
            confidence=round(conf, 2),
            reason=reason,
            position=round(position, 2),
            indicators={
                '投票详情': vote_detail,
                '买入票': len(buy_votes),
                '卖出票': len(sell_votes),
                '观望票': len(hold_votes),
                '有效策略': total,
                '模式': self.mode,
                '加权仓位': round(avg_position, 2),
            },
        )

    def _majority(self, buy_votes, sell_votes, total):
        """多数投票 — HOLD 不参与计分"""
        buy_ratio = len(buy_votes) / total
        sell_ratio = len(sell_votes) / total

        if buy_ratio >= self.buy_threshold:
            names = [n for n, _ in buy_votes]
            avg_conf = sum(s.confidence for _, s in buy_votes) / len(buy_votes)
            return (
                'BUY', avg_conf,
                f"多数看多({len(buy_votes)}/{total}): {', '.join(names)}"
            )

        if sell_ratio >= self.sell_threshold:
            names = [n for n, _ in sell_votes]
            avg_conf = sum(s.confidence for _, s in sell_votes) / len(sell_votes)
            return (
                'SELL', avg_conf,
                f"多数看空({len(sell_votes)}/{total}): {', '.join(names)}"
            )

        return (
            'HOLD', 0.5,
            f"信号分歧(买{len(buy_votes)}/卖{len(sell_votes)}"
            f"/持{total - len(buy_votes) - len(sell_votes)})，观望"
        )

    def _unanimous(self, buy_votes, sell_votes, total):
        """全票通过"""
        if len(buy_votes) == total:
            avg_conf = sum(s.confidence for _, s in buy_votes) / total
            return 'BUY', avg_conf, f"全票看多({total}/{total})，强势买入"

        if len(sell_votes) == total:
            avg_conf = sum(s.confidence for _, s in sell_votes) / total
            return 'SELL', avg_conf, f"全票看空({total}/{total})，强势卖出"

        return ('HOLD', 0.5,
                f"未达成共识(买{len(buy_votes)}/卖{len(sell_votes)}/{total})，观望")

    def _any(self, buy_votes, sell_votes):
        """任意一个信号就行动（卖出优先，保护利润）"""
        if sell_votes:
            best = max(sell_votes, key=lambda x: x[1].confidence)
            return 'SELL', best[1].confidence, f"{best[0]}发出卖出: {best[1].reason}"
        if buy_votes:
            best = max(buy_votes, key=lambda x: x[1].confidence)
            return 'BUY', best[1].confidence, f"{best[0]}发出买入: {best[1].reason}"
        return 'HOLD', 0.5, "所有策略均持观望"

    def _weighted(self, buy_votes, sell_votes, total):
        """
        加权投票 — HOLD 计0分，仅 BUY/SELL 的加权和决定方向

        buy_score  = Σ(权重 × confidence)  for BUY votes
        sell_score = Σ(权重 × confidence)  for SELL votes
        total_active = buy_score + sell_score

        如果 buy_score / total_active >= buy_threshold → BUY
        如果 sell_score / total_active >= sell_threshold → SELL
        否则 → HOLD
        """
        buy_score = sum(self.weights.get(n, 1.0) * s.confidence
                        for n, s in buy_votes)
        sell_score = sum(self.weights.get(n, 1.0) * s.confidence
                         for n, s in sell_votes)

        # HOLD 不参与计分
        total_active = buy_score + sell_score
        if total_active == 0:
            return 'HOLD', 0.5, "无有效方向性信号"

        buy_pct = buy_score / total_active
        sell_pct = sell_score / total_active

        if buy_pct > sell_pct and buy_pct >= self.buy_threshold:
            names = [n for n, _ in buy_votes]
            return (
                'BUY', round(buy_pct, 2),
                f"加权看多({buy_pct:.0%}): {', '.join(names)}"
            )

        if sell_pct > buy_pct and sell_pct >= self.sell_threshold:
            names = [n for n, _ in sell_votes]
            return (
                'SELL', round(sell_pct, 2),
                f"加权看空({sell_pct:.0%}): {', '.join(names)}"
            )

        return 'HOLD', 0.5, f"加权信号中性(买{buy_pct:.0%}/卖{sell_pct:.0%})，观望"


# ============================================================
# 预设组合模式
# ============================================================

class ConservativeEnsemble(EnsembleStrategy):
    """
    保守组合: majority 模式
    - 买入需 ≥50% 策略看多（阈值0.5）
    - 卖出仅需 ≥34% 策略看空（阈值0.34，保护优先）
    
    注意: 阈值是比例而非绝对数量，因此适用于任意数量的子策略。
    当前有7个子策略（6技术+1基本面），阈值仍然有效：
    - 买入: 需要 ≥4/7 策略看多（50%阈值）
    - 卖出: 需要 ≥3/7 策略看空（34%阈值）
    """
    name = '保守组合'
    description = '多数看多才买入、少数看空即卖出，保护优先'

    def __init__(self, **kwargs):
        super().__init__(mode='majority', buy_threshold=0.5,
                         sell_threshold=0.34, **kwargs)


class BalancedEnsemble(EnsembleStrategy):
    """
    均衡组合: majority 模式
    - 买入和卖出均需 ≥50% 策略同意（阈值0.5）
    
    注意: 阈值是比例，适用于任意数量的子策略。
    当前有7个子策略，买入/卖出均需 ≥4/7 策略同意。
    """
    name = '均衡组合'
    description = '过半策略同意就行动，平衡收益与风险'

    def __init__(self, **kwargs):
        super().__init__(mode='majority', buy_threshold=0.5,
                         sell_threshold=0.5, **kwargs)


class AggressiveEnsemble(EnsembleStrategy):
    """
    激进组合: weighted 加权投票模式
    - BUY/SELL 的加权得分占 active 总分≥35% 即行动
    - HOLD 不参与计分，反应更灵敏
    
    注意: 阈值是比例，适用于任意数量的子策略。
    当前有7个子策略，加权投票模式下阈值仍然有效。
    """
    name = '激进组合'
    description = '加权投票，HOLD不计分，反应灵敏'

    def __init__(self, **kwargs):
        super().__init__(mode='weighted', buy_threshold=0.35,
                         sell_threshold=0.35, **kwargs)


# ============================================================
# V3.3 全策略组合（11 策略 + 重大利空优先 + 冲突规则 + 新策略仓位 40%）
# ============================================================

class V33EnsembleStrategy(Strategy):
    """
    V3.3 组合：11 策略投票，重大利空无条件卖出优先，否则买入总分 vs 卖出总分×1.2；
    情绪+消息+政策触发的开仓合计 ≤ 40%。
    """

    name = "V33组合"
    description = "11策略投票+重大利空优先+卖出×1.2+新策略仓位≤40%"

    param_ranges = {
        "buy_threshold": (0.35, 0.5, 0.7, 0.05),
        "sell_threshold": (0.35, 0.5, 0.7, 0.05),
    }

    def __init__(
        self,
        symbol: Optional[str] = None,
        buy_threshold: float = 0.5,
        sell_threshold: float = 0.5,
        weights: Optional[Dict[str, float]] = None,
        use_dynamic_weights: bool = True,
        **kwargs,
    ):
        self.symbol = symbol
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.use_dynamic_weights = use_dynamic_weights and compute_v33_weights is not None
        self.sub_strategies: Dict[str, Strategy] = {
            "MA": MACrossStrategy(),
            "MACD": MACDStrategy(),
            "RSI": RSIStrategy(),
            "BOLL": BollingerBandStrategy(),
            "KDJ": KDJStrategy(),
            "DUAL": DualMomentumSingleStrategy(),
            "PE": PEStrategy(),
            "Sentiment": SentimentStrategy(),
            "NewsSentiment": NewsSentimentStrategy(symbol=symbol or ""),
            "PolicyEvent": PolicyEventStrategy(),
            "MoneyFlow": MoneyFlowStrategy(symbol=symbol),
        }
        self.weights: Dict[str, float] = weights or {
            "DUAL": 1.5, "BOLL": 1.3, "MA": 1.2, "MACD": 1.1,
            "RSI": 1.0, "PE": 1.0, "KDJ": 0.9,
            "Sentiment": 1.0, "NewsSentiment": 1.0, "PolicyEvent": 1.0, "MoneyFlow": 1.0,
        }
        self.min_bars = max(s.min_bars for s in self.sub_strategies.values())
        # 动态权重冷却：上次调整日期、冷却截止日期、当前市场状态
        self._weight_adjustment_date: Optional[pd.Timestamp] = None
        self._weight_cooldown_until: Optional[pd.Timestamp] = None
        self._weight_state: Optional[str] = None

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        # 动态权重与冷却（Phase 5.2–5.4）
        as_of = pd.Timestamp(datetime.now().date())
        if df is not None and len(df) > 0 and hasattr(df.get("date", pd.Series()), "iloc"):
            try:
                d = df["date"] if "date" in df.columns else df.index
                as_of = pd.Timestamp(d.iloc[-1]) if hasattr(d, "iloc") else pd.Timestamp(datetime.now().date())
            except Exception:
                pass
        if self.use_dynamic_weights and compute_v33_weights is not None and fetch_index_for_state is not None:
            in_cooldown = (
                self._weight_cooldown_until is not None
                and as_of is not None
                and as_of < self._weight_cooldown_until
            )
            if not in_cooldown:
                index_df = fetch_index_for_state("000300", 60)
                trigger = should_trigger_adjustment(index_df, self._weight_state) if should_trigger_adjustment else True
                if trigger and index_df is not None:
                    as_of_dt = as_of.to_pydatetime() if hasattr(as_of, "to_pydatetime") else datetime.now()
                    w, state, adj_date = compute_v33_weights(
                        index_df, self._weight_state, self._weight_adjustment_date, as_of_dt
                    )
                    self.weights = {k: v for k, v in w.items() if k in self.sub_strategies}
                    self._weight_state = state
                    self._weight_adjustment_date = pd.Timestamp(adj_date) if adj_date else as_of
                    self._weight_cooldown_until = self._weight_adjustment_date + pd.Timedelta(days=7)

        votes: Dict[str, StrategySignal] = {}
        buy_votes: List[tuple] = []
        sell_votes: List[tuple] = []

        for name, strat in self.sub_strategies.items():
            if strat.min_bars > 0 and (df is None or len(df) < strat.min_bars):
                continue
            try:
                sig = strat.analyze(df if df is not None else pd.DataFrame())
                votes[name] = sig
                if sig.action == "BUY":
                    buy_votes.append((name, sig))
                elif sig.action == "SELL":
                    sell_votes.append((name, sig))
            except Exception as e:
                logger.warning("[V33组合] 子策略 %s 异常: %s", name, e)

        total = len(votes)
        if total == 0:
            return StrategySignal("HOLD", 0.0, "无策略可用", 0.5, {})

        # 1) 重大利空优先：任一 SELL 原因包含「重大利空」则无条件卖出
        for name, sig in sell_votes:
            if sig.reason and MAJOR_NEGATIVE_REASON_KEY in sig.reason:
                return StrategySignal(
                    action="SELL",
                    confidence=sig.confidence,
                    position=sig.position,
                    reason=f"重大利空优先({name}): {sig.reason}",
                    indicators={"投票详情": {n: f"{s.action}({s.confidence:.0%})" for n, s in votes.items()}},
                )

        # 2) 加权得分：买入总分 vs 卖出总分×1.2
        buy_score = sum(self.weights.get(n, 1.0) * s.confidence for n, s in buy_votes)
        sell_score = sum(self.weights.get(n, 1.0) * s.confidence for n, s in sell_votes) * SELL_SCORE_MULTIPLIER
        total_active = buy_score + sell_score
        if total_active <= 0:
            action, conf = "HOLD", 0.5
        elif buy_score > sell_score and buy_score / total_active >= self.buy_threshold:
            action, conf = "BUY", buy_score / total_active
        elif sell_score > buy_score and sell_score / total_active >= self.sell_threshold:
            action, conf = "SELL", sell_score / total_active
        else:
            action, conf = "HOLD", 0.5

        # 3) 目标仓位：加权平均，且新策略（情绪+消息+政策）合计 ≤ 40%
        total_w = sum(self.weights.get(n, 1.0) for n in votes)
        rest_weighted_pos = 0.0
        new_weighted_pos = 0.0
        new_names = {"Sentiment", "NewsSentiment", "PolicyEvent"}
        for n, s in votes.items():
            w = self.weights.get(n, 1.0)
            if n in new_names and s.action == "BUY":
                new_weighted_pos += w * s.position
            else:
                rest_weighted_pos += w * s.position
        new_capped = min(new_weighted_pos, V33_NEW_STRATEGY_POSITION_CAP * total_w)
        position = (rest_weighted_pos + new_capped) / total_w if total_w > 0 else 0.5
        position = max(0.0, min(1.0, position))

        if action == "HOLD":
            position = 0.5

        reason = f"V33投票: 买{buy_score:.2f} vs 卖×1.2={sell_score:.2f} → {action}"
        return StrategySignal(
            action=action,
            confidence=round(conf, 2),
            position=round(position, 2),
            reason=reason,
            indicators={
                "投票详情": {n: f"{s.action}({s.confidence:.0%})" for n, s in votes.items()},
                "买入票": len(buy_votes),
                "卖出票": len(sell_votes),
            },
        )
