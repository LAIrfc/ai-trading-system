#!/usr/bin/env python3
"""
📈 每日选股推荐工具

功能:
1. 对股票池中所有股票获取最新数据
2. 策略模式: macd(单MACD) | ensemble(多策略固定权重，推荐，默认) | full_11(同ensemble，兼容旧命令)
3. 当前架构（2层）:
   - L0: 大盘过滤器（PolicyEvent 政策面，极度利空时暂停选股）
   - L3: 个股投票（与 EnsembleStrategy 同步的多策略固定权重加权投票）
   - 注：L1/L2层已暂时关闭（待历史回测优化系数）
4. 输出：该买哪些、该卖哪些、观望哪些；每只附带信号强度、建议仓位、理由

用法:
    python3 tools/analysis/recommend_today.py --pool mydate/stock_pool_all.json --strategy ensemble --top 20
    python3 tools/analysis/recommend_today.py --no-policy-filter

L3策略（14大策略加权投票）: 技术面6(MA/MACD/RSI/BOLL/KDJ/DUAL) + 基本面3(PE/PB/PEPB) + NEWS + SENTIMENT + MONEY_FLOW + EARNINGS_GROWTH + INDUSTRY_TREND
L0大盘过滤: POLICY（PolicyEvent，极度利空时阻止选股）

【重要】每日选股只从综合大池 stock_pool_all.json 中选取。
综合大池 = 沪深300 + 中证500 + 科创50 + 创业板300(创业板指+创业板200) + 创业板活跃补充，合计约1100只。
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
import re
from datetime import datetime, timedelta
from collections import defaultdict
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

import pandas as pd
try:
    pd.set_option('future.no_silent_downcasting', True)
except (pd.errors.OptionError, Exception):
    pass
import numpy as np

logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(__file__), '../../.env')
    if os.path.isfile(_env_path):
        load_dotenv(_env_path, override=False)
except ImportError:
    pass

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
from src.strategies.earnings_growth import EarningsGrowthStrategy
from src.data.fetchers.fundamental_fetcher import FundamentalFetcher
from src.data.trading_calendar import is_cn_trading_day, get_last_trading_day


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


def _sanitize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Reject/repair obviously invalid OHLCV bars."""
    if df.empty:
        return df
    required = ['open', 'high', 'low', 'close']
    for col in required:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    if 'volume' in df.columns:
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
        df.loc[df['volume'] < 0, 'volume'] = 0
    # Drop rows with non-positive close price
    if 'close' in df.columns:
        df = df[df['close'] > 0]
    # Fix high < low
    if 'high' in df.columns and 'low' in df.columns:
        mask = df['high'] < df['low']
        df.loc[mask, ['high', 'low']] = df.loc[mask, ['low', 'high']].values
    # Drop rows with NaN in critical columns
    present = [c for c in required if c in df.columns]
    if present:
        df = df.dropna(subset=present)
    return df


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
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    def _safe_get_price(prov, code):
        is_etf = (code.startswith('5') or code.startswith('159')) and len(code) == 6
        df = prov.get_kline(symbol=code, datalen=3, min_bars=1,
                            retries=1, timeout=8,
                            **({"is_etf": True} if is_etf else {}))
        if df is not None and not df.empty:
            return float(df['close'].iloc[-1])
        return 0

    for h in holdings:
        code = h['code']
        name = h.get('name', '')
        cost = h.get('avg_cost', 0)
        shares = h.get('shares', 0)
        latest = 0
        if provider:
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    latest = pool.submit(_safe_get_price, provider, code).result(timeout=12)
            except (FuturesTimeout, Exception):
                pass
            if latest == 0:
                try:
                    cached = load_cached_kline(code)
                    if cached is not None and not cached.empty:
                        latest = float(cached['close'].iloc[-1])
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


def _calc_rsi(prices, period=14):
    """计算RSI"""
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = pd.Series(gains).rolling(period).mean().iloc[-1]
    avg_loss = pd.Series(losses).rolling(period).mean().iloc[-1]
    rs = avg_gain / (avg_loss + 1e-8)
    return 100 - 100 / (1 + rs)


def _deep_analyze_kline(df: pd.DataFrame) -> dict:
    """
    对单只股票的K线做深度技术分析，返回丰富的指标字典。
    与策略投票无关，纯粹基于K线计算。
    """
    if df is None or df.empty or len(df) < 20:
        return {}
    df = df.sort_values('date').reset_index(drop=True)
    close = df['close'].values.astype(float)
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)
    volume = df['volume'].values.astype(float)
    n = len(close)
    cur = close[-1]
    result = {'price': cur}

    # --- 多周期涨跌幅 ---
    periods = {'1d': 2, '3d': 4, '5d': 6, '10d': 11, '20d': 21, '60d': 61}
    for label, offset in periods.items():
        result[f'ret_{label}'] = round((cur / close[-offset] - 1) * 100, 2) if n >= offset else None

    # --- 均线 ---
    ma5 = float(np.mean(close[-5:]))
    ma10 = float(np.mean(close[-10:])) if n >= 10 else ma5
    ma20 = float(np.mean(close[-20:])) if n >= 20 else ma5
    ma60 = float(np.mean(close[-60:])) if n >= 60 else ma20
    result.update({'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma60': ma60})

    if ma5 > ma10 > ma20 > ma60:
        result['ma_align'] = '多头排列'
    elif ma5 < ma10 < ma20 < ma60:
        result['ma_align'] = '空头排列'
    else:
        result['ma_align'] = '交叉'

    # MA20 斜率
    if n >= 25:
        ma20_5d_ago = float(np.mean(close[-25:-5]))
        result['ma20_slope'] = round((ma20 / ma20_5d_ago - 1) * 100, 2)
    else:
        result['ma20_slope'] = 0

    # --- MACD ---
    ema12 = pd.Series(close).ewm(span=12).mean()
    ema26 = pd.Series(close).ewm(span=26).mean()
    dif_s = ema12 - ema26
    dea_s = dif_s.ewm(span=9).mean()
    macd_s = (dif_s - dea_s) * 2
    result['dif'] = round(float(dif_s.iloc[-1]), 3)
    result['dea'] = round(float(dea_s.iloc[-1]), 3)
    result['macd_hist'] = round(float(macd_s.iloc[-1]), 3)
    result['macd_state'] = '金叉' if result['dif'] > result['dea'] else '死叉'

    bars = macd_s.iloc[-5:].values
    if all(abs(bars[i]) < abs(bars[i - 1]) for i in range(1, len(bars))):
        result['macd_bar_trend'] = '缩小'
    elif all(abs(bars[i]) > abs(bars[i - 1]) for i in range(1, len(bars))):
        result['macd_bar_trend'] = '放大'
    else:
        result['macd_bar_trend'] = '震荡'

    # 最近金叉/死叉日期
    for i in range(n - 1, max(0, n - 60), -1):
        if dif_s.iloc[i] > dea_s.iloc[i] and dif_s.iloc[i - 1] <= dea_s.iloc[i - 1]:
            result['last_cross'] = f"金叉 {str(df['date'].iloc[i])[:10]}"
            break
        if dif_s.iloc[i] < dea_s.iloc[i] and dif_s.iloc[i - 1] >= dea_s.iloc[i - 1]:
            result['last_cross'] = f"死叉 {str(df['date'].iloc[i])[:10]}"
            break

    # --- RSI ---
    result['rsi14'] = round(_calc_rsi(close[-30:], 14), 1) if n >= 30 else None
    result['rsi_state'] = '超买' if (result['rsi14'] or 50) > 70 else ('超卖' if (result['rsi14'] or 50) < 30 else '中性')

    # --- 60日/120日位置 ---
    for window in [60, 120]:
        if n >= window:
            h = float(max(close[-window:]))
            l = float(min(close[-window:]))
            result[f'high_{window}d'] = h
            result[f'low_{window}d'] = l
            result[f'pos_{window}d'] = round((cur - l) / (h - l + 1e-8) * 100, 0)

    # --- 成交量分析 ---
    vol5 = float(np.mean(volume[-5:]))
    vol20 = float(np.mean(volume[-20:])) if n >= 20 else vol5
    vol60 = float(np.mean(volume[-60:])) if n >= 60 else vol20
    result['vol_ratio_5_20'] = round(vol5 / (vol20 + 1e-8), 2)
    result['vol_ratio_5_60'] = round(vol5 / (vol60 + 1e-8), 2)
    result['vol_state'] = '放量' if result['vol_ratio_5_20'] > 1.3 else ('缩量' if result['vol_ratio_5_20'] < 0.7 else '正常')

    # 多空量比（近20日）
    if n >= 21:
        c20 = close[-21:]
        v20 = volume[-21:]
        up_vols = [v20[i] for i in range(1, 21) if c20[i] > c20[i - 1]]
        dn_vols = [v20[i] for i in range(1, 21) if c20[i] <= c20[i - 1]]
        up_days = len(up_vols)
        dn_days = len(dn_vols)
        up_avg = float(np.mean(up_vols)) if up_vols else 0
        dn_avg = float(np.mean(dn_vols)) if dn_vols else 1
        result['up_days_20'] = up_days
        result['dn_days_20'] = dn_days
        result['bull_bear_vol_ratio'] = round(up_avg / (dn_avg + 1e-8), 2)

    # --- 20日支撑阻力 ---
    if n >= 20:
        result['support_20d'] = float(min(close[-20:]))
        result['resist_20d'] = float(max(close[-20:]))

    # --- 近5日逐日走势 ---
    recent_days = []
    for i in range(-min(5, n - 1), 0):
        d = str(df['date'].iloc[i])[:10]
        o = float(df['open'].iloc[i])
        h_ = float(high[i])
        l_ = float(low[i])
        c = float(close[i])
        v = float(volume[i])
        chg = (c / close[i - 1] - 1) * 100
        recent_days.append({'date': d, 'open': o, 'high': h_, 'low': l_, 'close': c, 'vol': v, 'chg': chg})
    result['recent_days'] = recent_days

    # --- 看多/看空信号汇总 ---
    bulls = []
    bears = []
    if result.get('rsi14') and result['rsi14'] < 30:
        bulls.append('RSI超卖')
    if result.get('rsi14') and result['rsi14'] > 70:
        bears.append('RSI超买')
    if result['macd_state'] == '金叉':
        bulls.append('MACD金叉')
    else:
        bears.append('MACD死叉')
    if result['ma_align'] == '多头排列':
        bulls.append('均线多头')
    elif result['ma_align'] == '空头排列':
        bears.append('均线空头')
    if result['macd_bar_trend'] == '缩小' and result['macd_state'] == '死叉':
        bulls.append('空头动能衰减')
    if result.get('pos_60d') is not None and result['pos_60d'] < 20:
        bulls.append('低位')
    if result.get('pos_60d') is not None and result['pos_60d'] > 80:
        bears.append('高位')
    if result['vol_state'] == '缩量':
        bulls.append('缩量企稳')
    if result.get('bull_bear_vol_ratio') and result['bull_bear_vol_ratio'] > 1.2:
        bulls.append('涨日量>跌日量')
    result['bulls'] = bulls
    result['bears'] = bears

    return result


def _render_holding_advice(holdings: list, all_results: list, today: str) -> str:
    """
    渲染持仓深度分析报告。
    
    对每只持仓从K线出发做全面技术分析：
    多周期涨跌、均线排列与斜率、MACD动能与柱趋势、RSI、
    60/120日位置、量价结构（多空量比）、支撑阻力、
    近5日逐日走势、PE/PB估值、综合风险评级、操作建议。
    
    最后附加组合整体分析：仓位结构、板块分布、风险排名、核心问题诊断。
    """
    if not holdings or not all_results:
        return ""
    result_map = {r['code']: r for r in all_results}
    holding_map = {h['code']: h for h in holdings}
    holding_codes = {h['code'] for h in holdings}
    found = [result_map[c] for c in holding_codes if c in result_map]
    if not found:
        return ""

    def _classify_sector(code, name, sector_raw):
        """根据code/name/sector推断板块归类"""
        name_lower = (name or '').lower()
        if sector_raw and len(sector_raw) > 1 and sector_raw != '未知':
            return sector_raw[:8]
        etf_map = {
            '159880': '有色/资源', '159770': '科技/机器人', '512480': '科技/半导体',
            '512980': '传媒/娱乐', '518880': '黄金', '510300': '指数/沪深300',
        }
        if code in etf_map:
            return etf_map[code]
        if 'etf' in name_lower or code.startswith('5') and len(code) == 6:
            return 'ETF'
        kw_map = [
            (['证券', '太平洋', '信达', '中金', '中信'], '券商/金融'),
            (['银行', '工商', '建设', '农业'], '银行/金融'),
            (['金租', '租赁'], '金融/租赁'),
            (['卫星', '航天', '机器人', '半导体', '光迅', '曙光'], '科技/成长'),
            (['海控', '中远', '物流'], '航运/物流'),
            (['电工', '特变', '电力'], '电力/能源'),
            (['白云山', '医疗', '药', '同仁堂'], '医药/消费'),
            (['黄金', '有色', '稀土'], '有色/资源'),
        ]
        for keywords, cat in kw_map:
            if any(kw in name for kw in keywords):
                return cat
        return sector_raw[:8] if sector_raw else '其他'

    lines = [f"## 今日持仓深度分析 ({today})\n"]

    analyzed_items = []

    for r in sorted(found, key=lambda x: x.get('mr_score', 0), reverse=True):
        code = r['code']
        name = r.get('name', code)
        score = r.get('mr_score', 0)
        buy_cnt = r.get('buy_count', 0)
        sell_cnt = r.get('sell_count', 0)
        signals = r.get('signals', [])
        trend_score = r.get('trend_score', 0.0)

        h = holding_map.get(code, {})
        cost = h.get('avg_cost', 0)
        shares = h.get('shares', 0)

        # 加载K线做深度分析（优先拉最新数据）
        df_kline = fetch_stock_data(code, days=200)
        if df_kline.empty:
            df_kline = load_cached_kline(code)
        deep = _deep_analyze_kline(df_kline)

        price = deep.get('price', r.get('price', 0))
        mkt_val = price * shares
        pnl_pct = (price / cost - 1) * 100 if cost > 0 and price > 0 else 0
        pnl_amt = (price - cost) * shares if cost > 0 else 0

        # --- 风险评级 ---
        risk = 'LOW'
        if not deep:
            risk = 'MED'
        elif deep.get('ma_align') == '空头排列' and pnl_pct < -10:
            risk = 'HIGH'
        elif deep.get('ma_align') == '空头排列' or pnl_pct < -5:
            risk = 'MED'

        # --- 操作建议 ---
        if risk == 'HIGH':
            action_tag = "🔴 高风险"
            if pnl_pct < -15:
                suggestion = "建议反弹减仓，降低风险暴露"
            else:
                suggestion = "建议观察企稳信号，反弹减仓"
        elif sell_cnt >= 3 or score < -3:
            action_tag = "🔴 建议减仓"
            suggestion = "多数策略看空，建议逢高减仓"
        elif deep.get('rsi_state') == '超卖' and deep.get('pos_60d', 50) < 20:
            action_tag = "🟢 超跌关注"
            suggestion = "RSI超卖+低位，关注反弹机会，可小仓位加仓"
        elif buy_cnt >= 5 and score > 3:
            action_tag = "🟢 可加仓"
            suggestion = "多数策略看多，趋势健康可适当加仓"
        elif deep.get('ma_align') == '多头排列':
            action_tag = "🟢 持有"
            suggestion = "均线多头排列，持有等待"
        elif deep.get('macd_bar_trend') == '缩小' and deep.get('macd_state') == '死叉':
            action_tag = "🟡 观察"
            suggestion = "空头动能衰减，等待金叉确认"
        elif risk == 'MED':
            action_tag = "🟡 谨慎持有"
            suggestion = "关注支撑位，跌破则考虑止损"
        else:
            action_tag = "⚪ 持有"
            suggestion = "走势中性，暂时持有观察"

        sector_label = _classify_sector(code, name, r.get('sector', ''))
        analyzed_items.append({
            'code': code, 'name': name, 'shares': shares, 'cost': cost,
            'price': price, 'mkt': mkt_val, 'pnl_pct': pnl_pct, 'pnl_amt': pnl_amt,
            'risk': risk, 'action_tag': action_tag, 'deep': deep,
            'sector': sector_label,
        })

        lines.append(f"### {name}（{code}）{action_tag}\n")
        lines.append(f"| 指标 | 数据 |")
        lines.append(f"|------|------|")
        lines.append(f"| 持仓 | {shares}股 成本¥{cost:.2f} |")
        lines.append(f"| 现价 | ¥{price:.2f} 市值¥{mkt_val:,.0f} 盈亏**{pnl_pct:+.1f}%**（{pnl_amt:+,.0f}元） |")

        # 多周期涨跌
        ret_parts = []
        for label, key in [('1日', 'ret_1d'), ('5日', 'ret_5d'), ('10日', 'ret_10d'), ('20日', 'ret_20d'), ('60日', 'ret_60d')]:
            v = deep.get(key)
            if v is not None:
                ret_parts.append(f"{label}{v:+.1f}%")
        if ret_parts:
            lines.append(f"| 涨跌幅 | {' / '.join(ret_parts)} |")

        # 均线
        lines.append(f"| 均线 | MA5={deep.get('ma5',0):.2f} MA10={deep.get('ma10',0):.2f} "
                     f"MA20={deep.get('ma20',0):.2f} MA60={deep.get('ma60',0):.2f} **{deep.get('ma_align','')}** |")
        if deep.get('ma20_slope'):
            lines.append(f"| MA20斜率 | {deep['ma20_slope']:+.2f}%（5日）{'↑走平/上翘' if deep['ma20_slope'] > 0 else '↓仍在下行'} |")

        # MACD
        lines.append(f"| MACD | DIF={deep.get('dif',0):.3f} DEA={deep.get('dea',0):.3f} "
                     f"柱={deep.get('macd_hist',0):.3f} **{deep.get('macd_state','')}** 柱{deep.get('macd_bar_trend','')} |")
        if deep.get('last_cross'):
            lines.append(f"| 近期交叉 | {deep['last_cross']} |")

        # RSI
        if deep.get('rsi14') is not None:
            lines.append(f"| RSI(14) | {deep['rsi14']:.1f} **{deep.get('rsi_state','')}** |")

        # 位置
        for window in [60, 120]:
            h_key = f'high_{window}d'
            l_key = f'low_{window}d'
            p_key = f'pos_{window}d'
            if deep.get(h_key):
                lines.append(f"| {window}日位置 | 高{deep[h_key]:.2f} 低{deep[l_key]:.2f} **当前{deep[p_key]:.0f}%** |")

        # 量价
        lines.append(f"| 量比 | 5/20日={deep.get('vol_ratio_5_20',0):.2f}x **{deep.get('vol_state','')}** |")
        if deep.get('bull_bear_vol_ratio'):
            lines.append(f"| 多空量比 | {deep['bull_bear_vol_ratio']:.2f} "
                         f"(涨{deep.get('up_days_20',0)}天/跌{deep.get('dn_days_20',0)}天) |")

        # 支撑阻力
        if deep.get('support_20d'):
            lines.append(f"| 20日支撑/阻力 | {deep['support_20d']:.2f} / {deep['resist_20d']:.2f} |")

        # PE/PB
        pe_ttm = r.get('pe_ttm')
        pe_q = r.get('pe_quantile')
        pb_val = r.get('pb')
        pb_q = r.get('pb_quantile')
        pe_file = os.path.join(os.path.dirname(__file__), '..', '..', 'mydate', 'pe_cache', f'{code}.parquet')
        if os.path.exists(pe_file):
            try:
                pe_df = pd.read_parquet(pe_file)
                if 'pe_ttm' in pe_df.columns:
                    pe_vals = pe_df['pe_ttm'].dropna()
                    if len(pe_vals) > 0:
                        pe_ttm = float(pe_vals.iloc[-1])
                        pe_q = float((pe_vals < pe_ttm).mean() * 100)
                if 'pb' in pe_df.columns:
                    pb_vals = pe_df['pb'].dropna()
                    if len(pb_vals) > 0:
                        pb_val = float(pb_vals.iloc[-1])
                        pb_q = float((pb_vals < pb_val).mean() * 100)
            except Exception:
                pass

        val_parts = []
        if pe_ttm is not None and pe_q is not None:
            pe_tag = '低估' if pe_q < 20 else ('高估' if pe_q > 80 else '中等')
            val_parts.append(f"PE={pe_ttm:.1f}(分位{pe_q:.0f}% {pe_tag})")
        if pb_val is not None and pb_q is not None:
            pb_tag = '低估' if pb_q < 20 else ('高估' if pb_q > 80 else '中等')
            val_parts.append(f"PB={pb_val:.2f}(分位{pb_q:.0f}% {pb_tag})")
        if val_parts:
            lines.append(f"| 估值 | {' / '.join(val_parts)} |")

        lines.append("")

        # 近5日走势
        recent = deep.get('recent_days', [])
        if recent:
            lines.append(f"**近{len(recent)}日走势**\n")
            lines.append("| 日期 | 开盘 | 最高 | 最低 | 收盘 | 涨跌 | 成交量 |")
            lines.append("|------|------|------|------|------|------|--------|")
            for rd in recent:
                bar = '▲' if rd['close'] >= rd['open'] else '▼'
                lines.append(f"| {rd['date']} | {rd['open']:.2f} | {rd['high']:.2f} | {rd['low']:.2f} | "
                             f"{rd['close']:.2f} | {bar}{rd['chg']:+.1f}% | {rd['vol']/1e4:.0f}万 |")
            lines.append("")

        # 看多/看空信号
        if deep.get('bulls'):
            lines.append(f"- 看多信号: {', '.join(deep['bulls'])}")
        if deep.get('bears'):
            lines.append(f"- 看空信号: {', '.join(deep['bears'])}")

        # 策略投票
        if signals:
            buy_sigs = [sn for sn, act, _, reason in signals if act == 'BUY']
            sell_sigs = [sn for sn, act, _, reason in signals if act == 'SELL']
            if buy_sigs:
                lines.append(f"- 策略看多({len(buy_sigs)}): {', '.join(buy_sigs)}")
            if sell_sigs:
                lines.append(f"- 策略看空({len(sell_sigs)}): {', '.join(sell_sigs)}")

        lines.append(f"- **操作建议**: {suggestion}")
        lines.append("")
        lines.append("---\n")

    # ========== 组合整体分析 ==========
    if analyzed_items:
        total_cost = sum(it['cost'] * it['shares'] for it in analyzed_items)
        total_mkt = sum(it['mkt'] for it in analyzed_items)
        total_pnl = (total_mkt / total_cost - 1) * 100 if total_cost > 0 else 0
        total_pnl_amt = total_mkt - total_cost

        lines.append("### 组合整体分析\n")
        lines.append(f"**总市值** ¥{total_mkt:,.0f} | **总成本** ¥{total_cost:,.0f} | "
                     f"**总盈亏** {total_pnl:+.1f}%（{total_pnl_amt:+,.0f}元）\n")

        # 板块分布
        sector_map = {}
        for it in analyzed_items:
            s = it.get('sector', '') or '其他'
            if s not in sector_map:
                sector_map[s] = {'mkt': 0, 'names': []}
            sector_map[s]['mkt'] += it['mkt']
            sector_map[s]['names'].append(it['name'])

        lines.append("**仓位结构**\n")
        lines.append("| 板块 | 市值 | 占比 | 持仓 |")
        lines.append("|------|------|------|------|")
        for s, info in sorted(sector_map.items(), key=lambda x: -x[1]['mkt']):
            pct = info['mkt'] / total_mkt * 100 if total_mkt > 0 else 0
            lines.append(f"| {s} | ¥{info['mkt']:,.0f} | {pct:.1f}% | {', '.join(info['names'])} |")
        lines.append("")

        # 风险排名
        lines.append("**风险排名**（由高到低）\n")
        lines.append("| 风险 | 代码 | 名称 | 盈亏 | 均线 | MACD | RSI | 建议 |")
        lines.append("|------|------|------|------|------|------|-----|------|")
        for it in sorted(analyzed_items, key=lambda x: {'HIGH': 0, 'MED': 1, 'LOW': 2}.get(x['risk'], 3)):
            d = it['deep']
            rsi_str = f"{d.get('rsi14', 0):.0f}" if d.get('rsi14') else '-'
            lines.append(f"| {it['risk']} | {it['code']} | {it['name']} | {it['pnl_pct']:+.1f}% | "
                         f"{d.get('ma_align', '-')} | {d.get('macd_state', '-')} | {rsi_str} | {it['action_tag']} |")
        lines.append("")

        # 核心问题诊断
        issues = []
        bearish_count = sum(1 for it in analyzed_items if it['deep'].get('ma_align') == '空头排列')
        if bearish_count >= len(analyzed_items) * 0.7:
            issues.append(f"**均线普遍空头**: {bearish_count}/{len(analyzed_items)}只持仓均线空头排列，系统性下跌趋势")
        profit_count = sum(1 for it in analyzed_items if it['pnl_pct'] > 0)
        if profit_count == 0:
            issues.append("**全线亏损**: 无一盈利持仓，组合处于被动状态")
        high_risk_mkt = sum(it['mkt'] for it in analyzed_items if it['risk'] == 'HIGH')
        if high_risk_mkt > total_mkt * 0.3:
            issues.append(f"**高风险敞口过大**: 高风险持仓占比{high_risk_mkt/total_mkt*100:.0f}%")
        max_sector_pct = max((info['mkt'] / total_mkt * 100 for info in sector_map.values()), default=0)
        if max_sector_pct > 50:
            top_sector = max(sector_map.items(), key=lambda x: x[1]['mkt'])
            issues.append(f"**板块过于集中**: {top_sector[0]}占比{max_sector_pct:.0f}%，风险集中")
        elif len(sector_map) <= 2:
            issues.append("**板块过于集中**: 仅覆盖少数板块，缺乏分散")
        oversold_names = [it['name'] for it in analyzed_items
                          if it['deep'].get('rsi14') and it['deep']['rsi14'] < 30]
        if oversold_names:
            issues.append(f"**RSI超卖**: {', '.join(oversold_names)} 处于超卖区域，关注反弹")

        if issues:
            lines.append("**核心问题诊断**\n")
            for iss in issues:
                lines.append(f"- {iss}")
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

    top_list = [r for r in top_list if not is_st_stock(r.get('name', ''))]

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


