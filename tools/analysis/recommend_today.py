#!/usr/bin/env python3
"""
📈 每日选股推荐工具

功能:
1. 对股票池中所有股票获取最新数据
2. 策略模式: macd(单MACD) | ensemble(7策略) | full_11(11大策略，与持仓分析一致)
3. 输出：该买哪些、该卖哪些、观望哪些；每只附带信号强度、建议仓位、理由

用法:
    python3 tools/analysis/recommend_today.py --strategy full_11 --pool stock_pool_all.json --top 10
    python3 tools/analysis/recommend_today.py --pool stock_pool.json  # 默认池可选
    python3 tools/analysis/recommend_today.py --strategy ensemble --fast 12 --slow 30 --signal 9

11策略: MA | MACD | RSI | BOLL | KDJ | DUAL | Sentiment | NewsSentiment | PolicyEvent | MoneyFlow | PE | PB
默认池: stock_pool_all.json（812只），可 --pool stock_pool.json（100只）缩小范围。

输出:
    终端报告 + output/daily_recommendation_YYYY-MM-DD.md
"""

import sys
import os
import json
import time
import argparse
from datetime import datetime, timedelta
from collections import defaultdict

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

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


# ============================================================
# 数据获取
# ============================================================

def fetch_stock_data(code: str, days: int = 200) -> pd.DataFrame:
    """通过 baostock 获取数据"""
    import baostock as bs

    prefix = 'sh' if code.startswith(('5', '6')) else 'sz'
    bs_code = f'{prefix}.{code}'

    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=int(days * 1.6))).strftime('%Y-%m-%d')

    rs = bs.query_history_k_data_plus(
        bs_code,
        'date,open,high,low,close,volume,amount',
        start_date=start_date,
        end_date=end_date,
        frequency='d',
        adjustflag='2',
    )

    rows = []
    while rs.error_code == '0' and rs.next():
        rows.append(rs.get_row_data())

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume', 'amount'])
    for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['date'] = pd.to_datetime(df['date'])
    df.dropna(subset=['close'], inplace=True)
    return df


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
    ma20 = float(close.iloc[-20:].mean()) if len(df) >= 20 else ma5

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
        'ma20': round(ma20, 2),
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

    # 3. 量比 (15分) — 放量更好
    if sig.action == 'BUY':
        if info['volume_ratio'] > 1.5:
            score += 15  # 放量金叉
        elif info['volume_ratio'] > 1.0:
            score += 8
        else:
            score += 3   # 缩量金叉信号偏弱

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

