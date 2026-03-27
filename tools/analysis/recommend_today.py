#!/usr/bin/env python3
"""
📈 每日选股推荐工具

功能:
1. 对股票池中所有股票获取最新数据
2. 策略模式: macd(单MACD) | ensemble(11策略固定权重，推荐，默认) | full_11(同ensemble，兼容旧命令)
3. 当前架构（2层）:
   - L0: 大盘过滤器（PolicyEvent 政策面，极度利空时暂停选股）
   - L3: 个股投票（11策略固定权重加权投票）
   - 注：L1/L2层已暂时关闭（待历史回测优化系数）
4. 输出：该买哪些、该卖哪些、观望哪些；每只附带信号强度、建议仓位、理由

用法:
    # 推荐：11策略固定权重投票（L0过滤 + L3投票）
    python3 tools/analysis/recommend_today.py --pool mydate/stock_pool_all.json --strategy ensemble --top 20

    # 单 MACD 快速筛选
    python3 tools/analysis/recommend_today.py --pool mydate/stock_pool.json --strategy macd --top 10

    # 跳过政策面大盘过滤（强制执行选股）
    python3 tools/analysis/recommend_today.py --no-policy-filter

11策略（固定权重）: MA | MACD | RSI | BOLL | KDJ | DUAL（技术面6） | PE | PB | PEPB（基本面3） | NEWS | MONEY_FLOW
L0大盘过滤: POLICY（PolicyEvent，极度利空时阻止选股）

【重要】每日选股只从综合大池 stock_pool_all.json 中选取。
综合大池 = 沪深300 + 中证500 指数成分股 + 7大赛道龙头 + 56只主流ETF，合计约860只。
数据获取走 UnifiedDataProvider 统一接口，自动多源降级（sina > eastmoney > tencent > tushare > baostock）。

输出:
    终端报告 + output/daily_recommendation_YYYY-MM-DD.md
"""

import sys
import os
import json
import time
import argparse
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# 双引擎调度架构导入
from src.strategies.trend_strategies import Trend_Composite, Momentum_Adj, TechnicalConfirmation, VolumeConfirmation, RelativeStrength

from src.strategies.macd_cross import MACDStrategy
from src.strategies.ensemble import EnsembleStrategy
from src.strategies.fundamental_pe import PEStrategy
from src.strategies.fundamental_pb import PBStrategy
from src.strategies.ma_cross import MACrossStrategy
from src.strategies.rsi_signal import RSIStrategy
from src.strategies.bollinger_band import BollingerBandStrategy
from src.strategies.kdj_signal import KDJStrategy
from src.strategies.dual_momentum import DualMomentumSingleStrategy
from src.strategies.sentiment import SentimentStrategy
from src.strategies.news_sentiment import NewsSentimentStrategy
from src.strategies.policy_event import PolicyEventStrategy
from src.strategies.money_flow import MoneyFlowStrategy
from src.data.fetchers.fundamental_fetcher import FundamentalFetcher


def is_st_stock(name: str) -> bool:
    """
    检查是否为ST股票（特别处理股票）
    
    ST股票包括：
    - ST: 连续两年亏损
    - *ST: 连续三年亏损，有退市风险
    - S*ST: 连续三年亏损且未完成股改
    - SST: 连续两年亏损且未完成股改
    - S: 未完成股改
    
    Returns:
        True: 是ST股票，应过滤
        False: 正常股票
    """
    if not name:
        return False
    name_upper = name.upper()
    # 检查ST相关关键词
    st_keywords = ['ST', '*ST', 'S*ST', 'SST']
    if any(kw in name_upper for kw in st_keywords):
        return True
    # 单独的S需要更严格匹配（避免误判，如"深圳"）
    if name_upper.startswith('S ') or name_upper.startswith('S\t'):
        return True
    return False


# ============================================================
# 增量报告（累积到单文件，最新日期在前，持仓置顶）
# ============================================================

REPORT_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'mydate', 'daily_reports', 'daily_recommendation.md')
PORTFOLIO_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'mydate', 'my_portfolio.json')
DAILY_ARCHIVE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'mydate', 'daily_reports')


