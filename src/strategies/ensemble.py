"""
多策略组合投票策略 (Ensemble Strategy)

原理:
- 同时运行多个子策略（MA, MACD, RSI, BOLL, KDJ, DUAL + 基本面 + 消息面 + 资金面）
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
- symbol:         股票代码（NewsSentiment/MoneyFlow 需要）
- stock_name:     股票名称（NewsSentiment LLM 分析用）
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
from .fundamental_pb import PBStrategy
from .fundamental_pe_pb import PE_PB_CombinedStrategy
from .sentiment import SentimentStrategy
from .news_sentiment import NewsSentimentStrategy
from .policy_event import PolicyEventStrategy
from .money_flow import MoneyFlowStrategy

try:
    from src.strategies.v33_weights import (
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
        holding_cost:    float | None     持仓成本价（传入时启用止损感知）
        stop_loss_pct:   float            硬止损比例，默认 -8%
        warn_loss_pct:   float            预警比例，默认 -5%（触发减仓建议）
    """

    name = '多策略组合'
    description = '11策略投票决策（6技术+3基本面+消息面+资金面），加权投票'

    param_ranges = {
        'buy_threshold':  (0.3, 0.5, 0.8, 0.05),
        'sell_threshold': (0.3, 0.5, 0.8, 0.05),
    }

    def __init__(self, mode: str = 'weighted',
                 buy_threshold: float = 0.45,
                 sell_threshold: float = 0.45,
                 weights: Optional[Dict[str, float]] = None,
                 holding_cost: Optional[float] = None,
                 stop_loss_pct: float = -0.08,
                 warn_loss_pct: float = -0.05,
                 symbol: Optional[str] = None,
                 stock_name: str = '',
                 **kwargs):
        self.mode = mode
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.holding_cost = holding_cost
        self.stop_loss_pct = stop_loss_pct
        self.warn_loss_pct = warn_loss_pct
        self.symbol = symbol
        self.stock_name = stock_name

        # 子策略实例（技术面 6 + 基本面 3 + 消息面 1 + 资金面 1）
        self.sub_strategies: Dict[str, Strategy] = {
            'MA':           MACrossStrategy(),
            'MACD':         MACDStrategy(),
            'RSI':          RSIStrategy(),
            'BOLL':         BollingerBandStrategy(),
            'KDJ':          KDJStrategy(),
            'DUAL':         DualMomentumSingleStrategy(),
            'PE':           PEStrategy(),
            'PB':           PBStrategy(),
            'PEPB':         PE_PB_CombinedStrategy(),
            'NEWS':         NewsSentimentStrategy(symbol=symbol, stock_name=stock_name),
            'MONEY_FLOW':   MoneyFlowStrategy(symbol=symbol),
        }

        # 权重：基于 v3 回测结果（235只股票）调整
        # 回测夏普排名：BOLL(0.20) > MACD(0.16) > KDJ(0.15) > MA(0.12) > PE(0.11) > RSI(0.07)
        # 回测回撤排名：PE(9%) < BOLL(14%) < RSI(16%) < KDJ(19%) < MA(19%) < MACD(20%)
        # NEWS/MONEY_FLOW 无回测数据，保守权重；触发时信号质量高（LLM+龙虎榜）
        self.weights: Dict[str, float] = weights or {
            'BOLL':       1.5,   # 技术面：夏普最高(0.20)、回撤最小(13.8%)，综合最优
            'MACD':       1.3,   # 技术面：收益最高(+15.3%)，夏普第二(0.16)
            'KDJ':        1.1,   # 技术面：夏普第三(0.15)，盈利率70.6%
            'MA':         1.0,   # 技术面：收益第三(+13.9%)
            'DUAL':       0.9,   # 技术面：无单独回测数据，保守权重
            'RSI':        0.8,   # 技术面：夏普最低(0.07)，降权
            'PEPB':       0.8,   # 基本面：双因子共振，信号最强但数据要求高
            'PE':         0.6,   # 基本面：回撤最小(9%)，适合辅助过滤
            'PB':         0.6,   # 基本面：单因子PB
            'NEWS':       0.5,   # 消息面：关键词+LLM融合，触发频率中等，保守权重
            'MONEY_FLOW': 0.4,   # 资金面：龙虎榜+大宗，触发频率低但信号质量高
        }

        # min_bars 只取技术策略的最大值；其他策略有数据时参与，无数据时被剔除逻辑过滤
        non_tech_keys = {'PE', 'PB', 'PEPB', 'NEWS', 'MONEY_FLOW'}
        tech_strategies = {k: v for k, v in self.sub_strategies.items() if k not in non_tech_keys}
        self.min_bars = max(s.min_bars for s in tech_strategies.values())

        # 动态权重状态（冷却 7 日，市场状态变化时触发）
        self._use_dynamic_weights: bool = (compute_v33_weights is not None)
        self._weight_state: Optional[str] = None
        self._weight_adjustment_date: Optional[pd.Timestamp] = None
        self._weight_cooldown_until: Optional[pd.Timestamp] = None
        self._backtest_index_df = None

    def set_symbol(self, symbol: str, stock_name: str = '') -> None:
        """动态更新 symbol，供选股循环复用同一实例时逐股注入。"""
        self.symbol = symbol
        if stock_name:
            self.stock_name = stock_name
        news_strat = self.sub_strategies.get('NEWS')
        if news_strat is not None:
            news_strat.symbol = symbol
            if stock_name:
                news_strat.stock_name = stock_name
        mf_strat = self.sub_strategies.get('MONEY_FLOW')
        if mf_strat is not None:
            mf_strat.symbol = symbol

    def prepare_backtest(self, df: pd.DataFrame) -> None:
        """
        回测前预取沪深300指数（用于动态权重）及各子策略外部数据。
        实盘无需调用，analyze 时实时获取。
        """
        for strat in self.sub_strategies.values():
            if hasattr(strat, 'prepare_backtest'):
                try:
                    strat.prepare_backtest(df)
                except Exception:
                    pass
        if df is None or df.empty or 'date' not in df.columns:
            return
        start_d = pd.Timestamp(df['date'].iloc[0]) - pd.Timedelta(days=90)
        end_d = pd.Timestamp(df['date'].iloc[-1])
        start_str = start_d.strftime('%Y%m%d')
        end_str = end_d.strftime('%Y%m%d')
        idx_df = None
        try:
            # 优先复用 v33_weights 的进程级缓存，减少重复网络请求
            from src.strategies.v33_weights import fetch_index_for_state
            days_needed = max(90, (end_d - start_d).days + 30)
            idx_df = fetch_index_for_state(symbol='000300', days=days_needed)
            if idx_df is not None and not idx_df.empty:
                # 截取需要的时间范围
                idx_df = idx_df[idx_df['date'] >= pd.Timestamp(start_d)].reset_index(drop=True)
        except Exception:
            pass
        if idx_df is None or idx_df.empty:
            try:
                import akshare as ak
                raw = ak.stock_zh_index_hist_csindex(symbol='000300', start_date=start_str, end_date=end_str)
                if raw is not None and len(raw) >= 30:
                    raw = raw.rename(columns={'日期': 'date', '收盘': 'close', '最高': 'high', '最低': 'low'})
                    raw['date'] = pd.to_datetime(raw['date'])
                    for c in ['high', 'low']:
                        if c not in raw.columns:
                            raw[c] = raw['close']
                    for c in ['high', 'low', 'close']:
                        raw[c] = pd.to_numeric(raw[c], errors='coerce').fillna(raw['close'])
                    idx_df = raw.dropna(subset=['close']).sort_values('date').reset_index(drop=True)
            except Exception as e:
                logger.debug('prepare_backtest 预取沪深300失败: %s', e)
        self._backtest_index_df = idx_df

    def _update_dynamic_weights(self, as_of: pd.Timestamp) -> None:
        """根据市场状态动态调整权重（7日冷却）。"""
        if not self._use_dynamic_weights or compute_v33_weights is None:
            return
        in_cooldown = (
            self._weight_cooldown_until is not None
            and as_of < self._weight_cooldown_until
        )
        if in_cooldown:
            return
        from .base import _BACKTEST_ACTIVE
        index_df = None
        if _BACKTEST_ACTIVE and self._backtest_index_df is not None:
            sub = self._backtest_index_df[self._backtest_index_df['date'] <= as_of].tail(60)
            if len(sub) >= 30:
                index_df = sub.reset_index(drop=True)
        elif not _BACKTEST_ACTIVE and fetch_index_for_state is not None:
            index_df = fetch_index_for_state('000300', 60)
        if index_df is None:
            return
        if should_trigger_adjustment and not should_trigger_adjustment(index_df, self._weight_state):
            return
        as_of_dt = as_of.to_pydatetime() if hasattr(as_of, 'to_pydatetime') else datetime.now()
        w, state, adj_date = compute_v33_weights(
            index_df, self._weight_state, self._weight_adjustment_date, as_of_dt
        )
        # 只更新 Ensemble 中实际存在的策略权重
        for k, v in w.items():
            if k in self.sub_strategies:
                self.weights[k] = v
        self._weight_state = state
        self._weight_adjustment_date = pd.Timestamp(adj_date) if adj_date else as_of
        self._weight_cooldown_until = self._weight_adjustment_date + pd.Timedelta(days=7)
        logger.info('动态权重已更新: 市场状态=%s，冷却至%s', state, self._weight_cooldown_until.date())

    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        """运行所有子策略，投票决策，并叠加持仓成本感知"""

        # ========= 动态权重更新 =========
        try:
            as_of = pd.Timestamp(df['date'].iloc[-1]) if (df is not None and len(df) > 0 and 'date' in df.columns) else pd.Timestamp(datetime.now().date())
            self._update_dynamic_weights(as_of)
        except Exception as e:
            logger.debug('动态权重更新跳过: %s', e)

        # ========= 持仓成本感知（优先级最高）=========
        # 传入 holding_cost 时，检查当前价格是否触及止损/预警线
        # 止损信号直接返回，不经过投票，确保硬止损不被多数 HOLD 票压制
        cost_info: dict = {}
        if self.holding_cost and self.holding_cost > 0 and len(df) > 0:
            current_price = float(df['close'].iloc[-1])
            pnl_pct = (current_price / self.holding_cost - 1)
            cost_info = {
                '持仓成本': self.holding_cost,
                '当前价格': current_price,
                '持仓盈亏%': round(pnl_pct * 100, 2),
                '止损线': round(self.holding_cost * (1 + self.stop_loss_pct), 3),
                '预警线': round(self.holding_cost * (1 + self.warn_loss_pct), 3),
            }
            if pnl_pct <= self.stop_loss_pct:
                # 触及硬止损，无条件卖出
                return StrategySignal(
                    action='SELL',
                    confidence=0.95,
                    position=0.0,
                    reason=f'硬止损触发: 亏损{pnl_pct:.1%}，已达止损线{self.stop_loss_pct:.0%}',
                    indicators={**cost_info, '触发类型': '硬止损'},
                )
            if pnl_pct <= self.warn_loss_pct:
                # 预警区间：叠加到投票结果中，但不强制卖出
                cost_info['触发类型'] = f'预警(亏损{pnl_pct:.1%})'

        votes: Dict[str, StrategySignal] = {}
        buy_votes: List[tuple] = []
        sell_votes: List[tuple] = []
        hold_votes: List[tuple] = []

        for strat_name, strat in self.sub_strategies.items():
            if len(df) < strat.min_bars:
                continue
            try:
                sig = strat.analyze(df)
                # 基本面策略数据缺失时（confidence=0 且 reason 含"缺少"/"不足"）
                # 剔除出投票，避免拉低分母导致技术策略信号被稀释
                if (sig.action == 'HOLD' and sig.confidence == 0.0
                        and sig.reason and any(kw in sig.reason for kw in ('缺少', '不足', '无法'))):
                    continue
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
            return StrategySignal('HOLD', 0.0, '无策略可用', 0.5, {**cost_info})

        # ========= 重大利空优先（优先级仅次于硬止损）=========
        for strat_name, sig in sell_votes:
            if sig.reason and MAJOR_NEGATIVE_REASON_KEY in sig.reason:
                return StrategySignal(
                    action='SELL',
                    confidence=sig.confidence,
                    position=0.0,
                    reason=f'重大利空优先({strat_name}): {sig.reason}',
                    indicators={
                        '投票详情': {n: f"{s.action}({s.confidence:.0%})" for n, s in votes.items()},
                        **cost_info,
                    },
                )

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

        # ========= 持仓预警叠加 =========
        # 预警区间内（未到硬止损）：若技术面没有明确 BUY，降级为 SELL 建议减仓
        if cost_info.get('触发类型', '').startswith('预警') and action != 'BUY':
            action = 'SELL'
            conf = max(conf, 0.65)
            reason = f"{cost_info['触发类型']}+技术面无买入支撑，建议减仓"

        # ========= 仓位管理 =========
        # BUY: 取子策略加权平均仓位，下限0.4防过低，上限0.95防满仓
        # SELL: 清仓
        # HOLD: 维持加权平均仓位
        if action == 'BUY':
            suggested_position = round(min(0.95, max(0.4, avg_position)), 2)
        elif action == 'SELL':
            suggested_position = 0.0
        else:
            suggested_position = round(avg_position, 2)

        return StrategySignal(
            action=action,
            confidence=round(conf, 2),
            reason=reason,
            position=suggested_position,
            indicators={
                '投票详情': vote_detail,
                '买入票': len(buy_votes),
                '卖出票': len(sell_votes),
                '观望票': len(hold_votes),
                '有效策略': total,
                '模式': self.mode,
                '加权仓位': round(avg_position, 2),
                **cost_info,
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

        触发条件（同时满足）:
          1. buy_score / total_active >= buy_threshold
          2. 至少 2 个策略投 BUY（避免单策略孤票触发）
        """
        MIN_ACTIVE_VOTES = 2  # 至少需要 N 个策略同向才行动

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

        if (buy_pct > sell_pct and buy_pct >= self.buy_threshold
                and len(buy_votes) >= MIN_ACTIVE_VOTES):
            names = [n for n, _ in buy_votes]
            return (
                'BUY', round(buy_pct, 2),
                f"加权看多({buy_pct:.0%}, {len(buy_votes)}票): {', '.join(names)}"
            )

        if (sell_pct > buy_pct and sell_pct >= self.sell_threshold
                and len(sell_votes) >= MIN_ACTIVE_VOTES):
            names = [n for n, _ in sell_votes]
            return (
                'SELL', round(sell_pct, 2),
                f"加权看空({sell_pct:.0%}, {len(sell_votes)}票): {', '.join(names)}"
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
    当前默认是 11 个子策略（技术6 + 基本面3 + NEWS + MONEY_FLOW），阈值仍然有效：
    - 买入: 需要 ≥6/11 策略看多（50%阈值）
    - 卖出: 需要 ≥4/11 策略看空（34%阈值）
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
    当前默认是 11 个子策略，买入/卖出均需 ≥6/11 策略同意。
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
    当前默认是 11 个子策略，加权投票模式下阈值仍然有效。
    """
    name = '激进组合'
    description = '加权投票，HOLD不计分，反应灵敏'

    def __init__(self, **kwargs):
        super().__init__(mode='weighted', buy_threshold=0.35,
                         sell_threshold=0.35, **kwargs)


# V33EnsembleStrategy 已合并入 EnsembleStrategy（动态权重、重大利空优先均已迁移）
# 保留别名供旧代码兼容
V33EnsembleStrategy = EnsembleStrategy