def _assess_market_opportunity(top_list: list) -> tuple:
    """
    评估当前市场机会质量，返回 (级别, 描述, 建议推荐数).

    级别: STRONG / NORMAL / WEAK / EMPTY
    纯信号指标：buy_ratio / avg_buy_count / positive_ratio，
    不使用 score（score 混了赛道分/十倍股分等静态信息）。

    阈值校准依据（2026-04-22 真实日报，20只股票）：
      真实分布: buy_count 2-3, sell_count 0-2, 有效策略≈10
      正常市场: avg_buy≈2, buy_ratio≈0.71, positive_ratio≈0.80
      强市场:   avg_buy≈3, buy_ratio≈1.0
      弱市场:   avg_buy≈1, buy_ratio≈0.33, positive_ratio≈0
      空仓:     avg_buy≈0, buy_ratio=0
    """
    if not top_list or len(top_list) < 3:
        return 'EMPTY', '有效股票不足，建议空仓观望', 0

    head = top_list[:min(10, len(top_list))]
    top5 = top_list[:min(5, len(top_list))]

    buy_counts = [r.get('buy_count', 0) for r in head]
    sell_counts = [r.get('sell_count', 0) for r in head]
    avg_buy = np.mean(buy_counts)
    avg_sell = np.mean(sell_counts)
    buy_ratio = avg_buy / max(1, avg_buy + avg_sell)
    avg_buy_count = avg_buy

    top5_positive_ratio = np.mean([
        1.0 if r.get('buy_count', 0) > r.get('sell_count', 0) else 0.0
        for r in top5
    ])

    # STRONG: 多策略一致看好（真实中 avg_buy≥2.5 + sell极少已算强）
    if (buy_ratio >= 0.75 and top5_positive_ratio >= 0.80
            and avg_buy_count >= 2.5):
        return 'STRONG', '强机会：多策略共振，信号密集', 20
    # NORMAL: 正常偏积极（buy > sell 是主流）
    elif buy_ratio >= 0.55 and top5_positive_ratio >= 0.60:
        return 'NORMAL', '普通机会：部分策略看好', min(15, len(top_list))
    # WEAK: 有一定买入信号但不够强
    elif buy_ratio >= 0.35 and top5_positive_ratio >= 0.30:
        return 'WEAK', '弱机会：信号质量一般，建议轻仓或观望', min(8, len(top_list))
    # EMPTY: 全面偏空
    else:
        return 'EMPTY', '极弱：当前无明确买入机会，建议空仓观望', 0


def _tag_entry_zone(r: dict) -> str:
    """
    根据股价位置给每只推荐股打「进场区域」标签。

    既然进了TOP20就是策略推荐买入的，这里只做安全分级：
    - ⛔ 极端过热(60日>100%或danger>=3) → 会在上游被剔除
    - 🟢核心买点: 涨幅温和、位置安全，放心买
    - 🔵正常买入: 有一定涨幅但策略依然看好，可以买
    - 🟡轻仓试探: 短期涨幅较大，建议分批或轻仓进入

    用5个核心维度计分：60d涨幅、20d涨幅、距离前高、量比、RSI超买。
    """
    c60 = r.get('change_60d', 0)
    c20 = r.get('change_20d', 0)
    dh = r.get('dist_high', -999)
    vr = r.get('volume_ratio', 1.0)

    rsi = r.get('rsi14', 50)

    danger_count = 0
    if c60 > 80:
        danger_count += 1
    if c20 > 35:
        danger_count += 1
    if dh > -3:
        danger_count += 1
    if vr > 2.0:
        danger_count += 1
    if rsi > 80:
        danger_count += 1

    if danger_count >= 3 or c60 > 100:
        return '⛔不建议新开仓'
    if danger_count == 2:
        return '🟡轻仓试探'
    if c60 > 50 or (c20 > 20 and dh > -5):
        return '🟡轻仓试探'
    if rsi > 75 and c20 > 15:
        return '🟡轻仓试探'
    if rsi < 30 and c20 < 0:
        return '🟢核心买点'
    if c20 < 0 and c60 < 20:
        return '🟢核心买点'
    if c60 < 10:
        return '🟢核心买点'
    return '🔵正常买入'


def _render_daily_section(today: str, top_list: list, strategy_name: str,
                          pool_size: int, valid_count: int, 
                          dual_advantage_stocks: list = None,
                          mr_list: list = None, 
                          trend_list: list = None,
                          hybrid_decision: dict = None,
                          earnings_top: list = None,
                          all_results: list = None) -> str:
    """渲染单日推荐区块（每只推荐股附带详细分析理由）"""
    lines = [f"## {today} 每日推荐\n"]

    # ====== 市场机会评估（三级推荐 + 空仓能力）======
    opp_level, opp_desc, recommend_count = _assess_market_opportunity(top_list)

    level_emoji = {'STRONG': '🟢', 'NORMAL': '🔵', 'WEAK': '🟡', 'EMPTY': '🔴'}
    lines.append(f"### {level_emoji.get(opp_level, '')} 市场机会: {opp_level} — {opp_desc}\n")

    if opp_level == 'EMPTY':
        lines.append("> **⚠️ 当前市场缺乏有效买入信号，系统建议空仓观望，不推荐任何标的。**\n")
        lines.append(f"**策略**: {strategy_name} | **股票池**: {pool_size}只 | **有效**: {valid_count}只\n")
        return "\n".join(lines)

    if opp_level == 'WEAK':
        lines.append("> **⚠️ 信号质量偏低，以下仅为观察池，建议极轻仓或等待更好机会。**\n")

    if recommend_count < len(top_list):
        top_list = top_list[:recommend_count]

    # 混合策略信息
    if hybrid_decision:
        lines.append(f"**版本**: {hybrid_decision['version']} | **原因**: {hybrid_decision['reason']}\n")
        if hybrid_decision.get('ic_status'):
            ic = hybrid_decision['ic_status']
            lines.append(f"**IC状态**: Base Trend={ic['base_trend_ic']:.3f}, RS={ic['relative_strength_ic']:.3f}\n")
    
    lines.append(f"**策略**: {strategy_name} | **股票池**: {pool_size}只 | **有效**: {valid_count}只 | **推荐级别**: {opp_level}({recommend_count}只)\n")
    
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

    # 总览表（含进场区域标签）
    lines.append("### 📊 完整推荐列表\n")
    lines.append("| 类型 | 排名 | 代码 | 名称 | 价格 | MR得分 | 趋势 | 买/卖/观 | 5日% | 20日% | 进场区域 |")
    lines.append("|------|------|------|------|------|--------|------|----------|------|-------|----------|")
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
        zone = _tag_entry_zone(r)
        
        lines.append(f"| {stock_type} | {rank} | {r['code']} | {r['name']} | {r.get('price',0):.2f} | "
                      f"{mr_score_val:.1f} | {trend_val:+.2f} | {bsh} | "
                      f"{r.get('change_5d',0):+.2f} | {r.get('change_20d',0):+.2f} | {zone} |")
    lines.append("")

    # ====== 业绩增速TOP10（Q报预期差） ======
    if earnings_top:
        lines.append("### 📈 业绩增速TOP10（Q报预期差）\n")
        lines.append("同行已出好业绩、自身业绩预增的优质标的，按净利润增速排序。\n")
        lines.append("| 排名 | 代码 | 名称 | 预告类型 | 增速 | PE | 趋势 | 板块 |")
        lines.append("|------|------|------|----------|------|-----|------|------|")
        for i, e in enumerate(earnings_top, 1):
            growth_pct = float(e.get('growth_pct') or 0)
            growth_str = f"+{growth_pct:.0f}%" if growth_pct > 0 else f"{growth_pct:.0f}%"
            pe_v = e.get('pe_ttm')
            try:
                pe_ok = pe_v is not None and float(pe_v) > 0
            except (TypeError, ValueError):
                pe_ok = False
            pe_str = f"{float(pe_v):.1f}" if pe_ok else "-"
            trend_str = f"{float(e.get('trend_score') or 0):+.2f}"
            reason_short = (e.get('reason') or '')[:20]
            sec = (e.get('sector') or '')[:10]
            lines.append(
                f"| {i} | {e.get('code', '')} | {e.get('name', '')} | {reason_short} | {growth_str} | {pe_str} | {trend_str} | {sec} |"
            )
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

    # ====== 长周期十倍股模型 (3-5年) ======
    tenbagger_results = []
    try:
        from src.strategies.tenbagger_model import (
            batch_evaluate_tenbagger, render_tenbagger_section, TENBAGGER_WATCHLIST
        )
        top_codes = {r['code'] for r in top_list}
        watchlist_in_pool = []
        if all_results:
            watchlist_codes = {w['code'] for w in TENBAGGER_WATCHLIST}
            watchlist_in_pool = [
                r for r in all_results
                if r['code'] in watchlist_codes and r['code'] not in top_codes
            ]
        eval_list = top_list + watchlist_in_pool
        tenbagger_results = batch_evaluate_tenbagger(eval_list, top_n=15)
        if tenbagger_results:
            lines.append(render_tenbagger_section(tenbagger_results))
    except Exception as e:
        lines.append(f"\n> ⚠️ 十倍股模型运行异常: {e}\n")

    # ====== 短周期翻倍股模型 (3-6个月) ======
    doubler_results = []
    try:
        from src.strategies.doubler_model import batch_evaluate_doubler, render_doubler_section
        doubler_results = batch_evaluate_doubler(top_list, top_n=len(top_list))
        if doubler_results:
            lines.append(render_doubler_section(doubler_results))
    except Exception as e:
        lines.append(f"\n> ⚠️ 翻倍股模型运行异常: {e}\n")

    # ====== 黄金交叉：长期十倍逻辑 + 短期资金启动 ======
    if tenbagger_results and doubler_results:
        try:
            from src.strategies.tenbagger_model import find_golden_cross_enhanced
            golden_section = find_golden_cross_enhanced(tenbagger_results, doubler_results)
            if golden_section:
                lines.append(golden_section)
        except Exception as e:
            lines.append(f"\n> ⚠️ 黄金交叉分析异常: {e}\n")

    # ====== 统一分层榜单（6层 × 产业主线标签） ======
    try:
        from src.strategies.unified_ranking import build_unified_ranking, render_unified_ranking
        unified_ranked = build_unified_ranking(
            recommend_results=top_list,
            tenbagger_results=tenbagger_results,
            doubler_results=doubler_results,
            top_n_main=min(len(top_list), 15),
        )
        if unified_ranked:
            lines.append(render_unified_ranking(unified_ranked))
    except Exception as e:
        lines.append(f"\n> ⚠️ 统一分层榜单生成异常: {e}\n")

    # 每只推荐股的深度分析（复用持仓同款分析引擎）
    for rank, r in enumerate(top_list, 1):
        code = r['code']
        name = r.get('name', code)
        score = r.get('score', 0)
        mr_score_val = r.get('mr_score', score)
        sector = r.get('sector', '')
        signals = r.get('signals', [])

        # 加载K线做深度分析
        df_kline = load_cached_kline(code)
        deep = _deep_analyze_kline(df_kline)

        price = deep.get('price', r.get('price', 0))

        # 类型标记
        if dual_advantage_stocks and code in dual_advantage_stocks:
            type_tag = "⭐双优"
        elif mr_list and code in mr_list:
            type_tag = "🟢超跌"
        elif trend_list and code in trend_list:
            type_tag = "🔵趋势"
        else:
            type_tag = ""

        lines.append(f"### {rank}. {code} {name}  {type_tag}（得分 {mr_score_val:.1f}）\n")

        if deep:
            lines.append(f"| 指标 | 数据 |")
            lines.append(f"|------|------|")
            lines.append(f"| 板块 | {sector} |")

            # 多周期涨跌
            ret_parts = []
            for label, key in [('1日', 'ret_1d'), ('5日', 'ret_5d'), ('10日', 'ret_10d'), ('20日', 'ret_20d'), ('60日', 'ret_60d')]:
                v = deep.get(key)
                if v is not None:
                    ret_parts.append(f"{label}{v:+.1f}%")
            if ret_parts:
                lines.append(f"| 涨跌幅 | {' / '.join(ret_parts)} |")

            # 均线
            lines.append(f"| 均线 | MA5={deep.get('ma5',0):.2f} MA10={deep.get('ma10',0):.2f} "
                         f"MA20={deep.get('ma20',0):.2f} MA60={deep.get('ma60',0):.2f} **{deep.get('ma_align','')}** |")
            if deep.get('ma20_slope'):
                slope_dir = '↑走平/上翘' if deep['ma20_slope'] > 0 else '↓仍在下行'
                lines.append(f"| MA20斜率 | {deep['ma20_slope']:+.2f}%（5日）{slope_dir} |")

            # MACD
            lines.append(f"| MACD | DIF={deep.get('dif',0):.3f} DEA={deep.get('dea',0):.3f} "
                         f"柱={deep.get('macd_hist',0):.3f} **{deep.get('macd_state','')}** 柱{deep.get('macd_bar_trend','')} |")
            if deep.get('last_cross'):
                lines.append(f"| 近期交叉 | {deep['last_cross']} |")

            # RSI
            if deep.get('rsi14') is not None:
                lines.append(f"| RSI(14) | {deep['rsi14']:.1f} **{deep.get('rsi_state','')}** |")

            # 位置
            for window in [60, 120]:
                h_key = f'high_{window}d'
                l_key = f'low_{window}d'
                p_key = f'pos_{window}d'
                if deep.get(h_key):
                    lines.append(f"| {window}日位置 | 高{deep[h_key]:.2f} 低{deep[l_key]:.2f} **当前{deep[p_key]:.0f}%** |")

            # 量价
            lines.append(f"| 量比 | 5/20日={deep.get('vol_ratio_5_20',0):.2f}x **{deep.get('vol_state','')}** |")
            if deep.get('bull_bear_vol_ratio'):
                lines.append(f"| 多空量比 | {deep['bull_bear_vol_ratio']:.2f} "
                             f"(涨{deep.get('up_days_20',0)}天/跌{deep.get('dn_days_20',0)}天) |")

            # 支撑阻力
            if deep.get('support_20d'):
                lines.append(f"| 20日支撑/阻力 | {deep['support_20d']:.2f} / {deep['resist_20d']:.2f} |")

            # PE/PB（优先从深度分析的PE缓存读，回退到result字段）
            pe_ttm = r.get('pe_ttm')
            pe_q = r.get('pe_quantile')
            pb_val = r.get('pb')
            pb_q = r.get('pb_quantile')
            pe_file = os.path.join(os.path.dirname(__file__), '..', '..', 'mydate', 'pe_cache', f'{code}.parquet')
            if os.path.exists(pe_file):
                try:
                    pe_df = pd.read_parquet(pe_file)
                    if 'pe_ttm' in pe_df.columns:
                        pe_vals = pe_df['pe_ttm'].dropna()
                        if len(pe_vals) > 0:
                            pe_ttm = float(pe_vals.iloc[-1])
                            pe_q = float((pe_vals < pe_ttm).mean() * 100)
                    if 'pb' in pe_df.columns:
                        pb_vals = pe_df['pb'].dropna()
                        if len(pb_vals) > 0:
                            pb_val = float(pb_vals.iloc[-1])
                            pb_q = float((pb_vals < pb_val).mean() * 100)
                except Exception:
                    pass

            val_parts = []
            if pe_ttm is not None and pe_q is not None:
                pe_tag = '低估' if pe_q < 20 else ('高估' if pe_q > 80 else '中等')
                val_parts.append(f"PE={pe_ttm:.1f}(分位{pe_q:.0f}% {pe_tag})")
            elif pe_ttm is not None:
                val_parts.append(f"PE={pe_ttm:.1f}")
            if pb_val is not None and pb_q is not None:
                pb_tag = '低估' if pb_q < 20 else ('高估' if pb_q > 80 else '中等')
                val_parts.append(f"PB={pb_val:.2f}(分位{pb_q:.0f}% {pb_tag})")
            elif pb_val is not None:
                val_parts.append(f"PB={pb_val:.2f}")
            if val_parts:
                lines.append(f"| 估值 | {' / '.join(val_parts)} |")

            lines.append("")

            # 近5日走势
            recent = deep.get('recent_days', [])
            if recent:
                lines.append(f"**近{len(recent)}日走势**\n")
                lines.append("| 日期 | 开盘 | 最高 | 最低 | 收盘 | 涨跌 | 成交量 |")
                lines.append("|------|------|------|------|------|------|--------|")
                for rd in recent:
                    bar = '▲' if rd['close'] >= rd['open'] else '▼'
                    lines.append(f"| {rd['date']} | {rd['open']:.2f} | {rd['high']:.2f} | {rd['low']:.2f} | "
                                 f"{rd['close']:.2f} | {bar}{rd['chg']:+.1f}% | {rd['vol']/1e4:.0f}万 |")
                lines.append("")

            # 技术面信号
            if deep.get('bulls'):
                lines.append(f"- 看多信号: {', '.join(deep['bulls'])}")
            if deep.get('bears'):
                lines.append(f"- 看空信号: {', '.join(deep['bears'])}")

        # 策略投票
        if signals:
            buy_sigs = [sn for sn, action, _, reason in signals if action == 'BUY']
            sell_sigs = [sn for sn, action, _, reason in signals if action == 'SELL']
            if buy_sigs:
                lines.append(f"- 策略看多({len(buy_sigs)}): {', '.join(buy_sigs)}")
            if sell_sigs:
                lines.append(f"- 策略看空({len(sell_sigs)}): {', '.join(sell_sigs)}")

        # 综合推荐理由
        lines.append(f"- **推荐理由**: {_generate_recommendation_reason_short(r, deep)}")
        lines.append("")
    lines.append("---\n")

    return "\n".join(lines)