def _load_portfolio() -> list:
    """加载持仓数据"""
    if not os.path.exists(PORTFOLIO_FILE):
        return []
    try:
        with open(PORTFOLIO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return [h for h in data.get('holdings', []) if h.get('shares', 0) > 0]
    except Exception:
        return []


def _render_portfolio_section(holdings: list, provider=None) -> str:
    """渲染持仓状态区块（带最新价格和盈亏）"""
    if not holdings:
        return "## 我的持仓\n\n暂无持仓。\n\n"

    lines = ["## 我的持仓\n"]
    lines.append("| 代码 | 名称 | 成本价 | 最新价 | 持仓 | 市值 | 盈亏% |")
    lines.append("|------|------|--------|--------|------|------|-------|")

    total_cost = 0
    total_value = 0
    for h in holdings:
        code = h['code']
        name = h.get('name', '')
        cost = h.get('avg_cost', 0)
        shares = h.get('shares', 0)
        latest = 0
        if provider:
            try:
                # 先用通用接口（覆盖范围更广），ETF 专用接口常被封
                df = provider.get_kline(symbol=code, datalen=3, min_bars=1, retries=1, timeout=8)
                if df is not None and not df.empty:
                    latest = float(df['close'].iloc[-1])
                else:
                    # 通用接口失败，再试 ETF 专用
                    is_etf = (code.startswith('5') or code.startswith('159')) and len(code) == 6
                    if is_etf:
                        df2 = provider.get_kline(symbol=code, datalen=3, min_bars=1, retries=1, timeout=8, is_etf=True)
                        if df2 is not None and not df2.empty:
                            latest = float(df2['close'].iloc[-1])
            except Exception:
                pass
        cost_total = cost * shares
        value_total = latest * shares if latest > 0 else 0
        pnl = ((latest / cost - 1) * 100) if cost > 0 and latest > 0 else 0
        pnl_str = f"{pnl:+.2f}%" if latest > 0 else "N/A"
        latest_str = f"¥{latest:.2f}" if latest > 0 else "N/A"
        value_str = f"¥{value_total:,.0f}" if value_total > 0 else "N/A"
        total_cost += cost_total
        total_value += value_total
        lines.append(f"| {code} | {name} | ¥{cost:.3f} | {latest_str} | {shares} | {value_str} | {pnl_str} |")

    if total_cost > 0 and total_value > 0:
        total_pnl = (total_value / total_cost - 1) * 100
        lines.append(f"\n**总市值**: ¥{total_value:,.0f} | **总成本**: ¥{total_cost:,.0f} | **总盈亏**: {total_pnl:+.2f}%\n")
    lines.append("")
    return "\n".join(lines)


def _render_holding_advice(holdings: list, all_results: list, today: str) -> str:
    """
    渲染持仓操作建议（含详细原因分析）
    
    策略：均值回归为主，趋势得分作为风险修正
    - 基础判断：使用均值回归引擎的score（超跌/超买）
    - 风险修正：趋势得分<-0.3时，降低加仓建议；趋势得分>0.3时，提升持有信心
    """
    if not holdings or not all_results:
        return ""
    result_map = {r['code']: r for r in all_results}
    holding_map = {h['code']: h for h in holdings}
    holding_codes = {h['code'] for h in holdings}
    found = [result_map[c] for c in holding_codes if c in result_map]
    if not found:
        return ""

    lines = [f"## 今日持仓操作建议 ({today})\n"]
    for r in sorted(found, key=lambda x: x.get('mr_score', 0), reverse=True):
        code = r['code']
        score = r.get('mr_score', 0)  # 使用mr_score（均值回归得分）保持与超跌榜一致
        buy_cnt = r.get('buy_count', 0)
        sell_cnt = r.get('sell_count', 0)
        hold_cnt = r.get('hold_count', 0)
        price = r.get('price', 0)
        change_5d = r.get('change_5d', 0)
        change_20d = r.get('change_20d', 0)
        trend = r.get('trend', '')
        vol_ratio = r.get('volume_ratio', 0)
        signals = r.get('signals', [])
        
        # 趋势得分（风险修正因子）
        trend_score = r.get('trend_score', 0.0)
        momentum_score = r.get('momentum_score', 0.0)
        
        # 基础判断（均值回归逻辑）
        if sell_cnt >= 3 or score < -5:
            base_action = "🔴 建议减仓/止损"
        elif sell_cnt >= 2 or score < 0:
            base_action = "🟡 关注风险，考虑减仓"
        elif buy_cnt >= 3 and score > 5:
            base_action = "🟢 可以加仓"
        elif buy_cnt >= 2:
            base_action = "🟢 继续持有"
        else:
            base_action = "⚪ 观望持有"
        
        # 趋势风险修正
        action = base_action
        trend_warning = ""
        
        if trend_score < -0.3:  # 趋势转弱
            if "加仓" in base_action:
                action = "🟡 可持有，但暂缓加仓（趋势转弱）"
                trend_warning = "⚠️ 趋势得分较低，建议等待趋势企稳"
            elif "继续持有" in base_action:
                action = "🟡 谨慎持有（趋势转弱）"
                trend_warning = "⚠️ 趋势转弱，密切关注"
        elif trend_score > 0.3:  # 趋势向好
            if "关注风险" in base_action:
                action = "🟡 可继续观察（趋势尚可）"
                trend_warning = "✅ 趋势得分较好，可适当放宽止损"
            elif "继续持有" in base_action:
                action = "🟢 继续持有（趋势健康）"
                trend_warning = "✅ 趋势向好，可安心持有"

        # 持仓盈亏
        h = holding_map.get(code, {})
        cost = h.get('avg_cost', 0)
        pnl_str = ""
        if cost > 0 and price > 0:
            pnl = (price / cost - 1) * 100
            pnl_str = f" | 持仓盈亏 {pnl:+.1f}%"

        lines.append(f"#### {r['name']}（{code}）{action}\n")
        
        # 趋势得分显示
        trend_emoji = "📈" if trend_score > 0.3 else ("📉" if trend_score < -0.3 else "➡️")
        trend_desc = f"强势" if trend_score > 0.5 else (f"向好" if trend_score > 0.3 else (f"转弱" if trend_score < -0.3 else f"中性"))
        
        lines.append(f"- **价格** ¥{price:.2f} | **得分** {score:.1f} | **趋势** {trend}{pnl_str}")
        lines.append(f"- **涨跌幅** 5日 {change_5d:+.2f}% / 20日 {change_20d:+.2f}% | **量比** {vol_ratio:.1f}x")
        lines.append(f"- **趋势分析** {trend_emoji} 趋势得分: {trend_score:.2f} ({trend_desc}) | 动量得分: {momentum_score:.2f}")
        
        if trend_warning:
            lines.append(f"- {trend_warning}")

        # 策略信号
        if signals:
            buy_sigs = [f"{sn}({reason})" for sn, act, _, reason in signals if act == 'BUY']
            sell_sigs = [f"{sn}({reason})" for sn, act, _, reason in signals if act == 'SELL']
            hold_sigs = [f"{sn}" for sn, act, _, reason in signals if act == 'HOLD']
            if buy_sigs:
                lines.append(f"- 🟢 看多: {', '.join(buy_sigs)}")
            if sell_sigs:
                lines.append(f"- 🔴 看空: {', '.join(sell_sigs)}")
            if hold_sigs:
                lines.append(f"- ⚪ 观望: {', '.join(hold_sigs)}")

        # 操作建议理由（均值回归 + 趋势修正）
        reasons = []
        
        # 均值回归维度
        if score < -5:
            reasons.append(f"综合得分{score:.1f}偏低，多数策略看空")
        elif score < 0:
            reasons.append(f"综合得分{score:.1f}偏弱，存在下行风险")
        
        # 趋势修正维度
        if trend_score < -0.5:
            reasons.append(f"趋势得分{trend_score:.2f}，趋势明显转弱，建议降低仓位")
        elif trend_score < -0.3:
            reasons.append(f"趋势得分{trend_score:.2f}，趋势偏弱，暂缓加仓")
        elif trend_score > 0.5:
            reasons.append(f"趋势得分{trend_score:.2f}，趋势强劲，可安心持有")
        elif trend_score > 0.3:
            reasons.append(f"趋势得分{trend_score:.2f}，趋势向好，支持持有")
        
        # 技术面分析
        if change_5d < -5:
            reasons.append(f"近5日下跌{change_5d:+.1f}%，短期走势较弱")
        if '空头' in trend:
            reasons.append("均线空头排列，技术面不利")
        elif '偏空' in trend:
            reasons.append("股价在MA20下方，中期趋势偏弱")
        
        # 盈亏分析
        if cost > 0 and price > 0 and (price / cost - 1) < -0.10:
            reasons.append(f"持仓亏损已超10%，需重新评估持有逻辑")
        
        # 策略信号
        if buy_cnt >= 3:
            reasons.append(f"{buy_cnt}个策略看多，可考虑加仓或继续持有")
        elif buy_cnt >= 2 and sell_cnt == 0:
            reasons.append("技术面偏多且无卖出信号，可继续持有")
        if change_5d > 5 and sell_cnt == 0:
            reasons.append(f"近5日上涨{change_5d:+.1f}%且无卖出信号，趋势健康")

        if reasons:
            lines.append(f"- **分析**: {'；'.join(reasons)}")
        lines.append("")

    return "\n".join(lines)


def _select_elite_top5(top_list: list) -> list:
    """
    从 TOP20 中精选 TOP5：多维度加权打分，优中选优。

    评分维度（满分100）：
      1. 趋势质量 (25分)：多头排列 > 偏多 > 偏空 > 空头
      2. 量价配合 (20分)：温和放量最佳(1.0-2.0x)，过度放量/缩量扣分
      3. 涨幅安全 (20分)：5日涨幅0~8%最佳，涨太多追高风险
      4. 上涨空间 (20分)：距60日高点越远空间越大，但不要跌太深
      5. 中期动能 (15分)：20日涨幅正且适中最佳

    额外约束：同板块最多入选2只，保证分散。
    """
    if not top_list:
        return []

    # 过滤科创板（688开头）和ST股票
    top_list = [r for r in top_list 
                if not str(r.get('code', '')).startswith('688')
                and not is_st_stock(r.get('name', ''))]

    scored = []
    for r in top_list:
        es = 0.0  # elite score
        reasons = []
        trend = r.get('trend', '')
        vol_ratio = r.get('volume_ratio', 0)
        change_5d = r.get('change_5d', 0)
        change_20d = r.get('change_20d', 0)
        dist_high = r.get('dist_high', 0)

        # 1. 趋势质量 (25分)
        if '多头' in trend:
            es += 25
            reasons.append("多头排列")
        elif '偏多' in trend:
            es += 15
            reasons.append("偏多趋势")
        elif '偏空' in trend:
            es += 5
        else:
            es += 0

        # 2. 量价配合 (20分)
        if 1.0 <= vol_ratio <= 2.0:
            es += 20
            reasons.append("量价配合好")
        elif 0.7 <= vol_ratio < 1.0 or 2.0 < vol_ratio <= 3.0:
            es += 12
        elif vol_ratio > 3.0:
            es += 8
            reasons.append(f"放量{vol_ratio:.1f}x需留意")
        else:
            es += 5

        # 3. 涨幅安全 (20分) — 温和上涨最好，追高风险扣分
        if 0 < change_5d <= 5:
            es += 20
            reasons.append("温和上涨安全")
        elif 5 < change_5d <= 8:
            es += 15
            reasons.append("短线动能强")
        elif 8 < change_5d <= 12:
            es += 8
        elif change_5d > 12:
            es += 3
        elif -3 < change_5d <= 0:
            es += 14
            reasons.append("回踩企稳")
        elif -5 < change_5d <= -3:
            es += 10
        else:
            es += 4

        # 4. 上涨空间 (20分) — 距60日高点越近越强，突破新高是最强信号
        if dist_high > 0:
            es += 20  # 突破60日新高，趋势最强
            reasons.append("突破新高趋势强")
        elif -3 < dist_high <= 0:
            es += 17
            reasons.append("接近新高")
        elif -10 < dist_high <= -3:
            es += 13
            reasons.append("上涨空间充足")
        elif -20 < dist_high <= -10:
            es += 8
        elif dist_high <= -20:
            es += 3

        # 5. 中期动能 (15分)
        if 3 < change_20d <= 15:
            es += 15
            reasons.append("中期趋势向好")
        elif 0 < change_20d <= 3:
            es += 10
        elif 15 < change_20d <= 25:
            es += 8
        elif change_20d > 25:
            es += 4
        elif -5 < change_20d <= 0:
            es += 6
        else:
            es += 2

        reason_str = '、'.join(reasons[:3]) if reasons else '综合得分靠前'
        scored.append((r, es, reason_str))

    scored.sort(key=lambda x: x[1], reverse=True)

    # 板块分散：同板块最多入选2只
    result = []
    sector_count = {}
    for r, es, reason in scored:
        sector = str(r.get('sector', ''))[:10]
        cnt = sector_count.get(sector, 0)
        if cnt >= 2:
            continue
        result.append((r, es, reason))
        sector_count[sector] = cnt + 1
        if len(result) >= 5:
            break

    return result


def _render_daily_section(today: str, top_list: list, strategy_name: str,
                          pool_size: int, valid_count: int, 
                          dual_advantage_stocks: list = None,
                          mr_list: list = None, 
                          trend_list: list = None,
                          hybrid_decision: dict = None) -> str:
    """渲染单日推荐区块（每只推荐股附带详细分析理由）"""
    lines = [f"## {today} 每日推荐\n"]
    
    # 混合策略信息
    if hybrid_decision:
        lines.append(f"**版本**: {hybrid_decision['version']} | **原因**: {hybrid_decision['reason']}\n")
        if hybrid_decision.get('ic_status'):
            ic = hybrid_decision['ic_status']
            lines.append(f"**IC状态**: Base Trend={ic['base_trend_ic']:.3f}, RS={ic['relative_strength_ic']:.3f}\n")
    
    lines.append(f"**策略**: {strategy_name} | **股票池**: {pool_size}只 | **有效**: {valid_count}只\n")
    
    # 双优股票特别说明
    if dual_advantage_stocks:
        lines.append(f"\n### ⭐⭐⭐ 双优股票（既超跌又趋势强，黄金标的，重点关注！）\n")
        lines.append("> **双优股票**：同时出现在超跌榜和趋势榜的股票，兼具**低估值反弹潜力**和**强劲上升趋势**，是最优质的投资标的。")
        lines.append("> 这些股票在下方的完整推荐列表中会**重复出现两次**（在超跌榜和趋势榜各出现一次），请重点关注！\n")
        lines.append("| 代码 | 名称 | 价格 | MR得分 | 趋势得分 | 超跌榜排名 | 趋势榜排名 | 说明 |")
        lines.append("|------|------|------|--------|----------|-----------|-----------|------|")
        for code in dual_advantage_stocks:
            r = next((x for x in top_list if x['code'] == code), None)
            if r:
                mr_rank = mr_list.index(code) + 1 if mr_list and code in mr_list else '-'
                trend_rank = trend_list.index(code) + 1 if trend_list and code in trend_list else '-'
                mr_score_val = r.get('mr_score', r.get('score', 0))
                trend_val = r.get('trend_score', 0)
                lines.append(f"| {code} | {r['name']} | {r.get('price',0):.2f} | {mr_score_val:.1f} | {trend_val:+.2f} | "
                           f"第{mr_rank} | 第{trend_rank} | 低估值+强趋势 |")
        lines.append("")

    # 总览表
    lines.append("### 📊 完整推荐列表\n")
    lines.append("| 类型 | 排名 | 代码 | 名称 | 价格 | MR得分 | 趋势 | 买/卖/观 | 5日% | 20日% | 板块 |")
    lines.append("|------|------|------|------|------|--------|------|----------|------|-------|------|")
    for rank, r in enumerate(top_list, 1):
        code = r['code']
        if dual_advantage_stocks and code in dual_advantage_stocks:
            stock_type = "⭐双优"
        elif mr_list and code in mr_list:
            stock_type = "🟢超跌"
        elif trend_list and code in trend_list:
            stock_type = "🔵趋势"
        else:
            stock_type = "⚪其他"
        
        trend = r.get('trend', '')
        bsh = f"{r.get('buy_count',0)}/{r.get('sell_count',0)}/{r.get('hold_count',0)}"
        mr_score_val = r.get('mr_score', r.get('score', 0))
        trend_val = r.get('trend_score', 0)
        
        lines.append(f"| {stock_type} | {rank} | {r['code']} | {r['name']} | {r.get('price',0):.2f} | "
                      f"{mr_score_val:.1f} | {trend_val:+.2f} | {bsh} | "
                      f"{r.get('change_5d',0):+.2f} | {r.get('change_20d',0):+.2f} | {str(r.get('sector',''))[:15]} |")
    lines.append("")

    # ====== 精选 TOP5：从 TOP20 中多维度再筛选 ======
    elite5 = _select_elite_top5(top_list)
    if elite5:
        lines.append("### 🏆 精选 TOP5（优中选优）\n")
        lines.append("从 TOP20 中按「趋势+量价配合+涨幅安全+位置空间+板块分散」五维度综合再筛选。\n")
        lines.append("| 精选 | 代码 | 名称 | 价格 | 策略得分 | 精选得分 | 趋势 | 量比 | 5日% | 推荐理由 |")
        lines.append("|------|------|------|------|----------|----------|------|------|------|----------|")
        for i, (r, elite_score, elite_reason) in enumerate(elite5, 1):
            vol_ratio = r.get('volume_ratio', 0)
            vol_str = f"{vol_ratio:.1f}x"
            lines.append(f"| ⭐{i} | {r['code']} | {r['name']} | {r.get('price',0):.2f} | "
                          f"{r.get('score',0):.1f} | {elite_score:.0f} | {r.get('trend','')} | "
                          f"{vol_str} | {r.get('change_5d',0):+.2f} | {elite_reason} |")
        lines.append("")

    # 每只推荐股的详细分析
    for rank, r in enumerate(top_list, 1):
        lines.append(f"### {rank}. {r['code']} {r['name']}  （得分 {r.get('score',0):.1f}）\n")

        # 基本信息行
        price = r.get('price', 0)
        trend = r.get('trend', 'N/A')
        vol_ratio = r.get('volume_ratio', 0)
        change_5d = r.get('change_5d', 0)
        change_20d = r.get('change_20d', 0)
        dist_high = r.get('dist_high', 0)
        dist_low = r.get('dist_low', 0)
        sector = r.get('sector', '')
        pe = r.get('pe_ttm')
        pb = r.get('pb')
        ma5 = r.get('ma5', 0)
        ma10 = r.get('ma10', 0)
        ma20 = r.get('ma20', 0)
        ma60 = r.get('ma60', 0)

        lines.append(f"- **价格** ¥{price:.2f} | **板块** {sector}")
        lines.append(f"- **趋势** {trend} | **量比** {vol_ratio:.1f}x{'（放量）' if vol_ratio > 1.5 else ('（缩量）' if vol_ratio < 0.7 else '')}")
        lines.append(f"- **涨跌幅** 5日 {change_5d:+.2f}% / 20日 {change_20d:+.2f}%")
        if ma5 and ma20:
            lines.append(f"- **均线** MA5={ma5:.2f} / MA10={ma10:.2f} / MA20={ma20:.2f} / MA60={ma60:.2f}")
        lines.append(f"- **位置** 距60日高点 {dist_high:+.1f}% / 距60日低点 {dist_low:+.1f}%")
        pe_str = f"PE={pe:.1f}" if pe else "PE=N/A"
        pb_str = f"PB={pb:.2f}" if pb else "PB=N/A"
        lines.append(f"- **估值** {pe_str} / {pb_str}")

        # 策略信号明细
        signals = r.get('signals', [])
        if signals:
            buy_sigs = [(sn, conf, reason) for sn, action, conf, reason in signals if action == 'BUY']
            sell_sigs = [(sn, conf, reason) for sn, action, conf, reason in signals if action == 'SELL']
            hold_sigs = [(sn, conf, reason) for sn, action, conf, reason in signals if action == 'HOLD']
            lines.append(f"- **策略投票** 🟢买入{len(buy_sigs)} / 🔴卖出{len(sell_sigs)} / ⚪观望{len(hold_sigs)}")

            if buy_sigs:
                lines.append(f"  - 看多信号:")
                for sn, conf, reason in buy_sigs:
                    lines.append(f"    - 🟢 **{sn}** ({conf:.0%}): {reason}")
            if sell_sigs:
                lines.append(f"  - 看空信号:")
                for sn, conf, reason in sell_sigs:
                    lines.append(f"    - 🔴 **{sn}** ({conf:.0%}): {reason}")
            if hold_sigs:
                lines.append(f"  - 观望信号:")
                for sn, conf, reason in hold_sigs:
                    lines.append(f"    - ⚪ **{sn}** ({conf:.0%}): {reason}")

        # 综合推荐理由
        lines.append("")
        lines.append(_generate_recommendation_reason(r))
        lines.append("")

    lines.append("---\n")
    return "\n".join(lines)


def _generate_recommendation_reason(r: dict) -> str:
    """根据分析数据生成综合推荐理由文字"""
    parts = []
    price = r.get('price', 0)
    trend = r.get('trend', '')
    vol_ratio = r.get('volume_ratio', 0)
    change_5d = r.get('change_5d', 0)
    change_20d = r.get('change_20d', 0)
    dist_high = r.get('dist_high', 0)
    buy_count = r.get('buy_count', 0)
    sell_count = r.get('sell_count', 0)
    signals = r.get('signals', [])

    # 趋势判断
    if '多头' in trend:
        parts.append("均线呈多头排列，短中期趋势向上")
    elif '偏多' in trend:
        parts.append("股价站上MA20，中期趋势偏多")
    elif '偏空' in trend:
        parts.append("股价位于MA20下方，需注意回调风险")
    elif '空头' in trend:
        parts.append("均线空头排列，技术面偏弱，属于超跌反弹型机会")

    # 量价
    if vol_ratio > 2.0:
        parts.append(f"量比{vol_ratio:.1f}x显著放量，资金关注度高")
    elif vol_ratio > 1.5:
        parts.append(f"量比{vol_ratio:.1f}x温和放量，量价配合良好")
    elif vol_ratio < 0.5:
        parts.append(f"量比{vol_ratio:.1f}x明显缩量，需关注后续量能跟进")

    # 涨跌幅
    if 0 < change_5d <= 5:
        parts.append(f"近5日温和上涨{change_5d:+.1f}%，上升势头稳健")
    elif 5 < change_5d <= 10:
        parts.append(f"近5日上涨{change_5d:+.1f}%，短线动能较强")
    elif change_5d > 10:
        parts.append(f"近5日大涨{change_5d:+.1f}%，短线涨幅较大注意追高风险")
    elif -5 < change_5d < 0:
        parts.append(f"近5日小幅调整{change_5d:+.1f}%，可能是回踩企稳")
    elif change_5d <= -5:
        parts.append(f"近5日下跌{change_5d:+.1f}%，属于超跌博反弹")

    if change_20d > 15:
        parts.append(f"20日涨幅{change_20d:+.1f}%，中期趋势强劲")
    elif change_20d < -15:
        parts.append(f"20日跌幅{change_20d:+.1f}%，中期偏弱需谨慎")

    # 位置
    if -5 < dist_high <= 0:
        parts.append("接近60日新高，上方压力较小")
    elif -15 < dist_high <= -5:
        parts.append(f"距60日高点{dist_high:+.1f}%，仍有上涨空间")
    elif dist_high <= -30:
        parts.append(f"距60日高点{dist_high:+.1f}%，处于相对低位")

    # 策略信号
    buy_names = [sn for sn, action, _, _ in signals if action == 'BUY']
    if buy_names:
        parts.append(f"{len(buy_names)}个策略发出买入信号（{', '.join(buy_names)}）")

    # PE/PB
    pe = r.get('pe_ttm')
    pb = r.get('pb')
    if pe and 0 < pe < 20:
        parts.append(f"PE={pe:.1f}处于低估值区间")
    elif pe and pe > 80:
        parts.append(f"PE={pe:.1f}估值偏高")

    if not parts:
        parts.append("多维度分析综合得分靠前")

    return f"> **推荐理由**: {'；'.join(parts)}。"


def save_incremental_report(
    today: str,
    top_list: list,
    all_results: list,
    strategy_name: str,
    pool_size: int,
    valid_count: int,
    *,
    holdings_only: bool = False,
    sector_results_map: dict = None,
    dual_advantage_stocks: list = None,
    mr_list: list = None,
    trend_list: list = None,
    hybrid_decision: dict = None,
):
    """保存增量报告：持仓置顶 + 今日操作建议 + 今日推荐 + 专题板块 + 历史（最新在前）"""
    from src.data.provider.data_provider import get_default_kline_provider
    provider = get_default_kline_provider()
    holdings = _load_portfolio()

    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)

    # 读取已有报告中的历史区块（去掉旧的持仓和操作建议，保留各日推荐）
    old_daily_sections = ""
    today_daily_block = ""
    if os.path.exists(REPORT_FILE):
        with open(REPORT_FILE, 'r', encoding='utf-8') as f:
            old_content = f.read()
        # 提取从第一个日期推荐区块开始的内容（格式: ## YYYY-MM-DD 每日推荐）
        import re
        parts = re.split(r'(## \d{4}-\d{2}-\d{2} 每日推荐)', old_content)
        daily_blocks = []
        for i in range(1, len(parts), 2):
            header = parts[i]
            body = parts[i + 1] if i + 1 < len(parts) else ""
            date_in_header = re.search(r'(\d{4}-\d{2}-\d{2})', header)
            if not date_in_header:
                continue
            d = date_in_header.group(1)
            if d == today:
                today_daily_block = header + body
                continue
            daily_blocks.append(header + body)
        old_daily_sections = "".join(daily_blocks)

    # 构建新报告
    report_parts = []
    report_parts.append(f"# 📈 每日选股推荐\n")
    report_parts.append(f"> 最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 数据来源: UnifiedDataProvider (多源自动降级)\n\n")

    # 1. 持仓置顶
    report_parts.append(_render_portfolio_section(holdings, provider))

    # 2. 今日持仓操作建议
    report_parts.append(_render_holding_advice(holdings, all_results, today))

    # 3. 今日推荐
    if holdings_only and (not top_list):
        # 仅持仓模式：不覆盖今日推荐（若已有则保留），避免把 top20 清空
        if today_daily_block.strip():
            report_parts.append(today_daily_block)
        else:
            report_parts.append(_render_daily_section(today, [], strategy_name, pool_size, valid_count,
                                                      dual_advantage_stocks, mr_list, trend_list, hybrid_decision))
    else:
        report_parts.append(_render_daily_section(today, top_list, strategy_name, pool_size, valid_count,
                                                  dual_advantage_stocks, mr_list, trend_list, hybrid_decision))

    # 4. 健康上涨组推荐（趋势跟随型）
    if not holdings_only and all_results:
        healthy_growth_section = _generate_healthy_growth_section(all_results, today)
        if healthy_growth_section:
            report_parts.append(healthy_growth_section)
    
    # 5. 专题板块推荐（核电+算电协同等）
    if not holdings_only and sector_results_map:
        try:
            from tools.analysis.generate_sector_themes import generate_all_themes
            # 使用传入的分析结果生成专题推荐
            theme_content = generate_all_themes(sector_results_map)
            if theme_content:
                report_parts.append(theme_content)
        except Exception as e:
            print(f"⚠️ 专题板块推荐生成失败: {e}")
    
    # 6. 历史推荐（旧的，最新在前）
    if old_daily_sections.strip():
        report_parts.append(old_daily_sections)

    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(report_parts))

    # 同时保存当日独立归档
    archive_path = os.path.join(DAILY_ARCHIVE_DIR, f'daily_recommendation_{today}.md')
    if not (holdings_only and (not top_list)):
        with open(archive_path, 'w', encoding='utf-8') as f:
            f.write(f"# 📈 每日选股推荐 — {today}\n\n")
            f.write(_render_daily_section(today, top_list, strategy_name, pool_size, valid_count,
                                         dual_advantage_stocks, mr_list, trend_list, hybrid_decision))

    return REPORT_FILE, archive_path


