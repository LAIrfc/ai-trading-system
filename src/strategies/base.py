"""
策略统一基类

所有策略必须：
1. 接收一只股票的 DataFrame(date,open,high,low,close,volume,amount)
2. 返回 StrategySignal

StrategySignal 字段说明:

  action (str): BUY / SELL / HOLD — 交易方向

  confidence (float): 0.0 ~ 1.0 — 对方向判断的**确定性**
      0.0 ~ 0.4: 弱信号，方向不明确
      0.4 ~ 0.6: 中性/观望
      0.6 ~ 0.8: 较强信号
      0.8 ~ 1.0: 强信号

  position (float): 0.0 ~ 1.0 — 建议目标仓位（0=空仓，1=满仓）

  reason (str): 人类可读的决策理由

  indicators (dict): 指标快照

confidence 与 position 的关系:
  这两个字段**语义独立**，允许不同方向的组合：
  - confidence 描述"预测确定性" → 对未来方向判断有多确信
  - position   描述"行动建议"   → 建议持有多少仓位

  合理的组合示例：
  - conf=0.78, pos=0.85 → 方向明确+高仓位（典型的金叉/突破信号）
  - conf=0.4,  pos=0.7  → 方向不明确+高仓位（如上轨突破未拐头：
                           统计极端区域无法确信方向，但趋势跟踪哲学下
                           不应恐慌卖出，让利润奔跑）
  - conf=0.35, pos=0.15 → 方向不明确+低仓位（如下轨下方未拐头：
                           方向不明且风险较高，防御性降仓）

各模块如何使用这两个字段:
  - 回测引擎 (backtest):
      BUY  → 加仓到 min(0.95, position) 目标仓位，按A股100股取整
      SELL → 减仓到 position 目标仓位（position<0.05 或余股不足1手→全部清仓）
      HOLD → 不操作（position 不影响回测，仅记录建议）
      费用: 买入佣金(万2) + 卖出佣金(万2) + 印花税(千1，仅卖出)
  - 组合策略 (ensemble):
      confidence → 加权投票时作为信号强度的权重
      position   → 所有子策略的加权平均 → 组合的最终仓位建议
  - 推荐工具 (recommend_today):
      同时展示 confidence 和 position，供人工参考
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import logging
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class StrategySignal:
    """
    标准化交易信号

    Attributes:
        action:     BUY / SELL / HOLD — 交易方向
        confidence: 0.0~1.0 — 对方向判断的确定性（非概率，非仓位指导）
        reason:     人类可读的决策理由
        position:   0.0~1.0 — 建议目标仓位（与 confidence 独立，见模块文档）
        indicators: 指标快照，如 {'RSI': 28.5, 'MA5': 10.32}
    """
    action: str                # BUY / SELL / HOLD
    confidence: float          # 对方向判断的确定性 0.0~1.0
    reason: str                # 人类可读的决策理由
    position: float = 0.5      # 建议目标仓位 0.0~1.0 (与confidence独立)
    indicators: dict = field(default_factory=dict)

    def __post_init__(self):
        """确保 confidence 和 position 始终在有效范围内"""
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.position = max(0.0, min(1.0, self.position))


class Strategy(ABC):
    """
    策略基类 — 每个策略只需实现 analyze() 方法

    类属性:
        name:        策略名称
        description: 策略描述
        min_bars:    策略所需的最小K线条数

    可选类属性:
        param_ranges: dict  参数合理取值范围，用于参数扫描优化
            格式: { '参数名': (最小值, 默认值, 最大值, 步长), ... }
    """

    name: str = ''
    description: str = ''
    min_bars: int = 30

    # 子类可覆写：参数范围定义，用于后续参数优化扫描
    # 格式: { 'param_name': (min, default, max, step) }
    param_ranges: Dict[str, Tuple[float, float, float, float]] = {}

    def __init_subclass__(cls, **kwargs):
        """子类注册时检查 min_bars 是否被合理设置"""
        super().__init_subclass__(**kwargs)
        # 如果子类没有覆写 min_bars 且不是抽象类，给出警告
        if not getattr(cls, '__abstractmethods__', None):
            if 'min_bars' not in cls.__dict__ and '__init__' not in cls.__dict__:
                logger.warning(
                    f"策略 {cls.__name__} 未在 __init__ 中设置 min_bars，"
                    f"将使用默认值 {cls.min_bars}。建议显式设置以避免数据不足。"
                )

    @abstractmethod
    def analyze(self, df: pd.DataFrame) -> StrategySignal:
        """
        分析一只股票的历史数据，生成交易信号

        Args:
            df: DataFrame, 至少包含 columns=[date, open, high, low, close, volume]
                按日期升序排列，最后一行是最新数据

        Returns:
            StrategySignal — action/confidence/reason/position/indicators
        """
        ...

    @classmethod
    def calc_min_bars(cls, **params) -> int:
        """
        根据参数计算所需最小K线数

        子类可覆写此方法来动态计算 min_bars。
        默认实现：返回实例的 min_bars 属性。
        """
        return cls.min_bars

    def safe_analyze(self, df: pd.DataFrame) -> StrategySignal:
        """
        带异常保护的 analyze 封装

        数据不足或计算出错时返回 HOLD 信号而非抛出异常。
        异常会记录完整堆栈信息，便于调试。
        """
        if len(df) < self.min_bars:
            return StrategySignal(
                action='HOLD', confidence=0.0, position=0.5,
                reason=f'数据不足(需{self.min_bars}条，实际{len(df)}条)',
            )
        try:
            sig = self.analyze(df)
            return sig
        except Exception as e:
            # exc_info=True 记录完整堆栈，便于定位问题
            logger.warning(f"[{self.name}] analyze异常: {e}", exc_info=True)
            return StrategySignal(
                action='HOLD', confidence=0.0, position=0.5,
                reason=f'分析异常: {e}',
            )

    def backtest(self, df: pd.DataFrame,
                 initial_cash: float = 100000.0,
                 commission: float = 0.0002,
                 stamp_tax: float = 0.001,
                 stop_loss: float = 0.0,
                 trailing_stop: float = 0.0,
                 take_profit: float = 0.0) -> dict:
        """
        回测引擎：在整段历史数据上逐日运行策略

        支持动态仓位调整：
        - BUY:  建仓或加仓到 min(0.95, signal.position) 目标仓位
        - SELL: 减仓或清仓到 signal.position 目标仓位（position<0.05 为清仓）
        - HOLD: 不操作（忽略 position）

        仓位计算：
            当前仓位比例 = 持仓市值 / 总权益
            目标仓位比例 = signal.position
            差值 > 0 → 需要买入（加仓）
            差值 < 0 → 需要卖出（减仓）

        费用：
            买入: price × (1 + commission)
            卖出: price × (1 - commission - stamp_tax)
            A股印花税仅在卖出时收取（默认千分之一）

        风控优先级：止损/止盈 > 策略信号
            风控平仓后 continue 跳过当天策略信号，不会同天反手

        Args:
            initial_cash:   初始资金
            commission:     佣金费率（万分之2 = 0.0002，买卖均收）
            stamp_tax:      印花税率（千分之1 = 0.001，仅卖出时收取）
            stop_loss:      硬止损比例（0=不启用，如0.08表示亏8%止损）
            trailing_stop:  跟踪止损比例（0=不启用，如0.05表示从最高回撤5%止损）
            take_profit:    止盈比例（0=不启用，如0.20表示盈利20%止盈）

        Returns:
            {
                'trades': List[dict],
                'final_value': float,
                'total_return': float,          # 百分比
                'annualized_return': float,     # 百分比
                'max_drawdown': float,          # 百分比
                'win_rate': float,              # 百分比
                'trade_count': int,
                'sharpe': float,
            }
        """
        if len(df) < self.min_bars:
            return {
                'trades': [], 'final_value': initial_cash,
                'total_return': 0.0, 'annualized_return': 0.0,
                'max_drawdown': 0.0, 'win_rate': 0.0,
                'trade_count': 0, 'sharpe': 0.0,
            }

        cash = initial_cash
        shares = 0
        avg_buy_price = 0.0             # 加权平均买入价（支持多次加仓）
        total_buy_cost = 0.0            # 累计买入成本（用于计算平均价）
        max_price_since_buy = 0.0       # 跟踪止损用
        trades: List[dict] = []
        equity_curve: List[float] = []

        for i in range(self.min_bars, len(df)):
            # 不复制 DataFrame，策略只读不写，iloc 切片是视图
            window = df.iloc[:i + 1]
            close = float(window['close'].iloc[-1])
            date_str = str(window['date'].iloc[-1])[:10]

            # ---- 当前权益 ----
            equity = cash + shares * close

            # ---- 风控检查（持仓时优先于策略信号）----
            risk_exit = False
            risk_reason = ''

            if shares > 0:
                pnl_pct = (close - avg_buy_price) / avg_buy_price

                # 跟踪止损：更新最高价
                if close > max_price_since_buy:
                    max_price_since_buy = close

                # 硬止损
                if stop_loss > 0 and pnl_pct <= -stop_loss:
                    risk_exit = True
                    risk_reason = f'硬止损触发(亏损{pnl_pct:.1%}≤-{stop_loss:.0%})'

                # 跟踪止损
                if (trailing_stop > 0 and max_price_since_buy > avg_buy_price):
                    drawdown_from_peak = (max_price_since_buy - close) / max_price_since_buy
                    if drawdown_from_peak >= trailing_stop:
                        risk_exit = True
                        risk_reason = (f'跟踪止损触发(从最高{max_price_since_buy:.2f}'
                                       f'回撤{drawdown_from_peak:.1%}≥{trailing_stop:.0%})')

                # 止盈
                if take_profit > 0 and pnl_pct >= take_profit:
                    risk_exit = True
                    risk_reason = f'止盈触发(盈利{pnl_pct:.1%}≥{take_profit:.0%})'

            # ---- 风控强制平仓（全部清仓）----
            if risk_exit and shares > 0:
                revenue = shares * close * (1 - commission - stamp_tax)
                pnl = (close - avg_buy_price) / avg_buy_price
                cash += revenue
                trades.append({
                    'date': date_str, 'action': 'SELL',
                    'price': close, 'shares': shares,
                    'pnl_pct': round(pnl * 100, 2),
                    'reason': f'[风控] {risk_reason}',
                })
                shares = 0
                avg_buy_price = 0.0
                total_buy_cost = 0.0
                max_price_since_buy = 0.0
                equity = cash
                equity_curve.append(equity)
                continue  # 风控平仓后跳过当天策略信号，不同天反手

            # ---- 策略信号 ----
            try:
                signal = self.analyze(window)
            except Exception:
                signal = StrategySignal('HOLD', 0.0, '分析异常', 0.5)

            if signal.action == 'BUY':
                target_pos = min(0.95, signal.position)
                # 需要加仓的金额 = 目标持仓市值 - 当前持仓市值
                target_value = equity * target_pos
                current_value = shares * close
                delta_value = target_value - current_value

                if delta_value >= close * 100:  # 至少买1手(100股)才值得交易
                    add_shares = int(delta_value / close / 100) * 100
                    if add_shares > 0:
                        cost = add_shares * close * (1 + commission)
                        if cost <= cash:  # 现金充足
                            cash -= cost
                            # 更新加权平均买入价
                            total_buy_cost += add_shares * close
                            shares += add_shares
                            avg_buy_price = total_buy_cost / shares
                            if close > max_price_since_buy:
                                max_price_since_buy = close
                            trades.append({
                                'date': date_str, 'action': 'BUY',
                                'price': close, 'shares': add_shares,
                                'total_shares': shares,
                                'reason': signal.reason,
                            })

            elif signal.action == 'SELL' and shares > 0:
                target_pos = max(0.0, signal.position)
                target_value = equity * target_pos
                current_value = shares * close
                delta_value = current_value - target_value

                # 需要卖出的股数（A股最小交易单位100股，尾股允许一次卖出）
                sell_shares = int(delta_value / close / 100) * 100
                # 如果目标仓位接近 0 或剩余不足1手，则全部清仓
                if target_pos < 0.05 or (shares - sell_shares) < 100:
                    sell_shares = shares

                if sell_shares > 0 and sell_shares <= shares:
                    revenue = sell_shares * close * (1 - commission - stamp_tax)
                    pnl = (close - avg_buy_price) / avg_buy_price
                    cash += revenue
                    shares -= sell_shares
                    trades.append({
                        'date': date_str, 'action': 'SELL',
                        'price': close, 'shares': sell_shares,
                        'remaining_shares': shares,
                        'pnl_pct': round(pnl * 100, 2),
                        'reason': signal.reason,
                    })
                    if shares == 0:
                        avg_buy_price = 0.0
                        total_buy_cost = 0.0
                        max_price_since_buy = 0.0
                    else:
                        total_buy_cost = shares * avg_buy_price

            # ---- 记录当日收盘后权益（所有交易处理完毕）----
            equity = cash + shares * close
            equity_curve.append(equity)

        # 最终市值
        final_close = float(df['close'].iloc[-1])
        final_value = cash + shares * final_close

        # 计算指标
        total_return = (final_value / initial_cash - 1) * 100

        # 年化收益率
        days = len(df)
        try:
            days = (pd.Timestamp(df['date'].iloc[-1])
                    - pd.Timestamp(df['date'].iloc[self.min_bars])).days
        except Exception:
            pass
        years = max(days / 365.0, 0.01)
        annualized = ((final_value / initial_cash) ** (1 / years) - 1) * 100

        # 最大回撤
        max_drawdown = 0.0
        if equity_curve:
            peak = equity_curve[0]
            for eq in equity_curve:
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak
                if dd > max_drawdown:
                    max_drawdown = dd
        max_drawdown *= 100

        # 胜率（基于卖出交易的盈亏）
        sell_trades = [t for t in trades if t['action'] == 'SELL']
        wins = sum(1 for t in sell_trades if t.get('pnl_pct', 0) > 0)
        win_rate = (wins / len(sell_trades) * 100) if sell_trades else 0.0

        # 夏普比率
        sharpe = 0.0
        if len(equity_curve) > 1:
            import numpy as np
            returns = pd.Series(equity_curve).pct_change().dropna()
            if returns.std() > 0:
                sharpe = float((returns.mean() / returns.std()) * (252 ** 0.5))

        return {
            'trades': trades,
            'final_value': round(final_value, 2),
            'total_return': round(total_return, 2),
            'annualized_return': round(annualized, 2),
            'max_drawdown': round(max_drawdown, 2),
            'win_rate': round(win_rate, 2),
            'trade_count': len(sell_trades),
            'sharpe': round(sharpe, 2),
        }