def run_full_11_analysis(code: str, name: str, sector: str, df: pd.DataFrame, fetcher: FundamentalFetcher) -> dict:
    """
    运行 11 大策略: MA, MACD, RSI, BOLL, KDJ, DUAL, Sentiment, NewsSentiment, PolicyEvent, MoneyFlow, PE, PB。
    返回 buy_count, sell_count, hold_count, score（买-卖加权）, signals 列表。
    """
    tech_strategies = {
        'MA': MACrossStrategy(),
        'MACD': MACDStrategy(),
        'RSI': RSIStrategy(),
        'BOLL': BollingerBandStrategy(),
        'KDJ': KDJStrategy(),
        'DUAL': DualMomentumSingleStrategy(),
        'Sentiment': SentimentStrategy(),
        'NewsSentiment': NewsSentimentStrategy(symbol=code),
        'PolicyEvent': PolicyEventStrategy(),
        'MoneyFlow': MoneyFlowStrategy(symbol=code),
    }
    buy_count = sell_count = hold_count = 0
    signals = []
    score_sum = 0.0  # BUY +position, SELL -position, HOLD 0

    for strat_name, strat in tech_strategies.items():
        try:
            if len(df) < strat.min_bars:
                continue
            sig = strat.safe_analyze(df)
            if sig.action == 'BUY':
                buy_count += 1
                score_sum += sig.position
            elif sig.action == 'SELL':
                sell_count += 1
                score_sum -= sig.position
            else:
                hold_count += 1
            signals.append((strat_name, sig.action, sig.confidence, sig.reason[:40]))
        except Exception:
            pass

    industry = None
    industry_pe_data = industry_pb_data = None
    try:
        industry = fetcher.get_industry_classification(code)
        if industry:
            industry_data = fetcher.get_industry_pe_pb_data(code, datalen=min(len(df), 800))
            industry_pe_data = industry_data.get('industry_pe')
            industry_pb_data = industry_data.get('industry_pb')
    except Exception:
        pass

    if 'pe_ttm' in df.columns and df['pe_ttm'].notna().sum() > 100:
        try:
            available_data = len(df[df['pe_ttm'].notna()])
            rolling_window = min(available_data, 756)
            pe_strat = PEStrategy(industry=industry, industry_pe_data=industry_pe_data, rolling_window=rolling_window) if industry and industry_pe_data is not None else PEStrategy(rolling_window=rolling_window)
            pe_strat.min_bars = max(100, available_data)
            if len(df) >= pe_strat.min_bars:
                pe_sig = pe_strat.safe_analyze(df)
                if pe_sig.action == 'BUY':
                    buy_count += 1
                    score_sum += pe_sig.position
                elif pe_sig.action == 'SELL':
                    sell_count += 1
                    score_sum -= pe_sig.position
                else:
                    hold_count += 1
                signals.append(('PE', pe_sig.action, pe_sig.confidence, pe_sig.reason[:40]))
        except Exception:
            pass

    if 'pb' in df.columns and df['pb'].notna().sum() > 100:
        try:
            available_data = len(df[df['pb'].notna()])
            rolling_window = min(available_data, 756)
            roe_passes, _, _ = fetcher.get_roe_for_filter(code)
            pb_strat = PBStrategy(industry=industry, industry_pb_data=industry_pb_data, min_roe=8.0 if roe_passes else 0, rolling_window=rolling_window) if industry and industry_pb_data is not None else PBStrategy(min_roe=8.0 if roe_passes else 0, rolling_window=rolling_window)
            pb_strat.min_bars = max(100, available_data)
            if len(df) >= pb_strat.min_bars:
                pb_sig = pb_strat.safe_analyze(df)
                if pb_sig.action == 'BUY':
                    buy_count += 1
                    score_sum += pb_sig.position
                elif pb_sig.action == 'SELL':
                    sell_count += 1
                    score_sum -= pb_sig.position
                else:
                    hold_count += 1
                signals.append(('PB', pb_sig.action, pb_sig.confidence, pb_sig.reason[:40]))
        except Exception:
            pass

    # 综合得分：买数量*2 - 卖数量*2 + 仓位加权
    score = buy_count * 2 - sell_count * 2 + round(score_sum, 2)
    price = float(df['close'].iloc[-1])
    change_5d = (price / float(df['close'].iloc[-6]) - 1) * 100 if len(df) > 5 else 0
    change_20d = (price / float(df['close'].iloc[-21]) - 1) * 100 if len(df) > 20 else 0
    return {
        'code': code,
        'name': name,
        'sector': sector,
        'buy_count': buy_count,
        'sell_count': sell_count,
        'hold_count': hold_count,
        'score': score,
        'price': price,
        'change_5d': round(change_5d, 2),
        'change_20d': round(change_20d, 2),
        'signals': signals,
    }


