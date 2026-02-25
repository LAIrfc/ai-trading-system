"""
策略统一基类

所有策略必须：
1. 接收一只股票的 DataFrame(date,open,high,low,close,volume,amount)
2. 返回 StrategySignal

StrategySignal 包含:
- action:     BUY / SELL / HOLD
- confidence: 0.0 ~ 1.0，越高越确定
- reason:     人类可读的决策理由
- position:   建议目标仓位 0.0~1.0（0=空仓，1=满仓）
- indicators: 指标快照

信号字段含义:
  confidence 0.0 ~ 0.4: 弱信号，仅供参考
  confidence 0.4 ~ 0.6: 中性/观望
  confidence 0.6 ~ 0.8: 较强信号
  confidence 0.8 ~ 1.0: 强信号
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import logging
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class StrategySignal:
    """标准化交易信号"""
    action: str                # BUY / SELL / HOLD
    confidence: float          # 0.0 ~ 1.0
    reason: str                # 人类可读的决策理由
    position: float = 0.5      # 建议目标仓位 0.0~1.0 (0=清仓 0.5=半仓 1.0=满仓)
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
            logger.warning(f"[{self.name}] analyze异常: {e}")
            return StrategySignal(
                action='HOLD', confidence=0.0, position=0.5,
                reason=f'分析异常: {e}',
            )

    def backtest(self, df: pd.DataFrame,
                 initial_cash: float = 100000.0,
                 commission: float = 0.0002,
                 stop_loss: float = 0.0,
                 trailing_stop: float = 0.0,
                 take_profit: float = 0.0) -> dict:
        """
        简易回测：在整段历史数据上逐日运行策略

        Args:
            initial_cash:   初始资金
            commission:     手续费率（万分之2 = 0.0002）
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
        buy_price = 0.0
        max_price_since_buy = 0.0      # 跟踪止损用
        trades: List[dict] = []
        equity_curve: List[float] = []

        for i in range(self.min_bars, len(df)):
            window = df.iloc[:i + 1].copy()
            close = float(window['close'].iloc[-1])
            date_str = str(window['date'].iloc[-1])[:10]

            # ---- 风控检查（持仓时优先于策略信号）----
            risk_exit = False
            risk_reason = ''

            if shares > 0:
                pnl_pct = (close - buy_price) / buy_price

                # 跟踪止损：更新最高价
                if close > max_price_since_buy:
                    max_price_since_buy = close

                # 硬止损
                if stop_loss > 0 and pnl_pct <= -stop_loss:
                    risk_exit = True
                    risk_reason = f'硬止损触发(亏损{pnl_pct:.1%}≤-{stop_loss:.0%})'

                # 跟踪止损
                if (trailing_stop > 0 and max_price_since_buy > buy_price):
                    drawdown_from_peak = (max_price_since_buy - close) / max_price_since_buy
                    if drawdown_from_peak >= trailing_stop:
                        risk_exit = True
                        risk_reason = (f'跟踪止损触发(从最高{max_price_since_buy:.2f}'
                                       f'回撤{drawdown_from_peak:.1%}≥{trailing_stop:.0%})')

                # 止盈
                if take_profit > 0 and pnl_pct >= take_profit:
                    risk_exit = True
                    risk_reason = f'止盈触发(盈利{pnl_pct:.1%}≥{take_profit:.0%})'

            # ---- 风控强制平仓 ----
            if risk_exit and shares > 0:
                revenue = shares * close * (1 - commission)
                pnl = (close - buy_price) / buy_price
                cash += revenue
                trades.append({
                    'date': date_str, 'action': 'SELL',
                    'price': close, 'shares': shares,
                    'pnl_pct': round(pnl * 100, 2),
                    'reason': f'[风控] {risk_reason}',
                })
                shares = 0
                buy_price = 0.0
                max_price_since_buy = 0.0
                equity = cash
                equity_curve.append(equity)
                continue

            # ---- 策略信号 ----
            try:
                signal = self.analyze(window)
            except Exception:
                signal = StrategySignal('HOLD', 0.0, '分析异常', 0.5)

            equity = cash + shares * close
            equity_curve.append(equity)

            if signal.action == 'BUY' and shares == 0:
                # 使用 signal.position 决定投入比例（默认0.95*position）
                invest_ratio = min(0.95, signal.position)
                buy_amount = cash * invest_ratio
                shares = int(buy_amount / close / 100) * 100
                if shares > 0:
                    cost = shares * close * (1 + commission)
                    cash -= cost
                    buy_price = close
                    max_price_since_buy = close
                    trades.append({
                        'date': date_str, 'action': 'BUY',
                        'price': close, 'shares': shares,
                        'reason': signal.reason,
                    })

            elif signal.action == 'SELL' and shares > 0:
                revenue = shares * close * (1 - commission)
                pnl = (close - buy_price) / buy_price
                cash += revenue
                trades.append({
                    'date': date_str, 'action': 'SELL',
                    'price': close, 'shares': shares,
                    'pnl_pct': round(pnl * 100, 2),
                    'reason': signal.reason,
                })
                shares = 0
                buy_price = 0.0
                max_price_since_buy = 0.0

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

        # 胜率
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
