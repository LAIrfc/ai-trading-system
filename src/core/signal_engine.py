"""
每日信号生成器
基于双核动量轮动策略，分析市场数据，生成买卖信号并记录完整决策逻辑
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from loguru import logger

from src.data.market_data import ETF_POOL


@dataclass
class Signal:
    """交易信号"""
    date: str                   # 信号日期
    action: str                 # BUY / SELL / HOLD / EMPTY
    code: str                   # ETF 代码
    name: str                   # ETF 名称
    price: float                # 当前价格
    reason: str                 # 决策理由（人类可读）
    details: dict = field(default_factory=dict)  # 详细分析数据


@dataclass
class StrategyState:
    """策略状态"""
    holding_code: str = ''       # 当前持仓代码
    holding_name: str = ''       # 当前持仓名称
    holding_price: float = 0.0   # 买入价格
    holding_date: str = ''       # 买入日期
    last_rebalance: str = ''     # 上次调仓日期
    cash: float = 1000000.0      # 现金
    total_value: float = 1000000.0  # 总资产
    shares: int = 0              # 持仓份额


class DualMomentumEngine:
    """
    双核动量轮动策略引擎

    核心逻辑:
    1. 绝对动量: 价格 > N日均线 → 资产处于上升趋势
    2. 相对动量: 过去M日涨幅排名 → 选最强资产
    3. 调仓: 每F个交易日检查一次
    4. 风控: 止损、黑天鹅保护、流动性过滤
    """

    def __init__(self, config: dict = None):
        cfg = config or {}
        # 策略参数（可调旋钮）
        self.N = cfg.get('abs_momentum_period', 200)   # 绝对动量均线
        self.M = cfg.get('rel_momentum_period', 60)    # 相对动量周期
        self.F = cfg.get('rebalance_freq', 20)         # 调仓频率（交易日）
        self.K = cfg.get('hold_count', 1)              # 持有数量
        self.stop_loss = cfg.get('stop_loss', -0.10)   # 止损线
        self.crash_threshold = cfg.get('crash_threshold', -0.05)  # 黑天鹅阈值
        self.min_volume = cfg.get('min_volume', 50_000_000)       # 最低日成交额

        # 安全资产（空仓时持有）
        self.safe_asset = cfg.get('safe_asset', '511520')

    def analyze(self, all_data: Dict[str, pd.DataFrame],
                state: StrategyState) -> Tuple[Signal, dict]:
        """
        分析所有 ETF 数据，生成交易信号

        Args:
            all_data: {code: DataFrame} 所有ETF历史数据
            state: 当前策略状态

        Returns:
            (Signal, analysis_details)
        """
        today = None
        analysis = {
            'date': '',
            'absolute_momentum': {},
            'relative_momentum': {},
            'qualified_pool': [],
            'ranking': [],
            'risk_check': {},
            'decision': '',
        }

        # ========== 第一步: 获取最新日期 ==========
        for code, df in all_data.items():
            if len(df) > 0:
                last_date = df['date'].max()
                if today is None or last_date > today:
                    today = last_date

        if today is None:
            return Signal(
                date=datetime.now().strftime('%Y-%m-%d'),
                action='ERROR', code='', name='',
                price=0, reason='无有效市场数据'
            ), analysis

        today_str = today.strftime('%Y-%m-%d') if isinstance(today, pd.Timestamp) else str(today)
        analysis['date'] = today_str

        # ========== 第二步: 计算绝对动量 ==========
        logger.info(f"📅 分析日期: {today_str}")
        logger.info(f"📐 参数: N={self.N}, M={self.M}, F={self.F}, K={self.K}")

        abs_passed = []
        for code, df in all_data.items():
            if len(df) < self.N:
                analysis['absolute_momentum'][code] = {
                    'status': '数据不足',
                    'data_count': len(df),
                    'required': self.N,
                }
                continue

            info = ETF_POOL.get(code, {'name': code, 'short': code})
            current_price = float(df['close'].iloc[-1])
            ma_n = float(df['close'].tail(self.N).mean())
            above_ma = current_price > ma_n

            analysis['absolute_momentum'][code] = {
                'name': info['short'],
                'price': current_price,
                'ma': round(ma_n, 4),
                'above_ma': above_ma,
                'ratio': round(current_price / ma_n, 4),
            }

            if above_ma:
                abs_passed.append(code)
                logger.info(f"  ✅ {info['short']} ({code}): {current_price:.4f} > MA{self.N}={ma_n:.4f} → 通过")
            else:
                logger.info(f"  ❌ {info['short']} ({code}): {current_price:.4f} < MA{self.N}={ma_n:.4f} → 不通过")

        analysis['qualified_pool'] = abs_passed

        # ========== 第三步: 计算相对动量 ==========
        momentum_scores = {}
        for code in abs_passed:
            df = all_data[code]
            if len(df) < self.M:
                continue

            current_price = float(df['close'].iloc[-1])
            past_price = float(df['close'].iloc[-self.M])
            momentum = (current_price / past_price - 1) * 100  # 百分比

            # 流动性检查
            avg_amount = float(df['amount'].tail(20).mean())
            if avg_amount < self.min_volume:
                analysis['relative_momentum'][code] = {
                    'momentum': round(momentum, 2),
                    'filtered': True,
                    'reason': f'成交额不足 ({avg_amount/1e8:.2f}亿 < {self.min_volume/1e8:.2f}亿)',
                }
                logger.info(f"  ⚠️ {ETF_POOL[code]['short']}: 动量={momentum:.2f}% 但成交额不足，过滤")
                continue

            momentum_scores[code] = momentum
            analysis['relative_momentum'][code] = {
                'name': ETF_POOL.get(code, {}).get('short', code),
                'momentum': round(momentum, 2),
                'current_price': current_price,
                'past_price': round(past_price, 4),
                'avg_amount_yi': round(avg_amount / 1e8, 2),
                'filtered': False,
            }
            logger.info(
                f"  📊 {ETF_POOL[code]['short']}: 过去{self.M}日涨幅={momentum:+.2f}%  "
                f"日均成交额={avg_amount/1e8:.2f}亿"
            )

        # 排名
        ranking = sorted(momentum_scores.items(), key=lambda x: x[1], reverse=True)
        analysis['ranking'] = [
            {'rank': i + 1, 'code': c, 'name': ETF_POOL.get(c, {}).get('short', c),
             'momentum': round(m, 2)}
            for i, (c, m) in enumerate(ranking)
        ]

        if ranking:
            logger.info(f"\n  🏆 动量排名:")
            for i, (c, m) in enumerate(ranking):
                marker = " ← 最强" if i == 0 else ""
                logger.info(f"     #{i+1} {ETF_POOL[c]['short']}: {m:+.2f}%{marker}")

        # ========== 第四步: 风控检查 ==========
        risk_ok = True
        risk_reasons = []

        # 止损检查
        if state.holding_code and state.holding_price > 0:
            current_holding_data = all_data.get(state.holding_code)
            if current_holding_data is not None and len(current_holding_data) > 0:
                current_price = float(current_holding_data['close'].iloc[-1])
                pnl_pct = (current_price - state.holding_price) / state.holding_price
                if pnl_pct <= self.stop_loss:
                    risk_ok = False
                    risk_reasons.append(
                        f"触发止损: {state.holding_name} 亏损 {pnl_pct*100:.1f}% "
                        f"(买入价 {state.holding_price:.4f} → 现价 {current_price:.4f})"
                    )

        # 黑天鹅检查 (用沪深300近似大盘)
        hs300_data = all_data.get('510300')
        if hs300_data is not None and len(hs300_data) >= 2:
            last_close = float(hs300_data['close'].iloc[-1])
            prev_close = float(hs300_data['close'].iloc[-2])
            daily_return = (last_close - prev_close) / prev_close
            if daily_return <= self.crash_threshold:
                risk_ok = False
                risk_reasons.append(
                    f"黑天鹅警报: 沪深300单日跌幅 {daily_return*100:.2f}% "
                    f"(阈值 {self.crash_threshold*100:.1f}%)"
                )

        analysis['risk_check'] = {
            'passed': risk_ok,
            'reasons': risk_reasons,
        }

        # ========== 第五步: 生成信号 ==========

        # 风控触发 → 清仓
        if not risk_ok:
            reason = '风控触发强制清仓: ' + '; '.join(risk_reasons)
            analysis['decision'] = reason
            if state.holding_code:
                holding_data = all_data.get(state.holding_code)
                price = float(holding_data['close'].iloc[-1]) if holding_data is not None and len(holding_data) > 0 else 0
                return Signal(
                    date=today_str, action='SELL',
                    code=state.holding_code, name=state.holding_name,
                    price=price, reason=reason, details=analysis,
                ), analysis
            else:
                return Signal(
                    date=today_str, action='EMPTY', code='', name='',
                    price=0, reason=reason, details=analysis,
                ), analysis

        # 检查是否到调仓日
        should_rebalance = True
        if state.last_rebalance:
            try:
                last_rb = pd.Timestamp(state.last_rebalance)
                trading_days_since = 0
                # 统计自上次调仓以来经过的交易日数
                for code, df in all_data.items():
                    count = len(df[df['date'] > last_rb])
                    if count > trading_days_since:
                        trading_days_since = count
                    break
                should_rebalance = trading_days_since >= self.F
                if not should_rebalance:
                    logger.info(
                        f"  ⏳ 距上次调仓 {trading_days_since} 个交易日，"
                        f"未到调仓日（每 {self.F} 日）"
                    )
            except Exception:
                should_rebalance = True

        # 备选池为空 → 空仓/持有安全资产
        if not ranking:
            reason = (
                f"所有资产均未通过绝对动量测试（价格 < MA{self.N}），"
                f"市场整体处于下行趋势，建议空仓或持有国债ETF"
            )
            analysis['decision'] = reason

            if state.holding_code and state.holding_code != self.safe_asset:
                # 卖出当前持仓
                holding_data = all_data.get(state.holding_code)
                price = float(holding_data['close'].iloc[-1]) if holding_data is not None and len(holding_data) > 0 else 0
                return Signal(
                    date=today_str, action='SELL',
                    code=state.holding_code, name=state.holding_name,
                    price=price,
                    reason=f"空仓信号: {reason}",
                    details=analysis,
                ), analysis
            else:
                return Signal(
                    date=today_str, action='EMPTY', code='', name='',
                    price=0, reason=reason, details=analysis,
                ), analysis

        # 取排名第 1 的资产
        best_code, best_momentum = ranking[0]
        best_info = ETF_POOL.get(best_code, {'name': best_code, 'short': best_code})
        best_data = all_data[best_code]
        best_price = float(best_data['close'].iloc[-1])

        # 当前已持有最强资产 → 继续持有
        if state.holding_code == best_code:
            pnl = (best_price - state.holding_price) / state.holding_price * 100 if state.holding_price > 0 else 0
            reason = (
                f"继续持有 {best_info['short']}，"
                f"仍为动量最强资产 (涨幅 {best_momentum:+.2f}%)，"
                f"持仓盈亏 {pnl:+.2f}%"
            )
            analysis['decision'] = reason
            return Signal(
                date=today_str, action='HOLD',
                code=best_code, name=best_info['short'],
                price=best_price, reason=reason, details=analysis,
            ), analysis

        # 未到调仓日 → 维持现状
        if not should_rebalance and state.holding_code:
            pnl = 0
            if state.holding_price > 0:
                holding_data = all_data.get(state.holding_code)
                if holding_data is not None and len(holding_data) > 0:
                    curr = float(holding_data['close'].iloc[-1])
                    pnl = (curr - state.holding_price) / state.holding_price * 100
            reason = (
                f"未到调仓日，继续持有 {state.holding_name}，"
                f"持仓盈亏 {pnl:+.2f}%。"
                f"最强资产已切换为 {best_info['short']}，"
                f"将在下一个调仓日换仓"
            )
            analysis['decision'] = reason
            return Signal(
                date=today_str, action='HOLD',
                code=state.holding_code, name=state.holding_name,
                price=float(all_data[state.holding_code]['close'].iloc[-1]) if state.holding_code in all_data else 0,
                reason=reason, details=analysis,
            ), analysis

        # 需要换仓或首次建仓
        if state.holding_code:
            # 先卖后买，这里先生成卖出信号
            holding_data = all_data.get(state.holding_code)
            sell_price = float(holding_data['close'].iloc[-1]) if holding_data is not None and len(holding_data) > 0 else 0
            pnl = (sell_price - state.holding_price) / state.holding_price * 100 if state.holding_price > 0 else 0
            reason = (
                f"调仓换股: 卖出 {state.holding_name} (盈亏 {pnl:+.2f}%)，"
                f"买入 {best_info['short']} (动量排名第1, 涨幅 {best_momentum:+.2f}%)"
            )
            analysis['decision'] = reason
            # 返回 SWITCH 信号，包含买卖双方信息
            return Signal(
                date=today_str, action='SWITCH',
                code=best_code, name=best_info['short'],
                price=best_price,
                reason=reason,
                details={
                    **analysis,
                    'sell_code': state.holding_code,
                    'sell_name': state.holding_name,
                    'sell_price': sell_price,
                    'sell_pnl_pct': round(pnl, 2),
                    'buy_code': best_code,
                    'buy_name': best_info['short'],
                    'buy_price': best_price,
                },
            ), analysis
        else:
            # 首次建仓
            reason = (
                f"首次建仓: 买入 {best_info['short']} (动量排名第1, "
                f"过去{self.M}日涨幅 {best_momentum:+.2f}%, "
                f"价格 {best_price:.4f} > MA{self.N})"
            )
            analysis['decision'] = reason
            return Signal(
                date=today_str, action='BUY',
                code=best_code, name=best_info['short'],
                price=best_price, reason=reason, details=analysis,
            ), analysis