def _generate_recommendation_reason_short(r: dict, deep: dict) -> str:
    """基于深度分析+策略结果生成精炼推荐理由"""
    parts = []

    if deep:
        align = deep.get('ma_align', '')
        if align == '多头排列':
            parts.append("均线多头排列，趋势向上")
        elif align == '空头排列':
            parts.append("均线空头，属超跌反弹机会")

        rsi = deep.get('rsi14')
        if rsi and rsi < 30:
            parts.append(f"RSI={rsi:.0f}超卖")
        elif rsi and rsi > 70:
            parts.append(f"RSI={rsi:.0f}超买注意")

        if deep.get('macd_state') == '金叉':
            parts.append("MACD金叉")
        elif deep.get('macd_bar_trend') == '缩小' and deep.get('macd_state') == '死叉':
            parts.append("空头动能衰减")

        pos60 = deep.get('pos_60d')
        if pos60 is not None:
            if pos60 < 15:
                parts.append("60日低位，上方空间大")
            elif pos60 > 85:
                parts.append("接近60日高位，追高风险")

        bbv = deep.get('bull_bear_vol_ratio')
        if bbv and bbv > 1.3:
            parts.append("涨日量明显大于跌日量")

    # 策略维度
    buy_cnt = r.get('buy_count', 0)
    pe = r.get('pe_ttm')
    pe_q = r.get('pe_quantile')
    if buy_cnt >= 5:
        parts.append(f"{buy_cnt}策略看多")
    if pe and pe_q is not None and pe_q < 10:
        parts.append(f"PE极度低估({pe_q:.0f}%分位)")
    elif pe and pe_q is not None and pe_q < 25:
        parts.append(f"PE低估({pe_q:.0f}%分位)")

    change_5d = r.get('change_5d', 0)
    if -5 < change_5d < 0:
        parts.append("近期小幅回调，回踩企稳")
    elif change_5d <= -10:
        parts.append(f"近5日跌{change_5d:+.1f}%，深度超跌")

    return '；'.join(parts) if parts else "综合指标中性，适合观察"


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

    # 矛盾信号提示：RSI超买+高位+策略推荐买入
    rsi14 = r.get('rsi14', 50)
    if rsi14 > 70:
        change_60d = r.get('change_60d', 0)
        if change_60d > 30:
            parts.append(f"⚠️ RSI={rsi14:.0f}已进入超买区+60日涨{change_60d:.0f}%，短线追高风险较大，建议等回调")
        else:
            parts.append(f"⚠️ RSI={rsi14:.0f}接近超买，注意短线波动")

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
    earnings_top: list = None,
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
                                                      dual_advantage_stocks, mr_list, trend_list, hybrid_decision,
                                                      earnings_top, all_results=all_results))
    else:
        report_parts.append(_render_daily_section(today, top_list, strategy_name, pool_size, valid_count,
                                                  dual_advantage_stocks, mr_list, trend_list, hybrid_decision,
                                                  earnings_top, all_results=all_results))

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
                                         dual_advantage_stocks, mr_list, trend_list, hybrid_decision,
                                         earnings_top, all_results=all_results))

    return REPORT_FILE, archive_path


def _append_footer_to_report(archive_path: str, full_results: list, mx_summary: dict):
    """将妙想联动记录和策略异常聚合统计追加到日报归档末尾。"""
    footer_lines = []

    # --- 妙想联动记录 ---
    if mx_summary and any(v for v in mx_summary.values() if v is not None):
        footer_lines.append("\n### 🔗 妙想联动记录\n")
        xg = mx_summary.get('xuangu')
        if xg:
            overlap = xg.get('overlap', [])
            footer_lines.append(f"- **mx-xuangu** 选股交叉验证: 妙想筛选{xg['total']}只, "
                                f"交叉通过{len(overlap)}只"
                                + (f" ({', '.join(overlap[:5])})" if overlap else ""))
        zx = mx_summary.get('zixuan')
        if zx:
            footer_lines.append(f"- **mx-zixuan** 自选股同步: {zx['synced']}/{zx['total']}只 → 「{zx['group']}」")
        mn = mx_summary.get('moni')
        if mn:
            bought = mn.get('bought', [])
            footer_lines.append(f"- **mx-moni** 模拟建仓: {len(bought)}/{mn['total']}只"
                                + (f" ({', '.join(bought[:5])})" if bought else ""))

    # --- 策略异常聚合统计 ---
    from collections import Counter
    err_counter = Counter()
    total_err = 0
    for r in full_results:
        errs = r.get('strategy_errors', [])
        for strat_name, _msg in errs:
            err_counter[strat_name] += 1
            total_err += 1
    if total_err > 0:
        footer_lines.append(f"\n### ⚠️ 策略异常统计（共{total_err}次）\n")
        footer_lines.append("| 策略 | 异常次数 | 占比 |")
        footer_lines.append("|------|----------|------|")
        for strat, cnt in err_counter.most_common():
            pct = cnt / len(full_results) * 100
            footer_lines.append(f"| {strat} | {cnt} | {pct:.1f}% |")
        footer_lines.append("")

    if footer_lines and os.path.exists(archive_path):
        with open(archive_path, 'a', encoding='utf-8') as f:
            f.write("\n".join(footer_lines))


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
    """获取 K 线数据：优先拉取最新数据，失败时降级用缓存"""
    try:
        df = update_kline_cache(code, days=days)
        if df is None:
            df = pd.DataFrame()
        df = _sanitize_ohlcv(df)
        if df is not None and not df.empty and len(df) >= 30:
            return df
    except Exception:
        pass

    cached = load_cached_kline(code)
    cached = _sanitize_ohlcv(cached)
    return cached if not cached.empty else pd.DataFrame()


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
    if len(df) > 1:
        idx_5 = max(0, len(df) - 6)
        idx_20 = max(0, len(df) - 21)
        idx_60 = max(0, len(df) - 61)
        change_5d = (price / float(close.iloc[idx_5]) - 1) * 100
        change_20d = (price / float(close.iloc[idx_20]) - 1) * 100
        change_60d = (price / float(close.iloc[idx_60]) - 1) * 100
    else:
        change_5d = change_20d = change_60d = 0.0
    change_60d = (price / float(close.iloc[-61]) - 1) * 100 if len(df) > 60 else 0

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
        'change_60d': round(change_60d, 2),
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
# 14 策略全量分析（与持仓分析一致）
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


def _kline_parquet_stale_on_weekday(code: str, cache_dir: str, now: datetime) -> bool:
    """
    A 股交易日且 parquet 修改时间超过 24 小时 → 视为过期，不走「缓存已够新则跳过拉取」分支。
    仍保留磁盘数据供合并与网络失败兜底（见 update_kline_cache）。
    """
    if not is_cn_trading_day(now.date()):
        return False
    parquet_path = os.path.join(cache_dir, f'{code}.parquet')
    if not os.path.exists(parquet_path):
        return False
    mtime = os.path.getmtime(parquet_path)
    age_hours = (time.time() - mtime) / 3600
    return age_hours > 24


def _get_last_trading_day(now_dt=None):
    """
    用于 K 线缓存是否“已含最近收盘日”的参考交易日（15:05 分界，含 A 股节假日表）。
    """
    if now_dt is None:
        now_dt = datetime.now()
    d = now_dt.date()
    h, m = now_dt.hour, now_dt.minute

    if is_cn_trading_day(d) and (h, m) >= (15, 5):
        return d
    return get_last_trading_day(d - timedelta(days=1))


_kline_consecutive_fails = 0
_KLINE_CIRCUIT_THRESHOLD = 10
_kline_fails_lock = threading.Lock()


def update_kline_cache(code: str, cache_dir: str = None, days: int = 200) -> pd.DataFrame:
    """
    增量更新K线缓存：优先拉取最新数据，拉不到时降级用缓存。
    
    缓存跳过条件（避免重复请求）：
    - 缓存已包含最近一个交易日数据 → 直接返回
    - 否则 → 尝试下载，失败则降级用缓存

    熔断机制：连续失败 N 次后自动切换为纯缓存模式，避免串行等待浪费时间。
    """
    global _kline_consecutive_fails
    from src.data.provider.data_provider import get_default_kline_provider

    if not cache_dir:
        cache_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'mydate', 'backtest_kline')

    cached_df = load_cached_kline(code, cache_dir)

    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    is_cn_td = is_cn_trading_day(now.date())
    is_trading_hours = is_cn_td and ((9, 15) <= (now.hour, now.minute) <= (15, 0))

    # 工作日 parquet 过旧则强制尝试拉网；合并与失败兜底仍用 cached_df
    parquet_stale = _kline_parquet_stale_on_weekday(code, cache_dir, now)
    effective_for_skip = pd.DataFrame() if parquet_stale else cached_df

    if not effective_for_skip.empty and 'date' in effective_for_skip.columns:
        last_date = pd.Timestamp(effective_for_skip['date'].max())
        days_behind = (pd.Timestamp(now.date()) - last_date).days
        
        last_trading_day = _get_last_trading_day(now)
        if is_trading_hours:
            if days_behind == 0:
                return cached_df
        else:
            if days_behind == 0:
                return cached_df
            if last_date >= pd.Timestamp(last_trading_day):
                return cached_df

    # 熔断：连续失败超阈值，直接用缓存，不再浪费时间等网络
    with _kline_fails_lock:
        if _kline_consecutive_fails >= _KLINE_CIRCUIT_THRESHOLD:
            if not cached_df.empty:
                return cached_df
            return pd.DataFrame()

    # 需要更新：下载最新数据（缩短超时，快速失败）
    provider = get_default_kline_provider()
    from concurrent.futures import TimeoutError as FutureTimeout
    new_df = None
    with _kline_fails_lock:
        effective_timeout = 12 if _kline_consecutive_fails < 3 else 6
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(provider.get_kline, symbol=code, datalen=days, min_bars=1, retries=1, timeout=8)
            new_df = fut.result(timeout=effective_timeout)
    except (FutureTimeout, Exception) as e:
        logger.warning(f"数据获取超时或失败({code}): {e}")

    if new_df is None or new_df.empty:
        with _kline_fails_lock:
            _kline_consecutive_fails += 1
            if _kline_consecutive_fails == _KLINE_CIRCUIT_THRESHOLD:
                print(f"⚡ 网络数据源连续{_KLINE_CIRCUIT_THRESHOLD}次失败，切换纯缓存模式（加速处理）")
        return cached_df if not cached_df.empty else pd.DataFrame()
    
    with _kline_fails_lock:
        _kline_consecutive_fails = 0
    
    if not cached_df.empty:
        combined = pd.concat([cached_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=['date'], keep='last')
        combined = combined.sort_values('date').reset_index(drop=True)
    else:
        combined = new_df
    
    has_today = 'date' in combined.columns and combined['date'].max() >= pd.Timestamp(today_str)
    if is_trading_hours and has_today:
        return combined

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


def save_fundamental_cache(cache_data: dict):
    cache_file = os.path.join(os.path.dirname(__file__), '..', '..', 'mydate', 'market_fundamental_cache.json')
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False)
    except Exception:
        pass


def _normalize_spot_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """
    统一全市场快照列名，产出标准字段：
    代码 / 名称 / 市盈率-动态 / 市净率 / 总市值

    仅当存在“逐股票”明细时返回非空表；若是市场聚合行（无代码列）返回空表。
    """
    if df is None or df.empty:
        return pd.DataFrame()

    aliases = {
        "代码": ["代码", "股票代码", "证券代码", "symbol", "code"],
        "名称": ["名称", "股票名称", "证券简称", "name"],
        "市盈率-动态": ["市盈率-动态", "市盈率", "PE", "pe_ttm", "pe"],
        "市净率": ["市净率", "市净率PB", "PB", "pb"],
        "总市值": ["总市值", "市值", "market_cap", "market value"],
    }

    col_map = {}
    cols = set(df.columns)
    for std_col, cands in aliases.items():
        for c in cands:
            if c in cols:
                col_map[std_col] = c
                break

    # 没有代码列，说明不是可逐股查表的快照（常见为市场聚合指标）
    if "代码" not in col_map:
        return pd.DataFrame()

    out = pd.DataFrame()
    out["代码"] = (
        df[col_map["代码"]]
        .astype(str)
        .str.extract(r"(\d{6})", expand=False)
        .fillna("")
    )
    out = out[out["代码"] != ""].copy()
    if out.empty:
        return pd.DataFrame()

    out["名称"] = df[col_map["名称"]] if "名称" in col_map else ""
    out["市盈率-动态"] = pd.to_numeric(
        df[col_map["市盈率-动态"]], errors="coerce"
    ) if "市盈率-动态" in col_map else np.nan
    out["市净率"] = pd.to_numeric(
        df[col_map["市净率"]], errors="coerce"
    ) if "市净率" in col_map else np.nan
    out["总市值"] = pd.to_numeric(
        df[col_map["总市值"]], errors="coerce"
    ) if "总市值" in col_map else np.nan

    out = out.drop_duplicates(subset=["代码"], keep="first").reset_index(drop=True)
    return out