# ============================================================
# 健康上涨组筛选（趋势跟随型）
# ============================================================

def _generate_healthy_growth_section(all_results: list, today: str) -> str:
    """
    从全市场结果中筛选"健康上涨"的股票（趋势跟随型）
    
    筛选条件（适度放宽以捕捉更多健康标的）：
    1. 价格在MA20上方（中期趋势向上）
    2. 价格在MA60下方50%以内（不追高，有安全边际）
    3. 20日涨幅在3%-40%之间（健康上涨，包括温和上涨）
    4. 5日涨幅>-2%（短期未大幅回调）
    5. 量比>0.5（有基本资金参与）
    6. 综合得分>3（策略基本认可）
    7. 排除ST股票
    """
    healthy_stocks = []
    
    for r in all_results:
        # 基本信息
        price = r.get('price', 0)
        ma20 = r.get('ma20', 0)
        ma60 = r.get('ma60', 0)
        change_5d = r.get('change_5d', 0)
        change_20d = r.get('change_20d', 0)
        volume_ratio = r.get('volume_ratio', 0)
        score = r.get('score', 0)
        name = r.get('name', '')
        
        # 排除ST
        if 'ST' in name or '*' in name:
            continue
        
        # 条件1: 价格在MA20上方（中期趋势向上）
        if not (ma20 > 0 and price > ma20):
            continue
        
        # 条件2: 价格在MA60下方50%以内（不追高）
        if ma60 > 0 and price > ma60 * 1.5:
            continue
        
        # 条件3: 20日涨幅在3%-40%之间
        if not (3 <= change_20d <= 40):
            continue
        
        # 条件4: 5日涨幅>-2%（允许小幅回调）
        if change_5d < -2:
            continue
        
        # 条件5: 量比>0.5（有基本资金参与）
        if volume_ratio < 0.5:
            continue
        
        # 条件6: 综合得分>3
        if score <= 3:
            continue
        
        healthy_stocks.append(r)
    
    if not healthy_stocks:
        return ""
    
    # 按综合得分排序
    healthy_stocks.sort(key=lambda x: x['score'], reverse=True)
    top10 = healthy_stocks[:10]
    
    # 生成报告
    lines = []
    lines.append("## 📈 健康上涨组推荐（趋势跟随型）")
    lines.append("")
    lines.append("> **筛选逻辑**: 价格站稳MA20（中期趋势向上）+ 20日涨幅5-30%（健康上涨）+ 短期保持动能 + 有资金参与。这类股票适合趋势跟随，相比超跌反弹型更稳健。")
    lines.append("")
    lines.append(f"**分析时间**: {today} | **筛选结果**: {len(healthy_stocks)}只 | **展示**: TOP10")
    lines.append("")
    lines.append("### 📊 健康上涨 TOP10")
    lines.append("")
    lines.append("| 排名 | 代码 | 名称 | 价格 | 得分 | 买/卖/观 | 5日% | 20日% | 量比 | 板块 | 推荐理由 |")
    lines.append("|------|------|------|------|------|----------|------|-------|------|------|----------|")
    
    for i, r in enumerate(top10, 1):
        code = r['code']
        name = r['name']
        price = r['price']
        score = r['score']
        buy_cnt = r['buy_count']
        sell_cnt = r['sell_count']
        hold_cnt = r['hold_count']
        change_5d = r['change_5d']
        change_20d = r['change_20d']
        volume_ratio = r.get('volume_ratio', 0)
        sector = r.get('sector', '')
        
        # 推荐理由
        reason_parts = []
        if change_20d > 20:
            reason_parts.append("强势上涨")
        elif change_20d > 10:
            reason_parts.append("稳健上涨")
        else:
            reason_parts.append("温和上涨")
        
        if volume_ratio > 1.5:
            reason_parts.append("放量")
        elif volume_ratio > 1.0:
            reason_parts.append("量价配合")
        
        if buy_cnt >= 7:
            reason_parts.append("多策略共振")
        
        reason = "+".join(reason_parts)
        
        lines.append(f"| {i} | {code} | {name} | ¥{price:.2f} | {score:.1f} | {buy_cnt}/{sell_cnt}/{hold_cnt} | {change_5d:+.2f}% | {change_20d:+.2f}% | {volume_ratio:.1f}x | {sector} | {reason} |")
    
    lines.append("")
    lines.append("### 🌟 重点推荐 TOP3")
    lines.append("")
    
    for i, r in enumerate(top10[:3], 1):
        stars = "⭐" * (4 - i)
        lines.append(f"#### {i}️⃣ {r['name']}（{r['code']}）{stars} - 得分{r['score']:.1f}")
        lines.append("")
        lines.append("**基本信息**:")
        lines.append(f"- **价格**: ¥{r['price']:.2f}（最新） | **板块**: {r.get('sector', 'N/A')}")
        lines.append(f"- **趋势**: {r['trend']} | **量比**: {r.get('volume_ratio', 0):.1f}x")
        lines.append(f"- **涨跌幅**: 5日 {r['change_5d']:+.2f}% / 20日 {r['change_20d']:+.2f}%")
        lines.append("")
        
        lines.append("**核心优势**:")
        buy_signals = [s for s in r['signals'] if s[1] == 'BUY']
        if buy_signals:
            lines.append(f"- ✅ **{len(buy_signals)}个策略看多**")
            for sn, _, _, reason in buy_signals[:3]:
                lines.append(f"  - {sn}: {reason}")
        
        lines.append("")
        lines.append("**投资逻辑**:")
        lines.append(f"- 中期趋势向上（价格站稳MA20）")
        lines.append(f"- 20日涨幅{r['change_20d']:+.2f}%，属于健康上涨范围")
        lines.append(f"- 短期保持动能（5日{r['change_5d']:+.2f}%）")
        if r.get('volume_ratio', 0) > 1.0:
            lines.append(f"- 量价配合良好（量比{r.get('volume_ratio', 0):.1f}x）")
        
        pe = r.get('pe_ttm')
        pb = r.get('pb')
        if pe and 0 < pe < 30:
            lines.append(f"- 估值合理（PE={pe:.1f}）")
        
        lines.append("")
        lines.append("**风险提示**: 趋势跟随需要止损纪律，建议跌破MA20止损")
        lines.append("")
        lines.append("---")
        lines.append("")
    
    return "\n".join(lines)


# ============================================================
# 数据获取
# ============================================================

def fetch_stock_data(code: str, days: int = 200) -> pd.DataFrame:
    """通过统一数据接口获取 K 线数据（多数据源自动降级）"""
    from src.data.provider.data_provider import get_default_kline_provider

    provider = get_default_kline_provider()
    df = provider.get_kline(
        symbol=code,
        datalen=days,
        min_bars=30,
        retries=2,
        timeout=10,
    )
    return df if df is not None and not df.empty else pd.DataFrame()


def load_stock_pool(pool_file: str, max_count: int = 0) -> list:
    """加载股票池（兼容 sectors / stocks 格式，优先使用 pool_loader）"""
    try:
        from src.utils.pool_loader import load_pool
        return load_pool(pool_file, max_count=max_count, include_etf=False)
    except Exception:
        pass

    with open(pool_file, 'r', encoding='utf-8') as f:
        pool = json.load(f)

    stocks = []
    sectors = pool.get('stocks', pool.get('sectors', {}))
    for sec_name, sec_stocks in sectors.items():
        for s in sec_stocks:
            s = dict(s)
            s['sector'] = sec_name
            stocks.append(s)
    if max_count > 0 and len(stocks) > max_count:
        stocks = stocks[:max_count]
    return stocks


# ============================================================
# 技术指标扩展分析
# ============================================================

def analyze_stock_extended(df: pd.DataFrame, strat,
                           pe_strat: PEStrategy = None,
                           pb_strat: PBStrategy = None,
                           fund_flow_signal: dict = None) -> dict:
    """
    扩展分析：MACD信号 + 基本面PE/PB信号 + 资金流信号 + 辅助技术指标

    Args:
        fund_flow_signal: 资金流信号字典（来自fundamental_fetcher.get_fund_flow_signal）

    Returns:
        {
            'signal': StrategySignal,
            'price': float,         # 最新价
            'change_5d': float,     # 5日涨跌幅
            'change_20d': float,    # 20日涨跌幅
            'volume_ratio': float,  # 量比（当日/5日均量）
            'ma5': float,           # 5日均线
            'ma20': float,          # 20日均线
            'trend': str,           # 趋势判断
            'distance_from_high': float,  # 距离60日新高的距离
            'distance_from_low': float,   # 距离60日新低的距离
            'pe_signal': str,       # PE信号
            'pb_signal': str,       # PB信号
            'pe_ttm': float,        # 当前PE
            'pe_quantile': float,   # PE分位数
            'pb': float,            # 当前PB
            'pb_quantile': float,   # PB分位数
            'fund_flow_signal': str,  # 资金流信号
            'fund_flow_reason': str,   # 资金流原因
        }
    """
    close = df['close']
    volume = df['volume']
    price = float(close.iloc[-1])

    # MACD信号
    signal = strat.safe_analyze(df)

    # 涨跌幅
    change_5d = (price / float(close.iloc[-6]) - 1) * 100 if len(df) > 5 else 0
    change_20d = (price / float(close.iloc[-21]) - 1) * 100 if len(df) > 20 else 0

    # 量比
    avg_vol_5 = float(volume.iloc[-6:-1].mean()) if len(df) > 5 else 1
    vol_ratio = float(volume.iloc[-1]) / avg_vol_5 if avg_vol_5 > 0 else 1

    # 均线
    ma5 = float(close.iloc[-5:].mean())
    ma10 = float(close.iloc[-10:].mean()) if len(df) >= 10 else ma5
    ma20 = float(close.iloc[-20:].mean()) if len(df) >= 20 else ma5
    ma60 = float(close.iloc[-60:].mean()) if len(df) >= 60 else ma20

    # 趋势
    if price > ma5 > ma20:
        trend = '多头排列↑'
    elif price < ma5 < ma20:
        trend = '空头排列↓'
    elif price > ma20:
        trend = '偏多↗'
    else:
        trend = '偏空↘'

    # 60日高低点距离
    high_60 = float(close.iloc[-60:].max()) if len(df) >= 60 else float(close.max())
    low_60 = float(close.iloc[-60:].min()) if len(df) >= 60 else float(close.min())
    dist_high = (price / high_60 - 1) * 100
    dist_low = (price / low_60 - 1) * 100

    # 基本面信号
    pe_signal = 'N/A'
    pb_signal = 'N/A'
    pe_ttm = None
    pe_quantile = None
    pb_val = None
    pb_quantile = None
    
    if pe_strat and 'pe_ttm' in df.columns:
        try:
            pe_sig = pe_strat.analyze(df)
            pe_signal = pe_sig.action
            pe_ttm = pe_sig.indicators.get('pe_ttm')
            pe_quantile = pe_sig.indicators.get('pe_quantile')
        except Exception:
            pass
    
    if pb_strat and 'pb' in df.columns:
        try:
            pb_sig = pb_strat.analyze(df)
            pb_signal = pb_sig.action
            pb_val = pb_sig.indicators.get('pb')
            pb_quantile = pb_sig.indicators.get('pb_quantile')
        except Exception:
            pass

    # 资金流信号
    fund_flow = fund_flow_signal.get('signal', 'neutral') if fund_flow_signal else 'neutral'
    fund_flow_reason = fund_flow_signal.get('reason', '') if fund_flow_signal else ''
    
    return {
        'signal': signal,
        'price': price,
        'change_5d': round(change_5d, 2),
        'change_20d': round(change_20d, 2),
        'volume_ratio': round(vol_ratio, 2),
        'ma5': round(ma5, 2),
        'ma10': round(ma10, 2),
        'ma20': round(ma20, 2),
        'ma60': round(ma60, 2),
        'trend': trend,
        'distance_from_high': round(dist_high, 2),
        'distance_from_low': round(dist_low, 2),
        'pe_signal': pe_signal,
        'pb_signal': pb_signal,
        'pe_ttm': pe_ttm,
        'pe_quantile': pe_quantile,
        'pb': pb_val,
        'pb_quantile': pb_quantile,
        'fund_flow_signal': fund_flow,
        'fund_flow_reason': fund_flow_reason,
    }


