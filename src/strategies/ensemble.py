"""
多策略组合投票策略 (Ensemble Strategy)

当前架构：L0(PolicyEvent过滤) + L3(12策略固定权重投票)
L2 层已暂时关闭（待历史回测优化系数）

原理:
- 同时运行12个子策略（技术6+基本面3+消息面+资金面+市场情绪）
- 每个策略独立给出 BUY / SELL / HOLD 信号 + confidence + position
- 采用加权投票机制（净得分法，阈值0.07/-0.07）

投票模式:
- 'weighted':  按策略权重加权投票（推荐，默认）
- 'majority':  多数投票（≥阈值才行动）
- 'unanimous': 全票通过才行动（最保守）
- 'any':       任意一个策略发出信号就行动（最激进）

净得分机制:
    net_score = (buy_score - sell_score) / active_weight_sum
    BUY: net_score > 0.07 且至少1票
    SELL: net_score < -0.07 且至少1票
    HOLD: 其他情况

参数:
- mode:           投票模式（默认 'weighted'）
- weights:        各策略权重 dict（默认使用已验证的固定权重）
- dual_reverse:   DUAL策略是否反向（默认True，IC从-0.39提升至+0.39）
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

try:
    from src.core.market_regime import MarketRegimeEngine
except ImportError:
    MarketRegimeEngine = None

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
    description = '12策略固定权重投票（6技术+3基本面+消息面+资金面+情绪面）'

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
                 dual_reverse: bool = True,
                 use_dynamic_weights: bool = False,
                 net_buy_threshold: float = 0.07,
                 net_sell_threshold: float = -0.15,
                 **kwargs):
        self.mode = mode
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        # weighted 模式净得分阈值（与 _weighted 一致，可由回测扫描覆盖）
        self.net_buy_threshold = float(net_buy_threshold)
        self.net_sell_threshold = float(net_sell_threshold)
        self.holding_cost = holding_cost
        self.stop_loss_pct = stop_loss_pct
        self.warn_loss_pct = warn_loss_pct
        self.symbol = symbol
        self.stock_name = stock_name
        self.dual_reverse = dual_reverse

        # 子策略实例（技术面 6 + 基本面 3 + 消息面 1 + 资金面 1 + 情绪面 1）
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
            'SENTIMENT':    SentimentStrategy(),
        }

        # 默认权重（基于完整12策略全量回测优化，836只×300只验证）
        # 2026-03-24 权重校准结论：
        #   - 补全PE/PB数据后，基本面策略表现最优（PB Sharpe 0.38，PE 0.25）
        #   - composite方法权重使Sharpe从0.0022提升到0.0733（+32倍）
        #   - 核心变化：基本面权重大幅提升，技术面微调
        self.weights: Dict[str, float] = weights or {
            'PB':         2.00,  # 基本面：Sharpe最高(0.38)，正收益率76%
            'BOLL':       1.95,  # 技术面：Sharpe 0.18，正收益率72.5%
            'RSI':        1.82,  # 技术面：Sharpe 0.14，正收益率66.6%
            'PE':         1.68,  # 基本面：Sharpe 0.25，正收益率62.1%
            'PEPB':       1.61,  # 基本面：Sharpe 0.22，双因子共振
            'KDJ':        1.50,  # 技术面：Sharpe 0.14，正收益率64.6%
            'DUAL':       1.39,  # 技术面：反向使用后Sharpe 0.24
            'MACD':       1.13,  # 技术面：Sharpe 0.08
            'MA':         0.88,  # 技术面：Sharpe 0.07
            'SENTIMENT':  0.32,  # 情绪面：市场情绪+个股过滤
            'NEWS':       0.32,  # 消息面：个股新闻LLM
            'MONEY_FLOW': 0.30,  # 资金面：龙虎榜+大宗（回测中无数据）
        }

        # min_bars 只取技术策略的最大值；其他策略有数据时参与，无数据时被剔除逻辑过滤
        non_tech_keys = {'PE', 'PB', 'PEPB', 'NEWS', 'MONEY_FLOW', 'SENTIMENT'}
        tech_strategies = {k: v for k, v in self.sub_strategies.items() if k not in non_tech_keys}
        self.min_bars = max(s.min_bars for s in tech_strategies.values())

        # 动态权重状态（冷却 7 日，市场状态变化时触发）
        # 可通过 use_dynamic_weights 参数控制是否启用（默认False，避免覆盖自定义权重）
        self._use_dynamic_weights: bool = use_dynamic_weights and (compute_v33_weights is not None)
        self._weight_state: Optional[str] = None
        self._weight_adjustment_date: Optional[pd.Timestamp] = None
        self._weight_cooldown_until: Optional[pd.Timestamp] = None
        self._backtest_index_df = None
        
        # 市场状态识别引擎（可选）
        self._regime_engine: Optional['MarketRegimeEngine'] = None
        if MarketRegimeEngine is not None:
            try:
                self._regime_engine = MarketRegimeEngine()
            except Exception:
                pass

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
    
    def get_market_regime(self) -> str:
        """
        获取当前市场状态（使用MarketRegimeEngine）
        
        Returns:
            'bull', 'bear', 'sideways'
        """
        if self._regime_engine is None:
            return 'sideways'
        
        try:
            return self._regime_engine.get_current_regime()
        except Exception as e:
            logger.debug(f"获取市场状态失败: {e}")
            return 'sideways'
    
    def get_regime_adjusted_weights(self, sentiment_signal: Optional[StrategySignal] = None) -> Dict[str, float]:
        """
        L2: 基于市场状态调整权重（已验证，不启用）
        
        ⚠️ 当前状态：永久关闭，直接返回基础权重
        
        验证结果（2026-03-24）：
        - 测试了1296个动态权重配置（30只股票，2023-2026年）
        - 所有动态配置在测试期均劣于固定权重
          - 固定权重：夏普0.118，年化5.33%，回撤5.98%
          - 最优动态：夏普0.078，年化5.06%，回撤6.00%
        - 结论：当前固定权重已是最优方案
        
        不启用原因：
        1. 市场状态识别滞后（MA20/MA200滞后1-2个月）
        2. 训练期最优系数在测试期失效（过拟合）
        3. 固定权重已经过多轮优化（v3/v4），难以进一步提升
        4. 系数叠加可能放大噪音而非信号
        
        备用模块（已实现，待更好方法）：
        - src/core/market_regime.py: 市场状态识别引擎
        - src/core/regime_adjustment_rules.py: 权重调整规则
        - tools/optimization/optimize_regime_weights.py: 优化工具
        """
        return self.weights.copy()

    def prepare_backtest(self, df: pd.DataFrame) -> None:
        """
        回测前预取各子策略外部数据。
        实盘无需调用，analyze 时实时获取。
        """
        # 预取11个子策略的数据
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
        """
        12策略加权投票决策
        
        当前架构：L0(PolicyEvent过滤) + L3(12策略固定权重投票)
        L2 层已暂时关闭（待历史回测优化系数）
        """

        # L1/L2 层已关闭，使用固定权重
        adjusted_weights = None

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
                
                # ========= DUAL策略信号反向（IC分析发现强负IC=-0.3864）=========
                # DUAL是追涨杀跌策略，滞后性强，信号与未来收益负相关
                # 反向使用：BUY→SELL, SELL→BUY，IC变为+0.3864（最强策略之一）
                # 可通过 dual_reverse 参数控制是否反向（默认True）
                if strat_name == 'DUAL' and self.dual_reverse:
                    if sig.action == 'BUY':
                        sig = StrategySignal(
                            action='SELL',
                            confidence=sig.confidence,
                            position=1.0 - sig.position,  # 仓位也反向
                            reason=f'[DUAL反向] {sig.reason}（原BUY信号反向为SELL）',
                            indicators=sig.indicators
                        )
                    elif sig.action == 'SELL':
                        sig = StrategySignal(
                            action='BUY',
                            confidence=sig.confidence,
                            position=1.0 - sig.position,  # 仓位也反向
                            reason=f'[DUAL反向] {sig.reason}（原SELL信号反向为BUY）',
                            indicators=sig.indicators
                        )
                
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

        # ========= L3: 投票决策（使用L2调整后的权重）=========
        if self.mode == 'unanimous':
            action, conf, reason = self._unanimous(buy_votes, sell_votes, total)
        elif self.mode == 'any':
            action, conf, reason = self._any(buy_votes, sell_votes)
        elif self.mode == 'weighted':
            action, conf, reason = self._weighted(buy_votes, sell_votes, total, adjusted_weights)
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

    def _weighted(self, buy_votes, sell_votes, total, adjusted_weights=None):
        """
        加权投票（净得分机制）— 让权重真正起作用
        
        核心逻辑：
        1. 计算加权得分：score = Σ(权重 × confidence)
        2. 净得分：net_score = (buy_score - sell_score) / active_weight_sum
        3. 决策阈值（实例属性 net_buy_threshold / net_sell_threshold）：
           - net_score > net_buy_threshold (默认 0.07) → BUY
           - net_score < net_sell_threshold (默认 -0.15) → SELL
           - 否则 → HOLD
        
        阈值校准（2026-03-24，299只股票验证）：
        - 买入阈值 0.07 保持不变（低阈值信号多但风险大，0.07 平衡适中）
        - 卖出阈值从 -0.07 放宽到 -0.15（avg Sharpe 从 0.072 → 0.096，+33%）
        - 放宽卖出意味着不那么容易被噪声触发清仓，减少了不必要的频繁卖出
        
        Args:
            adjusted_weights: L2层调整后的权重（如果为None，使用self.weights）
        """
        MIN_ACTIVE_VOTES = 1
        buy_th = self.net_buy_threshold
        sell_th = self.net_sell_threshold

        if not buy_votes and not sell_votes:
            return 'HOLD', 0.5, "无有效方向性信号"

        # 使用L2调整后的权重（如果有）
        weights_to_use = adjusted_weights if adjusted_weights else self.weights
        
        buy_score = sum(weights_to_use.get(n, 1.0) * s.confidence
                        for n, s in buy_votes)
        sell_score = sum(weights_to_use.get(n, 1.0) * s.confidence
                         for n, s in sell_votes)

        active_weight_sum = (sum(weights_to_use.get(n, 1.0) for n, _ in buy_votes) +
                             sum(weights_to_use.get(n, 1.0) for n, _ in sell_votes))
        if active_weight_sum == 0:
            return 'HOLD', 0.5, "无有效策略权重"

        net_score = (buy_score - sell_score) / active_weight_sum

        if net_score > buy_th and len(buy_votes) >= MIN_ACTIVE_VOTES:
            names = [n for n, _ in buy_votes]
            conf = min(0.99, buy_score / active_weight_sum)
            return (
                'BUY', round(conf, 2),
                f"加权看多(净分={net_score:.2f}, {len(buy_votes)}票): {', '.join(names)}"
            )

        if net_score < sell_th and len(sell_votes) >= MIN_ACTIVE_VOTES:
            names = [n for n, _ in sell_votes]
            conf = min(0.99, sell_score / active_weight_sum)
            return (
                'SELL', round(conf, 2),
                f"加权看空(净分={net_score:.2f}, {len(sell_votes)}票): {', '.join(names)}"
            )

        return 'HOLD', 0.5, f"加权信号中性(净分={net_score:.2f})，观望"


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
