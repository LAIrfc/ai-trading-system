"""
虚拟持仓管理器
追踪策略信号产生的虚拟交易，记录每笔操作和完整盈亏
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from loguru import logger

from src.core.signal_engine import Signal, StrategyState


# 持仓文件路径
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
STATE_FILE = os.path.join(DATA_DIR, 'portfolio_state.json')
TRADE_LOG_FILE = os.path.join(DATA_DIR, 'trade_log.jsonl')
DAILY_LOG_DIR = os.path.join(DATA_DIR, 'daily_reports')


@dataclass
class TradeRecord:
    """交易记录"""
    timestamp: str
    date: str
    action: str       # BUY / SELL / SWITCH
    code: str
    name: str
    price: float
    shares: int
    amount: float      # 成交金额
    commission: float  # 手续费
    reason: str
    pnl: float = 0.0  # 本次盈亏（卖出时）
    pnl_pct: float = 0.0


class Portfolio:
    """虚拟持仓管理器"""

    def __init__(self, initial_cash: float = 1_000_000):
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(DAILY_LOG_DIR, exist_ok=True)

        self.commission_rate = 0.0002  # 万分之二

        # 加载已有状态
        self.state = self._load_state(initial_cash)

    def _load_state(self, initial_cash: float) -> StrategyState:
        """从文件加载持仓状态"""
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                state = StrategyState()
                state.holding_code = data.get('holding_code', '')
                state.holding_name = data.get('holding_name', '')
                state.holding_price = data.get('holding_price', 0.0)
                state.holding_date = data.get('holding_date', '')
                state.last_rebalance = data.get('last_rebalance', '')
                state.cash = data.get('cash', initial_cash)
                state.total_value = data.get('total_value', initial_cash)
                state.shares = data.get('shares', 0)
                logger.info(f"加载持仓状态: 现金={state.cash:.2f}, 持仓={state.holding_name or '空仓'}")
                return state
            except Exception as e:
                logger.warning(f"加载状态失败: {e}, 使用初始状态")

        return StrategyState(cash=initial_cash, total_value=initial_cash)

    def _save_state(self):
        """保存持仓状态到文件"""
        data = {
            'holding_code': self.state.holding_code,
            'holding_name': self.state.holding_name,
            'holding_price': self.state.holding_price,
            'holding_date': self.state.holding_date,
            'last_rebalance': self.state.last_rebalance,
            'cash': self.state.cash,
            'total_value': self.state.total_value,
            'shares': self.state.shares,
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _log_trade(self, record: TradeRecord):
        """追加交易记录"""
        with open(TRADE_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + '\n')

    def execute_signal(self, signal: Signal, current_prices: Dict[str, float] = None):
        """
        执行交易信号（虚拟）

        更新持仓状态，记录交易日志
        """
        if signal.action == 'HOLD' or signal.action == 'EMPTY' or signal.action == 'ERROR':
            # 仅更新市值
            if self.state.holding_code and current_prices:
                price = current_prices.get(self.state.holding_code, self.state.holding_price)
                self.state.total_value = self.state.cash + self.state.shares * price
            self._save_state()
            return

        if signal.action == 'BUY':
            self._execute_buy(signal)
        elif signal.action == 'SELL':
            self._execute_sell(signal)
        elif signal.action == 'SWITCH':
            self._execute_switch(signal)

        self._save_state()

    def _execute_buy(self, signal: Signal):
        """执行买入"""
        # 计算可买数量（整百）
        available = self.state.cash * 0.999  # 预留手续费
        shares = int(available / signal.price / 100) * 100
        if shares <= 0:
            logger.warning(f"资金不足，无法买入 {signal.name}")
            return

        amount = shares * signal.price
        commission = max(amount * self.commission_rate, 5)  # 最低5元

        self.state.cash -= (amount + commission)
        self.state.holding_code = signal.code
        self.state.holding_name = signal.name
        self.state.holding_price = signal.price
        self.state.holding_date = signal.date
        self.state.shares = shares
        self.state.last_rebalance = signal.date
        self.state.total_value = self.state.cash + shares * signal.price

        record = TradeRecord(
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            date=signal.date,
            action='BUY',
            code=signal.code,
            name=signal.name,
            price=signal.price,
            shares=shares,
            amount=amount,
            commission=commission,
            reason=signal.reason,
        )
        self._log_trade(record)
        logger.info(
            f"✅ 买入 {signal.name} x{shares}股 @ {signal.price:.4f}  "
            f"成交额: {amount:.2f}  手续费: {commission:.2f}"
        )

    def _execute_sell(self, signal: Signal):
        """执行卖出"""
        if self.state.shares <= 0:
            return

        amount = self.state.shares * signal.price
        commission = max(amount * self.commission_rate, 5)
        pnl = (signal.price - self.state.holding_price) * self.state.shares - commission
        pnl_pct = (signal.price - self.state.holding_price) / self.state.holding_price * 100 if self.state.holding_price > 0 else 0

        self.state.cash += (amount - commission)
        old_name = self.state.holding_name
        old_shares = self.state.shares

        self.state.holding_code = ''
        self.state.holding_name = ''
        self.state.holding_price = 0
        self.state.holding_date = ''
        self.state.shares = 0
        self.state.total_value = self.state.cash
        self.state.last_rebalance = signal.date

        record = TradeRecord(
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            date=signal.date,
            action='SELL',
            code=signal.code,
            name=old_name,
            price=signal.price,
            shares=old_shares,
            amount=amount,
            commission=commission,
            reason=signal.reason,
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 2),
        )
        self._log_trade(record)
        logger.info(
            f"✅ 卖出 {old_name} x{old_shares}股 @ {signal.price:.4f}  "
            f"盈亏: {pnl:+.2f}元 ({pnl_pct:+.2f}%)"
        )

    def _execute_switch(self, signal: Signal):
        """执行换仓"""
        details = signal.details

        # 先卖
        sell_price = details.get('sell_price', 0)
        if self.state.shares > 0 and sell_price > 0:
            sell_amount = self.state.shares * sell_price
            sell_commission = max(sell_amount * self.commission_rate, 5)
            pnl = (sell_price - self.state.holding_price) * self.state.shares - sell_commission
            pnl_pct = details.get('sell_pnl_pct', 0)

            self.state.cash += (sell_amount - sell_commission)

            sell_record = TradeRecord(
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                date=signal.date,
                action='SELL',
                code=details.get('sell_code', ''),
                name=details.get('sell_name', ''),
                price=sell_price,
                shares=self.state.shares,
                amount=sell_amount,
                commission=sell_commission,
                reason=f"换仓卖出: {signal.reason}",
                pnl=round(pnl, 2),
                pnl_pct=round(pnl_pct, 2),
            )
            self._log_trade(sell_record)
            logger.info(
                f"✅ 卖出 {details.get('sell_name', '')} x{self.state.shares}股 "
                f"@ {sell_price:.4f}  盈亏: {pnl:+.2f}元"
            )

        # 再买
        buy_price = details.get('buy_price', signal.price)
        available = self.state.cash * 0.999
        shares = int(available / buy_price / 100) * 100
        if shares > 0:
            buy_amount = shares * buy_price
            buy_commission = max(buy_amount * self.commission_rate, 5)
            self.state.cash -= (buy_amount + buy_commission)

            self.state.holding_code = signal.code
            self.state.holding_name = signal.name
            self.state.holding_price = buy_price
            self.state.holding_date = signal.date
            self.state.shares = shares
            self.state.last_rebalance = signal.date
            self.state.total_value = self.state.cash + shares * buy_price

            buy_record = TradeRecord(
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                date=signal.date,
                action='BUY',
                code=signal.code,
                name=signal.name,
                price=buy_price,
                shares=shares,
                amount=buy_amount,
                commission=buy_commission,
                reason=f"换仓买入: {signal.reason}",
            )
            self._log_trade(buy_record)
            logger.info(
                f"✅ 买入 {signal.name} x{shares}股 @ {buy_price:.4f}  "
                f"成交额: {buy_amount:.2f}"
            )

    def get_summary(self, current_prices: Dict[str, float] = None) -> str:
        """获取持仓摘要"""
        s = self.state
        # 更新市值
        if s.holding_code and current_prices and s.holding_code in current_prices:
            current_price = current_prices[s.holding_code]
            market_value = s.shares * current_price
            s.total_value = s.cash + market_value
            pnl = (current_price - s.holding_price) * s.shares if s.holding_price > 0 else 0
            pnl_pct = (current_price - s.holding_price) / s.holding_price * 100 if s.holding_price > 0 else 0
        else:
            market_value = 0
            pnl = 0
            pnl_pct = 0
            s.total_value = s.cash

        lines = [
            "💰 虚拟持仓状态",
            "=" * 55,
            f"  总资产:     {s.total_value:>15,.2f} 元",
            f"  可用现金:   {s.cash:>15,.2f} 元",
        ]

        if s.holding_code:
            lines += [
                f"  ────────────────────────────────────────",
                f"  持仓:       {s.holding_name} ({s.holding_code})",
                f"  份额:       {s.shares:>15,d} 股",
                f"  买入价:     {s.holding_price:>15.4f}",
                f"  买入日期:   {s.holding_date:>15s}",
                f"  持仓市值:   {market_value:>15,.2f} 元",
                f"  浮动盈亏:   {pnl:>+15,.2f} 元 ({pnl_pct:+.2f}%)",
            ]
        else:
            lines.append(f"  持仓:       空仓")

        lines.append("=" * 55)
        return '\n'.join(lines)

    def get_trade_history(self) -> List[dict]:
        """获取所有历史交易记录"""
        if not os.path.exists(TRADE_LOG_FILE):
            return []
        records = []
        with open(TRADE_LOG_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return records

    def reset(self, initial_cash: float = 1_000_000):
        """重置持仓（全部清零）"""
        self.state = StrategyState(cash=initial_cash, total_value=initial_cash)
        self._save_state()
        # 清除交易日志
        if os.path.exists(TRADE_LOG_FILE):
            os.remove(TRADE_LOG_FILE)
        logger.info(f"持仓已重置，初始资金: {initial_cash:,.2f}")