# ============================================================
# 综合评分
# ============================================================

def compute_score(info: dict) -> float:
    """
    综合评分 = MACD信号 + 趋势 + 量价 + 位置 + 基本面

    满分 100+
    """
    sig = info['signal']
    score = 0.0

    # 1. MACD信号权重 (35分)
    if sig.action == 'BUY':
        score += 20 + sig.confidence * 15  # 20~35
    elif sig.action == 'SELL':
        score -= 20 + sig.confidence * 15
    else:
        score += 0  # HOLD

    # 2. 趋势 (20分)
    if '多头' in info['trend']:
        score += 20
    elif '偏多' in info['trend']:
        score += 10
    elif '偏空' in info['trend']:
        score -= 10
    elif '空头' in info['trend']:
        score -= 20

    # 3. 量比 (15分) — 放量配合方向
    if sig.action == 'BUY':
        if info['volume_ratio'] > 1.5:
            score += 15  # 放量金叉
        elif info['volume_ratio'] > 1.0:
            score += 8
        else:
            score += 3   # 缩量金叉信号偏弱
    elif sig.action == 'SELL':
        if info['volume_ratio'] > 2.0:
            score -= 15  # 放量下跌，恐慌出逃
        elif info['volume_ratio'] > 1.5:
            score -= 10  # 明显放量卖出
        elif info['volume_ratio'] > 1.0:
            score -= 5
        else:
            score -= 2   # 缩量下跌，抛压较轻

    # 4. 近期涨幅 (10分) — 短线追涨动量
    if 0 < info['change_5d'] < 10:
        score += 10  # 温和上涨
    elif info['change_5d'] > 10:
        score += 5   # 涨太多有回调风险
    elif -5 < info['change_5d'] < 0:
        score += 3   # 小幅调整，可能企稳
    else:
        score -= 5   # 大跌中

    # 5. 位置 (10分) — 不追太高
    if info['distance_from_high'] > -5:
        score += 2   # 接近新高，追高风险
    elif info['distance_from_high'] > -15:
        score += 10  # 距新高有空间
    elif info['distance_from_high'] > -30:
        score += 5   # 较低位
    else:
        score -= 5   # 跌太深

    # 6. 基本面PE/PB (10分) — 估值共振加分
    pe_sig = info.get('pe_signal', 'N/A')
    pb_sig = info.get('pb_signal', 'N/A')
    
    if pe_sig == 'BUY':
        score += 5   # PE低估加分
    elif pe_sig == 'SELL':
        score -= 3   # PE高估扣分
    
    if pb_sig == 'BUY':
        score += 5   # PB低估加分
    elif pb_sig == 'SELL':
        score -= 3   # PB高估扣分

    # 7. 资金流信号 (8分) — 主力资金方向
    fund_flow = info.get('fund_flow_signal', 'neutral')
    if fund_flow == 'bullish':
        score += 8   # 主力净流入，强烈看多
    elif fund_flow == 'bearish':
        score -= 5   # 主力净流出，看空

    return round(score, 1)


# ============================================================
# 11 策略全量分析（与持仓分析一致）
# ============================================================

def load_cached_kline(code: str, cache_dir: str = None) -> pd.DataFrame:
    """从缓存加载K线数据"""
    if not cache_dir:
        cache_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'mydate', 'backtest_kline')
    cache_file = os.path.join(cache_dir, f'{code}.parquet')
    if os.path.exists(cache_file):
        try:
            df = pd.read_parquet(cache_file)
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
            return df
        except:
            pass
    return pd.DataFrame()


def update_kline_cache(code: str, cache_dir: str = None, days: int = 200) -> pd.DataFrame:
    """
    增量更新K线缓存：使用统一数据接口获取数据，合并本地缓存。
    
    缓存策略：
    - 缓存已是今日数据 → 直接返回（不重复请求）
    - 缓存是昨日收盘数据 + 当前在交易时间 → 调 provider.get_kline（会自动拼接今日盘中数据），
      但不写入缓存文件（盘中数据不完整，不应持久化）
    - 缓存超过1天以上 → 下载并更新缓存文件
    """
    from src.data.provider.data_provider import get_default_kline_provider

    cached_df = load_cached_kline(code, cache_dir)
    
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    is_weekday = now.weekday() < 5
    is_trading_hours = is_weekday and ((9, 15) <= (now.hour, now.minute) <= (15, 0))
    # 收盘后至次日凌晨：交易日15:00之后，缓存是昨天的，应当拉取今日收盘数据
    is_after_close = is_weekday and (now.hour, now.minute) > (15, 0)

    if not cached_df.empty and 'date' in cached_df.columns:
        last_date = pd.Timestamp(cached_df['date'].max())
        days_behind = (pd.Timestamp(now.date()) - last_date).days
        
        if days_behind == 0:
            # 已经有今日数据（收盘后写入），直接返回
            return cached_df
        
        if days_behind == 1 and not is_trading_hours and not is_after_close:
            # 昨收数据，且当前既不在盘中也不在收盘后（即周末/假日/非交易日深夜），直接用缓存
            return cached_df

    # 需要更新：下载最新数据
    provider = get_default_kline_provider()
    new_df = provider.get_kline(
                symbol=code,
        datalen=days,
        min_bars=1,
        retries=2,
        timeout=10,
    )

    if new_df is None or new_df.empty:
        logger.error(f"所有数据源均失败，使用缓存数据: {code}")
        return cached_df if not cached_df.empty else pd.DataFrame()
    
    if not cached_df.empty:
        combined = pd.concat([cached_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=['date'], keep='last')
        combined = combined.sort_values('date').reset_index(drop=True)
    else:
        combined = new_df
    
    # 盘中实时数据（最新行是今天）不写入缓存文件，避免覆盖昨日完整数据
    has_today = 'date' in combined.columns and combined['date'].max() >= pd.Timestamp(today_str)
    if is_trading_hours and has_today:
        return combined  # 仅在内存中使用，不落盘

    if not cache_dir:
        cache_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'mydate', 'backtest_kline')
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f'{code}.parquet')
    combined.to_parquet(cache_file, index=False)
    
    return combined


def load_fundamental_cache():
    """加载基本面缓存"""
    cache_file = os.path.join(os.path.dirname(__file__), '..', '..', 'mydate', 'market_fundamental_cache.json')
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        except:
            pass
    return {'date': '', 'all_data': {}}


def _preload_akshare_spot() -> pd.DataFrame:
    """预加载 AKShare 全市场实时行情（只调一次），失败返回空 DataFrame"""
    try:
        import akshare as ak
        from concurrent.futures import ThreadPoolExecutor as _TPE, TimeoutError as _FTE
        with _TPE(max_workers=1) as _ex:
            df = _ex.submit(ak.stock_zh_a_spot_em).result(timeout=20)
        if df is not None and not df.empty:
            print(f"✅ AKShare全市场行情预加载成功: {len(df)} 只")
            return df
    except Exception as e:
        print(f"⚠️ AKShare全市场行情预加载失败: {e}，将使用缓存数据")
    return pd.DataFrame()


def update_fundamental_cache(code: str, fetcher: FundamentalFetcher, cache_data: dict, spot_df: pd.DataFrame = None) -> dict:
    """
    增量更新单只股票的基本面数据（PE/PB/市值）
    
    多数据源降级逻辑：
    1. Baostock daily_basic（主力）
    2. 预加载的 AKShare 全市场行情 DataFrame 查表（备用，无网络请求）
    3. 返回缓存（如果以上都失败）
    """
    today = datetime.now().strftime('%Y-%m-%d')
    cache_date = cache_data.get('date', '')
    all_data = cache_data.get('all_data', {})
    
    if cache_date == today and code in all_data:
        return all_data[code]
    
    # 方案1: Baostock get_daily_basic（传入 spot_df 作为备用）
    try:
        fund_df = fetcher.get_daily_basic(code, start_date=today, end_date=today, spot_df=spot_df)
        if not fund_df.empty:
            fund_info = {
                'name': fund_df['name'].iloc[0] if 'name' in fund_df.columns else '',
                'pe_ttm': float(fund_df['pe_ttm'].iloc[0]) if 'pe_ttm' in fund_df.columns and pd.notna(fund_df['pe_ttm'].iloc[0]) else None,
                'pb': float(fund_df['pb'].iloc[0]) if 'pb' in fund_df.columns and pd.notna(fund_df['pb'].iloc[0]) else None,
                'market_cap_yi': float(fund_df['market_cap'].iloc[0]) / 100000000 if 'market_cap' in fund_df.columns and pd.notna(fund_df['market_cap'].iloc[0]) else None,
                'is_st': False
            }
            return fund_info
    except Exception as e:
        logger.debug(f"Baostock获取 {code} 基本面失败: {e}")
    
    # 方案2: 从预加载的全市场 DataFrame 查表（零网络开销）
    if spot_df is not None and not spot_df.empty:
        try:
            stock_row = spot_df[spot_df['代码'] == code]
            if not stock_row.empty:
                row = stock_row.iloc[0]
                fund_info = {
                    'name': row.get('名称', ''),
                    'pe_ttm': float(row['市盈率-动态']) if '市盈率-动态' in row and pd.notna(row['市盈率-动态']) else None,
                    'pb': float(row['市净率']) if '市净率' in row and pd.notna(row['市净率']) else None,
                    'market_cap_yi': float(row['总市值']) / 100000000 if '总市值' in row and pd.notna(row['总市值']) else None,
                    'is_st': 'ST' in str(row.get('名称', ''))
                }
                return fund_info
        except Exception:
            pass
    
    # 方案3: 返回缓存
    if code in all_data:
        return all_data[code]
    
    logger.warning(f"❌ 所有数据源均失败: {code}")
    return None


# ============================================================
# 全局策略实例（避免重复创建，性能优化）
# ============================================================
_GLOBAL_STRATEGIES = None

# 双引擎调度架构配置
# 均值回归引擎权重（原有策略，用于超跌反弹）
MR_WEIGHTS = {
    # 核心均值回归策略（高权重）
    'PB': 2.0, 'PE': 1.68, 'PEPB': 1.61, 'DUAL': 1.39,
    'BOLL': 1.95, 'RSI': 1.82, 'KDJ': 1.5,
    'NEWS': 0.32, 'SENTIMENT': 0.32, 'MONEY_FLOW': 0.3,
    
    # 技术确认因子（低权重，避免趋势信号主导超跌榜）
    'MACD': 0.5,  # 降权：原 1.13 → 0.5（技术确认作用）
    'MA': 0.3,    # 降权：原 0.88 → 0.3（技术确认作用）
}

# 趋势引擎配置
TREND_WEIGHT_BASE = 0.5       # 基础权重（无趋势时的最低权重）
TREND_WEIGHT_RANGE = 0.5      # 权重调整范围（趋势越强，权重越高）
TREND_SCORE_WEIGHT = 0.7      # 趋势得分权重
MOMENTUM_SCORE_WEIGHT = 0.3   # 动量得分权重
TREND_STRENGTH_THRESHOLD = 0.03  # 市场趋势强度阈值（MA20/MA60斜率）

# 兼容旧代码：保留原权重变量名
_GLOBAL_STRATEGY_WEIGHTS = MR_WEIGHTS


def get_index_data():
    """获取指数数据（沪深300）用于市场状态判断"""
    from src.data.provider.data_provider import get_default_kline_provider
    provider = get_default_kline_provider()
    for code in ['sh000300', '000300', 'CSI300']:
        try:
            df = provider.get_kline(code, datalen=200, min_bars=60, retries=1, timeout=8)
            if df is not None and not df.empty:
                return df
        except Exception:
            continue
    return pd.DataFrame()


def get_market_regime(index_df):
    """
    判断市场状态（趋势市 vs 震荡市）
    
    返回:
        regime: 'trend' 或 'range'
        strength: 趋势强度（MA20相对MA60的斜率）
    """
    if index_df.empty or len(index_df) < 60:
        return 'range', 0.0
    
    close = index_df['close']
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    
    if ma60.iloc[-1] == 0:
        return 'range', 0.0
    
    strength = (ma20.iloc[-1] - ma60.iloc[-1]) / ma60.iloc[-1]
    regime = 'trend' if strength > TREND_STRENGTH_THRESHOLD else 'range'
    
    return regime, strength


def _get_global_strategies():
    """
    获取全局策略实例（单例模式，避免重复创建）
    
    策略集合与 ensemble.py 保持一致（12策略 L3投票层）：
    - 技术面6个: MA, MACD, RSI, BOLL, KDJ, DUAL
    - 基本面3个: PE, PB, PEPB
    - 消息面1个: NEWS
    - 情绪面1个: SENTIMENT（全市场情绪Z-score + 个股趋势过滤）
    - 资金面1个: MONEY_FLOW
    
    注：
    - POLICY（政策事件）仅作L0大盘过滤器（_check_policy_filter），不参与投票
    """
    global _GLOBAL_STRATEGIES
    if _GLOBAL_STRATEGIES is None:
        from src.strategies.fundamental_pe_pb import PE_PB_CombinedStrategy
        _GLOBAL_STRATEGIES = {
            'MA': MACrossStrategy(),
            'MACD': MACDStrategy(),
            'RSI': RSIStrategy(),
            'BOLL': BollingerBandStrategy(),
            'KDJ': KDJStrategy(),
            'DUAL': DualMomentumSingleStrategy(),
            'PE': PEStrategy(),
            'PB': PBStrategy(),
            'PEPB': PE_PB_CombinedStrategy(),
            'NEWS': NewsSentimentStrategy(),
            'SENTIMENT': SentimentStrategy(),
            'MONEY_FLOW': MoneyFlowStrategy(),
        }
    return _GLOBAL_STRATEGIES