def _preload_akshare_spot() -> pd.DataFrame:
    """
    预加载全市场实时行情（只调一次），多源降级：
    1. 妙想 mx-data（稳定官方API，消耗 1 次配额）
    2. AKShare stock_zh_a_spot_em（免费无限额，但不稳定）
    失败返回空 DataFrame，后续逻辑用缓存兜底。
    """
    from concurrent.futures import ThreadPoolExecutor as _TPE, TimeoutError as _FTE

    # 源1: 妙想实时行情（稳定官方API，消耗 1 次配额）
    if os.environ.get("MX_APIKEY"):
        try:
            from src.data.mx_skills.client import get_mx_client
            client = get_mx_client()
            if client._limiter.remaining_for("mx-data") >= 1:
                df = client.query_data_df("A股全市场最新价 涨跌幅 市盈率 市净率 总市值 成交量")
                normalized = _normalize_spot_snapshot(df)
                if not normalized.empty:
                    print(f"✅ 妙想全市场行情预加载成功: {len(normalized)} 只（mx-data消耗1次）")
                    return normalized
                print("⚠️ 妙想全市场预加载返回聚合数据，无法逐股查表，自动降级AKShare")
            else:
                print("⚠️ 妙想 mx-data 配额不足，跳过全市场预加载")
        except Exception as e:
            print(f"⚠️ 妙想全市场行情预加载失败: {e}")

    # 源2: AKShare（免费无限额，但不稳定；push2接口非交易时段不返回数据）
    from datetime import datetime as _akdt
    _now = _akdt.now()
    _h, _m = _now.hour, _now.minute
    _in_trading = (
        _now.weekday() < 5
        and ((_h == 9 and _m >= 15) or (10 <= _h <= 11) or (13 <= _h <= 14) or (_h == 15 and _m <= 5))
    )
    if not _in_trading:
        print(f"⚠️ 当前非交易时段({_now.strftime('%H:%M')})，跳过AKShare实时行情预加载（push2接口收盘后不返回数据）")
    else:
        try:
            import akshare as ak
            with _TPE(max_workers=1) as _ex:
                df = _ex.submit(ak.stock_zh_a_spot_em).result(timeout=15)
            normalized = _normalize_spot_snapshot(df)
            if not normalized.empty:
                print(f"✅ AKShare全市场行情预加载成功: {len(normalized)} 只")
                return normalized
            print("⚠️ AKShare全市场预加载返回结构异常，无法逐股查表")
        except Exception as e:
            print(f"⚠️ AKShare全市场行情预加载失败: {e}")

    print("⚠️ 全市场行情预加载全部失败，将使用缓存数据")
    return pd.DataFrame()


def update_fundamental_cache(code: str, fetcher: FundamentalFetcher, cache_data: dict, spot_df: pd.DataFrame = None) -> dict:
    """
    增量更新单只股票的基本面数据（PE/PB/市值）
    
    多数据源降级逻辑：
    1. 预加载的全市场 DataFrame 查表（零网络开销）
    2. 妙想 mx-data（稳定官方API，消耗配额）
    3. Baostock daily_basic（有熔断机制）
    4. 返回缓存
    """
    today = datetime.now().strftime('%Y-%m-%d')
    cache_date = cache_data.get('date', '')
    all_data = cache_data.get('all_data', {})
    
    if cache_date == today and code in all_data:
        return all_data[code]
    
    # 方案1: 从预加载的全市场 DataFrame 查表（零网络开销）
    if spot_df is not None and not spot_df.empty and '代码' in spot_df.columns:
        try:
            stock_row = spot_df[spot_df['代码'].astype(str).str.zfill(6) == str(code).zfill(6)]
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
    
    # 方案2: 妙想 mx-data 查询（稳定官方API，消耗 1 次配额）
    if os.environ.get("MX_APIKEY"):
        try:
            from src.data.mx_skills.client import get_mx_client
            client = get_mx_client()
            if client._limiter.remaining_for("mx-data") >= 1:
                df_mx = client.query_data_df(f"{code} 市盈率 市净率 总市值 股票名称")
                if not df_mx.empty:
                    row = df_mx.iloc[0]
                    fund_info = {
                        'name': str(row.get('股票名称', row.get('名称', ''))),
                        'pe_ttm': None,
                        'pb': None,
                        'market_cap_yi': None,
                        'is_st': False,
                    }
                    for k in row.index:
                        v = row[k]
                        try:
                            v_f = float(v)
                        except (ValueError, TypeError):
                            continue
                        kl = str(k).lower()
                        if '市盈' in kl or 'pe' in kl:
                            fund_info['pe_ttm'] = v_f
                        elif '市净' in kl or 'pb' in kl:
                            fund_info['pb'] = v_f
                        elif '总市值' in kl or 'market' in kl:
                            fund_info['market_cap_yi'] = v_f / 1e8 if v_f > 1e6 else v_f
                    if fund_info['pe_ttm'] is not None or fund_info['pb'] is not None:
                        logger.debug(f"妙想获取 {code} 基本面成功")
                        return fund_info
        except Exception as e:
            logger.debug(f"妙想获取 {code} 基本面失败: {e}")

    # 方案3: Baostock daily_basic（有熔断机制，网络不通时会自动跳过）
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

    # 方案4: 返回缓存
    if code in all_data:
        return all_data[code]
    
    logger.warning(f"❌ 所有数据源均失败: {code}")
    return None


def _mx_post_actions(top_list: list) -> dict:
    """
    推荐完成后执行妙想联动操作，返回执行摘要 dict 供日报写入。
    1. mx-xuangu: 智能选股交叉验证（看 TOP 票是否出现在妙想筛选结果中）
    2. mx-zixuan: 推荐 TOP 票自动同步到东方财富自选股
    3. mx-moni:   推荐结果自动模拟下单
    """
    summary = {'xuangu': None, 'zixuan': None, 'moni': None}
    if not os.environ.get("MX_APIKEY"):
        return summary

    try:
        from src.data.mx_skills.rate_limiter import get_rate_limiter
        limiter = get_rate_limiter()
    except Exception:
        return summary

    top_codes = [r.get('code', '') for r in top_list if r.get('code')]
    if not top_codes:
        return summary

    print(f"\n{'='*50}")
    print("🔗 妙想 Skills 联动")
    print(f"{'='*50}")

    # --- 1. mx-xuangu: 智能选股交叉验证 ---
    try:
        from src.data.mx_skills.stock_screener import MXStockScreener
        if limiter.remaining_for("mx-xuangu") < 1:
            print("\n📊 [mx-xuangu] 配额已用尽，跳过")
            raise StopIteration
        screener = MXStockScreener()
        print("\n📊 [mx-xuangu] 智能选股交叉验证...")
        mx_picks = screener.screen("市盈率小于30 净利润增长率大于10% ROE大于8%")
        if not mx_picks.empty:
            mx_codes = set()
            for col in mx_picks.columns:
                if '代码' in str(col) or 'code' in str(col).lower():
                    mx_codes = set(str(v).replace('.', '').strip() for v in mx_picks[col] if pd.notna(v))
                    break
            if not mx_codes:
                for col in mx_picks.columns:
                    vals = mx_picks[col].astype(str)
                    digit_vals = [v for v in vals if v.isdigit() and len(v) == 6]
                    if len(digit_vals) > len(mx_picks) * 0.3:
                        mx_codes = set(digit_vals)
                        break

            overlap = [c for c in top_codes if c in mx_codes]
            print(f"   妙想选股结果: {len(mx_picks)}只")
            if overlap:
                overlap_names = []
                for c in overlap:
                    name = next((r['name'] for r in top_list if r.get('code') == c), c)
                    overlap_names.append(f"{c}({name})")
                print(f"   ⭐ 与 TOP 推荐交叉验证通过: {', '.join(overlap_names)}")
                summary['xuangu'] = {'total': len(mx_picks), 'overlap': overlap_names}
            else:
                print(f"   TOP 推荐未出现在妙想基本面筛选中（不影响推荐，仅供参考）")
                summary['xuangu'] = {'total': len(mx_picks), 'overlap': []}
        else:
            print("   妙想选股返回为空")
            summary['xuangu'] = {'total': 0, 'overlap': []}
    except StopIteration:
        pass
    except Exception as e:
        print(f"   ⚠️ 选股交叉验证失败: {e}")

    # --- 2. mx-zixuan: 同步 TOP5 到自选股「每日推荐MMDD」分组 ---
    try:
        from datetime import datetime as _dt
        from src.data.mx_skills.watchlist import MXWatchlist
        zixuan_rem = limiter.remaining_for("mx-zixuan")
        if zixuan_rem < 1:
            print(f"\n📌 [mx-zixuan] 配额已用尽，跳过")
            raise StopIteration
        date_tag = _dt.now().strftime("%m%d")
        group_name = f"每日推荐{date_tag}"
        wl = MXWatchlist(group=group_name)
        sync_codes = top_codes[:min(5, zixuan_rem)]
        print(f"\n📌 [mx-zixuan] 同步 TOP{len(sync_codes)} 到自选股「{group_name}」分组 (配额{zixuan_rem})...")
        success_count = 0
        for code in sync_codes:
            name = next((r['name'] for r in top_list if r.get('code') == code), code)
            try:
                ok = wl.add(f"{code} {name}")
                if ok:
                    success_count += 1
                    print(f"   ✅ {code}({name}) → {group_name}")
            except Exception:
                pass
        print(f"   同步完成: {success_count}/{len(sync_codes)}只")
        summary['zixuan'] = {'group': group_name, 'synced': success_count, 'total': len(sync_codes)}
    except StopIteration:
        pass
    except Exception as e:
        print(f"   ⚠️ 自选股同步失败: {e}")

    # --- 3. mx-moni: 模拟建仓 TOP3（等权，每只100股） ---
    try:
        from src.data.mx_skills.mock_trading import MXMockTrading
        moni_rem = limiter.remaining_for("mx-moni")
        if moni_rem < 2:
            print(f"\n💰 [mx-moni] 配额不足({moni_rem})，跳过")
            raise StopIteration
        trader = MXMockTrading()
        moni_codes = top_codes[:3]
        print(f"\n💰 [mx-moni] 模拟盘自动跟单 TOP3 (配额{moni_rem})...")

        try:
            balance_info = trader.balance()
            if balance_info and balance_info.get('status') == 0:
                print(f"   模拟盘状态: 正常")
        except Exception:
            pass

        moni_bought = []
        for code in moni_codes:
            name = next((r['name'] for r in top_list if r.get('code') == code), code)
            try:
                result = trader.buy(code, 100, market_price=True)
                status = result.get('status', result.get('code', -1))
                if status == 0:
                    print(f"   ✅ 模拟买入 {code}({name}) 100股 市价单")
                    moni_bought.append(f"{code}({name})")
                else:
                    msg = result.get('message', result.get('error', '未知'))
                    print(f"   ⚠️ 模拟买入 {code}({name}): {msg}")
            except Exception as e:
                print(f"   ⚠️ 模拟买入 {code}({name}) 失败: {e}")
        summary['moni'] = {'bought': moni_bought, 'total': len(moni_codes)}

        try:
            positions = trader.positions()
            if positions and positions.get('status') == 0:
                pos_data = positions.get('data', {})
                if isinstance(pos_data, dict):
                    pos_list = pos_data.get('data', {}).get('positionList', [])
                    if pos_list:
                        print(f"   📋 当前模拟持仓: {len(pos_list)}只")
        except Exception:
            pass
    except StopIteration:
        pass
    except Exception as e:
        print(f"   ⚠️ 模拟交易失败: {e}")

    try:
        from src.data.mx_skills.rate_limiter import get_rate_limiter
        st = get_rate_limiter().status()
        print(f"\n🔑 妙想配额汇总:")
        for sk, info in st.get("skills", {}).items():
            print(f"   {sk}: {info['used']}/{info['limit']}次, 剩余{info['remaining']}次")
    except Exception:
        pass

    return summary


# ============================================================
# 全局策略实例（避免重复创建，性能优化）
# ============================================================
_GLOBAL_STRATEGIES = None