# ============================================================
# 主逻辑
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='每日选股推荐')
    parser.add_argument('--pool', type=str, default='stock_pool_all.json', help='股票池（默认大池 812 只）')
    parser.add_argument('--max-pool', type=int, default=0, help='最多扫描池内前 N 只（0=全部）')
    parser.add_argument('--strategy', type=str, default='full_11',
                        choices=['macd', 'ensemble', 'full_11'],
                        help='策略: macd | ensemble(7策略) | full_11(11大策略)')
    parser.add_argument('--fast', type=int, default=12, help='MACD快线(仅macd模式)')
    parser.add_argument('--slow', type=int, default=30, help='MACD慢线(仅macd模式)')
    parser.add_argument('--signal', type=int, default=9, help='MACD信号线(仅macd模式)')
    parser.add_argument('--top', type=int, default=20, help='推荐TOP N只')
    parser.add_argument('--fundamental', action='store_true', default=True,
                        help='启用基本面分析(PE/PB)')
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

    # ---------- 11 策略全量模式 ----------
    if args.strategy == 'full_11':
        strategy_name = '11大策略(MA|MACD|RSI|BOLL|KDJ|DUAL|Sentiment|NewsSentiment|PolicyEvent|MoneyFlow|PE|PB)'
        print(f"{'='*70}")
        print(f"📈 每日选股推荐 — {today} [全策略+大池]")
        print(f"{'='*70}")
        print(f"📌 策略: {strategy_name}")
        print(f"📌 股票池: {len(stocks)} 只")
        print(f"📌 推荐TOP: {args.top} 只")
        print()

        import baostock as bs
        bs.login()
        fetcher = FundamentalFetcher()
        full_results = []
        fail_count = 0
        BATCH_SIZE = 80

        for i, stock in enumerate(stocks, 1):
            code = stock.get('code') or stock.get('symbol', '')
            name = stock.get('name', '')
            sector = stock.get('sector', '')
            if not code:
                continue
            if i > 1 and (i - 1) % BATCH_SIZE == 0:
                try:
                    bs.logout()
                except Exception:
                    pass
                time.sleep(0.5)
                bs.login()
            if i % 50 == 0 or i == len(stocks) or len(stocks) <= 30:
                pct = i / len(stocks) * 100
                bar = '█' * int(pct / 2) + '░' * (50 - int(pct / 2))
                print(f"\r  [{bar}] {i}/{len(stocks)} ({pct:.0f}%)", end='', flush=True)

            df = pd.DataFrame()
            for attempt in range(3):
                df = fetch_stock_data(code, 200)
                if len(df) >= 60:
                    break
                if attempt < 2:
                    try:
                        bs.logout()
                    except Exception:
                        pass
                    time.sleep(0.3)
                    bs.login()
            if len(df) < 60:
                fail_count += 1
                continue
            try:
                start_dt = df['date'].iloc[0].strftime('%Y%m%d')
                end_dt = df['date'].iloc[-1].strftime('%Y%m%d')
                fund_df = fetcher.get_daily_basic(code, start_date=start_dt, end_date=end_dt)
                if not fund_df.empty:
                    df = fetcher.merge_to_daily(df, fund_df, fill_method='ffill')
            except Exception:
                pass
            res = run_full_11_analysis(code, name, sector, df, fetcher)
            full_results.append(res)
            time.sleep(0.03)

        try:
            bs.logout()
        except Exception:
            pass
        fetcher._bs_logout()

        if fail_count:
            print(f"\n⚠️  {fail_count} 只数据不足，已跳过")
        if not full_results:
            print("\n⚠️ 无有效分析结果")
            return

        full_results.sort(key=lambda x: x['score'], reverse=True)
        top_list = full_results[:args.top]

        print(f"\n\n{'='*70}")
        print(f"🟢 11策略选股 TOP {len(top_list)}（按综合得分排序）")
        print(f"{'='*70}")
        print(f"{'排名':>4} {'代码':>8} {'名称':>10} {'价格':>8} {'得分':>6} {'买':>3} {'卖':>3} {'观':>3} {'5日%':>7} {'20日%':>7} {'板块'}")
        print("-" * 75)
        for rank, r in enumerate(top_list, 1):
            print(f"{rank:>4} {r['code']:>8} {r['name']:>10} {r['price']:>8.2f} {r['score']:>6.1f} "
                  f"{r['buy_count']:>3} {r['sell_count']:>3} {r['hold_count']:>3} "
                  f"{r['change_5d']:>+7.2f} {r['change_20d']:>+7.2f} {str(r['sector'])[:12]}")
        print("-" * 75)
        print("\n📋 策略信号明细（TOP3）:")
        for rank, r in enumerate(top_list[:3], 1):
            print(f"\n  {rank}. {r['code']} {r['name']} (得分 {r['score']:.1f}, 买{r['buy_count']}/卖{r['sell_count']}/观{r['hold_count']})")
            for sn, action, conf, reason in r['signals']:
                em = '🟢' if action == 'BUY' else ('🔴' if action == 'SELL' else '⚪')
                print(f"      {sn:>12} {em} {action:>4} {conf:.0%} {reason[:45]}")
        output_dir = os.path.join(os.path.dirname(__file__), '..', 'output')
        os.makedirs(output_dir, exist_ok=True)
        md_path = os.path.join(output_dir, f'daily_recommendation_{today}.md')
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(f"# 📈 每日选股推荐 — {today}（11策略+大池）\n\n")
            f.write(f"**策略**: {strategy_name}\n")
            f.write(f"**股票池**: {len(stocks)} 只，有效 {len(full_results)} 只\n\n")
            f.write("## TOP 推荐\n\n")
            f.write("| 排名 | 代码 | 名称 | 价格 | 得分 | 买 | 卖 | 观 | 5日% | 20日% | 板块 |\n")
            f.write("|------|------|------|------|------|----|----|----|------|-------|------|\n")
            for rank, r in enumerate(top_list, 1):
                f.write(f"| {rank} | {r['code']} | {r['name']} | {r['price']:.2f} | {r['score']:.1f} | "
                        f"{r['buy_count']} | {r['sell_count']} | {r['hold_count']} | "
                        f"{r['change_5d']:+.2f} | {r['change_20d']:+.2f} | {r['sector']} |\n")
        print(f"\n📝 报告已保存: {md_path}")
        print("\n✅ 分析完成!")
        return

    # ---------- 原有 macd / ensemble 模式 ----------
    if args.strategy == 'ensemble':
        strat = EnsembleStrategy(mode='majority', buy_threshold=0.5, sell_threshold=0.5)
        strategy_name = '7策略组合(MA+MACD+RSI+BOLL+KDJ+DUAL+PE)'
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

    import baostock as bs
    bs.login()
    BATCH_SIZE = 80
    all_results = []
    fail_count = 0

    for i, stock in enumerate(stocks, 1):
        code = stock['code']
        name = stock['name']
        sector = stock.get('sector', '')

        # 分批重连
        if i > 1 and (i - 1) % BATCH_SIZE == 0:
            try:
                bs.logout()
            except Exception:
                pass
            time.sleep(0.5)
            bs.login()

        # 进度
        if len(stocks) <= 50:
            print(f"\r  分析 [{i}/{len(stocks)}] {code} {name} ...", end='', flush=True)
        elif i == 1 or i % 50 == 0 or i == len(stocks):
            pct = i / len(stocks) * 100
            bar = '█' * int(pct / 2) + '░' * (50 - int(pct / 2))
            print(f"\r  [{bar}] {i}/{len(stocks)} ({pct:.0f}%)", end='', flush=True)

        # 获取数据（带重试）
        df = pd.DataFrame()
        for attempt in range(3):
            df = fetch_stock_data(code, 200)
            if len(df) >= strat.min_bars:
                break
            if attempt < 2:
                try:
                    bs.logout()
                except Exception:
                    pass
                time.sleep(0.3)
                bs.login()

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

    try:
        bs.logout()
    except Exception:
        pass

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
    # 保存 Markdown 报告
    # ============================================================
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'output')
    os.makedirs(output_dir, exist_ok=True)
    md_path = os.path.join(output_dir, f'daily_recommendation_{today}.md')

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(f"# 📈 每日选股推荐 — {today}\n\n")
        f.write(f"**MACD参数**: ({args.fast},{args.slow},{args.signal})\n")
        f.write(f"**股票池**: {len(stocks)} 只\n")
        f.write(f"**有效分析**: {len(df_all)} 只\n\n")

        # 市场总览
        f.write("## 一、市场总览\n\n")
        f.write(f"| 信号 | 数量 | 占比 |\n")
        f.write(f"|------|------|------|\n")
        f.write(f"| 🟢 买入 | {len(buy_stocks)} | {len(buy_stocks)/len(df_all)*100:.1f}% |\n")
        f.write(f"| 🔴 卖出 | {len(sell_stocks)} | {len(sell_stocks)/len(df_all)*100:.1f}% |\n")
        f.write(f"| ⚪ 观望 | {len(hold_stocks)} | {len(hold_stocks)/len(df_all)*100:.1f}% |\n\n")

        # 买入推荐
        f.write("## 二、买入推荐\n\n")
        if len(buy_stocks) > 0:
            f.write("| 排名 | 代码 | 名称 | 价格 | 评分 | 信心 | 建议仓位 | 5日涨幅 | 量比 | 趋势 | 理由 |\n")
            f.write("|------|------|------|------|------|------|---------|--------|------|------|------|\n")
            for rank, (_, row) in enumerate(buy_stocks.head(args.top).iterrows(), 1):
                f.write(f"| {rank} | {row['code']} | {row['name']} | "
                        f"¥{row['price']:.2f} | {row['score']:.1f} | "
                        f"{row['confidence']:.0%} | {row['position']:.0%} | "
                        f"{row['change_5d']:+.2f}% | {row['volume_ratio']:.1f}x | "
                        f"{row['trend']} | {row['reason'][:40]} |\n")
        else:
            f.write("今日无买入信号，建议空仓观望。\n")

        # 卖出预警
        f.write("\n## 三、卖出预警\n\n")
        if len(sell_stocks) > 0:
            f.write("| 排名 | 代码 | 名称 | 价格 | 5日涨幅 | 理由 |\n")
            f.write("|------|------|------|------|--------|------|\n")
            for rank, (_, row) in enumerate(sell_stocks.head(20).iterrows(), 1):
                f.write(f"| {rank} | {row['code']} | {row['name']} | "
                        f"¥{row['price']:.2f} | {row['change_5d']:+.2f}% | "
                        f"{row['reason'][:50]} |\n")
        else:
            f.write("今日无卖出信号。\n")

        # 操盘建议
        f.write("\n## 四、操盘建议（10万元资金）\n\n")
        if len(buy_stocks) > 0:
            top_buys = buy_stocks.head(min(5, len(buy_stocks)))
            total_score = top_buys['score'].sum()

            f.write("| 代码 | 名称 | 价格 | 建议仓位 | 建议金额 | 手数 | 理由 |\n")
            f.write("|------|------|------|---------|---------|------|------|\n")
            total_used = 0
            for _, row in top_buys.iterrows():
                weight = min(row['score'] / total_score, max_per_stock)
                amount = total_capital * weight
                shares = int(amount / row['price'] / 100) * 100
                if shares <= 0:
                    continue
                actual = shares * row['price']
                total_used += actual
                f.write(f"| {row['code']} | {row['name']} | ¥{row['price']:.2f} | "
                        f"{weight:.0%} | ¥{actual:,.0f} | {shares}股 | "
                        f"{row['reason'][:35]} |\n")

            f.write(f"\n- **预计投入**: ¥{total_used:,.0f}\n")
            f.write(f"- **预留现金**: ¥{total_capital - total_used:,.0f}\n")
        else:
            f.write("今日建议：**空仓观望**，等待MACD金叉信号。\n")

        # 风险提示
        f.write("\n## ⚠️ 风险提示\n\n")
        f.write("1. 本推荐基于MACD技术指标分析，仅供参考，不构成投资建议\n")
        f.write("2. 股市有风险，入市需谨慎\n")
        f.write("3. 建议设置止损位（买入价-8%），严格执行\n")
        f.write("4. 单只股票仓位不超过30%，分散风险\n")
        f.write(f"5. 策略回测5个月平均收益 +9.4%，但历史收益不代表未来\n")

    print(f"\n📝 详细报告已保存: {md_path}")
    print(f"\n✅ 分析完成!")


if __name__ == '__main__':
    main()