def run_full_12_analysis(code: str, name: str, sector: str, df: pd.DataFrame, fetcher: FundamentalFetcher, skip_industry: bool = False, index_df: pd.DataFrame = None) -> dict:
    """
    运行 12 大策略: MA, MACD, RSI, BOLL, KDJ, DUAL, PE, PB, PEPB, NEWS, SENTIMENT, MONEY_FLOW。
    返回 buy_count, sell_count, hold_count, score（买-卖加权）, signals 列表。
    
    Args:
        skip_industry: 是否跳过行业PE/PB查询（纯缓存模式用，避免网络请求）
        index_df: 指数数据（沪深300），避免重复获取
    
    优化:
        1. 使用全局策略实例（避免重复创建）
        2. DUAL策略信号反向（与ensemble.py保持一致）
        3. 基本面数据缺失时跳过PE/PB策略
        4. SENTIMENT使用全市场情绪数据 + 个股趋势过滤
    """
    tech_strategies = _get_global_strategies()
    strat_weights = _GLOBAL_STRATEGY_WEIGHTS
    
    # 为需要symbol的策略设置当前股票
    if 'NEWS' in tech_strategies:
        tech_strategies['NEWS'].symbol = code
    if 'MONEY_FLOW' in tech_strategies:
        tech_strategies['MONEY_FLOW'].symbol = code
    
    buy_count = sell_count = hold_count = 0
    weighted_buy = weighted_sell = 0.0
    signals = []
    score_sum = 0.0
    
    # 双引擎架构：分别计算均值回归得分和全策略得分
    mr_weighted_buy = mr_weighted_sell = 0.0
    mr_score_sum = 0.0
    
    # 定义均值回归策略集合（包含MA/MACD作为技术确认因子，但权重已降低）
    MR_STRATEGY_NAMES = {'PB', 'PE', 'PEPB', 'DUAL', 'BOLL', 'RSI', 'KDJ', 'MONEY_FLOW', 'NEWS', 'SENTIMENT', 'MA', 'MACD'}

    for strat_name, strat in tech_strategies.items():
        try:
            if len(df) < strat.min_bars:
                continue
            sig = strat.safe_analyze(df)
            
            # 【修复1】DUAL策略信号反向（与ensemble.py保持一致）
            if strat_name == 'DUAL':
                if sig.action == 'BUY':
                    sig.action = 'SELL'
                    sig.reason = f'[DUAL反向] {sig.reason}（原BUY→SELL）'
                elif sig.action == 'SELL':
                    sig.action = 'BUY'
                    sig.reason = f'[DUAL反向] {sig.reason}（原SELL→BUY）'
            
            w = strat_weights.get(strat_name, 1.0)
            
            # 全策略得分累加
            if sig.action == 'BUY':
                buy_count += 1
                weighted_buy += w
                score_sum += w * sig.confidence
            elif sig.action == 'SELL':
                sell_count += 1
                weighted_sell += w
                score_sum -= w * sig.confidence
            else:
                hold_count += 1
            
            # 均值回归得分累加（仅包含MR策略）
            if strat_name in MR_STRATEGY_NAMES:
                if sig.action == 'BUY':
                    mr_weighted_buy += w
                    mr_score_sum += w * sig.confidence
                elif sig.action == 'SELL':
                    mr_weighted_sell += w
                    mr_score_sum -= w * sig.confidence
            
            signals.append((strat_name, sig.action, sig.confidence, sig.reason[:40]))
        except Exception:
            pass

    # 【修复3】基本面数据验证：数据不足时跳过PE/PB/PEPB策略
    has_pe_data = 'pe_ttm' in df.columns and df['pe_ttm'].notna().sum() > 100
    has_pb_data = 'pb' in df.columns and df['pb'].notna().sum() > 100
    has_pepb_data = has_pe_data and has_pb_data
    
    # 获取行业PE/PB数据（用于行业分位数对比，总超时15s防止卡死）
    industry = None
    industry_pe_data = industry_pb_data = None
    
    if not skip_industry and (has_pe_data or has_pb_data):
        try:
            industry = fetcher.get_industry_classification(code)
            if industry:
                cninfo_data = fetcher.get_industry_pe_cninfo(industry)
                if cninfo_data:
                    pe_val = cninfo_data.get('pe_weighted') or cninfo_data.get('pe_median')
                    if pe_val and pe_val > 0:
                        industry_pe_data = pd.Series([pe_val] * 400)
        except Exception:
            pass

    # PE策略
    if has_pe_data:
        try:
            available_data = len(df[df['pe_ttm'].notna()])
            rolling_window = min(available_data, 756)
            pe_strat = PEStrategy(industry=industry, industry_pe_data=industry_pe_data, rolling_window=rolling_window) if industry and industry_pe_data is not None else PEStrategy(rolling_window=rolling_window)
            pe_strat.min_bars = max(100, available_data)
            if len(df) >= pe_strat.min_bars:
                pe_sig = pe_strat.safe_analyze(df)
                pe_w = strat_weights.get('PE', 1.68)
                if pe_sig.action == 'BUY':
                    buy_count += 1
                    weighted_buy += pe_w
                    score_sum += pe_w * pe_sig.confidence
                    mr_weighted_buy += pe_w
                    mr_score_sum += pe_w * pe_sig.confidence
                elif pe_sig.action == 'SELL':
                    sell_count += 1
                    weighted_sell += pe_w
                    score_sum -= pe_w * pe_sig.confidence
                    mr_weighted_sell += pe_w
                    mr_score_sum -= pe_w * pe_sig.confidence
                else:
                    hold_count += 1
                signals.append(('PE', pe_sig.action, pe_sig.confidence, pe_sig.reason[:40]))
        except Exception:
            pass

    # PB策略
    if has_pb_data:
        try:
            available_data = len(df[df['pb'].notna()])
            rolling_window = min(available_data, 756)
            
            # 跳过网络请求的ROE查询
            if skip_industry:
                roe_passes = False
            else:
                roe_passes, _, _ = fetcher.get_roe_for_filter(code)
            
            pb_strat = PBStrategy(industry=industry, industry_pb_data=industry_pb_data, min_roe=8.0 if roe_passes else 0, rolling_window=rolling_window) if industry and industry_pb_data is not None else PBStrategy(min_roe=8.0 if roe_passes else 0, rolling_window=rolling_window)
            pb_strat.min_bars = max(100, available_data)
            if len(df) >= pb_strat.min_bars:
                pb_sig = pb_strat.safe_analyze(df)
                pb_w = strat_weights.get('PB', 2.0)
                if pb_sig.action == 'BUY':
                    buy_count += 1
                    weighted_buy += pb_w
                    score_sum += pb_w * pb_sig.confidence
                    mr_weighted_buy += pb_w
                    mr_score_sum += pb_w * pb_sig.confidence
                elif pb_sig.action == 'SELL':
                    sell_count += 1
                    weighted_sell += pb_w
                    score_sum -= pb_w * pb_sig.confidence
                    mr_weighted_sell += pb_w
                    mr_score_sum -= pb_w * pb_sig.confidence
                else:
                    hold_count += 1
                signals.append(('PB', pb_sig.action, pb_sig.confidence, pb_sig.reason[:40]))
        except Exception:
            pass
    
    # 【修复4】PEPB双因子策略（与ensemble.py保持一致）
    if has_pepb_data:
        try:
            from src.strategies.fundamental_pe_pb import PE_PB_CombinedStrategy
            available_data = min(len(df[df['pe_ttm'].notna()]), len(df[df['pb'].notna()]))
            rolling_window = min(available_data, 756)
            
            # 跳过网络请求的ROE查询
            if skip_industry:
                roe_passes = False
            else:
                roe_passes, _, _ = fetcher.get_roe_for_filter(code)
            
            pepb_strat = PE_PB_CombinedStrategy(
                industry=industry, 
                industry_pe_data=industry_pe_data,
                industry_pb_data=industry_pb_data,
                min_roe=8.0 if roe_passes else 0,
                rolling_window=rolling_window
            ) if industry else PE_PB_CombinedStrategy(min_roe=8.0 if roe_passes else 0, rolling_window=rolling_window)
            pepb_strat.min_bars = max(100, available_data)
            
            if len(df) >= pepb_strat.min_bars:
                pepb_sig = pepb_strat.safe_analyze(df)
                pepb_w = strat_weights.get('PEPB', 1.61)
                if pepb_sig.action == 'BUY':
                    buy_count += 1
                    weighted_buy += pepb_w
                    score_sum += pepb_w * pepb_sig.confidence
                    mr_weighted_buy += pepb_w
                    mr_score_sum += pepb_w * pepb_sig.confidence
                elif pepb_sig.action == 'SELL':
                    sell_count += 1
                    weighted_sell += pepb_w
                    score_sum -= pepb_w * pepb_sig.confidence
                    mr_weighted_sell += pepb_w
                    mr_score_sum -= pepb_w * pepb_sig.confidence
                else:
                    hold_count += 1
                signals.append(('PEPB', pepb_sig.action, pepb_sig.confidence, pepb_sig.reason[:40]))
        except Exception:
            pass

    # 综合得分：加权买票 - 加权卖票 + confidence加权得分
    # 注：SENTIMENT 和 POLICY 不在此处投票，它们在 ensemble.py 的分层框架中使用
    score = round(weighted_buy * 2 - weighted_sell * 2 + score_sum, 2)
    
    # 均值回归得分（仅包含均值回归类策略，不含MA和MACD）
    mr_score = round(mr_weighted_buy * 2 - mr_weighted_sell * 2 + mr_score_sum, 2)
    close = df['close']
    volume = df['volume']
    price = float(close.iloc[-1])
    change_5d = (price / float(close.iloc[-6]) - 1) * 100 if len(df) > 5 else 0
    change_20d = (price / float(close.iloc[-21]) - 1) * 100 if len(df) > 20 else 0

    # 均线与趋势
    ma5 = float(close.iloc[-5:].mean())
    ma10 = float(close.iloc[-10:].mean()) if len(df) >= 10 else ma5
    ma20 = float(close.iloc[-20:].mean()) if len(df) >= 20 else ma5
    ma60 = float(close.iloc[-60:].mean()) if len(df) >= 60 else ma20
    if price > ma5 > ma20:
        trend = '多头排列↑'
    elif price < ma5 < ma20:
        trend = '空头排列↓'
    elif price > ma20:
        trend = '偏多↗'
    else:
        trend = '偏空↘'

    # 量比
    avg_vol_5 = float(volume.iloc[-6:-1].mean()) if len(df) > 5 else 1
    vol_ratio = float(volume.iloc[-1]) / avg_vol_5 if avg_vol_5 > 0 else 1

    # 60日高低点距离
    high_60 = float(close.iloc[-60:].max()) if len(df) >= 60 else float(close.max())
    low_60 = float(close.iloc[-60:].min()) if len(df) >= 60 else float(close.min())
    dist_high = (price / high_60 - 1) * 100
    dist_low = (price / low_60 - 1) * 100

    # PE/PB
    pe_ttm = float(df['pe_ttm'].iloc[-1]) if 'pe_ttm' in df.columns and pd.notna(df['pe_ttm'].iloc[-1]) else None
    pb_val = float(df['pb'].iloc[-1]) if 'pb' in df.columns and pd.notna(df['pb'].iloc[-1]) else None

    # 新增：计算趋势得分和动量得分（双引擎调度架构）
    trend_score = 0.0
    momentum_score = 0.0
    trend_weight = 0.0
    
    try:
        trend_strat = Trend_Composite()
        trend_df = trend_strat.generate_signals(df)
        if 'trend_score' in trend_df.columns and not trend_df.empty:
            trend_score = float(trend_df['trend_score'].iloc[-1])
    except Exception:
        pass
    
    try:
        mom_strat = Momentum_Adj()
        mom_df = mom_strat.generate_signals(df)
        if 'score' in mom_df.columns and not mom_df.empty:
            momentum_score = float(mom_df['score'].iloc[-1])
    except Exception:
        pass
    
    # 技术确认因子（Phase 1增强）
    tech_confirm_score = 0.0
    try:
        tech_strat = TechnicalConfirmation()
        tech_df = tech_strat.generate_signals(df)
        if 'tech_confirm_score' in tech_df.columns and not tech_df.empty:
            tech_confirm_score = float(tech_df['tech_confirm_score'].iloc[-1])
    except Exception:
        pass
    
    # 量价配合因子（Phase 2增强）
    volume_confirm_score = 0.0
    try:
        vol_strat = VolumeConfirmation()
        vol_df = vol_strat.generate_signals(df)
        if 'volume_confirm_score' in vol_df.columns and not vol_df.empty:
            volume_confirm_score = float(vol_df['volume_confirm_score'].iloc[-1])
    except Exception:
        pass
    
    # 相对强度因子（Phase 2增强）
    relative_strength_score = 0.0
    try:
        # 使用传入的指数数据（避免重复获取）
        rs_strat = RelativeStrength()
        rs_df = rs_strat.generate_signals(df, index_df=index_df, sector_df=None)
        if 'relative_strength_score' in rs_df.columns and not rs_df.empty:
            relative_strength_score = float(rs_df['relative_strength_score'].iloc[-1])
    except Exception:
        pass
    
    trend_weight = max(0.0, min(1.0, trend_score))

    return {
        'code': code,
        'name': name,
        'sector': sector,
        'buy_count': buy_count,
        'sell_count': sell_count,
        'hold_count': hold_count,
        'score': score,  # 全策略综合得分（含MA/MACD）
        'mr_score': mr_score,  # 均值回归得分（仅含PB/PE/PEPB/DUAL/BOLL/RSI/KDJ/MONEY_FLOW/NEWS/SENTIMENT）
        'price': price,
        'change_5d': round(change_5d, 2),
        'change_20d': round(change_20d, 2),
        'signals': signals,
        'trend': trend,
        'volume_ratio': round(vol_ratio, 2),
        'ma5': round(ma5, 2),
        'ma10': round(ma10, 2),
        'ma20': round(ma20, 2),
        'ma60': round(ma60, 2),
        'dist_high': round(dist_high, 2),
        'dist_low': round(dist_low, 2),
        'pe_ttm': pe_ttm,
        'pb': pb_val,
        # 双引擎调度架构新增字段
        'trend_score': round(trend_score, 3),
        'momentum_score': round(momentum_score, 3),
        'trend_weight': round(trend_weight, 3),
        'tech_confirm_score': round(tech_confirm_score, 3),  # Phase 1增强：技术确认因子
        'volume_confirm_score': round(volume_confirm_score, 3),  # Phase 2增强：量价配合
        'relative_strength_score': round(relative_strength_score, 3),  # Phase 2增强：相对强度
    }