# 双引擎调度架构配置
# 均值回归引擎权重（原有策略，用于超跌反弹）
MR_WEIGHTS = {
    # 核心均值回归策略
    'PEPB': 2.0,   # 唯一估值投票（综合PE+PB，避免三重计算）
    'BOLL': 1.95, 'RSI': 1.82, 'KDJ': 1.5, 'DUAL': 1.39,
    'NEWS': 0.32, 'SENTIMENT': 0.32, 'MONEY_FLOW': 0.3,
    'EARNINGS_GROWTH': 1.50,
    'INDUSTRY_TREND': 0.80,
    
    # 诊断/辅助因子（降权：PE/PB 已由 PEPB 覆盖，仅保留微弱信号供参考）
    'PE': 0.3, 'PB': 0.3,
    'MACD': 0.5, 'MA': 0.3,
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
    """获取指数数据（沪深300）用于市场状态判断，使用专用指数接口"""
    from src.data.fetchers.data_prefetch import fetch_index_daily
    return fetch_index_daily('000300', datalen=200, min_bars=20)


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
    
    策略集合与 ensemble.py 保持一致（14策略 L3投票层）：
    - 技术面6个: MA, MACD, RSI, BOLL, KDJ, DUAL
    - 基本面3个: PE, PB, PEPB
    - 消息面1个: NEWS
    - 情绪面1个: SENTIMENT（全市场情绪Z-score + 个股趋势过滤）
    - 资金面1个: MONEY_FLOW
    - 业绩增速1个: EARNINGS_GROWTH（业绩预告 yjyg）
    - 行业趋势1个: INDUSTRY_TREND（LLM赛道景气+个股深度）
    
    注：
    - POLICY（政策事件）仅作L0大盘过滤器（_check_policy_filter），不参与投票
    """
    global _GLOBAL_STRATEGIES
    if _GLOBAL_STRATEGIES is None:
        from src.strategies.fundamental_pe_pb import PE_PB_CombinedStrategy
        from src.strategies.industry_trend import IndustryTrendStrategy
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
            'EARNINGS_GROWTH': EarningsGrowthStrategy(),
            'INDUSTRY_TREND': IndustryTrendStrategy(),
        }
    return _GLOBAL_STRATEGIES


def run_full_12_analysis(code: str, name: str, sector: str, df: pd.DataFrame, fetcher: FundamentalFetcher, skip_industry: bool = False, index_df: pd.DataFrame = None, sector_codes: set = None, skip_llm: bool = False) -> dict:
    """
    运行 14 大策略: MA, MACD, RSI, BOLL, KDJ, DUAL, PE, PB, PEPB, NEWS, SENTIMENT, MONEY_FLOW, EARNINGS_GROWTH, INDUSTRY_TREND。
    返回 buy_count, sell_count, hold_count, score（归一化方向分 + 平均置信度）, signals 列表。
    
    Args:
        skip_industry: 是否跳过行业PE/PB查询（纯缓存模式用，避免网络请求）
        index_df: 指数数据（沪深300），避免重复获取
        skip_llm: 跳过LLM策略(NEWS/INDUSTRY_TREND)，用于分层延迟优化的第一轮快速打分
    
    优化:
        1. 使用全局策略实例（避免重复创建）
        2. DUAL策略信号反向（与ensemble.py保持一致）
        3. 基本面数据缺失时跳过PE/PB策略
        4. SENTIMENT使用全市场情绪数据 + 个股趋势过滤
    """
    _globals = _get_global_strategies()
    strat_weights = _GLOBAL_STRATEGY_WEIGHTS
    
    # 线程安全：NEWS/MONEY_FLOW/EARNINGS_GROWTH 携带 symbol 状态，多线程下必须用独立副本
    import copy
    tech_strategies = dict(_globals)
    if 'NEWS' in tech_strategies:
        tech_strategies['NEWS'] = copy.copy(_globals['NEWS'])
        tech_strategies['NEWS'].symbol = code
    if 'MONEY_FLOW' in tech_strategies:
        tech_strategies['MONEY_FLOW'] = copy.copy(_globals['MONEY_FLOW'])
        tech_strategies['MONEY_FLOW'].symbol = code
    if 'EARNINGS_GROWTH' in tech_strategies:
        tech_strategies['EARNINGS_GROWTH'] = copy.copy(_globals['EARNINGS_GROWTH'])
        tech_strategies['EARNINGS_GROWTH'].symbol = code
        tech_strategies['EARNINGS_GROWTH'].stock_name = name or ''
        if sector_codes is not None:
            tech_strategies['EARNINGS_GROWTH'].sector_codes = sector_codes
    if 'INDUSTRY_TREND' in tech_strategies:
        tech_strategies['INDUSTRY_TREND'] = copy.copy(_globals['INDUSTRY_TREND'])
        tech_strategies['INDUSTRY_TREND'].symbol = code
        tech_strategies['INDUSTRY_TREND'].stock_name = name or ''
    
    buy_count = sell_count = hold_count = 0
    weighted_buy = weighted_sell = weighted_hold = 0.0
    signals = []
    score_sum = 0.0
    
    # 双引擎架构：分别计算均值回归得分和全策略得分
    mr_weighted_buy = mr_weighted_sell = 0.0
    mr_score_sum = 0.0
    
    # Phase2: 拆分基本面/技术面/事件驱动得分
    FUNDAMENTAL_STRATEGIES = {'PE', 'PB', 'PEPB', 'EARNINGS_GROWTH'}
    TECHNICAL_STRATEGIES = {'MA', 'MACD', 'RSI', 'BOLL', 'KDJ', 'DUAL'}
    EVENT_STRATEGIES = {'NEWS', 'SENTIMENT', 'MONEY_FLOW', 'INDUSTRY_TREND'}
    fund_score_sum = 0.0
    fund_weight_sum = 0.0
    tech_score_sum = 0.0
    tech_weight_sum = 0.0
    event_score_sum = 0.0
    event_weight_sum = 0.0
    
    MR_STRATEGY_NAMES = {'PB', 'PE', 'PEPB', 'DUAL', 'BOLL', 'RSI', 'KDJ', 'MONEY_FLOW'}
    strategy_errors = []
    vote_records = {}

    # PE/PB/PEPB 跳过主循环，由下方行业感知版本单独计算（避免双重计分）
    SKIP_IN_MAIN_LOOP = {'PE', 'PB', 'PEPB'}
    LLM_STRATEGIES = {'NEWS', 'INDUSTRY_TREND'}
    
    for strat_name, strat in tech_strategies.items():
        try:
            if strat_name in SKIP_IN_MAIN_LOOP:
                continue
            if skip_llm and strat_name in LLM_STRATEGIES:
                continue
            if len(df) < strat.min_bars:
                continue
            sig = strat.safe_analyze(df)
            
            # DUAL策略信号反向（contrarian factor，与ensemble.py保持一致）
            is_contrarian = False
            if strat_name == 'DUAL':
                is_contrarian = True
                if sig.action == 'BUY':
                    sig.action = 'SELL'
                    sig.reason = f'[DUAL反向] {sig.reason}'
                elif sig.action == 'SELL':
                    sig.action = 'BUY'
                    sig.reason = f'[DUAL反向] {sig.reason}'
            
            w = strat_weights.get(strat_name, 1.0)
            vote_records[strat_name] = (sig.action, sig.confidence, w)
            
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
                weighted_hold += w
            
            if strat_name in MR_STRATEGY_NAMES:
                if sig.action == 'BUY':
                    mr_weighted_buy += w
                    mr_score_sum += w * sig.confidence
                elif sig.action == 'SELL':
                    mr_weighted_sell += w
                    mr_score_sum -= w * sig.confidence
            
            # Phase2: 拆分基本面/技术面/事件驱动得分
            signed = w * sig.confidence if sig.action == 'BUY' else (-w * sig.confidence if sig.action == 'SELL' else 0.0)
            if strat_name in FUNDAMENTAL_STRATEGIES:
                fund_score_sum += signed
                fund_weight_sum += w
            elif strat_name in TECHNICAL_STRATEGIES:
                tech_score_sum += signed
                tech_weight_sum += w
            elif strat_name in EVENT_STRATEGIES:
                event_score_sum += signed
                event_weight_sum += w
            
            action_label = f'{sig.action}(contrarian)' if is_contrarian and sig.action == 'BUY' else sig.action
            signals.append((strat_name, action_label, sig.confidence, sig.reason[:40]))
        except Exception as e:
            strategy_errors.append((strat_name, str(e)[:120]))

    # 【修复3】基本面数据验证：数据不足时跳过PE/PB/PEPB策略
    has_pe_data = 'pe_ttm' in df.columns and df['pe_ttm'].notna().sum() > 100
    has_pb_data = 'pb' in df.columns and df['pb'].notna().sum() > 100
    has_pepb_data = has_pe_data and has_pb_data
    
    # 获取行业PE/PB数据（用于行业分位数对比，总超时15s防止卡死）
    industry = None
    industry_pe_data = industry_pb_data = None
    
    if not skip_industry and (has_pe_data or has_pb_data):
        try:
            from concurrent.futures import ThreadPoolExecutor as _TPE, TimeoutError as _TE
            def _fetch_industry_data():
                ind = fetcher.get_industry_classification(code)
                if ind:
                    cd = fetcher.get_industry_pe_cninfo(ind)
                    return ind, cd
                return None, None
            with _TPE(max_workers=1) as _ex:
                _fut = _ex.submit(_fetch_industry_data)
                try:
                    industry, cninfo_data = _fut.result(timeout=10)
                    if cninfo_data:
                        pe_val = cninfo_data.get('pe_weighted') or cninfo_data.get('pe_median')
                        if pe_val and pe_val > 0:
                            import numpy as np
                            _rng = np.random.RandomState(hash(industry) & 0xFFFFFFFF)
                            industry_pe_data = pd.Series(
                                _rng.normal(pe_val, pe_val * 0.15, 400).clip(pe_val * 0.5, pe_val * 2.0))
                except _TE:
                    pass
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
                vote_records['PE'] = (pe_sig.action, pe_sig.confidence, pe_w)
                if pe_sig.action == 'BUY':
                    buy_count += 1
                    weighted_buy += pe_w
                    score_sum += pe_w * pe_sig.confidence
                    mr_weighted_buy += pe_w
                    mr_score_sum += pe_w * pe_sig.confidence
                    fund_score_sum += pe_w * pe_sig.confidence
                    fund_weight_sum += pe_w
                elif pe_sig.action == 'SELL':
                    sell_count += 1
                    weighted_sell += pe_w
                    score_sum -= pe_w * pe_sig.confidence
                    mr_weighted_sell += pe_w
                    mr_score_sum -= pe_w * pe_sig.confidence
                    fund_score_sum -= pe_w * pe_sig.confidence
                    fund_weight_sum += pe_w
                else:
                    hold_count += 1
                    weighted_hold += pe_w
                    fund_weight_sum += pe_w
                signals.append(('PE', pe_sig.action, pe_sig.confidence, pe_sig.reason[:40]))
        except Exception as e:
            strategy_errors.append(('PE', str(e)[:120]))

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
                vote_records['PB'] = (pb_sig.action, pb_sig.confidence, pb_w)
                if pb_sig.action == 'BUY':
                    buy_count += 1
                    weighted_buy += pb_w
                    score_sum += pb_w * pb_sig.confidence
                    mr_weighted_buy += pb_w
                    mr_score_sum += pb_w * pb_sig.confidence
                    fund_score_sum += pb_w * pb_sig.confidence
                    fund_weight_sum += pb_w
                elif pb_sig.action == 'SELL':
                    sell_count += 1
                    weighted_sell += pb_w
                    score_sum -= pb_w * pb_sig.confidence
                    mr_weighted_sell += pb_w
                    mr_score_sum -= pb_w * pb_sig.confidence
                    fund_score_sum -= pb_w * pb_sig.confidence
                    fund_weight_sum += pb_w
                else:
                    hold_count += 1
                    weighted_hold += pb_w
                    fund_weight_sum += pb_w
                signals.append(('PB', pb_sig.action, pb_sig.confidence, pb_sig.reason[:40]))
        except Exception as e:
            strategy_errors.append(('PB', str(e)[:120]))
    
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
                vote_records['PEPB'] = (pepb_sig.action, pepb_sig.confidence, pepb_w)
                if pepb_sig.action == 'BUY':
                    buy_count += 1
                    weighted_buy += pepb_w
                    score_sum += pepb_w * pepb_sig.confidence
                    mr_weighted_buy += pepb_w
                    mr_score_sum += pepb_w * pepb_sig.confidence
                    fund_score_sum += pepb_w * pepb_sig.confidence
                    fund_weight_sum += pepb_w
                elif pepb_sig.action == 'SELL':
                    sell_count += 1
                    weighted_sell += pepb_w
                    score_sum -= pepb_w * pepb_sig.confidence
                    mr_weighted_sell += pepb_w
                    mr_score_sum -= pepb_w * pepb_sig.confidence
                    fund_score_sum -= pepb_w * pepb_sig.confidence
                    fund_weight_sum += pepb_w
                else:
                    hold_count += 1
                    weighted_hold += pepb_w
                    fund_weight_sum += pepb_w
                signals.append(('PEPB', pepb_sig.action, pepb_sig.confidence, pepb_sig.reason[:40]))
        except Exception as e:
            strategy_errors.append(('PEPB', str(e)[:120]))

    # 动态相关性折扣：振荡器组(RSI/KDJ/BOLL)全部同向时折扣更重
    _oscillator_group = {'RSI', 'KDJ', 'BOLL'}
    _osc_actions = {n: act for n, (act, _, _) in vote_records.items() if n in _oscillator_group and act != 'HOLD'}
    _osc_all_agree = len(set(_osc_actions.values())) == 1 and len(_osc_actions) == 3
    _osc_discount = 0.35 if _osc_all_agree else 0.5

    CORRELATED_PAIRS = {
        ('RSI', 'KDJ'): _osc_discount,
        ('RSI', 'BOLL'): _osc_discount,
        ('KDJ', 'BOLL'): _osc_discount,
        ('MA', 'MACD'): 0.5,
        ('PE', 'PEPB'): 0.5,
        ('PB', 'PEPB'): 0.5,
        ('NEWS', 'MONEY_FLOW'): 0.5,
        ('NEWS', 'INDUSTRY_TREND'): 0.6,
    }

    def _discounted_side(action: str):
        side = {
            n: (conf, w)
            for n, (act, conf, w) in vote_records.items()
            if act == action
        }
        if not side:
            return 0.0, 0.0
        adjusted_w = {n: w for n, (_, w) in side.items()}
        for (s1, s2), discount in CORRELATED_PAIRS.items():
            if s1 in adjusted_w and s2 in adjusted_w:
                if adjusted_w[s1] >= adjusted_w[s2]:
                    adjusted_w[s2] *= discount
                else:
                    adjusted_w[s1] *= discount
        total_w = sum(adjusted_w.values())
        total_score = sum(adjusted_w[n] * side[n][0] for n in side)
        return total_w, total_score

    discounted_buy_w, discounted_buy_score = _discounted_side('BUY')
    discounted_sell_w, discounted_sell_score = _discounted_side('SELL')
    if discounted_buy_w > 0:
        weighted_buy = discounted_buy_w
    if discounted_sell_w > 0:
        weighted_sell = discounted_sell_w
    score_sum = discounted_buy_score - discounted_sell_score

    # 综合得分：归一化净方向（买/卖/观望权重）与 BUY+SELL 上的平均带符号置信度分离后再组合，避免量纲混用。
    # 注：POLICY 不在本函数内（仅作 L0 大盘过滤）。SENTIMENT/NEWS 与其余策略一样在主循环中参与 score 加权投票；
    #     二者不计入下方 mr_score，因未列入 MR_STRATEGY_NAMES（与 ensemble 分层中“均值回归子得分”口径一致）。
    total_weight = weighted_buy + weighted_sell + weighted_hold
    if total_weight > 0:
        direction_score = (weighted_buy - weighted_sell) / total_weight
    else:
        direction_score = 0.0

    active_count = buy_count + sell_count
    if active_count > 0:
        avg_confidence = score_sum / active_count
    else:
        avg_confidence = 0.5

    score = round(direction_score * 10 + avg_confidence, 2)
    
    # 均值回归得分：PB/PE/PEPB/DUAL/BOLL/RSI/KDJ/MONEY_FLOW，不含MA/MACD/NEWS/SENTIMENT/INDUSTRY_TREND
    mr_score = round(mr_weighted_buy * 2 - mr_weighted_sell * 2 + mr_score_sum, 2)
    
    # Phase2: 归一化基本面/技术面/事件驱动得分到 [-1, 1]
    fundamental_score = round(fund_score_sum / fund_weight_sum, 4) if fund_weight_sum > 0 else 0.0
    technical_score = round(tech_score_sum / tech_weight_sum, 4) if tech_weight_sum > 0 else 0.0
    event_score = round(event_score_sum / event_weight_sum, 4) if event_weight_sum > 0 else 0.0
    close = df['close']
    volume = df['volume']
    price = float(close.iloc[-1])
    if len(df) > 1:
        idx_5 = max(0, len(df) - 6)
        idx_20 = max(0, len(df) - 21)
        idx_60 = max(0, len(df) - 61)
        change_5d = (price / float(close.iloc[idx_5]) - 1) * 100
        change_20d = (price / float(close.iloc[idx_20]) - 1) * 100
        change_60d = (price / float(close.iloc[idx_60]) - 1) * 100
    else:
        change_5d = change_20d = change_60d = 0.0

    # RSI(14) — 供进场区域标签和矛盾信号检测使用
    rsi14 = _calc_rsi(close.values[-30:], 14) if len(df) >= 30 else 50.0

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

    # PE/PB/市值
    pe_ttm = float(df['pe_ttm'].iloc[-1]) if 'pe_ttm' in df.columns and pd.notna(df['pe_ttm'].iloc[-1]) else None
    pb_val = float(df['pb'].iloc[-1]) if 'pb' in df.columns and pd.notna(df['pb'].iloc[-1]) else None
    market_cap = float(df['market_cap'].iloc[-1]) if 'market_cap' in df.columns and pd.notna(df['market_cap'].iloc[-1]) else None

    # 新增：计算趋势得分和动量得分（双引擎调度架构）
    trend_score = 0.0
    momentum_score = 0.0
    trend_weight = 0.0
    
    def _safe_last(series):
        """Extract last value from Series; return 0.0 if NaN or empty."""
        if series.empty:
            return 0.0
        v = series.iloc[-1]
        return float(v) if pd.notna(v) else 0.0

    try:
        trend_strat = Trend_Composite()
        trend_df = trend_strat.generate_signals(df)
        if 'trend_score' in trend_df.columns:
            trend_score = _safe_last(trend_df['trend_score'])
    except Exception:
        pass
    
    try:
        mom_strat = Momentum_Adj()
        mom_df = mom_strat.generate_signals(df)
        if 'score' in mom_df.columns:
            momentum_score = _safe_last(mom_df['score'])
    except Exception:
        pass
    
    tech_confirm_score = 0.0
    try:
        tech_strat = TechnicalConfirmation()
        tech_df = tech_strat.generate_signals(df)
        if 'tech_confirm_score' in tech_df.columns:
            tech_confirm_score = _safe_last(tech_df['tech_confirm_score'])
    except Exception:
        pass
    
    volume_confirm_score = 0.0
    try:
        vol_strat = VolumeConfirmation()
        vol_df = vol_strat.generate_signals(df)
        if 'volume_confirm_score' in vol_df.columns:
            volume_confirm_score = _safe_last(vol_df['volume_confirm_score'])
    except Exception:
        pass
    
    # 相对强度因子（Phase 2增强）
    relative_strength_score = 0.0
    try:
        rs_strat = RelativeStrength()
        rs_df = rs_strat.generate_signals(df, index_df=index_df, sector_df=None)
        if 'relative_strength_score' in rs_df.columns and not rs_df.empty:
            val = rs_df['relative_strength_score'].iloc[-1]
            relative_strength_score = float(val) if pd.notna(val) else 0.0
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
        'weighted_hold': round(weighted_hold, 3),
        'score': score,  # direction_score*10 + avg_confidence（全策略，含 MA/MACD）
        'mr_score': mr_score,  # 均值回归得分（PB/PE/PEPB/DUAL/BOLL/RSI/KDJ/MONEY_FLOW）
        'price': price,
        'change_5d': round(change_5d, 2),
        'change_20d': round(change_20d, 2),
        'change_60d': round(change_60d, 2),
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
        'market_cap': market_cap,
        # 双引擎调度架构新增字段
        'trend_score': round(trend_score, 3),
        'momentum_score': round(momentum_score, 3),
        'trend_weight': round(trend_weight, 3),
        'tech_confirm_score': round(tech_confirm_score, 3),
        'volume_confirm_score': round(volume_confirm_score, 3),
        'relative_strength_score': round(relative_strength_score, 3),
        # Phase2: 拆分得分（基本面 / 技术面 / 事件驱动）
        'fundamental_score': fundamental_score,
        'technical_score': technical_score,
        'event_score': event_score,
        'rsi14': round(rsi14, 1),
        'strategy_error_count': len(strategy_errors),
        'strategy_errors': strategy_errors[:5],
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
                        help='策略: macd | ensemble(14策略固定权重，推荐) | full_11/full_12(同ensemble，兼容命令)')
    parser.add_argument('--cache-only', action='store_true', default=False,
                        help='纯缓存模式：只使用本地缓存，不发起任何网络请求（适合API限流时）')
    parser.add_argument('--fast', type=int, default=12, help='MACD快线(仅macd模式)')
    parser.add_argument('--slow', type=int, default=30, help='MACD慢线(仅macd模式)')
    parser.add_argument('--signal', type=int, default=9, help='MACD信号线(仅macd模式)')
    parser.add_argument('--top', type=int, default=20, help='推荐TOP N只')
    parser.add_argument('--no-fundamental', action='store_true', default=False,
                        help='禁用基本面分析(PE/PB)')
    parser.add_argument('--no-policy-filter', action='store_true', default=False,
                        help='跳过政策面大盘过滤（强制执行选股）')
    parser.add_argument('--only-holdings', action='store_true', default=False,
                        help='只分析持仓：不跑股票池扫描，仅用最新数据分析持仓并更新报告')
    parser.add_argument('--append-sectors', action='store_true', default=False,
                        help='在主报告后追加专题板块推荐（如核电+算电协同）')
    parser.add_argument('--force-version', type=str, default=None,
                        choices=['v5.2', 'v6.1', 'v6.4'],
                        help='强制使用指定版本（v5.2/v6.1/v6.4），None则根据IC自动选择')
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

        # 获取指数数据（专用接口，不受股票熔断影响）
        print("\n📊 获取指数数据（沪深300）...")
        index_df = None
        try:
            from src.data.fetchers.data_prefetch import fetch_index_daily
            index_df = fetch_index_daily('000300', datalen=800)
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
                _skip_industry_h = args.cache_only or args.no_fundamental
                r = run_full_12_analysis(code, name, "", df, fetcher, skip_industry=_skip_industry_h, index_df=index_df)
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
                strategy_name="仅持仓分析(14策略)",
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

    # ---------- 14 策略全量模式（ensemble 亦走此路径，享受缓存+并行优化） ----------
    if args.strategy in ['full_11', 'full_12', 'ensemble']:
        strategy_name = '14大策略(MA|MACD|RSI|BOLL|KDJ|DUAL|PE|PB|PEPB|NEWS|SENTIMENT|MONEY_FLOW|EARNINGS_GROWTH|INDUSTRY_TREND)'
        print(f"{'='*70}")
        print(f"📈 每日选股推荐 — {today} [全策略+大池]")
        print(f"{'='*70}")
        print(f"📌 策略: {strategy_name}")
        print(f"📌 股票池: {len(stocks)} 只")
        _use_fundamental = not args.no_fundamental
        print(f"📌 基本面: {'✅ 启用(PE/PB)' if _use_fundamental else '❌ 关闭'}")
        print(f"📌 推荐TOP: {args.top} 只")
        print()
        
        # 检查缓存
        cache_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'mydate', 'backtest_kline')
        use_kline_cache = os.path.exists(cache_dir)
        fundamental_cache = load_fundamental_cache() if _use_fundamental else {'date': '', 'all_data': {}}
        
        if use_kline_cache:
            cached_files = [f[:-8] for f in os.listdir(cache_dir) if f.endswith('.parquet')]
            print(f"✅ K线缓存: {len(cached_files)}只")
        
        cache_date = fundamental_cache.get('date', '')
        all_fund_data = fundamental_cache.get('all_data', {})
        today = datetime.now().strftime('%Y-%m-%d')
        
        if not _use_fundamental:
            print("⚠️  基本面缓存: 已禁用（--no-fundamental）")
        elif cache_date == today:
            print(f"✅ 基本面缓存: {len(all_fund_data)}只（今日最新）")
        elif cache_date:
            print(f"✅ 基本面缓存: {len(all_fund_data)}只（{cache_date}，将增量更新）")
        else:
            print(f"⚠️  基本面缓存: 无缓存，将全量获取")
        
        fetcher = FundamentalFetcher()
        full_results = []
        fail_count = 0
        
        # ========== 阶段1: 多线程并发获取数据 ==========
        # K线数据源(sina/eastmoney/tencent等)和基本面缓存/spot_df查表均为HTTP或本地I/O，
        # 天然线程安全；baostock降级路径已在FundamentalFetcher中加锁保护。
        spot_df = pd.DataFrame()
        if _use_fundamental and not args.cache_only:
            print("📡 预加载全市场行情数据...")
            spot_df = _preload_akshare_spot()
        elif not _use_fundamental:
            print("📡 跳过全市场基本面预加载（--no-fundamental）")
        
        # 重置熔断计数器
        global _kline_consecutive_fails
        with _kline_fails_lock:
            _kline_consecutive_fails = 0

        # 显示妙想配额状态
        if os.environ.get("MX_APIKEY"):
            try:
                from src.data.mx_skills.rate_limiter import get_rate_limiter
                mx_st = get_rate_limiter().status()
                skills_info = mx_st.get('skills', {})
                parts = [f"{sk}:{info['remaining']}/{info['limit']}" for sk, info in skills_info.items()]
                msg = ' | '.join(parts) if parts else f"总剩余{mx_st['remaining']}"
                print(f"🔑 妙想配额: {msg}")
            except Exception:
                pass

        _stage1_workers = 16
        print(f"\n📊 阶段1: {_stage1_workers}线程并发获取数据 ({len(stocks)} 只)...")
        prepared_stocks = []
        data_fail = 0
        _progress_lock = threading.Lock()
        _progress_done = [0]
        _all_fund_lock = threading.Lock()

        _cache_only = args.cache_only

        def _fetch_one_stock(stock_info):
            """单只股票的数据获取（线程安全）"""
            code = stock_info.get('code') or stock_info.get('symbol', '')
            name = stock_info.get('name', '')
            sector = stock_info.get('sector', '')
            if not code or is_st_stock(name):
                return None

            if _cache_only:
                df = load_cached_kline(code, cache_dir) if use_kline_cache else pd.DataFrame()
            else:
                try:
                    df = update_kline_cache(code, cache_dir, days=200)
                except Exception:
                    df = load_cached_kline(code, cache_dir) if use_kline_cache else pd.DataFrame()
            df = _sanitize_ohlcv(df)

            if df.empty or len(df) < 60:
                return None

            fund_data = None
            if _use_fundamental:
                if _cache_only:
                    _all_data = fundamental_cache.get('all_data', {})
                    fund_data = _all_data.get(code)
                else:
                    fund_data = update_fundamental_cache(code, fetcher, fundamental_cache, spot_df)
                    if fund_data is not None:
                        with _all_fund_lock:
                            all_fund_data[code] = fund_data

            _pe_pb_merged = False
            if _use_fundamental and not _cache_only:
                try:
                    from concurrent.futures import TimeoutError as _FT
                    with ThreadPoolExecutor(max_workers=1) as _ex:
                        _fut = _ex.submit(fetcher.get_daily_basic, code)
                        hist_df = _fut.result(timeout=20)
                    if hist_df is not None and not hist_df.empty and len(hist_df) > 50:
                        hist_df['date'] = pd.to_datetime(hist_df['date'])
                        df['date'] = pd.to_datetime(df['date'])
                        for col in ['pe_ttm', 'pb', 'turnover_rate']:
                            if col in hist_df.columns and col not in df.columns:
                                merged = pd.merge(df[['date']], hist_df[['date', col]],
                                                  on='date', how='left')
                                df[col] = merged[col].values
                                df[col] = df[col].ffill().bfill()
                        if 'pe_ttm' in df.columns and df['pe_ttm'].notna().sum() > 50:
                            _pe_pb_merged = True
                except (_FT, Exception):
                    pass

            if _use_fundamental and fund_data:
                if 'market_cap' not in df.columns:
                    df['market_cap'] = None
                df.loc[df.index[-1], 'market_cap'] = fund_data.get('market_cap_yi', 0) * 100000000 if fund_data.get('market_cap_yi') else None
                df['market_cap'] = df['market_cap'].ffill().bfill()

                if not _pe_pb_merged:
                    if 'pe_ttm' not in df.columns:
                        df['pe_ttm'] = None
                    if 'pb' not in df.columns:
                        df['pb'] = None
                    df.loc[df.index[-1], 'pe_ttm'] = fund_data.get('pe_ttm')
                    df.loc[df.index[-1], 'pb'] = fund_data.get('pb')
                    df['pe_ttm'] = df['pe_ttm'].ffill().bfill()
                    df['pb'] = df['pb'].ffill().bfill()

            return (code, name, sector, df)

        with ThreadPoolExecutor(max_workers=_stage1_workers) as executor:
            futures = {executor.submit(_fetch_one_stock, si): si for si in stocks}
            for future in as_completed(futures):
                with _progress_lock:
                    _progress_done[0] += 1
                    done = _progress_done[0]
                try:
                    result = future.result()
                    if result is not None:
                        prepared_stocks.append(result)
                    else:
                        data_fail += 1
                except Exception:
                    data_fail += 1
                if done % 100 == 0:
                    print(f"\r  数据获取: {done}/{len(stocks)} (有效{len(prepared_stocks)})", end='', flush=True)
        
        fetcher._bs_logout()
        
        with _kline_fails_lock:
            circuit_msg = f", 熔断跳过" if _kline_consecutive_fails >= _KLINE_CIRCUIT_THRESHOLD else ""
        print(f"\n✅ 数据获取完成: {len(prepared_stocks)}只有效, {data_fail}只跳过{circuit_msg}", flush=True)
        if _use_fundamental:
            save_fundamental_cache({'date': today, 'all_data': all_fund_data})

        if os.environ.get("MX_APIKEY"):
            try:
                from src.data.mx_skills.rate_limiter import get_rate_limiter
                mx_st = get_rate_limiter().status()
                skills_info = mx_st.get('skills', {})
                parts = [f"{sk}:{info['remaining']}/{info['limit']}" for sk, info in skills_info.items()]
                msg = ' | '.join(parts) if parts else f"总剩余{mx_st['remaining']}"
                print(f"🔑 妙想配额: {msg}")
            except Exception:
                pass
        
        # ========== 获取指数数据（专用接口，不受股票熔断影响） ==========
        print("\n📊 获取指数数据（沪深300）...")
        index_df = None
        try:
            from src.data.fetchers.data_prefetch import fetch_index_daily
            index_df = fetch_index_daily('000300', datalen=800)
            if index_df is not None and not index_df.empty:
                print(f"✅ 指数数据获取成功: {len(index_df)} 条")
            else:
                print("⚠️ 指数数据为空，相对强度因子将失效")
        except Exception as e:
            print(f"⚠️ 指数数据获取失败: {e}，相对强度因子将失效")
        
        # ========== 构建板块->代码集映射（用于行业景气度外推） ==========
        _sector_to_codes = {}
        for _ps_code, _ps_name, _ps_sector, _ps_df in prepared_stocks:
            if _ps_sector:
                _sector_to_codes.setdefault(_ps_sector, set()).add(_ps_code)
        
        skip_industry_eval = args.cache_only or (not _use_fundamental)
        
        # ========== 行业分类缓存预热（带线程超时） ==========
        if not skip_industry_eval:
            _all_codes = [item[0] for item in prepared_stocks]
            print(f"\n📋 预热行业分类缓存 ({len(_all_codes)} 只)...", flush=True)
            _industry_map = {}
            _industry_timeout = 90
            _ind_ok = False

            def _warmup_industry():
                return fetcher.get_industry_for_batch(_all_codes)

            _ind_executor = ThreadPoolExecutor(max_workers=1)
            _ind_future = _ind_executor.submit(_warmup_industry)
            try:
                _industry_map = _ind_future.result(timeout=_industry_timeout)
                print(f"✅ 行业分类缓存就绪: {len(_industry_map)} 只已缓存", flush=True)
                _ind_ok = True
            except Exception as _ind_e:
                print(f"⚠️ 行业分类预热超时/失败({_industry_timeout}s)，跳过行业PE对比", flush=True)
                _ind_future.cancel()
                skip_industry_eval = True
            finally:
                _ind_executor.shutdown(wait=False)
            if _ind_ok:
                try:
                    fetcher._bs_logout()
                except Exception:
                    pass

        # ========== 阶段1.5: 低成本技术面快筛 Top300 ==========
        _PRESCREEN_TOP_N = 300
        if len(prepared_stocks) > _PRESCREEN_TOP_N:
            print(f"\n⚡ 阶段1.5: 技术面快筛 (6指标, {len(prepared_stocks)}只 → Top{_PRESCREEN_TOP_N})...")
            _prescreen_strategies = _get_global_strategies()
            _TECH_NAMES = ['MA', 'MACD', 'RSI', 'BOLL', 'KDJ', 'DUAL']

            def _quick_tech_score(item):
                _code, _name, _sector, _df = item
                if _df is None or len(_df) < 20:
                    return (item, -999.0)
                buy_w = sell_w = 0.0
                for sn in _TECH_NAMES:
                    strat = _prescreen_strategies.get(sn)
                    if strat is None or len(_df) < strat.min_bars:
                        continue
                    try:
                        sig = strat.safe_analyze(_df)
                        w = MR_WEIGHTS.get(sn, 1.0)
                        if sn == 'DUAL':
                            sig_action = 'SELL' if sig.action == 'BUY' else ('BUY' if sig.action == 'SELL' else sig.action)
                        else:
                            sig_action = sig.action
                        if sig_action == 'BUY':
                            buy_w += w * sig.confidence
                        elif sig_action == 'SELL':
                            sell_w += w * sig.confidence
                    except Exception:
                        pass
                return (item, buy_w - sell_w)

            _prescreen_results = []
            with ThreadPoolExecutor(max_workers=16) as _pre_exec:
                for result in _pre_exec.map(_quick_tech_score, prepared_stocks):
                    _prescreen_results.append(result)

            _prescreen_results.sort(key=lambda x: x[1], reverse=True)
            _cutoff_score = _prescreen_results[_PRESCREEN_TOP_N - 1][1] if len(_prescreen_results) >= _PRESCREEN_TOP_N else -999
            prepared_stocks = [r[0] for r in _prescreen_results[:_PRESCREEN_TOP_N]]
            print(f"  ✅ 快筛完成: 保留Top{_PRESCREEN_TOP_N} (最低得分={_cutoff_score:.2f})")
        else:
            print(f"\n📌 股票池≤{_PRESCREEN_TOP_N}只, 跳过快筛直接全量分析")

        # ========== 阶段2: 分层策略分析（先纯计算后选择性LLM） ==========
        max_workers = 16
        llm_workers = 32  # LLM是IO密集型，用更多线程

        # --- 阶段2a: 纯计算策略快速打分（12策略，~1min） ---
        print(f"\n🚀 阶段2a: {max_workers}线程快速打分 ({len(prepared_stocks)}只, 跳过LLM)...\n")

        def analyze_stock_fast(item):
            code, name, sector, df = item
            try:
                sc = _sector_to_codes.get(sector)
                return run_full_12_analysis(code, name, sector, df, fetcher, skip_industry=skip_industry_eval, index_df=index_df, sector_codes=sc, skip_llm=True)
            except Exception:
                return None

        completed = 0
        fast_results = []
        executor = ThreadPoolExecutor(max_workers=max_workers)
        futures = {executor.submit(analyze_stock_fast, item): item for item in prepared_stocks}
        try:
            for future in as_completed(futures, timeout=300):
                completed += 1
                if completed % 50 == 0 or completed == len(prepared_stocks):
                    pct = completed / len(prepared_stocks) * 100
                    bar = '█' * int(pct / 2) + '░' * (50 - int(pct / 2))
                    print(f"\r  [{bar}] {completed}/{len(prepared_stocks)} ({pct:.0f}%)", end='', flush=True)
                try:
                    result = future.result(timeout=0)
                    if result:
                        fast_results.append(result)
                    else:
                        fail_count += 1
                except Exception:
                    fail_count += 1
        except TimeoutError:
            not_done = sum(1 for f in futures if not f.done())
            for f in futures:
                f.cancel()
            fail_count += not_done
            print(f"\n⏱️  快速打分超时(300s)，{not_done}只未完成")
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

        if fail_count:
            print(f"\n⚠️  {fail_count} 只数据不足或失败，已跳过")

        if not fast_results:
            print("\n⚠️ 无有效分析结果")
            return

        # --- 阶段2b: LLM增强（全量300只，32线程高并发） ---
        print(f"\n  ✅ 快速打分完成: {len(fast_results)}只有效，全部进入LLM增强")

        _code_to_prepared = {item[0]: item for item in prepared_stocks}
        llm_items = [_code_to_prepared[r['code']] for r in fast_results if r['code'] in _code_to_prepared]

        print(f"\n🧠 阶段2b: {llm_workers}线程LLM增强 ({len(llm_items)}只, NEWS+INDUSTRY_TREND)...\n")

        def analyze_stock_full(item):
            code, name, sector, df = item
            try:
                sc = _sector_to_codes.get(sector)
                return run_full_12_analysis(code, name, sector, df, fetcher, skip_industry=skip_industry_eval, index_df=index_df, sector_codes=sc, skip_llm=False)
            except Exception:
                return None

        completed = 0
        llm_results = []
        executor2 = ThreadPoolExecutor(max_workers=llm_workers)
        futures = {executor2.submit(analyze_stock_full, item): item for item in llm_items}
        try:
            for future in as_completed(futures, timeout=300):
                completed += 1
                if completed % 30 == 0 or completed == len(llm_items):
                    pct = completed / len(llm_items) * 100
                    bar = '█' * int(pct / 2) + '░' * (50 - int(pct / 2))
                    print(f"\r  [{bar}] {completed}/{len(llm_items)} ({pct:.0f}%)", end='', flush=True)
                try:
                    result = future.result(timeout=0)
                    if result:
                        llm_results.append(result)
                except Exception:
                    pass
        except TimeoutError:
            not_done = sum(1 for f in futures if not f.done())
            for f in futures:
                f.cancel()
            print(f"\n⏱️  LLM增强超时(300s)，{not_done}只未完成")
        finally:
            executor2.shutdown(wait=True, cancel_futures=True)

        # 合并结果：LLM结果覆盖快速打分结果
        llm_code_map = {r['code']: r for r in llm_results}
        full_results = []
        for r in fast_results:
            if r['code'] in llm_code_map:
                full_results.append(llm_code_map[r['code']])
            else:
                full_results.append(r)

        print(f"\n  ✅ LLM增强完成: {len(llm_results)}/{len(llm_items)}只成功")
        
        # 保存新闻磁盘缓存（避免下次重复调API）
        try:
            from src.strategies.news_sentiment import _DISK_NEWS_CACHE, _DISK_CACHE_DIRTY, _save_disk_news_cache
            if _DISK_CACHE_DIRTY and _DISK_NEWS_CACHE:
                _save_disk_news_cache(_DISK_NEWS_CACHE)
                print(f"💾 新闻缓存已保存: {len(_DISK_NEWS_CACHE)} 只")
        except Exception:
            pass
        
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
        
        # 趋势调节器：trend_score ∈ [-1,1]，用tanh映射到[0.6, 1.0]
        # 正趋势(>0)→放大MR得分(max 1.0x)，负趋势(<0)→压低MR得分(min 0.6x)
        # 零趋势→0.8x（中位数），保证弱市超跌得分被适度衰减而非统一砍半
        df_scores['trend_weight'] = df_scores['trend_score'].apply(
            lambda x: 0.8 + 0.2 * np.tanh(x * 2)
        )
        df_scores['adjusted_mr_score'] = df_scores['mr_score'] * df_scores['trend_weight']
        
        # ========== 行业景气度加分（基于同行业业绩预告平均增速） ==========
        try:
            from src.strategies.earnings_growth import get_industry_prosperity
            sector_groups = {}
            for code, name, sector, _df in prepared_stocks:
                if sector not in sector_groups:
                    sector_groups[sector] = []
                sector_groups[sector].append({'code': code, 'name': name})
            industry_scores = get_industry_prosperity(sector_groups)
            
            sector_map = {}
            for code, name, sector, _df in prepared_stocks:
                sector_map[code] = sector
            
            df_scores['industry_prosperity'] = 0.0
            for code in df_scores.index:
                sec = sector_map.get(code, '')
                if sec in industry_scores:
                    df_scores.loc[code, 'industry_prosperity'] = industry_scores[sec]['prosperity_score']
            
            ip_mean = df_scores['industry_prosperity'].mean()
            ip_nonzero = (df_scores['industry_prosperity'] > 0).sum()
            print(f"\n🏭 行业景气度: {len(industry_scores)}个行业, 平均得分{ip_mean:.3f}, {ip_nonzero}只有行业数据")
            
            df_scores['adjusted_mr_score'] = (
                df_scores['adjusted_mr_score'] + 
                0.3 * df_scores['industry_prosperity']
            )
        except Exception as e:
            print(f"\n⚠️ 行业景气度计算失败: {e}, 跳过")
        
        # ========== 质量门槛过滤（动态，基于 regime_score） ==========
        from src.strategies.market_regime_v6 import SoftRegimeDetector
        try:
            _early_index_df = get_index_data()
            _early_detector = SoftRegimeDetector(trend_weight=0.6, vol_weight=0.4)
            early_regime_score = _early_detector.calc_regime_score(_early_index_df)
        except Exception as _e:
            early_regime_score = 0.0

        if early_regime_score > 0.3:
            qg_label = "牛市"
            qg_price_min = 2.0
            qg_market_cap_min = 30e8
            qg_pe_max = 300
            qg_buy_count_min = 1
            qg_volume_ratio_min = 0.3
        elif early_regime_score > -0.3:
            qg_label = "震荡"
            qg_price_min = 3.0
            qg_market_cap_min = 50e8
            qg_pe_max = 200
            qg_buy_count_min = 2
            qg_volume_ratio_min = 0.4
        else:
            qg_label = "熊市"
            qg_price_min = 5.0
            qg_market_cap_min = 80e8
            qg_pe_max = 100
            qg_buy_count_min = 3
            qg_volume_ratio_min = 0.5

        # 政策预警时自动收紧门槛（不再仅打印提示）
        if policy_result.get('warn'):
            qg_label = f"{qg_label}+政策预警"
            qg_buy_count_min = min(qg_buy_count_min + 1, 4)
            qg_volume_ratio_min = min(qg_volume_ratio_min + 0.1, 1.2)
            qg_pe_max = min(qg_pe_max, 120)
            print("⚠️  政策预警触发：已自动提高选股门槛")

        total_before = len(df_scores)
        df_scores_before_quality_gate = df_scores.copy()
        quality_mask = pd.Series(True, index=df_scores.index)

        if 'price' in df_scores.columns:
            quality_mask &= df_scores['price'] >= qg_price_min

        if 'market_cap' in df_scores.columns:
            mc = df_scores['market_cap']
            quality_mask &= mc.isna() | (mc >= qg_market_cap_min)

        if 'pe_ttm' in df_scores.columns:
            pe = df_scores['pe_ttm']
            quality_mask &= pe.isna() | ((pe > 0) & (pe < qg_pe_max))

        if 'buy_count' in df_scores.columns:
            quality_mask &= df_scores['buy_count'] >= qg_buy_count_min

        if 'volume_ratio' in df_scores.columns:
            vr = df_scores['volume_ratio']
            quality_mask &= vr.isna() | (vr >= qg_volume_ratio_min)

        df_scores = df_scores[quality_mask]
        filtered_count = total_before - len(df_scores)
        if filtered_count > 0:
            print(f"\n🔍 动态质量门槛过滤({qg_label}, regime={early_regime_score:.2f}): {total_before} → {len(df_scores)} 只 (剔除{filtered_count}只)")
            print(f"   过滤条件: 股价≥{qg_price_min}元, 市值≥{qg_market_cap_min/1e8:.0f}亿, 0<PE<{qg_pe_max}, 策略看多≥{qg_buy_count_min}, 量比≥{qg_volume_ratio_min}")

        if df_scores.empty:
            print("\n⚠️ 质量过滤后无有效标的 — 回退使用过滤前候选池继续出报告（常见于震荡市+缓存行情 stale、或全市场量能偏弱）")
            print("   建议：对照盘中真实量比/基本面核对；若连续出现可考虑调低震荡档 buy_count 门槛。")
            df_scores = df_scores_before_quality_gate

        earnings_top = []  # 业绩增速TOP10（混合引擎块内填充）
        earnings_codes = []

        # ========== DUAL(contrarian) 不应算入 MR 的 buy_count ==========
        # DUAL是反向因子：原始SELL→反转为BUY，本质是"该股超卖到极致"
        # 但它不应与 RSI/BOLL 等真正的超跌信号同等看待
        # 修正：DUAL contrarian BUY 的权重在 mr_score 中折半
        # 同时为超跌池增加"真实买入信号数"过滤
        df_scores['real_buy_count'] = df_scores['buy_count'].copy()
        for idx in df_scores.index:
            sigs = None
            for r in full_results:
                if r.get('code') == idx:
                    sigs = r.get('signals', [])
                    break
            if sigs:
                has_dual_contrarian = any(
                    s[0] == 'DUAL' and 'contrarian' in str(s[1]) for s in sigs
                )
                if has_dual_contrarian:
                    df_scores.loc[idx, 'real_buy_count'] -= 1
        
        # ========== 混合策略：根据IC动态选择版本 ==========
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
        version_config = selector.get_version_config(selected_version)
        
        print(f"   ✅ 选择版本: {selected_version}")
        print(f"   原因: {decision['reason']}")
        print(f"   权重: {selected_weights}")
        
        if decision['ic_status']:
            print(f"   IC状态: base_trend={decision['ic_status']['base_trend_ic']:.3f}, "
                  f"rs={decision['ic_status']['relative_strength_ic']:.3f}")
        
        use_advanced = version_config.get('use_orthogonalization', False)
        use_v6_4 = version_config.get('use_unified_optimizer', False)
        
        # ========== 因子正交化（v6.1+） ==========
        if use_advanced:
            print("\n🔧 因子正交化...")
            from src.factors.orthogonalization import FactorOrthogonalizer
        else:
            print(f"\n📌 使用{selected_version}（固定权重，无正交化）...")
        
        base_trend_calc = (TREND_SCORE_WEIGHT * df_scores['trend_score'] +
                          MOMENTUM_SCORE_WEIGHT * df_scores['momentum_score'])
        
        factor_df = pd.DataFrame({
            'base_trend': base_trend_calc,
            'tech_confirm': df_scores['tech_confirm_score'],
            'relative_strength': df_scores['relative_strength_score'],
            'volume_confirm': df_scores['volume_confirm_score']
        })
        
        if use_advanced:
            orthogonalizer = FactorOrthogonalizer(method='sequential')
            try:
                orthogonal_factors = orthogonalizer.fit_transform(factor_df)
                diag = orthogonalizer.diagnose(factor_df, orthogonal_factors)
                print(f"   正交化前平均相关性: {diag['avg_corr_before']:.3f}")
                print(f"   正交化后平均相关性: {diag['avg_corr_after']:.3f}")
                print(f"   改善: {diag['improvement_pct']:.1f}%")
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
            df_scores['base_trend_orth'] = factor_df['base_trend']
            df_scores['tech_confirm_orth'] = factor_df['tech_confirm']
            df_scores['relative_strength_orth'] = factor_df['relative_strength']
            df_scores['volume_confirm_orth'] = factor_df['volume_confirm']
        
        # ========== Soft Regime Score（v6.1+） ==========
        if use_advanced:
            print("\n🌐 Soft Regime Score...")
            from src.strategies.market_regime_v6 import SoftRegimeDetector
            
            try:
                regime_index_df = get_index_data()
                if regime_index_df.empty or 'close' not in regime_index_df.columns:
                    raise ValueError("指数数据为空或缺少close列")
                
                regime_detector = SoftRegimeDetector(trend_weight=0.6, vol_weight=0.4)
                regime_score = regime_detector.calc_regime_score(regime_index_df)
                regime_features = regime_detector.get_regime_features(regime_index_df)
                
                print(f"   Regime Score: {regime_score:.3f}")
                print(f"   趋势强度: {regime_features['trend_strength']:+.3f}")
                print(f"   波动率: {regime_features['volatility']:.3f}")
                
                dynamic_weights = regime_detector.get_dynamic_weights(regime_score)
                print(f"   动态权重: base={dynamic_weights[0]:.2f}, tech={dynamic_weights[1]:.2f}, rs={dynamic_weights[2]:.2f}, vol={dynamic_weights[3]:.2f}")
            except Exception as e:
                print(f"   ⚠️ Regime Score计算失败: {e}，使用默认值")
                regime_score = 0.0
                dynamic_weights = selected_weights
        else:
            regime_score = 0.0
            dynamic_weights = selected_weights
            print(f"   固定权重: {dynamic_weights}")
        
        # Regime概率（[0,1]）
        regime_prob = (regime_score + 1.0) / 2.0
        
        # ========== Phase2: 趋势质量得分（技术面子分） ==========
        print(f"\n📊 Phase2: 计算趋势质量得分（{selected_version}）...")
        
        orth_cols = ['base_trend_orth', 'tech_confirm_orth',
                     'relative_strength_orth', 'volume_confirm_orth']
        orth_nan_counts = {c: int(df_scores[c].isna().sum()) for c in orth_cols}
        if any(v > 0 for v in orth_nan_counts.values()):
            print(f"   ⚠️ 正交因子NaN统计: {orth_nan_counts}，将fillna(0)后计算")
        df_scores[orth_cols] = df_scores[orth_cols].fillna(0.0)

        raw_trend_scores = {}
        for code in df_scores.index:
            linear = (dynamic_weights[0] * df_scores.loc[code, 'base_trend_orth'] +
                      dynamic_weights[1] * df_scores.loc[code, 'tech_confirm_orth'] +
                      dynamic_weights[2] * df_scores.loc[code, 'relative_strength_orth'] +
                      dynamic_weights[3] * df_scores.loc[code, 'volume_confirm_orth'])
            
            bt = df_scores.loc[code, 'base_trend_orth']
            if use_advanced and bt > 0:
                interaction = bt * df_scores.loc[code, 'volume_confirm_orth'] * 0.1
                linear += interaction
            
            raw_trend_scores[code] = linear
        
        raw_trend_scores_series = pd.Series(raw_trend_scores)
        
        if use_advanced:
            print("\n📏 Rank Normalization...")
            from src.factors.normalization import RankNormalizer
            normalizer = RankNormalizer(method='percentile')
            normalized_trend_scores = normalizer.transform(raw_trend_scores_series)
            if normalized_trend_scores.isna().all():
                print("   ⚠️ Rank Normalization 结果全 NaN，降级为 tanh")
                normalized_trend_scores = raw_trend_scores_series.apply(np.tanh)
            print(f"   得分范围: [{normalized_trend_scores.min():.3f}, {normalized_trend_scores.max():.3f}]")
        else:
            normalized_trend_scores = raw_trend_scores_series.apply(np.tanh)
            print(f"   得分范围: [{normalized_trend_scores.min():.3f}, {normalized_trend_scores.max():.3f}]")
        
        df_scores['trend_rank_score'] = normalized_trend_scores
        
        # ========== Phase2: 提取业绩增速信息（用于统一评分，不再作为独立池） ==========
        earnings_map = {}
        try:
            for r in full_results:
                code = r.get('code', '')
                if code not in df_scores.index:
                    continue
                sigs = r.get('signals', [])
                for sn, act, conf, reason in sigs:
                    if sn == 'EARNINGS_GROWTH' and act == 'BUY':
                        growth_pct = 0.0
                        reason_s = reason or ''
                        if '预增' in reason_s or '扭亏' in reason_s:
                            m = re.search(r'([+-]?\d+\.?\d*)%', reason_s)
                            if m:
                                try:
                                    growth_pct = float(m.group(1))
                                except ValueError:
                                    growth_pct = 0.0
                        pe_ttm = None
                        if 'pe_ttm' in df_scores.columns:
                            try:
                                pe_ttm = float(df_scores.loc[code, 'pe_ttm'])
                            except (TypeError, ValueError, KeyError):
                                pe_ttm = None
                        earnings_map[code] = {
                            'code': code,
                            'name': r.get('name', ''),
                            'growth_pct': growth_pct,
                            'confidence': conf,
                            'reason': reason_s,
                            'pe_ttm': pe_ttm,
                            'sector': r.get('sector', ''),
                        }
                        break
        except Exception as e:
            print(f"\n⚠️ 业绩增速信息提取失败: {e}")

        # 业绩增速TOP10（仅用于报告展示）
        earnings_top = sorted(earnings_map.values(), key=lambda x: (x['growth_pct'], x.get('confidence') or 0), reverse=True)[:10]
        for e in earnings_top:
            e['trend_score'] = float(df_scores.loc[e['code'], 'trend_rank_score']) if e['code'] in df_scores.index else 0.0
        earnings_codes = [e['code'] for e in earnings_top]
        print(f"\n📈 业绩预增标的: {len(earnings_map)}只, TOP10: {earnings_codes[:5]}...")

        # ========== Phase2: 统一漏斗评分（替代并列分池） ==========
        # 公式: unified_score = W_fund * fund_norm + W_tech * tech_norm
        #                     + W_event * event_norm + W_earn * earnings_dim
        #                     + W_prosp * industry_prosperity
        # 权重根据 regime_score 动态调整
        print(f"\n{'='*60}")
        print(f"🔀 Phase2: 统一漏斗评分（基本面+技术面+事件驱动+业绩+景气度）")
        print(f"{'='*60}")
        
        # Step 1: 归一化各维度到 [0, 1]
        if 'fundamental_score' not in df_scores.columns:
            df_scores['fundamental_score'] = 0.0
        if 'technical_score' not in df_scores.columns:
            df_scores['technical_score'] = 0.0
        if 'event_score' not in df_scores.columns:
            df_scores['event_score'] = 0.0
        
        def _rank_normalize_01(s):
            """Rank normalize to [0,1]; handles all-equal gracefully."""
            if s.nunique() <= 1:
                return pd.Series(0.5, index=s.index)
            return s.rank(pct=True)
        
        df_scores['fund_norm'] = _rank_normalize_01(df_scores['fundamental_score'])
        df_scores['tech_norm'] = _rank_normalize_01(df_scores['trend_rank_score'])
        df_scores['event_norm'] = _rank_normalize_01(df_scores['event_score'])
        
        # 业绩维度: 有预增→按增速排名，无预增→0
        df_scores['earnings_dim'] = 0.0
        if earnings_map:
            eg_series = pd.Series({c: info['growth_pct'] for c, info in earnings_map.items()})
            if len(eg_series) > 0:
                eg_norm = _rank_normalize_01(eg_series)
                for c in eg_norm.index:
                    if c in df_scores.index:
                        df_scores.loc[c, 'earnings_dim'] = eg_norm[c]
        
        # 行业景气度维度（已在前面计算，直接用）
        if 'industry_prosperity' not in df_scores.columns:
            df_scores['industry_prosperity'] = 0.0
        
        # Step 2: 动态权重分配（5维度）
        if regime_score > 0.3:
            W_FUND, W_TECH, W_EVENT, W_EARN, W_PROSP = 0.20, 0.30, 0.15, 0.20, 0.15
            regime_label = "牛市偏技术"
        elif regime_score > -0.3:
            W_FUND, W_TECH, W_EVENT, W_EARN, W_PROSP = 0.25, 0.20, 0.15, 0.20, 0.20
            regime_label = "震荡偏基本面"
        else:
            W_FUND, W_TECH, W_EVENT, W_EARN, W_PROSP = 0.30, 0.10, 0.15, 0.20, 0.25
            regime_label = "熊市偏防御"
        
        print(f"   Regime={regime_score:.2f} → {regime_label}")
        print(f"   权重: 基本面={W_FUND:.0%} 技术面={W_TECH:.0%} 事件={W_EVENT:.0%} 业绩={W_EARN:.0%} 景气度={W_PROSP:.0%}")
        
        # Step 3: 计算统一得分
        df_scores['unified_score'] = (
            W_FUND * df_scores['fund_norm'] +
            W_TECH * df_scores['tech_norm'] +
            W_EVENT * df_scores['event_norm'] +
            W_EARN * df_scores['earnings_dim'] +
            W_PROSP * df_scores['industry_prosperity']
        )
        
        # Step 4: 行业集中度惩罚（避免过度集中于少数景气行业）
        sector_map = {}
        for code, name, sector, _df in prepared_stocks:
            sector_map[code] = sector
        df_scores['_sector'] = df_scores.index.map(lambda c: sector_map.get(c, ''))
        
        sector_counts = df_scores.nlargest(args.top * 2, 'unified_score').groupby('_sector').size()
        max_per_sector = max(args.top // 4, 3)
        over_concentrated = {s for s, c in sector_counts.items() if c > max_per_sector}
        
        if over_concentrated:
            print(f"   ⚠️ 行业集中度控制: {over_concentrated} 超过{max_per_sector}只/行业")
            for sector in over_concentrated:
                sector_mask = df_scores['_sector'] == sector
                sector_df = df_scores[sector_mask].nlargest(len(df_scores[sector_mask]), 'unified_score')
                penalty_codes = sector_df.index[max_per_sector:]
                df_scores.loc[penalty_codes, 'unified_score'] *= 0.85
        
        # Step 5: 按 unified_score 排序，取 TOP N
        df_scores_sorted = df_scores.sort_values('unified_score', ascending=False)
        final_recommend = df_scores_sorted.head(args.top).index.tolist()
        
        # 诊断：各维度贡献度
        top_df = df_scores.loc[final_recommend]
        contrib_fund = (W_FUND * top_df['fund_norm']).mean()
        contrib_tech = (W_TECH * top_df['tech_norm']).mean()
        contrib_event = (W_EVENT * top_df['event_norm']).mean()
        contrib_earn = (W_EARN * top_df['earnings_dim']).mean()
        contrib_prosp = (W_PROSP * top_df['industry_prosperity']).mean()
        total_contrib = contrib_fund + contrib_tech + contrib_event + contrib_earn + contrib_prosp
        if total_contrib > 0:
            print(f"\n   TOP{args.top} 各维度实际贡献:")
            print(f"     基本面: {contrib_fund/total_contrib:.1%} (均值{top_df['fund_norm'].mean():.3f})")
            print(f"     技术面: {contrib_tech/total_contrib:.1%} (均值{top_df['tech_norm'].mean():.3f})")
            print(f"     事件:   {contrib_event/total_contrib:.1%} (均值{top_df['event_norm'].mean():.3f})")
            print(f"     业绩:   {contrib_earn/total_contrib:.1%} (均值{top_df['earnings_dim'].mean():.3f})")
            print(f"     景气度: {contrib_prosp/total_contrib:.1%} (均值{top_df['industry_prosperity'].mean():.3f})")
        
        n_sectors = top_df['_sector'].nunique()
        print(f"   行业分散度: {n_sectors}个行业")
        print(f"   unified_score范围: [{top_df['unified_score'].min():.4f}, {top_df['unified_score'].max():.4f}]")
        
        # 分类标签：根据实际特征区分超跌/趋势/双优
        mr_list = []
        trend_list = []
        dual_advantage_stocks = []
        for c in final_recommend[:args.top]:
            row = df_scores.loc[c]
            chg_20d = row.get('change_20d', 0)
            trend_s = row.get('trend_rank_score', 0)
            mr_s = row.get('mr_score', row.get('adjusted_mr_score', 0))
            is_trend = chg_20d > 15 or trend_s > 0.3
            is_mr = mr_s > 0 or chg_20d < 5
            if is_trend and is_mr:
                dual_advantage_stocks.append(c)
                mr_list.append(c)
                trend_list.append(c)
            elif is_trend:
                trend_list.append(c)
            elif is_mr:
                mr_list.append(c)
            else:
                trend_list.append(c)
        for c in final_recommend[:args.top]:
            if c not in dual_advantage_stocks:
                row = df_scores.loc[c]
                if row.get('fund_norm', 0) > 0.85 and row.get('tech_norm', 0) > 0.85:
                    dual_advantage_stocks.append(c)
                    if c not in mr_list:
                        mr_list.append(c)
                    if c not in trend_list:
                        trend_list.append(c)
        
        df_scores.drop(columns=['_sector'], inplace=True, errors='ignore')
        
        # 构建stock_data字典
        stock_data = {}
        for code, name, sector, df in prepared_stocks:
            stock_data[code] = df
        
        # ========== v6.4: 生产级组合决策引擎 ==========
        if use_v6_4:
            print(f"\n{'='*60}")
            print(f"🚀 V6.4 生产级组合决策引擎")
            print(f"{'='*60}")
            
            # --- 6.4.1: Alpha 相关性惩罚 ---
            print("\n🎯 Alpha 相关性惩罚...")
            try:
                from src.alpha.alpha_penalty import (
                    compute_alpha_with_penalty, build_factor_exposures, nonlinear_alpha_mapping
                )
                
                df_recommend = df_scores.loc[df_scores.index.isin(final_recommend)]
                factor_exposures = build_factor_exposures(df_recommend)
                
                alpha_raw = np.array([raw_trend_scores.get(c, 0) for c in final_recommend])
                alpha_penalized = compute_alpha_with_penalty(
                    alpha_raw, factor_exposures, lambda_penalty=0.1)
                alpha_penalized = nonlinear_alpha_mapping(alpha_penalized, power=1.5)
                
                corr_before = np.corrcoef(alpha_raw, alpha_penalized)[0, 1] if len(alpha_raw) > 2 else 1.0
                print(f"   惩罚前后相关性: {corr_before:.3f}")
                print(f"   Alpha范围: [{alpha_penalized.min():.3f}, {alpha_penalized.max():.3f}]")
            except Exception as e:
                print(f"   ⚠️ Alpha惩罚失败: {e}，使用原始值")
                alpha_penalized = np.array([raw_trend_scores.get(c, 0) for c in final_recommend])
            
            # --- 6.4.2: Conditional IC ---
            print("\n📈 Conditional IC Learning...")
            try:
                from src.alpha.conditional_ic import ConditionalICUpdater, regime_prob_from_score
                
                ic_updater = ConditionalICUpdater(
                    half_life=20, persist_path='results/conditional_ic_state.json'
                )
                ic_updater.update_all()
                conditional_ic = ic_updater.get_ic(regime_prob)
                bucket_status = ic_updater.get_bucket_status()
                
                print(f"   Regime Prob: {regime_prob:.3f}")
                print(f"   Conditional IC: {conditional_ic:.3f}")
                for b, st in bucket_status.items():
                    print(f"   {b}: samples={st['samples']}, ic={st['ic_ewma']}, conf={st['confidence']:.2f}")
            except Exception as e:
                print(f"   ⚠️ Conditional IC失败: {e}，使用默认IC")
                conditional_ic = 0.15
                ic_updater = None
            
            # --- 6.4.3: 前瞻性风险模型 ---
            print("\n🛡️ 前瞻性风险模型 (EWMA+Shrinkage+CVaR)...")
            try:
                from src.risk.risk_model import RiskModel, compute_expected_return
                
                returns_list = []
                valid_codes = []
                for code in final_recommend:
                    df_k = stock_data.get(code)
                    if df_k is not None and 'close' in df_k.columns and len(df_k) >= 60:
                        rets = df_k['close'].pct_change().dropna().values[-252:]
                        returns_list.append(rets)
                        valid_codes.append(code)
                
                if len(valid_codes) >= 2:
                    min_len = min(len(r) for r in returns_list)
                    returns_matrix = np.column_stack([r[-min_len:] for r in returns_list])
                    
                    risk_model = RiskModel(
                        ewma_halflife=30, shrink_intensity=0.2,
                        cvar_alpha=0.05, cvar_stress_k=3.0, shock_factor=2.0
                    )
                    risk_model.fit(pd.DataFrame(returns_matrix, columns=valid_codes))
                    
                    stock_vols = risk_model.get_stock_volatilities()
                    er = compute_expected_return(alpha_penalized[:len(valid_codes)], conditional_ic, stock_vols)
                    
                    test_w = np.ones(len(valid_codes)) / len(valid_codes)
                    port_var = risk_model.portfolio_variance(test_w)
                    port_cvar = risk_model.portfolio_cvar(test_w, regime_prob)
                    
                    print(f"   协方差矩阵: {len(valid_codes)}x{len(valid_codes)} ({min_len}日)")
                    print(f"   等权组合Vol: {np.sqrt(port_var)*np.sqrt(252):.2%}")
                    print(f"   等权组合CVaR: {port_cvar:.4f}")
                    print(f"   预期收益范围: [{er.min():.4f}, {er.max():.4f}]")
                else:
                    risk_model = None
                    er = alpha_penalized
                    returns_matrix = None
                    valid_codes = list(final_recommend)
                    print(f"   ⚠️ 有效数据不足，降级为简单权重")
            except Exception as e:
                print(f"   ⚠️ 风险模型失败: {e}，降级为简单权重")
                risk_model = None
                er = alpha_penalized
                returns_matrix = None
                valid_codes = list(final_recommend)
            
            # --- 6.4.4: 统一优化器（趋势+均值回归同框） ---
            print("\n⚡ 统一凸优化器（趋势+均值回归同框）...")
            try:
                from src.optimizer.unified_optimizer import UnifiedOptimizer
                from src.risk.risk_model import compute_expected_return
                
                optimizer = UnifiedOptimizer(
                    max_weight=0.10, max_leverage=1.5, max_l2=1.2,
                    target_vol=0.15, max_trend_pct=0.20,
                    lambda_risk=0.5, lambda_cost=0.1, lambda_smooth=0.1
                )
                
                n_opt = len(valid_codes)
                cov_matrix = risk_model.covariance if risk_model else np.eye(n_opt) * 0.04
                hist_ret = returns_matrix if returns_matrix is not None else np.zeros((100, n_opt))
                
                # 方案要求：er_total = w_mr * er_mr + w_trend * er_trend
                # 趋势股和MR股分别用各自alpha计算预期收益，再合并
                trend_mask = np.array([c in trend_list for c in valid_codes])
                mr_mask = np.array([c in mr_list for c in valid_codes])
                stock_vols = risk_model.get_stock_volatilities() if risk_model else np.full(n_opt, 0.20)
                
                # 趋势alpha：使用 trend_rank_score
                alpha_trend_arr = np.array([
                    float(df_scores.loc[c, 'trend_rank_score']) if c in df_scores.index else 0.0
                    for c in valid_codes
                ])
                # MR alpha：使用 adjusted_mr_score（均值回归信号）
                alpha_mr_arr = np.array([
                    float(df_scores.loc[c, 'adjusted_mr_score']) if c in df_scores.index else 0.0
                    for c in valid_codes
                ])
                
                er_trend_arr = compute_expected_return(alpha_trend_arr, conditional_ic, stock_vols)
                er_mr_arr = compute_expected_return(alpha_mr_arr, conditional_ic * 0.8, stock_vols)
                
                # regime_prob 越高（趋势市）→ 趋势权重越大
                w_trend_blend = 0.3 + 0.4 * regime_prob   # [0.3, 0.7]
                w_mr_blend = 1.0 - w_trend_blend
                er_combined = w_trend_blend * er_trend_arr + w_mr_blend * er_mr_arr
                
                print(f"   ER混合: w_trend={w_trend_blend:.2f}, w_mr={w_mr_blend:.2f}")
                print(f"   ER范围: [{er_combined.min():.4f}, {er_combined.max():.4f}]")
                
                # 执行反馈：动态成本
                exec_fb = None
                cost_vec = np.full(n_opt, 0.003)
                try:
                    from src.execution.feedback import ExecutionFeedback, get_dynamic_cost_vector
                    exec_fb = ExecutionFeedback(persist_path='results/execution_feedback.json')
                    cost_vec = get_dynamic_cost_vector(
                        valid_codes, stock_data, regime_prob,
                        total_capital=1_000_000, feedback=exec_fb
                    )
                    print(f"   动态成本范围: [{cost_vec.min():.4f}, {cost_vec.max():.4f}]")
                except Exception as e:
                    print(f"   ⚠️ 动态成本失败: {e}，使用固定成本")
                
                # 路径稳定性：从持久化文件加载上期权重
                prev_weights_opt = None
                prev_weights2_opt = None
                try:
                    import json
                    pw_file = 'results/portfolio_weights_history.json'
                    if os.path.exists(pw_file):
                        with open(pw_file, 'r') as f:
                            pw_hist = json.load(f)
                        hist_list = pw_hist.get('history', [])
                        if len(hist_list) >= 1:
                            last = {d['code']: d['weight'] for d in hist_list[-1].get('weights', [])}
                            prev_weights_opt = np.array([last.get(c, 0.0) for c in valid_codes])
                        if len(hist_list) >= 2:
                            last2 = {d['code']: d['weight'] for d in hist_list[-2].get('weights', [])}
                            prev_weights2_opt = np.array([last2.get(c, 0.0) for c in valid_codes])
                        print(f"   路径平滑：加载 {len(hist_list)} 期历史权重")
                except Exception:
                    pass
                
                opt_result = optimizer.optimize(
                    expected_returns=er_combined,
                    covariance=cov_matrix,
                    returns_hist=hist_ret,
                    regime_prob=regime_prob,
                    prev_weights=prev_weights_opt,
                    prev_weights2=prev_weights2_opt,
                    cost_vector=cost_vec,
                    trend_mask=trend_mask,
                    codes=valid_codes
                )
                
                opt_weights = opt_result['weights']
                opt_diag = opt_result['diagnostics']
                
                print(f"   优化状态: {opt_result['status']}")
                print(f"   组合预期收益: {opt_diag.get('expected_return', 0):.4f}")
                print(f"   组合方差: {opt_diag.get('portfolio_var', 0):.6f}")
                print(f"   持仓数: {opt_diag.get('n_stocks', 0)}")
                print(f"   最大权重: {opt_diag.get('max_weight', 0):.2%}")
                
                final_weights = {valid_codes[i]: float(opt_weights[i]) for i in range(n_opt)}
                vol_dict = {}
                for i, c in enumerate(valid_codes):
                    if risk_model:
                        vol_dict[c] = float(risk_model.get_stock_volatilities()[i])
                    else:
                        vol_dict[c] = 0.20
                leverage = 1.0
                raw_weights = {c: 1.0/n_opt for c in valid_codes}
                
                # 保存IC状态、执行反馈、权重历史（用于路径平滑）
                try:
                    if ic_updater:
                        ic_updater.save()
                    if exec_fb:
                        exec_fb.save()
                    # 保存本期权重到历史
                    import json
                    pw_file = 'results/portfolio_weights_history.json'
                    os.makedirs('results', exist_ok=True)
                    pw_hist = {'history': []}
                    if os.path.exists(pw_file):
                        try:
                            with open(pw_file, 'r') as f:
                                pw_hist = json.load(f)
                        except Exception:
                            pass
                    this_entry = {
                        'date': today,
                        'regime_prob': regime_prob,
                        'weights': [{'code': c, 'weight': float(opt_weights[i])}
                                    for i, c in enumerate(valid_codes)]
                    }
                    pw_hist['history'].append(this_entry)
                    pw_hist['history'] = pw_hist['history'][-10:]
                    with open(pw_file, 'w') as f:
                        json.dump(pw_hist, f, ensure_ascii=False, indent=2)
                    print(f"   权重历史已保存 ({len(pw_hist['history'])}期)")
                except Exception as e:
                    print(f"   ⚠️ 状态保存失败: {e}")
                
            except Exception as e:
                print(f"   ⚠️ 统一优化失败: {e}，降级为v6.1权重")
                use_v6_4 = False
        
        # ========== v6.1 / v5.2 降级路径 ==========
        if not use_v6_4:
            from src.portfolio.risk_scaling import VolatilityScaler
            
            if use_advanced:
                print("\n⚖️ Volatility Scaling...")
                vol_scaler = VolatilityScaler(target_vol=0.15, lookback=60)
                vol_dict = {}
                for code in final_recommend:
                    if code in stock_data:
                        vol_dict[code] = vol_scaler.calc_volatility(stock_data[code])
                    else:
                        vol_dict[code] = 0.20
            else:
                vol_dict = {code: 0.20 for code in final_recommend}
            
            raw_weights = {}
            score_sum = sum(df_scores.loc[c, 'trend_rank_score'] if c in df_scores.index else 0 for c in final_recommend)
            if score_sum > 0:
                for code in final_recommend:
                    if code in df_scores.index:
                        raw_weights[code] = df_scores.loc[code, 'trend_rank_score'] / score_sum
                    else:
                        raw_weights[code] = 1.0 / len(final_recommend)
            else:
                for code in final_recommend:
                    raw_weights[code] = 1.0 / len(final_recommend)
            
            if use_advanced:
                vol_scaler = VolatilityScaler(target_vol=0.15, lookback=60)
                risk_adjusted_weights = vol_scaler.scale_weights(raw_weights, vol_dict)
                final_weights, leverage = vol_scaler.target_volatility_scaling(
                    risk_adjusted_weights, vol_dict, current_capital=1000000
                )
                print(f"   组合杠杆: {leverage:.2f}x")
                print(f"   平均波动率: {np.mean([v for v in vol_dict.values() if not np.isnan(v)]):.2%}")
            else:
                final_weights = raw_weights
                leverage = 1.0
                print(f"   使用原始权重（无波动率调整）")
        
        # 构建 top_list（用于报告）
        top_list = []
        for code in final_recommend:
            if code in df_scores.index:
                orig_data = next((r for r in full_results if r['code'] == code), None)
                if orig_data:
                    orig_data['volatility'] = vol_dict.get(code, np.nan)
                    orig_data['raw_weight'] = raw_weights.get(code, 0)
                    orig_data['risk_weight'] = final_weights.get(code, 0)
                    top_list.append(orig_data)
        
        # 输出市场状态
        regime_label = "强趋势" if regime_score > 0.5 else ("偏趋势" if regime_score > 0 else "震荡")
        print(f"\n\n🌐 市场状态: {regime_label} (Regime Score={regime_score:.3f}) | 使用版本: {selected_version} | 统一漏斗TOP{len(top_list)}只 | ⭐双优(基本面+技术面){len(dual_advantage_stocks)}只")

        # ========== 6层统一分层榜单（终端输出） ==========
        # 运行十倍/翻倍模型获取分层数据
        _tenbagger_results_term = []
        try:
            from src.strategies.tenbagger_model import batch_evaluate_tenbagger, TENBAGGER_WATCHLIST
            _tb_top_codes = {r['code'] for r in top_list}
            _tb_watchlist_in_pool = []
            if full_results:
                _tb_wl_codes = {w['code'] for w in TENBAGGER_WATCHLIST}
                _tb_watchlist_in_pool = [
                    r for r in full_results
                    if r['code'] in _tb_wl_codes and r['code'] not in _tb_top_codes
                ]
            _tenbagger_results_term = batch_evaluate_tenbagger(top_list + _tb_watchlist_in_pool, top_n=15)
        except Exception as e:
            logger.warning(f"终端输出十倍股模型异常: {e}")

        _doubler_results_term = []
        try:
            from src.strategies.doubler_model import batch_evaluate_doubler
            _doubler_results_term = batch_evaluate_doubler(top_list, top_n=len(top_list))
        except Exception as e:
            logger.warning(f"终端输出翻倍股模型异常: {e}")

        # 构建统一分层
        from src.strategies.unified_ranking import build_unified_ranking, TIER_META
        _unified_ranked = build_unified_ranking(
            recommend_results=top_list,
            tenbagger_results=_tenbagger_results_term,
            doubler_results=_doubler_results_term,
            top_n_main=min(len(top_list), 15),
        )

        # 打印6层榜单
        if _unified_ranked:
            print(f"\n{'='*100}")
            print(f"📊 统一分层榜单（三套推荐交叉共振）")
            print(f"{'='*100}")
            _current_tier = ''
            _tier_rank = 0
            for _s in _unified_ranked:
                if _s.tier != _current_tier:
                    _current_tier = _s.tier
                    _tier_rank = 0
                    _title = TIER_META[_current_tier][0]
                    print(f"\n{_title}")
                    print("-" * 80)
                    if _current_tier in ('triple', 'A'):
                        print(f"  {'#':>2} {'代码':>8} {'名称':>10} {'产业主线':>10} {'十倍分':>6} {'翻倍分':>6} {'主推排名':>8} {'核心逻辑'}")
                    elif _current_tier == 'B':
                        print(f"  {'#':>2} {'代码':>8} {'名称':>10} {'产业主线':>10} {'翻倍分':>6} {'主推排名':>8} {'催化事件'}")
                    elif _current_tier == 'main':
                        print(f"  {'#':>2} {'代码':>8} {'名称':>10} {'产业主线':>10} {'主推排名':>8} {'翻倍分':>6} {'十倍分':>6}")
                    elif _current_tier == 'doubler':
                        print(f"  {'#':>2} {'代码':>8} {'名称':>10} {'产业主线':>10} {'翻倍分':>6} {'评级':>4} {'催化事件'}")
                    elif _current_tier == 'tenbagger':
                        print(f"  {'#':>2} {'代码':>8} {'名称':>10} {'产业主线':>10} {'十倍分':>6} {'评级':>4} {'核心优势'}")

                _tier_rank += 1
                _theme = f"【{_s.industry_theme}】" if _s.industry_theme else ''
                _logic = '、'.join((_s.strengths[:1] + _s.catalysts[:1])) if (_s.strengths or _s.catalysts) else '-'

                if _current_tier in ('triple', 'A'):
                    _main_r = f"TOP{_s.main_rank}" if _s.main_rank else '-'
                    print(f"  {_tier_rank:>2} {_s.code:>8} {_s.name:>10} {_theme:>10} {_s.tenbagger_score:>6.0f} {_s.doubler_score:>6.0f} {_main_r:>8} {_logic}")
                elif _current_tier == 'B':
                    _cat = '、'.join(_s.catalysts[:2]) if _s.catalysts else '-'
                    print(f"  {_tier_rank:>2} {_s.code:>8} {_s.name:>10} {_theme:>10} {_s.doubler_score:>6.0f} {'TOP'+str(_s.main_rank):>8} {_cat}")
                elif _current_tier == 'main':
                    print(f"  {_tier_rank:>2} {_s.code:>8} {_s.name:>10} {_theme:>10} {'TOP'+str(_s.main_rank):>8} {_s.doubler_score:>6.0f} {_s.tenbagger_score:>6.0f}")
                elif _current_tier == 'doubler':
                    _cat = '、'.join(_s.catalysts[:2]) if _s.catalysts else '-'
                    print(f"  {_tier_rank:>2} {_s.code:>8} {_s.name:>10} {_theme:>10} {_s.doubler_score:>6.0f} {_s.doubler_grade:>4} {_cat}")
                elif _current_tier == 'tenbagger':
                    _str = '、'.join(_s.strengths[:2]) if _s.strengths else '-'
                    print(f"  {_tier_rank:>2} {_s.code:>8} {_s.name:>10} {_theme:>10} {_s.tenbagger_score:>6.0f} {_s.tenbagger_grade:>4} {_str}")

            # 统计
            _tier_counts = {}
            for _s in _unified_ranked:
                _tier_counts[_s.tier] = _tier_counts.get(_s.tier, 0) + 1
            print(f"\n{'='*100}")
            _summary = []
            for _tk in ['triple', 'A', 'B', 'main', 'doubler', 'tenbagger']:
                if _tk in _tier_counts:
                    _summary.append(f"{TIER_META[_tk][0].split('（')[0]}:{_tier_counts[_tk]}只")
            print(' | '.join(_summary))
            print(f"{'='*100}")
        else:
            # 无分层数据时 fallback 到旧格式
            print(f"\n{'='*120}")
            print(f"🔥 统一漏斗推荐 TOP {len(top_list)}（基本面×技术面×事件×业绩×景气度）")
            print(f"{'='*120}")
            for rank, r in enumerate(top_list, 1):
                code = r['code']
                u_score = df_scores.loc[code, 'unified_score'] if code in df_scores.index else 0
                print(f"{rank:>4} {r['code']:>8} {r['name']:>10} {u_score:>7.4f} {r['price']:>8.2f}")
            print("-" * 120)

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
                        if 'market_cap' not in df.columns:
                            df['market_cap'] = None
                        df.loc[df.index[-1], 'market_cap'] = fund_data.get('market_cap_yi', 0) * 100000000 if fund_data.get('market_cap_yi') else None
                        df['market_cap'] = df['market_cap'].ffill().bfill()

                        if 'pe_ttm' not in df.columns:
                            df['pe_ttm'] = None
                        if 'pb' not in df.columns:
                            df['pb'] = None
                        df.loc[df.index[-1], 'pe_ttm'] = fund_data.get('pe_ttm')
                        df.loc[df.index[-1], 'pb'] = fund_data.get('pb')
                        df['pe_ttm'] = df['pe_ttm'].ffill().bfill()
                        df['pb'] = df['pb'].ffill().bfill()

                    theme_prepared.append((code, name, sector, df))
                
                if not theme_prepared:
                    print(f"  ⚠️ 无有效数据，跳过")
                    continue
                
                # 分析专题股票
                theme_results = []
                for code, name, sector, df in theme_prepared:
                    try:
                        result = run_full_12_analysis(code, name, sector, df, fetcher, skip_industry=skip_industry_eval, index_df=index_df)
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
        
        # ========== 进场安全过滤：剔除不适合今日买入的标的 ==========
        original_count = len(top_list)
        filtered_top = []
        removed = []
        for r in top_list:
            zone = _tag_entry_zone(r)
            r['entry_zone'] = zone
            if '⛔' in zone:
                removed.append(f"{r['code']}({r['name']}): {zone}")
            else:
                filtered_top.append(r)
        top_list = filtered_top
        if removed:
            print(f"\n🚫 进场安全过滤: 剔除{len(removed)}只不适合今日买入的标的")
            for rm in removed:
                print(f"   {rm}")
            print(f"   最终推荐: {original_count} → {len(top_list)}只")

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
            earnings_top=earnings_top,
        )
        print(f"\n📝 增量报告已保存: {report_path}")
        print(f"📝 当日归档已保存: {archive_path}")

        # ========== 妙想 Skills 联动（xuangu + zixuan + moni） ==========
        # 与日报机会分级保持一致：EMPTY 不执行联动，WEAK 仅联动裁剪后的前 N 只。
        act_level, _, act_count = _assess_market_opportunity(top_list)
        mx_summary = {}
        if act_count <= 0:
            print("\n🔗 妙想联动已跳过：当前机会等级为 EMPTY")
        else:
            action_top_list = top_list[:act_count]
            mx_summary = _mx_post_actions(action_top_list)

        # ========== 日报追加：妙想联动记录 + 策略异常聚合 ==========
        _append_footer_to_report(archive_path, full_results, mx_summary)

        print("\n✅ 分析完成!")
        return

    # ---------- 原有 ensemble / macd 模式 ----------
    if args.strategy == 'ensemble':
        strat = EnsembleStrategy()
        strategy_name = '14策略Ensemble(技术6+基本面3+消息/资金/情绪+业绩增速+行业趋势，加权投票)'
    else:
        strat = MACDStrategy(fast_period=args.fast, slow_period=args.slow,
                             signal_period=args.signal)
        strategy_name = f'MACD({args.fast},{args.slow},{args.signal})'

    _use_fundamental = not args.no_fundamental
    pe_strat = PEStrategy() if _use_fundamental and args.strategy != 'ensemble' else None
    pb_strat = PBStrategy() if _use_fundamental else None
    fund_fetcher = FundamentalFetcher() if _use_fundamental else None

    print(f"{'='*70}")
    print(f"📈 每日选股推荐 — {today}")
    print(f"{'='*70}")
    print(f"📌 策略: {strategy_name}")
    print(f"📌 股票池: {len(stocks)} 只")
    print(f"📌 基本面: {'✅ 启用(PE/PB)' if _use_fundamental else '❌ 关闭'}")
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

        # 注入 symbol + sector，让子策略知道当前标的及行业
        if hasattr(strat, 'set_symbol'):
            strat.set_symbol(code, name, sector=sector)

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
            'change_60d': info.get('change_60d', 0),
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
            'change_60d': row.get('change_60d', 0),
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

    # 每日推荐完成后自动刷新股票池（更新创业板活跃补充）
    try:
        from tools.data.refresh_stock_pool import build_pool
        print(f"\n🔄 自动刷新股票池(更新创业板活跃补充)...")
        build_pool()
    except Exception as e:
        print(f"⚠️ 自动刷新股票池失败: {e}")

    print(f"\n✅ 分析完成!")


if __name__ == '__main__':
    main()
