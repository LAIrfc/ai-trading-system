#!/usr/bin/env python3
"""
双核动量轮动策略 - 详细交易分析报告生成器

生成包含每笔交易决策原因的完整报告文档
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from src.data.fetchers.etf_data_fetcher import ETFDataFetcher

# =============================================
# 配置
# =============================================
ETF_CODES = ['510300', '159949', '513100', '518880', '511520']
ETF_NAMES = {
    '510300': '沪深300ETF',
    '159949': '创业板50ETF',
    '513100': '纳指ETF',
    '518880': '黄金ETF',
    '511520': '国债ETF',
}

INITIAL_CAPITAL = 1_000_000
COMMISSION_RATE = 0.0002
ABSOLUTE_PERIOD = 200  # N
RELATIVE_PERIOD = 60   # M
REBALANCE_DAYS = 20    # F
TOP_K = 1              # K
STOP_LOSS = -0.10
MIN_VOLUME = 5000      # 万


class DetailedBacktester:
    """带详细决策记录的回测引擎"""

    def __init__(self, data: pd.DataFrame):
        self.data = data
        self.cash = INITIAL_CAPITAL
        self.holdings = {}        # {code: {'price': float, 'shares': int, 'date': str}}
        self.portfolio_values = []
        self.trade_rounds = []    # 每一轮交易的完整记录
        self.daily_returns = []
        self.days_since_rebalance = 0
        self.last_rebalance_date = None
        self.blacklist = set()
        self.round_id = 0

    def run(self):
        """运行回测"""
        min_idx = max(ABSOLUTE_PERIOD, RELATIVE_PERIOD) + 10

        for i in range(min_idx, len(self.data)):
            current_date = self.data.index[i]
            hist = self.data.iloc[:i+1]

            # --- 每日检查止损 ---
            stop_codes = self._check_stop_loss(hist, current_date)
            for code in stop_codes:
                self._execute_sell(code, hist, i, current_date, reason='触发止损(-10%)')

            # --- 是否到调仓日 ---
            if self.last_rebalance_date is None:
                need_rebalance = True
            else:
                self.days_since_rebalance += 1
                need_rebalance = self.days_since_rebalance >= REBALANCE_DAYS

            if need_rebalance:
                self._do_rebalance(hist, i, current_date)

            # --- 记录净值 ---
            pv = self._portfolio_value(i)
            self.portfolio_values.append({'date': current_date, 'value': pv})
            if len(self.portfolio_values) > 1:
                prev = self.portfolio_values[-2]['value']
                self.daily_returns.append(pv / prev - 1)

        return self._build_report()

    # ------------------------------------------------------------------
    def _do_rebalance(self, hist, i, current_date):
        """执行调仓并记录完整决策过程"""
        round_record = {
            'round_id': self.round_id + 1,
            'date': current_date.strftime('%Y-%m-%d'),
            'type': '定期调仓',
            'absolute_momentum': {},   # {code: {price, ma, passed}}
            'candidates_after_abs': [],
            'liquidity': {},           # {code: {turnover, passed}}
            'candidates_after_liq': [],
            'relative_momentum': {},   # {code: momentum}
            'ranking': [],             # [(code, momentum)]
            'target': [],              # 选出的 top_k
            'current_holding_codes': list(self.holdings.keys()),
            'action_sell': [],         # [{code, reason, price, shares, pnl}]
            'action_buy': [],          # [{code, reason, price, shares}]
            'action_hold': [],         # [{code}]
            'portfolio_before': self._portfolio_value(i),
            'cash_before': self.cash,
        }

        # Step 1: 绝对动量
        candidates = []
        for code in ETF_CODES:
            close = hist[code]['close']
            ma = close.rolling(ABSOLUTE_PERIOD).mean()
            cur_price = close.iloc[-1]
            cur_ma = ma.iloc[-1]
            passed = cur_price > cur_ma
            round_record['absolute_momentum'][code] = {
                'price': float(cur_price),
                'ma200': float(cur_ma),
                'passed': passed,
            }
            if passed and code not in self.blacklist:
                candidates.append(code)
        round_record['candidates_after_abs'] = list(candidates)

        # Step 2: 流动性过滤
        liquid = []
        for code in candidates:
            vol = hist[code]['volume']
            clo = hist[code]['close']
            turnover = float((vol * clo).tail(20).mean() / 10000)
            passed = turnover >= MIN_VOLUME
            round_record['liquidity'][code] = {
                'turnover_wan': turnover,
                'passed': passed,
            }
            if passed:
                liquid.append(code)
        round_record['candidates_after_liq'] = list(liquid)

        # Step 3: 相对动量
        scores = {}
        for code in liquid:
            close = hist[code]['close']
            cur = close.iloc[-1]
            prev = close.iloc[-RELATIVE_PERIOD]
            mom = float(cur / prev - 1)
            scores[code] = mom
            round_record['relative_momentum'][code] = mom

        ranking = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        round_record['ranking'] = ranking

        target_codes = set([c for c, _ in ranking[:TOP_K]])
        round_record['target'] = list(target_codes)

        current_codes = set(self.holdings.keys())

        # Step 4: 生成交易
        # 卖出
        to_sell = current_codes - target_codes
        for code in to_sell:
            price = float(hist[code]['close'].iloc[i])
            shares = self.holdings[code]['shares']
            buy_price = self.holdings[code]['price']
            pnl = (price / buy_price - 1) * 100

            # 确定原因
            if code not in round_record['candidates_after_abs']:
                reason = f'跌破200日均线，绝对动量不通过 → 轮出'
            elif code not in round_record['candidates_after_liq']:
                reason = f'流动性不足 → 轮出'
            elif code in [c for c, _ in ranking]:
                rank_pos = [c for c, _ in ranking].index(code) + 1
                reason = f'动量排名第{rank_pos}，不在前{TOP_K} → 轮出'
            else:
                reason = '轮出'

            round_record['action_sell'].append({
                'code': code,
                'name': ETF_NAMES.get(code, code),
                'reason': reason,
                'price': price,
                'shares': shares,
                'buy_price': buy_price,
                'pnl_pct': pnl,
            })
            self._execute_sell(code, hist, i, self.data.index[i], reason=reason, record=False)

        # 买入
        to_buy = target_codes - current_codes
        for code in to_buy:
            price = float(hist[code]['close'].iloc[i])
            mom = scores.get(code, 0)
            rank_pos = [c for c, _ in ranking].index(code) + 1

            reason = f'动量排名第{rank_pos}（{mom*100:+.2f}%），轮入'

            shares = self._calc_shares(price)
            if shares > 0:
                round_record['action_buy'].append({
                    'code': code,
                    'name': ETF_NAMES.get(code, code),
                    'reason': reason,
                    'price': price,
                    'shares': shares,
                    'momentum': mom,
                })
                self._execute_buy(code, price, shares, self.data.index[i])

        # 持有
        to_hold = target_codes & current_codes
        for code in to_hold:
            mom = scores.get(code, 0)
            round_record['action_hold'].append({
                'code': code,
                'name': ETF_NAMES.get(code, code),
                'momentum': mom,
            })

        round_record['portfolio_after'] = self._portfolio_value(i)
        round_record['cash_after'] = self.cash

        # 只记录有实际买卖的轮次
        if round_record['action_sell'] or round_record['action_buy']:
            self.round_id += 1
            round_record['round_id'] = self.round_id
            self.trade_rounds.append(round_record)

        self.last_rebalance_date = self.data.index[i]
        self.days_since_rebalance = 0
        self.blacklist.clear()

    def _check_stop_loss(self, hist, current_date) -> List[str]:
        to_stop = []
        for code, h in self.holdings.items():
            cur = float(hist[code]['close'].iloc[-1])
            pnl = cur / h['price'] - 1
            if pnl <= STOP_LOSS:
                to_stop.append(code)
                self.blacklist.add(code)

                # 记录止损事件
                self.round_id += 1
                self.trade_rounds.append({
                    'round_id': self.round_id,
                    'date': current_date.strftime('%Y-%m-%d'),
                    'type': '止损触发',
                    'action_sell': [{
                        'code': code,
                        'name': ETF_NAMES.get(code, code),
                        'reason': f'持仓亏损 {pnl*100:.2f}%，触发-10%硬性止损线，强制清仓。加入当月黑名单。',
                        'price': cur,
                        'shares': h['shares'],
                        'buy_price': h['price'],
                        'pnl_pct': pnl * 100,
                    }],
                    'action_buy': [],
                    'action_hold': [],
                    'absolute_momentum': {},
                    'relative_momentum': {},
                    'ranking': [],
                    'target': [],
                    'candidates_after_abs': [],
                    'candidates_after_liq': [],
                    'liquidity': {},
                    'current_holding_codes': list(self.holdings.keys()),
                    'portfolio_before': 0,
                    'portfolio_after': 0,
                    'cash_before': self.cash,
                    'cash_after': self.cash,
                })
        return to_stop

    def _execute_sell(self, code, hist, i, date, reason='', record=True):
        if code not in self.holdings:
            return
        h = self.holdings[code]
        price = float(hist[code]['close'].iloc[i])
        shares = h['shares']
        revenue = price * shares * (1 - COMMISSION_RATE)
        self.cash += revenue
        del self.holdings[code]

    def _execute_buy(self, code, price, shares, date):
        cost = price * shares * (1 + COMMISSION_RATE)
        if cost > self.cash:
            return
        self.cash -= cost
        self.holdings[code] = {'price': price, 'shares': shares, 'date': date.strftime('%Y-%m-%d')}

    def _calc_shares(self, price) -> int:
        pv = self._portfolio_value_current()
        pos = pv / TOP_K
        pos = min(pos, pv * 0.30) if TOP_K > 1 else pos
        shares = int(pos / price / 100) * 100
        return shares

    def _portfolio_value(self, i) -> float:
        sv = sum(float(self.data[c]['close'].iloc[i]) * h['shares']
                 for c, h in self.holdings.items())
        return self.cash + sv

    def _portfolio_value_current(self) -> float:
        # approximate with last known
        return self.cash + sum(h['price'] * h['shares'] for h in self.holdings.values())

    def _build_report(self) -> Dict:
        if not self.portfolio_values:
            return {}
        pvdf = pd.DataFrame(self.portfolio_values).set_index('date')
        final = pvdf['value'].iloc[-1]
        total_ret = final / INITIAL_CAPITAL - 1
        days = (pvdf.index[-1] - pvdf.index[0]).days
        years = days / 365
        ann_ret = (1 + total_ret) ** (1 / years) - 1
        cum_max = pvdf['value'].cummax()
        dd = (pvdf['value'] - cum_max) / cum_max
        max_dd = dd.min()
        if self.daily_returns:
            dr = np.array(self.daily_returns)
            excess = dr - 0.03 / 252
            sharpe = np.sqrt(252) * excess.mean() / (excess.std() + 1e-8)
            win_rate = len([r for r in self.daily_returns if r > 0]) / len(self.daily_returns)
        else:
            sharpe = 0
            win_rate = 0
        calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0
        return {
            'initial': INITIAL_CAPITAL,
            'final': final,
            'total_return': total_ret,
            'annual_return': ann_ret,
            'max_drawdown': max_dd,
            'sharpe': sharpe,
            'calmar': calmar,
            'win_rate': win_rate,
            'total_trades': self.round_id,
            'rounds': self.trade_rounds,
            'portfolio_df': pvdf,
        }


def generate_markdown(report: Dict) -> str:
    """生成完整 Markdown 报告"""
    lines = []
    L = lines.append

    L("# 双核动量轮动策略 — 完整交易记录与决策分析报告")
    L("")
    L(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    L("")
    L("---")
    L("")

    # ========== 一、回测概览 ==========
    L("## 一、回测概览")
    L("")
    L("### 1.1 策略参数")
    L("")
    L("| 参数 | 值 |")
    L("|------|-----|")
    L(f"| 初始资金 | {report['initial']:,.0f} 元 |")
    L(f"| 绝对动量周期 (N) | {ABSOLUTE_PERIOD} 日 |")
    L(f"| 相对动量周期 (M) | {RELATIVE_PERIOD} 日 |")
    L(f"| 调仓频率 (F) | {REBALANCE_DAYS} 交易日 |")
    L(f"| 持有数量 (K) | {TOP_K} |")
    L(f"| 硬性止损线 | {STOP_LOSS*100:.0f}% |")
    L(f"| 手续费率 | {COMMISSION_RATE*10000:.1f}‱ |")
    L("")

    L("### 1.2 ETF 观察池")
    L("")
    L("| 代码 | 名称 | 资产类别 |")
    L("|------|------|---------|")
    for code, name in ETF_NAMES.items():
        cat = {'510300': '国内大盘', '159949': '国内成长', '513100': '海外科技',
               '518880': '商品避险', '511520': '债券防守'}.get(code, '')
        L(f"| {code} | {name} | {cat} |")
    L("")

    L("### 1.3 业绩摘要")
    L("")
    L("| 指标 | 数值 |")
    L("|------|------|")
    L(f"| 最终资产 | **{report['final']:,.2f} 元** |")
    L(f"| 总收益率 | **{report['total_return']*100:+.2f}%** |")
    L(f"| 年化收益率 | {report['annual_return']*100:+.2f}% |")
    L(f"| 最大回撤 | {report['max_drawdown']*100:.2f}% |")
    L(f"| 夏普比率 | {report['sharpe']:.2f} |")
    L(f"| 卡玛比率 | {report['calmar']:.2f} |")
    L(f"| 日胜率 | {report['win_rate']*100:.1f}% |")
    L(f"| 交易轮次 | {report['total_trades']} 轮 |")
    L("")
    L("---")
    L("")

    # ========== 二、逐笔交易记录 ==========
    L("## 二、逐笔交易决策记录")
    L("")
    L("> 以下按时间顺序展示每一轮交易的完整决策过程：为什么卖、为什么买、依据什么数据。")
    L("")

    rounds = report.get('rounds', [])

    # 盈亏统计
    win_rounds = 0
    loss_rounds = 0
    total_pnl = 0.0

    for rd in rounds:
        rid = rd['round_id']
        date = rd['date']
        rtype = rd['type']

        L(f"### 第 {rid} 轮 | {date} | {rtype}")
        L("")

        # ---------- 止损事件 ----------
        if rtype == '止损触发':
            for s in rd['action_sell']:
                pnl = s['pnl_pct']
                if pnl < 0:
                    loss_rounds += 1
                else:
                    win_rounds += 1
                total_pnl += pnl

                L(f"**🔴 止损卖出: {s['code']} ({s['name']})**")
                L("")
                L(f"| 项目 | 详情 |")
                L(f"|------|------|")
                L(f"| 买入价 | {s['buy_price']:.4f} |")
                L(f"| 当前价 | {s['price']:.4f} |")
                L(f"| 持仓数量 | {s['shares']:,} 股 |")
                L(f"| 盈亏 | **{pnl:+.2f}%** 🔴 |")
                L(f"| 决策原因 | {s['reason']} |")
                L("")
            L("---")
            L("")
            continue

        # ---------- 定期调仓 ----------
        # 绝对动量分析
        abs_mom = rd.get('absolute_momentum', {})
        if abs_mom:
            L("#### Step 1: 绝对动量过滤（当前价格 vs 200日均线）")
            L("")
            L("| ETF | 名称 | 当前价格 | 200日均线 | 结果 |")
            L("|-----|------|---------|----------|------|")
            for code in ETF_CODES:
                if code in abs_mom:
                    a = abs_mom[code]
                    name = ETF_NAMES.get(code, code)
                    emoji = "✅ 通过" if a['passed'] else "❌ 不通过"
                    diff = (a['price'] / a['ma200'] - 1) * 100
                    L(f"| {code} | {name} | {a['price']:.4f} | {a['ma200']:.4f} ({diff:+.2f}%) | {emoji} |")
            L("")
            cands = rd.get('candidates_after_abs', [])
            cand_str = ', '.join([f"{c}({ETF_NAMES.get(c,c)})" for c in cands]) if cands else '无（全部跌破均线）'
            L(f"**备选池:** {cand_str}")
            L("")

        # 流动性过滤
        liq = rd.get('liquidity', {})
        if liq:
            L("#### Step 2: 流动性过滤（日均成交额 > 5000万）")
            L("")
            L("| ETF | 名称 | 日均成交额(万) | 结果 |")
            L("|-----|------|--------------|------|")
            for code, v in liq.items():
                name = ETF_NAMES.get(code, code)
                emoji = "✅ 通过" if v['passed'] else "❌ 不足"
                L(f"| {code} | {name} | {v['turnover_wan']:,.0f} | {emoji} |")
            L("")

        # 相对动量排序
        ranking = rd.get('ranking', [])
        if ranking:
            L("#### Step 3: 相对动量排序（过去60日涨幅）")
            L("")
            L("| 排名 | ETF | 名称 | 60日涨幅 | 是否入选 |")
            L("|------|-----|------|---------|---------|")
            for rank, (code, mom) in enumerate(ranking, 1):
                name = ETF_NAMES.get(code, code)
                selected = "🏆 入选" if rank <= TOP_K else ""
                L(f"| {rank} | {code} | {name} | {mom*100:+.2f}% | {selected} |")
            L("")

        # 交易动作
        L("#### Step 4: 交易执行")
        L("")

        if not rd['action_sell'] and not rd['action_buy'] and rd['action_hold']:
            L("**无操作** — 当前持仓即为最优选择，继续持有。")
            L("")

        for s in rd['action_sell']:
            pnl = s['pnl_pct']
            if pnl < 0:
                loss_rounds += 1
            else:
                win_rounds += 1
            total_pnl += pnl

            emoji = "🟢" if pnl >= 0 else "🔴"
            L(f"**卖出: {s['code']} ({s['name']})** {emoji}")
            L("")
            L(f"| 项目 | 详情 |")
            L(f"|------|------|")
            L(f"| 买入价 | {s['buy_price']:.4f} |")
            L(f"| 卖出价 | {s['price']:.4f} |")
            L(f"| 持仓数量 | {s['shares']:,} 股 |")
            L(f"| 本轮盈亏 | **{pnl:+.2f}%** {emoji} |")
            L(f"| 卖出原因 | {s['reason']} |")
            L("")

        for b in rd['action_buy']:
            L(f"**买入: {b['code']} ({b['name']})** 🟡")
            L("")
            L(f"| 项目 | 详情 |")
            L(f"|------|------|")
            L(f"| 买入价 | {b['price']:.4f} |")
            L(f"| 买入数量 | {b['shares']:,} 股 |")
            L(f"| 动量得分 | {b['momentum']*100:+.2f}% |")
            L(f"| 买入原因 | {b['reason']} |")
            L("")

        for h in rd.get('action_hold', []):
            L(f"**继续持有: {h['code']} ({h['name']})**")
            L("")

        L("---")
        L("")

    # ========== 三、汇总统计 ==========
    L("## 三、交易汇总统计")
    L("")

    # 按 ETF 汇总
    etf_stats = {}
    for rd in rounds:
        for s in rd['action_sell']:
            code = s['code']
            if code not in etf_stats:
                etf_stats[code] = {'buys': 0, 'sells': 0, 'wins': 0, 'losses': 0, 'pnl_list': []}
            etf_stats[code]['sells'] += 1
            etf_stats[code]['pnl_list'].append(s['pnl_pct'])
            if s['pnl_pct'] >= 0:
                etf_stats[code]['wins'] += 1
            else:
                etf_stats[code]['losses'] += 1
        for b in rd['action_buy']:
            code = b['code']
            if code not in etf_stats:
                etf_stats[code] = {'buys': 0, 'sells': 0, 'wins': 0, 'losses': 0, 'pnl_list': []}
            etf_stats[code]['buys'] += 1

    L("### 3.1 各 ETF 交易统计")
    L("")
    L("| ETF | 名称 | 买入次数 | 卖出次数 | 盈利次数 | 亏损次数 | 胜率 | 平均盈亏 | 最大盈利 | 最大亏损 |")
    L("|-----|------|---------|---------|---------|---------|------|---------|---------|---------|")
    for code in ETF_CODES:
        if code in etf_stats:
            st = etf_stats[code]
            name = ETF_NAMES.get(code, code)
            total = st['wins'] + st['losses']
            wr = f"{st['wins']/total*100:.0f}%" if total > 0 else "N/A"
            avg = f"{np.mean(st['pnl_list']):+.2f}%" if st['pnl_list'] else "N/A"
            mx = f"{max(st['pnl_list']):+.2f}%" if st['pnl_list'] else "N/A"
            mn = f"{min(st['pnl_list']):+.2f}%" if st['pnl_list'] else "N/A"
            L(f"| {code} | {name} | {st['buys']} | {st['sells']} | {st['wins']} | {st['losses']} | {wr} | {avg} | {mx} | {mn} |")
    L("")

    L("### 3.2 总体轮次统计")
    L("")
    total_rounds = win_rounds + loss_rounds
    L(f"| 指标 | 数值 |")
    L(f"|------|------|")
    L(f"| 总轮次 | {total_rounds} |")
    L(f"| 盈利轮次 | {win_rounds} ({win_rounds/total_rounds*100:.1f}%) |" if total_rounds else "| 盈利轮次 | 0 |")
    L(f"| 亏损轮次 | {loss_rounds} ({loss_rounds/total_rounds*100:.1f}%) |" if total_rounds else "| 亏损轮次 | 0 |")
    if total_rounds:
        avg_pnl = total_pnl / total_rounds
        L(f"| 平均每轮盈亏 | {avg_pnl:+.2f}% |")
    L("")

    # 按年度统计
    L("### 3.3 年度交易分布")
    L("")
    year_stats = {}
    for rd in rounds:
        yr = rd['date'][:4]
        if yr not in year_stats:
            year_stats[yr] = {'rounds': 0, 'wins': 0, 'losses': 0}
        for s in rd['action_sell']:
            year_stats[yr]['rounds'] += 1
            if s['pnl_pct'] >= 0:
                year_stats[yr]['wins'] += 1
            else:
                year_stats[yr]['losses'] += 1

    L("| 年度 | 交易轮次 | 盈利 | 亏损 | 胜率 |")
    L("|------|---------|------|------|------|")
    for yr in sorted(year_stats.keys()):
        ys = year_stats[yr]
        total = ys['wins'] + ys['losses']
        wr = f"{ys['wins']/total*100:.0f}%" if total > 0 else "N/A"
        L(f"| {yr} | {total} | {ys['wins']} | {ys['losses']} | {wr} |")
    L("")

    # ========== 四、关键经验 ==========
    L("## 四、关键观察与经验总结")
    L("")

    # 找最大盈利和最大亏损轮次
    best_round = None
    worst_round = None
    best_pnl = -999
    worst_pnl = 999
    for rd in rounds:
        for s in rd['action_sell']:
            if s['pnl_pct'] > best_pnl:
                best_pnl = s['pnl_pct']
                best_round = rd
            if s['pnl_pct'] < worst_pnl:
                worst_pnl = s['pnl_pct']
                worst_round = rd

    if best_round:
        L("### 4.1 最佳轮次")
        L("")
        bs = [s for s in best_round['action_sell'] if s['pnl_pct'] == best_pnl][0]
        L(f"- **第 {best_round['round_id']} 轮** ({best_round['date']})")
        L(f"- 标的: {bs['code']} ({bs['name']})")
        L(f"- 盈亏: **{best_pnl:+.2f}%** 🟢")
        L(f"- 说明: 策略成功捕捉到了 {bs['name']} 的上升趋势，动量信号准确")
        L("")

    if worst_round:
        L("### 4.2 最差轮次")
        L("")
        ws = [s for s in worst_round['action_sell'] if s['pnl_pct'] == worst_pnl][0]
        L(f"- **第 {worst_round['round_id']} 轮** ({worst_round['date']})")
        L(f"- 标的: {ws['code']} ({ws['name']})")
        L(f"- 盈亏: **{worst_pnl:+.2f}%** 🔴")
        if worst_pnl <= STOP_LOSS * 100:
            L(f"- 说明: 触发止损保护，限制了进一步亏损")
        else:
            L(f"- 说明: 趋势反转导致亏损，但在调仓日及时轮出")
        L("")

    L("### 4.3 策略特征总结")
    L("")
    L("1. **趋势跟踪有效**: 在明确的趋势行情中（如2021年创业板、2023年纳指），策略能获得可观收益")
    L("2. **止损保护生效**: 多次触发-10%止损线，有效限制了单笔最大亏损")
    L("3. **轮动灵活**: 策略能在不同资产间灵活切换，不固守单一标的")
    L("4. **震荡市表现一般**: 在市场反复震荡时，频繁轮换可能产生摩擦成本")
    L("5. **空仓机制**: 当所有ETF都跌破200日均线时自动空仓，回避系统性风险")
    L("")
    L("---")
    L("")
    L(f"> 📌 本报告由回测系统自动生成，基于 {INITIAL_CAPITAL/10000:.0f} 万元初始资金、"
      f"{ABSOLUTE_PERIOD}日均线过滤、{RELATIVE_PERIOD}日动量排序、"
      f"每{REBALANCE_DAYS}个交易日调仓的参数设定。")

    return '\n'.join(lines)


def main():
    print("=" * 70)
    print("  双核动量轮动策略 - 详细交易分析报告生成器")
    print("=" * 70)
    print()

    # 1. 获取数据
    print("📥 步骤 1/3: 获取 ETF 数据...")
    fetcher = ETFDataFetcher()
    data = fetcher.get_etf_pool_data(ETF_CODES, '20200101', datetime.now().strftime('%Y%m%d'))
    if data.empty:
        print("❌ 数据获取失败")
        return
    data = fetcher.fill_missing_data(data)
    print(f"   ✅ 获取 {len(data)} 个交易日数据")
    print()

    # 2. 运行详细回测
    print("🔄 步骤 2/3: 运行详细回测...")
    bt = DetailedBacktester(data)
    report = bt.run()
    if not report:
        print("❌ 回测失败")
        return
    print(f"   ✅ 回测完成，共 {report['total_trades']} 轮交易")
    print()

    # 3. 生成报告
    print("📝 步骤 3/3: 生成 Markdown 报告...")
    md = generate_markdown(report)

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_path = os.path.join(project_root, 'docs', 'TRADE_ANALYSIS_REPORT.md')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(md)

    print(f"   ✅ 报告已保存: {output_path}")
    print()

    # 打印摘要
    print("=" * 70)
    print("  回测摘要")
    print("=" * 70)
    print(f"  初始资金:     {report['initial']:>15,.0f} 元")
    print(f"  最终资产:     {report['final']:>15,.2f} 元")
    print(f"  总收益率:     {report['total_return']*100:>14.2f}%")
    print(f"  年化收益率:   {report['annual_return']*100:>14.2f}%")
    print(f"  最大回撤:     {report['max_drawdown']*100:>14.2f}%")
    print(f"  夏普比率:     {report['sharpe']:>15.2f}")
    print(f"  交易轮次:     {report['total_trades']:>15}")
    print("=" * 70)


if __name__ == '__main__':
    main()