# ============================================================
# 主逻辑
# ============================================================

def _check_policy_filter() -> dict:
    """
    检查政策面大盘过滤状态。
    返回 dict:
        blocked   bool   是否阻止选股
        score     float  政策情感分 [-1, 1]
        reason    str    说明
    """
    try:
        from src.data.policy import get_policy_sentiment_v33
        result = get_policy_sentiment_v33(max_news=15, use_llm=True)
        if result is None:
            return {'blocked': False, 'score': 0.0, 'reason': '政策面数据获取失败，跳过过滤'}
        agg_score, has_major_neg, avg_inf = result
        # 极度利空：综合分 < -0.5 且 存在重大利空关键词
        if agg_score < -0.5 and has_major_neg:
            return {
                'blocked': True,
                'score': agg_score,
                'reason': f'政策面极度利空(score={agg_score:.2f}, 重大利空关键词触发)，建议暂停选股',
            }
        # 较强利空：综合分 < -0.35
        if agg_score < -0.35:
            return {
                'blocked': False,
                'score': agg_score,
                'reason': f'政策面偏利空(score={agg_score:.2f})，建议提高选股门槛',
                'warn': True,
            }
        return {'blocked': False, 'score': agg_score, 'reason': f'政策面正常(score={agg_score:.2f})'}
    except Exception as e:
        return {'blocked': False, 'score': 0.0, 'reason': f'政策面过滤异常({e})，跳过'}


def main():
    parser = argparse.ArgumentParser(description='每日选股推荐')
    parser.add_argument('--pool', type=str, default='stock_pool_all.json',
                        help='股票池（默认综合大池 stock_pool_all.json，约860只，每日选股只从此池选取）')
    parser.add_argument('--max-pool', type=int, default=0, help='最多扫描池内前 N 只（0=全部）')
    parser.add_argument('--strategy', type=str, default='ensemble',
                        choices=['macd', 'ensemble', 'full_11', 'full_12'],
                        help='策略: macd | ensemble(12策略固定权重，推荐) | full_11/full_12(同ensemble，兼容命令)')
    parser.add_argument('--cache-only', action='store_true', default=False,
                        help='纯缓存模式：只使用本地缓存，不发起任何网络请求（适合API限流时）')
    parser.add_argument('--fast', type=int, default=12, help='MACD快线(仅macd模式)')
    parser.add_argument('--slow', type=int, default=30, help='MACD慢线(仅macd模式)')
    parser.add_argument('--signal', type=int, default=9, help='MACD信号线(仅macd模式)')
    parser.add_argument('--top', type=int, default=20, help='推荐TOP N只')
    parser.add_argument('--fundamental', action='store_true', default=True,
                        help='启用基本面分析(PE/PB)')
    parser.add_argument('--no-policy-filter', action='store_true', default=False,
                        help='跳过政策面大盘过滤（强制执行选股）')
    parser.add_argument('--only-holdings', action='store_true', default=False,
                        help='只分析持仓：不跑股票池扫描，仅用最新数据分析持仓并更新报告')
    parser.add_argument('--append-sectors', action='store_true', default=False,
                        help='在主报告后追加专题板块推荐（如核电+算电协同）')
    parser.add_argument('--force-version', type=str, default=None,
                        choices=['v5.2', 'v6.1'],
                        help='强制使用指定版本（v5.2或v6.1），None则根据IC自动选择')
    args = parser.parse_args()

    # 优先使用 mydate 目录，如果不存在则使用 data 目录
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pool_file = os.path.join(base_dir, 'mydate', args.pool)
    if not os.path.exists(pool_file):
        pool_file = os.path.join(base_dir, 'data', args.pool)
    if not os.path.exists(pool_file):
        pool_file = args.pool
    stocks = load_stock_pool(pool_file, max_count=args.max_pool if args.max_pool > 0 else 0)

    today = datetime.now().strftime('%Y-%m-%d')

    # ========== 仅持仓分析模式 ==========
    if args.only_holdings:
        holdings = _load_portfolio()
        if not holdings:
            print("⚠️ 无持仓，退出")
            return
        print(f"{'='*70}")
        print(f"📌 仅持仓分析 — {today}（使用日内最新/收盘数据）")
        print(f"{'='*70}")

        from src.data.provider.data_provider import get_default_kline_provider
        provider = get_default_kline_provider()
        fetcher = FundamentalFetcher()

        # 获取指数数据（全局共享）
        print("\n📊 获取指数数据（沪深300）...")
        index_df = None
        try:
            from src.data.fetchers.data_prefetch import fetch_stock_daily
            index_df = fetch_stock_daily('000300', datalen=800)
            if index_df is not None and not index_df.empty:
                print(f"✅ 指数数据获取成功: {len(index_df)} 条")
            else:
                print("⚠️ 指数数据为空，相对强度因子将失效")
        except Exception as e:
            print(f"⚠️ 指数数据获取失败: {e}，相对强度因子将失效")

        # 只为持仓拉取最新数据并分析（避免跑 808 只）
        full_results = []
        for h in holdings:
            code = h.get("code", "")
            name = h.get("name", "")
            if not code:
                continue
            try:
                df = provider.get_kline(symbol=code, datalen=200, min_bars=60, retries=2, timeout=10)
                if df is None or df.empty or len(df) < 60:
                    # ETF/个别标的可能无日K，持仓区仍可用 spot 价，但策略分析需要日K，失败则跳过分析
                    continue
                r = run_full_12_analysis(code, name, "", df, fetcher, skip_industry=True, index_df=index_df)
                if r:
                    full_results.append(r)
            except Exception:
                continue

        # 仅更新报告中的“持仓区块”和“持仓建议”，不影响历史累计内容结构
        try:
            report_path, archive_path = save_incremental_report(
                today=today,
                top_list=[],
                all_results=full_results,
                strategy_name="仅持仓分析(12策略)",
                pool_size=0,
                valid_count=len(full_results),
                holdings_only=True,
            )
            print(f"\n📝 持仓报告已更新: {report_path}")
            print(f"📝 当日归档已保存: {archive_path}")
        except Exception as e:
            print(f"\n⚠️ 更新报告失败: {e}")
        return

    # ========= 政策面大盘过滤 =========
    policy_result = {'blocked': False, 'score': 0.0, 'reason': '未启用政策面过滤'}
    if not args.no_policy_filter:
        print("🔍 检查政策面大盘环境...")
        policy_result = _check_policy_filter()
        score_str = f"{policy_result['score']:+.2f}"
        if policy_result['blocked']:
            print(f"\n🚫 【大盘过滤】{policy_result['reason']}")
            print("   如需强制执行选股，请添加 --no-policy-filter 参数")
            return
        elif policy_result.get('warn'):
            print(f"⚠️  【政策预警】{policy_result['reason']}")
            print("   继续选股，但建议降低仓位、提高确定性要求\n")
        else:
            print(f"✅ 政策面: {policy_result['reason']}\n")

    # ---------- 12 策略全量模式 ----------
    if args.strategy in ['full_11', 'full_12']:
        strategy_name = '12大策略(MA|MACD|RSI|BOLL|KDJ|DUAL|PE|PB|PEPB|NEWS|SENTIMENT|MONEY_FLOW)'
        print(f"{'='*70}")
        print(f"📈 每日选股推荐 — {today} [全策略+大池]")
        print(f"{'='*70}")
        print(f"📌 策略: {strategy_name}")
        print(f"📌 股票池: {len(stocks)} 只")
        print(f"📌 推荐TOP: {args.top} 只")
        print()
        
        # 检查缓存
        cache_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'mydate', 'backtest_kline')
        use_kline_cache = os.path.exists(cache_dir)
        fundamental_cache = load_fundamental_cache()
        
        if use_kline_cache:
            cached_files = [f[:-8] for f in os.listdir(cache_dir) if f.endswith('.parquet')]
            print(f"✅ K线缓存: {len(cached_files)}只")
        
        cache_date = fundamental_cache.get('date', '')
        all_fund_data = fundamental_cache.get('all_data', {})
        today = datetime.now().strftime('%Y-%m-%d')
        
        if cache_date == today:
            print(f"✅ 基本面缓存: {len(all_fund_data)}只（今日最新）")
        elif cache_date:
            print(f"✅ 基本面缓存: {len(all_fund_data)}只（{cache_date}，将增量更新）")
        else:
            print(f"⚠️  基本面缓存: 无缓存，将全量获取")
        
        fetcher = FundamentalFetcher()
        full_results = []
        fail_count = 0
        
        # ========== 阶段1: 串行获取数据（baostock 非线程安全） ==========
        spot_df = pd.DataFrame()
        if not args.cache_only:
            print("📡 预加载全市场行情数据...")
            spot_df = _preload_akshare_spot()
        
        print(f"\n📊 阶段1: 串行获取数据 ({len(stocks)} 只)...")
        prepared_stocks = []
        data_fail = 0
        for i, stock_info in enumerate(stocks):
            code = stock_info.get('code') or stock_info.get('symbol', '')
            name = stock_info.get('name', '')
            sector = stock_info.get('sector', '')
            if not code:
                data_fail += 1
                continue
            
            # 过滤ST股票（风险高、涨跌幅限制不同）
            if is_st_stock(name):
                data_fail += 1
                continue
            
            if args.cache_only:
                df = load_cached_kline(code, cache_dir) if use_kline_cache else pd.DataFrame()
            else:
                try:
                    df = update_kline_cache(code, cache_dir, days=200)
                except Exception:
                    df = load_cached_kline(code, cache_dir) if use_kline_cache else pd.DataFrame()
            
            if df.empty or len(df) < 60:
                data_fail += 1
                if (i + 1) % 100 == 0:
                    print(f"\r  数据获取: {i+1}/{len(stocks)}", end='', flush=True)
                continue
            
            if args.cache_only:
                all_data = fundamental_cache.get('all_data', {})
                fund_data = all_data.get(code)
            else:
                fund_data = update_fundamental_cache(code, fetcher, fundamental_cache, spot_df)
            
            if fund_data:
                if 'pe_ttm' not in df.columns:
                    df['pe_ttm'] = None
                if 'pb' not in df.columns:
                    df['pb'] = None
                if 'market_cap' not in df.columns:
                    df['market_cap'] = None
                
                df.loc[df.index[-1], 'pe_ttm'] = fund_data.get('pe_ttm')
                df.loc[df.index[-1], 'pb'] = fund_data.get('pb')
                df.loc[df.index[-1], 'market_cap'] = fund_data.get('market_cap_yi', 0) * 100000000 if fund_data.get('market_cap_yi') else None
                df['pe_ttm'] = df['pe_ttm'].ffill()
                df['pb'] = df['pb'].ffill()
                df['market_cap'] = df['market_cap'].ffill()
            
            prepared_stocks.append((code, name, sector, df))
            
            if (i + 1) % 100 == 0:
                print(f"\r  数据获取: {i+1}/{len(stocks)} (有效{len(prepared_stocks)})", end='', flush=True)
        
        try:
            import baostock as bs
            bs.logout()
        except Exception:
            pass
        fetcher._bs_logout()
        
        print(f"\n✅ 数据获取完成: {len(prepared_stocks)}只有效, {data_fail}只跳过")
        
        # ========== 获取指数数据（全局共享，避免重复请求） ==========
        print("\n📊 获取指数数据（沪深300）...")
        index_df = None
        try:
            from src.data.fetchers.data_prefetch import fetch_stock_daily
            index_df = fetch_stock_daily('000300', datalen=800)
            if index_df is not None and not index_df.empty:
                print(f"✅ 指数数据获取成功: {len(index_df)} 条")
            else:
                print("⚠️ 指数数据为空，相对强度因子将失效")
        except Exception as e:
            print(f"⚠️ 指数数据获取失败: {e}，相对强度因子将失效")
        
        # ========== 阶段2: 多线程并行策略分析（纯CPU计算） ==========
        max_workers = 8
        print(f"\n🚀 阶段2: {max_workers}线程并行策略分析...\n")
        
        def analyze_stock(item):
            code, name, sector, df = item
            try:
                return run_full_12_analysis(code, name, sector, df, fetcher, skip_industry=True, index_df=index_df)
            except Exception:
                return None
        
        completed = 0
        analysis_timeout = 1200
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(analyze_stock, item): item for item in prepared_stocks}
            try:
                for future in as_completed(futures, timeout=analysis_timeout):
                    completed += 1
                    if completed % 50 == 0 or completed == len(prepared_stocks):
                        pct = completed / len(prepared_stocks) * 100
                        bar = '█' * int(pct / 2) + '░' * (50 - int(pct / 2))
                        print(f"\r  [{bar}] {completed}/{len(prepared_stocks)} ({pct:.0f}%)", end='', flush=True)
                    try:
                        result = future.result(timeout=0)
                        if result:
                            full_results.append(result)
                        else:
                            fail_count += 1
                    except Exception:
                        fail_count += 1
            except TimeoutError:
                not_done = sum(1 for f in futures if not f.done())
                fail_count += not_done
                print(f"\n⏱️  策略分析总超时({analysis_timeout}s)，{not_done}只未完成")
        if fail_count:
            print(f"\n⚠️  {fail_count} 只数据不足或失败，已跳过")
        if not full_results:
            print("\n⚠️ 无有效分析结果")
            return

        # ========== 双引擎调度架构 v6.1：均值回归 + 趋势引擎（机构级修复版） ==========
        df_scores = pd.DataFrame(full_results)
        df_scores.set_index('code', inplace=True)
        
        # 确保有趋势列和mr_score列
        for col in ['trend_score', 'momentum_score', 'trend_weight', 'mr_score', 
                    'tech_confirm_score', 'volume_confirm_score', 'relative_strength_score']:
            if col not in df_scores.columns:
                df_scores[col] = 0.0
        
        # 软过滤调整得分（趋势越强，均值回归得分权重越高）
        # 【修复】使用mr_score（仅均值回归策略）而非score（全策略）
        df_scores['trend_weight'] = np.clip(df_scores['trend_score'], 0, 1)
        df_scores['adjusted_mr_score'] = df_scores['mr_score'] * (TREND_WEIGHT_BASE + TREND_WEIGHT_RANGE * df_scores['trend_weight'])
        
        # ========== 混合策略：根据IC动态选择v5.2/v6.1 ==========
        print("\n🔀 混合策略：根据IC选择版本...")
        from src.strategies.hybrid_selector import HybridVersionSelector
        
        selector = HybridVersionSelector(
            ic_threshold_base=0.20,
            ic_threshold_rs=0.15,
            ic_cache_file='results/factor_ic_monitoring.json'
        )
        
        decision = selector.select_version(force_version=args.force_version)
        selector.log_decision(decision)
        
        selected_version = decision['version']
        selected_weights = decision['weights']
        
        print(f"   ✅ 选择版本: {selected_version}")
        print(f"   原因: {decision['reason']}")
        print(f"   权重: {selected_weights}")
        
        if decision['ic_status']:
            print(f"   IC状态: base_trend={decision['ic_status']['base_trend_ic']:.3f}, "
                  f"rs={decision['ic_status']['relative_strength_ic']:.3f}")
        
        # ========== v6.1 修复1: 因子正交化（Factor Orthogonalization） ==========
        use_v6_1 = (selected_version == 'v6.1')
        
        if use_v6_1:
            print("\n🔧 v6.1修复: 因子正交化...")
            from src.factors.orthogonalization import FactorOrthogonalizer
        else:
            print("\n📌 使用v5.2（固定权重，无正交化）...")
        
        # 计算base_trend
        base_trend_calc = (TREND_SCORE_WEIGHT * df_scores['trend_score'] +
                          MOMENTUM_SCORE_WEIGHT * df_scores['momentum_score'])
        
        # 准备因子数据
        factor_df = pd.DataFrame({
            'base_trend': base_trend_calc,
            'tech_confirm': df_scores['tech_confirm_score'],
            'relative_strength': df_scores['relative_strength_score'],
            'volume_confirm': df_scores['volume_confirm_score']
        })
        
        # 根据版本选择处理方式
        if use_v6_1:
            # v6.1: 正交化
            orthogonalizer = FactorOrthogonalizer(method='sequential')
            try:
                orthogonal_factors = orthogonalizer.fit_transform(factor_df)
                
                # 诊断
                diag = orthogonalizer.diagnose(factor_df, orthogonal_factors)
                print(f"   正交化前平均相关性: {diag['avg_corr_before']:.3f}")
                print(f"   正交化后平均相关性: {diag['avg_corr_after']:.3f}")
                print(f"   改善: {diag['improvement_pct']:.1f}%")
                
                # 使用正交化后的因子
                df_scores['base_trend_orth'] = orthogonal_factors['base_trend']
                df_scores['tech_confirm_orth'] = orthogonal_factors['tech_confirm']
                df_scores['relative_strength_orth'] = orthogonal_factors['relative_strength']
                df_scores['volume_confirm_orth'] = orthogonal_factors['volume_confirm']
            except Exception as e:
                print(f"   ⚠️ 正交化失败: {e}，使用原始因子")
                df_scores['base_trend_orth'] = factor_df['base_trend']
                df_scores['tech_confirm_orth'] = factor_df['tech_confirm']
                df_scores['relative_strength_orth'] = factor_df['relative_strength']
                df_scores['volume_confirm_orth'] = factor_df['volume_confirm']
        else:
            # v5.2: 不正交化，直接使用原始因子
            df_scores['base_trend_orth'] = factor_df['base_trend']
            df_scores['tech_confirm_orth'] = factor_df['tech_confirm']
            df_scores['relative_strength_orth'] = factor_df['relative_strength']
            df_scores['volume_confirm_orth'] = factor_df['volume_confirm']
        
        # ========== v6.1 修复4: Soft Regime Score（连续市场状态） ==========
        if use_v6_1:
            print("\n🌐 v6.1修复: Soft Regime Score...")
            from src.strategies.market_regime_v6 import SoftRegimeDetector
            
            try:
                index_df = get_index_data()
                if index_df.empty or 'close' not in index_df.columns:
                    raise ValueError("指数数据为空或缺少close列")
                
                regime_detector = SoftRegimeDetector(trend_weight=0.6, vol_weight=0.4)
                regime_score = regime_detector.calc_regime_score(index_df)
                regime_features = regime_detector.get_regime_features(index_df)
                
                print(f"   Regime Score: {regime_score:.3f}")
                print(f"   趋势强度: {regime_features['trend_strength']:+.3f}")
                print(f"   波动率: {regime_features['volatility']:.3f}")
                
                # 动态权重（连续过渡）
                dynamic_weights = regime_detector.get_dynamic_weights(regime_score)
                print(f"   动态权重: base={dynamic_weights[0]:.2f}, tech={dynamic_weights[1]:.2f}, rs={dynamic_weights[2]:.2f}, vol={dynamic_weights[3]:.2f}")
            except Exception as e:
                print(f"   ⚠️ Regime Score计算失败: {e}，使用默认值")
                regime_score = 0.0
                dynamic_weights = selected_weights
                print(f"   降级为固定权重: base={dynamic_weights[0]:.2f}, tech={dynamic_weights[1]:.2f}, rs={dynamic_weights[2]:.2f}, vol={dynamic_weights[3]:.2f}")
        else:
            # v5.2: 使用固定权重
            regime_score = 0.0
            dynamic_weights = selected_weights
            print(f"   固定权重: base={dynamic_weights[0]:.2f}, tech={dynamic_weights[1]:.2f}, rs={dynamic_weights[2]:.2f}, vol={dynamic_weights[3]:.2f}")
        
        # 根据regime_score决定选股数量（连续）
        if regime_score > 0.5:
            mr_n, trend_n = 10, 10  # 强趋势市
        elif regime_score > 0:
            mr_n, trend_n = 12, 7   # 偏趋势市
        else:
            mr_n, trend_n = 15, 5   # 震荡市
        
        # 超跌榜（均值回归引擎）- 使用adjusted_mr_score
        mr_list = df_scores.nlargest(mr_n, 'adjusted_mr_score').index.tolist()
        
        # ========== 趋势质量得分（根据版本选择） ==========
        print(f"\n📊 计算趋势质量得分（{selected_version}）...")
        
        # 使用正交化后的因子 + 动态权重
        raw_trend_scores = {}
        for code in df_scores.index:
            # 线性组合（使用动态权重）
            linear = (dynamic_weights[0] * df_scores.loc[code, 'base_trend_orth'] +
                      dynamic_weights[1] * df_scores.loc[code, 'tech_confirm_orth'] +
                      dynamic_weights[2] * df_scores.loc[code, 'relative_strength_orth'] +
                      dynamic_weights[3] * df_scores.loc[code, 'volume_confirm_orth'])
            
            # 门控交互（仅v6.1启用）
            if use_v6_1 and df_scores.loc[code, 'base_trend_orth'] > 0:
                interaction = (df_scores.loc[code, 'base_trend_orth'] *
                              df_scores.loc[code, 'volume_confirm_orth'] * 0.1)
                linear += interaction
            
            raw_trend_scores[code] = linear
        
        raw_trend_scores_series = pd.Series(raw_trend_scores)
        
        # ========== v6.1 修复2: Rank Normalization（稳定化） ==========
        if use_v6_1:
            print("\n📏 v6.1修复: Rank Normalization...")
            from src.factors.normalization import RankNormalizer
            
            normalizer = RankNormalizer(method='percentile')
            normalized_trend_scores = normalizer.transform(raw_trend_scores_series)
            
            print(f"   得分范围: [{normalized_trend_scores.min():.3f}, {normalized_trend_scores.max():.3f}]")
        else:
            # v5.2: 使用tanh压缩
            normalized_trend_scores = raw_trend_scores_series.apply(np.tanh)
            print(f"   得分范围: [{normalized_trend_scores.min():.3f}, {normalized_trend_scores.max():.3f}]")
        
        # 保存到df_scores
        df_scores['trend_rank_score'] = normalized_trend_scores
        
        # 趋势榜（趋势引擎，不去重，允许双优股票重复出现）
        trend_list = df_scores.nlargest(trend_n, 'trend_rank_score').index.tolist()
        
        # 识别双优股票（既在超跌榜又在趋势榜）
        dual_advantage_stocks = [code for code in mr_list if code in trend_list]
        
        # 合并推荐（保留重复，双优股票会出现两次）
        final_recommend = mr_list + trend_list
        if len(final_recommend) < args.top:
            remaining = df_scores[~df_scores.index.isin(final_recommend)].nlargest(args.top - len(final_recommend), 'score').index.tolist()
            final_recommend.extend(remaining)
        final_recommend = final_recommend[:args.top]
        
        # ========== v6.1 修复3: Volatility Scaling（风险调整权重） ==========
        if use_v6_1:
            print("\n⚖️  v6.1修复: Volatility Scaling...")
            from src.portfolio.risk_scaling import VolatilityScaler
            
            # 构建stock_data字典（从prepared_stocks）
            stock_data = {}
            for code, name, sector, df in prepared_stocks:
                stock_data[code] = df
            
            # 计算个股波动率
            vol_scaler = VolatilityScaler(target_vol=0.15, lookback=60)
            vol_dict = {}
            for code in final_recommend:
                if code in stock_data:
                    vol_dict[code] = vol_scaler.calc_volatility(stock_data[code])
                else:
                    # 如果没有数据，使用默认波动率
                    vol_dict[code] = 0.20
        else:
            # v5.2: 不使用波动率调整
            vol_dict = {code: 0.20 for code in final_recommend}
        
        # 初始权重（基于得分）
        raw_weights = {}
        score_sum = sum(df_scores.loc[c, 'trend_rank_score'] if c in df_scores.index else 0 for c in final_recommend)
        if score_sum > 0:
            for code in final_recommend:
                if code in df_scores.index:
                    raw_weights[code] = df_scores.loc[code, 'trend_rank_score'] / score_sum
                else:
                    raw_weights[code] = 1.0 / len(final_recommend)
        else:
            # 等权
            for code in final_recommend:
                raw_weights[code] = 1.0 / len(final_recommend)
        
        # 波动率调整（仅v6.1）
        if use_v6_1:
            from src.portfolio.risk_scaling import VolatilityScaler
            vol_scaler = VolatilityScaler(target_vol=0.15, lookback=60)
            risk_adjusted_weights = vol_scaler.scale_weights(raw_weights, vol_dict)
            
            # 目标波动率调整（可选）
            final_weights, leverage = vol_scaler.target_volatility_scaling(
                risk_adjusted_weights, vol_dict, current_capital=1000000
            )
            
            print(f"   组合杠杆: {leverage:.2f}x")
            print(f"   平均波动率: {np.mean([v for v in vol_dict.values() if not np.isnan(v)]):.2%}")
        else:
            # v5.2: 不调整波动率
            final_weights = raw_weights
            leverage = 1.0
            print(f"   使用原始权重（无波动率调整）")
        
        # 构建 top_list（用于报告）
        top_list = []
        for code in final_recommend:
            if code in df_scores.index:
                # 从原始 full_results 中找到完整数据
                orig_data = next((r for r in full_results if r['code'] == code), None)
                if orig_data:
                    # 添加风险调整权重信息
                    orig_data['volatility'] = vol_dict.get(code, np.nan)
                    orig_data['raw_weight'] = raw_weights.get(code, 0)
                    orig_data['risk_weight'] = final_weights.get(code, 0)
                    top_list.append(orig_data)
        
        # 输出市场状态和榜单统计
        regime_label = "强趋势" if regime_score > 0.5 else ("偏趋势" if regime_score > 0 else "震荡")
        print(f"\n\n🌐 市场状态: {regime_label} (Regime Score={regime_score:.3f}) | 使用版本: {selected_version} | 超跌榜{len(mr_list)}只 | 趋势榜{len(trend_list)}只 | ⭐双优{len(dual_advantage_stocks)}只")
        
        # 双优股票特别提示
        if dual_advantage_stocks:
            print(f"\n{'='*90}")
            print(f"⭐⭐⭐ 双优股票（既超跌又趋势强，黄金标的，重点关注！）")
            print(f"{'='*90}")
            for code in dual_advantage_stocks:
                r = df_scores.loc[code]
                orig_data = next((x for x in full_results if x['code'] == code), None)
                if orig_data:
                    mr_rank = mr_list.index(code) + 1
                    trend_rank = trend_list.index(code) + 1
                    print(f"  {code} {orig_data['name']:>10} | MR得分={r['mr_score']:>6.1f}(超跌榜第{mr_rank}) | 趋势={r['trend_score']:>+5.2f}(趋势榜第{trend_rank}) | 价格¥{orig_data['price']:.2f}")
            print(f"{'='*90}\n")
        
        print(f"\n{'='*95}")
        print(f"🔥 双引擎调度推荐 TOP {len(top_list)}（超跌反弹 + 趋势跟随）")
        print(f"{'='*95}")
        print(f"{'类型':>6} {'排名':>4} {'代码':>8} {'名称':>10} {'价格':>8} {'MR得分':>7} {'趋势':>6} {'买':>3} {'卖':>3} {'5日%':>7} {'20日%':>7} {'板块'}")
        print("-" * 95)
        
        # 标注股票类型
        for rank, r in enumerate(top_list, 1):
            code = r['code']
            if code in dual_advantage_stocks:
                stock_type = "⭐双优"
            elif code in mr_list:
                stock_type = "🟢超跌"
            else:
                stock_type = "🔵趋势"
            
            mr_score_val = r.get('mr_score', r['score'])
            trend_val = r.get('trend_score', 0)
            
            print(f"{stock_type:>6} {rank:>4} {r['code']:>8} {r['name']:>10} {r['price']:>8.2f} "
                  f"{mr_score_val:>7.1f} {trend_val:>+6.2f} "
                  f"{r['buy_count']:>3} {r['sell_count']:>3} "
                  f"{r['change_5d']:>+7.2f} {r['change_20d']:>+7.2f} {str(r['sector'])[:12]}")
        print("-" * 95)
        print("\n📋 策略信号明细（TOP3）:")
        for rank, r in enumerate(top_list[:3], 1):
            print(f"\n  {rank}. {r['code']} {r['name']} (得分 {r['score']:.1f}, 买{r['buy_count']}/卖{r['sell_count']}/观{r['hold_count']})")
            for sn, action, conf, reason in r['signals']:
                em = '🟢' if action == 'BUY' else ('🔴' if action == 'SELL' else '⚪')
                print(f"      {sn:>12} {em} {action:>4} {conf:.0%} {reason[:45]}")
        
        # ========== 专题板块分析（如果启用） ==========
        sector_results_map = {}
        if args.append_sectors:
            print(f"\n{'='*70}")
            print(f"🔋 专题板块分析")
            print(f"{'='*70}")
            from tools.analysis.generate_sector_themes import SECTOR_THEMES, load_stock_pool_for_theme
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            
            for theme_key, theme_config in SECTOR_THEMES.items():
                print(f"\n📊 分析专题: {theme_config['name']}")
                theme_stocks = load_stock_pool_for_theme(theme_key, base_dir)
                if not theme_stocks:
                    print(f"  ⚠️ 股票池为空，跳过")
                    continue
                
                print(f"  股票池: {len(theme_stocks)} 只")
                theme_prepared = []
                for stock_info in theme_stocks:
                    code = stock_info.get('code', '')
                    name = stock_info.get('name', '')
                    sector = stock_info.get('sector', theme_config['name'])
                    if not code:
                        continue
                    
                    if is_st_stock(name):
                        continue
                    
                    # 使用缓存数据（避免重复请求）
                    df = load_cached_kline(code, cache_dir) if use_kline_cache else pd.DataFrame()
                    if df.empty or len(df) < 60:
                        continue
                    
                    # 使用缓存的基本面数据
                    all_data = fundamental_cache.get('all_data', {})
                    fund_data = all_data.get(code)
                    if fund_data:
                        if 'pe_ttm' not in df.columns:
                            df['pe_ttm'] = None
                        if 'pb' not in df.columns:
                            df['pb'] = None
                        if 'market_cap' not in df.columns:
                            df['market_cap'] = None
                        
                        df.loc[df.index[-1], 'pe_ttm'] = fund_data.get('pe_ttm')
                        df.loc[df.index[-1], 'pb'] = fund_data.get('pb')
                        df.loc[df.index[-1], 'market_cap'] = fund_data.get('market_cap_yi', 0) * 100000000 if fund_data.get('market_cap_yi') else None
                        df['pe_ttm'] = df['pe_ttm'].ffill()
                        df['pb'] = df['pb'].ffill()
                        df['market_cap'] = df['market_cap'].ffill()
                    
                    theme_prepared.append((code, name, sector, df))
                
                if not theme_prepared:
                    print(f"  ⚠️ 无有效数据，跳过")
                    continue
                
                # 分析专题股票
                theme_results = []
                for code, name, sector, df in theme_prepared:
                    try:
                        result = run_full_12_analysis(code, name, sector, df, fetcher, skip_industry=True, index_df=index_df)
                        if result:
                            theme_results.append(result)
                    except Exception:
                        pass
                
                if theme_results:
                    theme_results.sort(key=lambda x: x['score'], reverse=True)
                    sector_results_map[theme_key] = theme_results
                    print(f"  ✅ 完成分析: {len(theme_results)} 只有效")
                    # 显示TOP3
                    for i, r in enumerate(theme_results[:3], 1):
                        print(f"    {i}. {r['code']} {r['name']} 得分{r['score']:.1f}")
                else:
                    print(f"  ⚠️ 无有效分析结果")
        
        report_path, archive_path = save_incremental_report(
            today=today,
            top_list=top_list,
            all_results=full_results,
            strategy_name=strategy_name,
            pool_size=len(stocks),
            valid_count=len(full_results),
            sector_results_map=sector_results_map if args.append_sectors else None,
            dual_advantage_stocks=dual_advantage_stocks,
            mr_list=mr_list,
            trend_list=trend_list,
            hybrid_decision=decision,
        )
        print(f"\n📝 增量报告已保存: {report_path}")
        print(f"📝 当日归档已保存: {archive_path}")
        print("\n✅ 分析完成!")
        return

    # ---------- 原有 ensemble / macd 模式 ----------
    if args.strategy == 'ensemble':
        strat = EnsembleStrategy()
        strategy_name = '12策略Ensemble(技术6+基本面3+消息面+资金面+情绪面，加权投票)'
    else:
        strat = MACDStrategy(fast_period=args.fast, slow_period=args.slow,
                             signal_period=args.signal)
        strategy_name = f'MACD({args.fast},{args.slow},{args.signal})'

    pe_strat = PEStrategy() if args.fundamental and args.strategy != 'ensemble' else None
    pb_strat = PBStrategy() if args.fundamental else None
    fund_fetcher = FundamentalFetcher() if args.fundamental else None

    print(f"{'='*70}")
    print(f"📈 每日选股推荐 — {today}")
    print(f"{'='*70}")
    print(f"📌 策略: {strategy_name}")
    print(f"📌 股票池: {len(stocks)} 只")
    print(f"📌 基本面: {'✅ 启用(PE/PB)' if args.fundamental else '❌ 关闭'}")
    print(f"📌 推荐TOP: {args.top} 只")
    print()

    all_results = []
    fail_count = 0

    for i, stock in enumerate(stocks, 1):
        code = stock['code']
        name = stock['name']
        sector = stock.get('sector', '')

        # 进度
        if len(stocks) <= 50:
            print(f"\r  分析 [{i}/{len(stocks)}] {code} {name} ...", end='', flush=True)
        elif i == 1 or i % 50 == 0 or i == len(stocks):
            pct = i / len(stocks) * 100
            bar = '█' * int(pct / 2) + '░' * (50 - int(pct / 2))
            print(f"\r  [{bar}] {i}/{len(stocks)} ({pct:.0f}%)", end='', flush=True)

        # 获取数据（统一接口自带重试和降级）
        df = fetch_stock_data(code, 200)

        if len(df) < strat.min_bars:
            fail_count += 1
            continue

        # 合并基本面数据（PE/PB）
        fund_flow_signal = None
        if fund_fetcher:
            try:
                start_dt = df['date'].iloc[0].strftime('%Y%m%d')
                end_dt = df['date'].iloc[-1].strftime('%Y%m%d')
                fund_df = fund_fetcher.get_daily_basic(code, start_date=start_dt, end_date=end_dt)
                if not fund_df.empty:
                    df = fund_fetcher.merge_to_daily(df, fund_df, fill_method='ffill')
                
                # 获取资金流信号
                try:
                    fund_flow_signal = fund_fetcher.get_fund_flow_signal(code)
                except Exception:
                    pass
            except Exception:
                pass

        # 注入 symbol，让 NEWS/MONEY_FLOW 子策略知道当前标的
        if hasattr(strat, 'set_symbol'):
            strat.set_symbol(code, name)

        info = analyze_stock_extended(df, strat, pe_strat, pb_strat, fund_flow_signal)
        score = compute_score(info)

        all_results.append({
            'code': code,
            'name': name,
            'sector': sector,
            'action': info['signal'].action,
            'confidence': info['signal'].confidence,
            'position': info['signal'].position,
            'reason': info['signal'].reason,
            'price': info['price'],
            'change_5d': info['change_5d'],
            'change_20d': info['change_20d'],
            'volume_ratio': info['volume_ratio'],
            'trend': info['trend'],
            'ma5': info['ma5'],
            'ma10': info['ma10'],
            'ma20': info['ma20'],
            'ma60': info['ma60'],
            'dist_high': info['distance_from_high'],
            'dist_low': info['distance_from_low'],
            'score': score,
            'dif': info['signal'].indicators.get('DIF', 0),
            'dea': info['signal'].indicators.get('DEA', 0),
            'pe_signal': info['pe_signal'],
            'pb_signal': info['pb_signal'],
            'pe_ttm': info['pe_ttm'],
            'pe_quantile': info['pe_quantile'],
            'pb': info['pb'],
            'pb_quantile': info['pb_quantile'],
            'fund_flow_signal': info.get('fund_flow_signal', 'neutral'),
            'fund_flow_reason': info.get('fund_flow_reason', ''),
        })

        time.sleep(0.05)

    if fail_count:
        print(f"\n⚠️  {fail_count} 只数据不足，已跳过")

    # ============================================================
    # 分类排序
    # ============================================================
    df_all = pd.DataFrame(all_results)

    buy_stocks = df_all[df_all['action'] == 'BUY'].sort_values('score', ascending=False)
    sell_stocks = df_all[df_all['action'] == 'SELL'].sort_values('score', ascending=True)
    hold_stocks = df_all[df_all['action'] == 'HOLD'].sort_values('score', ascending=False)

    # ============================================================
    # 终端输出
    # ============================================================
    print(f"\n\n{'='*70}")
    print(f"🟢 买入推荐 ({len(buy_stocks)} 只发出买入信号)")
    print(f"{'='*70}")

    if len(buy_stocks) > 0:
        print(f"{'排名':>4} {'代码':>8} {'名称':>8} {'价格':>8} {'评分':>6} "
              f"{'信心':>5} {'仓位':>5} {'5日涨幅':>8} {'量比':>5} {'PE':>6} {'PB':>5} {'资金流':>6} {'趋势':>8} {'理由'}")
        print("-" * 145)
        for rank, (_, row) in enumerate(buy_stocks.head(args.top).iterrows(), 1):
            star = '🌟' if row['score'] >= 60 else ('⭐' if row['score'] >= 45 else '  ')
            pe_str = f"{row['pe_ttm']:.0f}" if pd.notna(row.get('pe_ttm')) and row.get('pe_ttm') else '-'
            pb_str = f"{row['pb']:.1f}" if pd.notna(row.get('pb')) and row.get('pb') else '-'
            flow_emoji = '🟢' if row.get('fund_flow_signal') == 'bullish' else ('🔴' if row.get('fund_flow_signal') == 'bearish' else '⚪')
            flow_str = f"{flow_emoji}{row.get('fund_flow_signal', 'neutral')[:4]}"
            print(f"{star}{rank:>2} {row['code']:>8} {row['name']:>8} "
                  f"{row['price']:>8.2f} {row['score']:>6.1f} "
                  f"{row['confidence']:>5.0%} {row['position']:>5.0%} "
                  f"{row['change_5d']:>+8.2f}% {row['volume_ratio']:>5.1f}x "
                  f"{pe_str:>6} {pb_str:>5} {flow_str:>6} "
                  f"{row['trend']:>8} {row['reason'][:30]}")
    else:
        print("  ⚠️ 今日无买入信号")

    print(f"\n{'='*70}")
    print(f"🔴 卖出预警 ({len(sell_stocks)} 只发出卖出信号)")
    print(f"{'='*70}")

    if len(sell_stocks) > 0:
        for rank, (_, row) in enumerate(sell_stocks.head(10).iterrows(), 1):
            print(f"  {rank:>2}. {row['code']} {row['name']:8s} "
                  f"¥{row['price']:.2f} | 5日{row['change_5d']:+.2f}% | {row['reason'][:50]}")
    else:
        print("  ✅ 今日无卖出信号")

    print(f"\n{'='*70}")
    print(f"📊 市场总览")
    print(f"{'='*70}")
    print(f"  买入信号: {len(buy_stocks)} 只 ({len(buy_stocks)/len(df_all)*100:.1f}%)")
    print(f"  卖出信号: {len(sell_stocks)} 只 ({len(sell_stocks)/len(df_all)*100:.1f}%)")
    print(f"  观望信号: {len(hold_stocks)} 只 ({len(hold_stocks)/len(df_all)*100:.1f}%)")

    # 板块统计
    if len(buy_stocks) > 0:
        sector_buy = buy_stocks.groupby('sector').size().sort_values(ascending=False)
        print(f"\n  🔥 买入信号集中板块:")
        for sec, cnt in sector_buy.head(5).items():
            # 简化板块名
            short_sec = sec.replace('C39计算机、通信和其他电子设备制造业', '电子/半导体')
            short_sec = short_sec[:15]
            print(f"     {short_sec}: {cnt}只")

    # ============================================================
    # 操盘建议
    # ============================================================
    print(f"\n{'='*70}")
    print(f"💰 操盘建议 (假设总资金 10万元)")
    print(f"{'='*70}")

    total_capital = 100000
    max_per_stock = 0.30  # 单只最大仓位30%

    if len(buy_stocks) > 0:
        top_buys = buy_stocks.head(min(5, len(buy_stocks)))
        # 按评分分配权重
        total_score = top_buys['score'].sum()

        print(f"\n  📋 建议买入 {len(top_buys)} 只:")
        print(f"  {'代码':>8} {'名称':>8} {'价格':>8} {'建议仓位':>8} "
              f"{'建议金额':>10} {'建议手数':>8} {'理由'}")
        print("  " + "-" * 90)

        total_used = 0
        for _, row in top_buys.iterrows():
            weight = min(row['score'] / total_score, max_per_stock)
            amount = total_capital * weight
            shares = int(amount / row['price'] / 100) * 100  # 整百股

            if shares <= 0:
                continue

            actual_amount = shares * row['price']
            total_used += actual_amount

            print(f"  {row['code']:>8} {row['name']:>8} "
                  f"¥{row['price']:>7.2f} {weight:>7.0%} "
                  f"¥{actual_amount:>9,.0f} {shares:>7}股 "
                  f"{row['reason'][:35]}")

        remaining = total_capital - total_used
        print(f"\n  💵 预计投入: ¥{total_used:,.0f}")
        print(f"  💵 预留现金: ¥{remaining:,.0f} ({remaining/total_capital:.0%})")
    else:
        print(f"\n  💤 今日建议：空仓观望，等待MACD金叉信号")

    # ============================================================
    # 保存增量报告
    # ============================================================
    # 将 ensemble/macd 结果转换为统一格式
    unified_results = []
    for _, row in df_all.iterrows():
        buy_count = 1 if row['action'] == 'BUY' else 0
        sell_count = 1 if row['action'] == 'SELL' else 0
        hold_count = 1 if row['action'] == 'HOLD' else 0
        unified_results.append({
            'code': row['code'],
            'name': row['name'],
            'price': row['price'],
            'score': row['score'],
            'buy_count': buy_count,
            'sell_count': sell_count,
            'hold_count': hold_count,
            'change_5d': row.get('change_5d', 0),
            'change_20d': row.get('change_20d', 0),
            'sector': row.get('sector', ''),
            'signals': [],
            'trend': row.get('trend', ''),
            'volume_ratio': row.get('volume_ratio', 0),
            'ma5': row.get('ma5', 0),
            'ma10': row.get('ma10', 0),
            'ma20': row.get('ma20', 0),
            'ma60': row.get('ma60', 0),
            'dist_high': row.get('dist_high', 0),
            'dist_low': row.get('dist_low', 0),
            'pe_ttm': row.get('pe_ttm'),
            'pb': row.get('pb'),
        })
    unified_results.sort(key=lambda x: x['score'], reverse=True)
    top_list = unified_results[:args.top]

    report_path, archive_path = save_incremental_report(
        today=today,
        top_list=top_list,
        all_results=unified_results,
        strategy_name=strategy_name,
        pool_size=len(stocks),
        valid_count=len(df_all),
    )
    print(f"\n📝 增量报告已保存: {report_path}")
    print(f"📝 当日归档已保存: {archive_path}")
    print(f"\n✅ 分析完成!")


if __name__ == '__main__':
    main()
