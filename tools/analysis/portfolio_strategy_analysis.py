#!/usr/bin/env python3
"""
持仓多策略分析工具
使用 11 大策略分析持仓（MA/MACD/RSI/BOLL/KDJ/DUAL + Sentiment/NewsSentiment/PolicyEvent/MoneyFlow + PE/PB）
"""

import sys
import os
import json
import pandas as pd
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.strategies.ma_cross import MACrossStrategy
from src.strategies.macd_cross import MACDStrategy
from src.strategies.rsi_signal import RSIStrategy
from src.strategies.bollinger_band import BollingerBandStrategy
from src.strategies.kdj_signal import KDJStrategy
from src.strategies.dual_momentum import DualMomentumSingleStrategy
from src.strategies.sentiment import SentimentStrategy
from src.strategies.news_sentiment import NewsSentimentStrategy
from src.strategies.policy_event import PolicyEventStrategy
from src.strategies.money_flow import MoneyFlowStrategy
from src.strategies.fundamental_pe import PEStrategy
from src.strategies.fundamental_pb import PBStrategy
from src.data.fetchers.fundamental_fetcher import FundamentalFetcher
import akshare as ak
import baostock as bs
import time

def get_stock_data_bs(code):
    """使用baostock获取历史数据（股票）"""
    prefix = 'sh' if code.startswith(('5', '6')) else 'sz'
    bs_code = f'{prefix}.{code}'
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=1200)).strftime('%Y-%m-%d')
    
    rs = bs.query_history_k_data_plus(bs_code, "date,open,high,low,close,volume", 
                                       start_date=start_date, end_date=end_date, 
                                       frequency="d", adjustflag="2")
    rows = []
    while rs.error_code == '0' and rs.next():
        rows.append(rs.get_row_data())
    
    if rows and len(rows) >= 60:
        df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
        df['date'] = pd.to_datetime(df['date'])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.sort_values('date').reset_index(drop=True)
        return df
    return None

def get_etf_data_akshare(code):
    """使用akshare获取ETF历史数据"""
    try:
        # 确定市场
        if code.startswith('15') or code.startswith('16'):
            symbol = f'sz{code}'  # 深交所ETF
        elif code.startswith('51'):
            symbol = f'sh{code}'  # 上交所ETF
        else:
            symbol = code
        
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=800)).strftime('%Y%m%d')
        
        # 方法1: stock_zh_a_hist (优先)
        try:
            df = ak.stock_zh_a_hist(symbol=symbol, period="日k", start_date=start_date, end_date=end_date, adjust="qfq")
            if not df.empty and len(df) >= 60:
                # 转换列名
                df = df.rename(columns={
                    '日期': 'date',
                    '开盘': 'open',
                    '收盘': 'close',
                    '最高': 'high',
                    '最低': 'low',
                    '成交量': 'volume'
                })
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                return df
        except Exception:
            pass
        
        # 方法2: fund_etf_hist_em
        try:
            df = ak.fund_etf_hist_em(symbol=code, period="日k", start_date=start_date, end_date=end_date, adjust="qfq")
            if not df.empty and len(df) >= 60:
                df = df.rename(columns={
                    '日期': 'date',
                    '开盘': 'open',
                    '收盘': 'close',
                    '最高': 'high',
                    '最低': 'low',
                    '成交量': 'volume'
                })
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                return df
        except Exception:
            pass
        
    except Exception:
        pass
    
    return None

def get_realtime_price(code):
    """获取实时价格"""
    try:
        if code.startswith('6') or code.startswith('5'):
            symbol = f'sh{code}'
        else:
            symbol = f'sz{code}'
        minute_df = ak.stock_zh_a_minute(symbol=symbol, period='1', adjust='')
        if not minute_df.empty:
            return float(minute_df.iloc[-1]['close'])
    except Exception:
        pass
    return None

def main():
    # 读取持仓
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    portfolio_path = os.path.join(base_dir, 'mydate', 'my_portfolio.json')
    if not os.path.exists(portfolio_path):
        portfolio_path = os.path.join(base_dir, 'data', 'my_portfolio.json')
    with open(portfolio_path, 'r') as f:
        portfolio = json.load(f)
    
    fetcher = FundamentalFetcher()
    bs.login()
    
    print("=" * 100)
    print("📊 持仓多策略分析报告（11大策略）")
    print("=" * 100)
    print(f"更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    print("策略: MA | MACD | RSI | BOLL | KDJ | DUAL | Sentiment | NewsSentiment | PolicyEvent(政策) | PE | PB\n")
    
    for holding in portfolio['holdings']:
        code = holding['code']
        name = holding['name']
        avg_cost = holding['avg_cost']
        shares = holding.get('shares', 0)
        
        if shares == 0 or 'comment' in holding:
            continue
        
        print("=" * 100)
        print(f"📈 {code} {name} | 持仓{shares}股 | 成本¥{avg_cost:.2f}")
        print("=" * 100)
        
        # 获取实时价格
        current_price = get_realtime_price(code)
        if current_price:
            current_value = current_price * shares
            pnl = current_value - avg_cost * shares
            pnl_pct = (current_price / avg_cost - 1) * 100
            pnl_emoji = '🟢' if pnl > 0 else ('🔴' if pnl < 0 else '⚪')
            print(f"💰 现价: ¥{current_price:.2f} | 市值: ¥{current_value:,.0f} | 盈亏: {pnl_emoji}¥{pnl:+,.0f} ({pnl_pct:+.2f}%)")
        else:
            print(f"⚠️  无法获取实时价格")
        
        print()
        
        # 获取历史数据
        df = get_stock_data_bs(code)
        
        if df is None or len(df) < 60:
            print("  ⚠️  历史数据不足，无法运行策略分析\n")
            continue
        
        print(f"📊 历史数据: {len(df)}条 ({df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')})")
        
        # 获取基本面数据
        try:
            start_dt = df['date'].iloc[0].strftime('%Y%m%d')
            end_dt = df['date'].iloc[-1].strftime('%Y%m%d')
            fund_df = fetcher.get_daily_basic(code, start_date=start_dt, end_date=end_dt)
            if not fund_df.empty:
                df = fetcher.merge_to_daily(df, fund_df, fill_method='ffill')
                print(f"📊 基本面数据: PE/PB已加载")
        except Exception:
            pass
        
        # 获取行业信息
        industry = None
        industry_pe_data = None
        industry_pb_data = None
        try:
            industry = fetcher.get_industry_classification(code)
            if industry:
                industry_data = fetcher.get_industry_pe_pb_data(code, datalen=min(len(df), 800))
                industry_pe_data = industry_data.get('industry_pe')
                industry_pb_data = industry_data.get('industry_pb')
                if industry_pe_data is not None:
                    print(f"📊 行业: {industry} | 行业PE: {len(industry_pe_data)}条 | 行业PB: {len(industry_pb_data) if industry_pb_data is not None else 0}条")
        except Exception:
            pass
        
        print()
        
        # 运行所有策略
        print("📊 策略信号汇总:")
        print(f"{'策略':>8} {'信号':>6} {'信心':>8} {'仓位':>8} {'理由'}")
        print("-" * 100)
        
        buy_count = 0
        sell_count = 0
        hold_count = 0
        
        # 技术面策略
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
        
        for strat_name, strat in tech_strategies.items():
            try:
                if len(df) < strat.min_bars:
                    print(f"{strat_name:>8} {'数据不足':>6} {'-':>8} {'-':>8} 需要{strat.min_bars}条")
                    continue
                
                sig = strat.safe_analyze(df)
                action_emoji = '🟢' if sig.action == 'BUY' else ('🔴' if sig.action == 'SELL' else '⚪')
                print(f"{strat_name:>8} {action_emoji}{sig.action:>4} {sig.confidence:>7.0%} {sig.position:>7.0%} {sig.reason[:50]}")
                
                if sig.action == 'BUY':
                    buy_count += 1
                elif sig.action == 'SELL':
                    sell_count += 1
                else:
                    hold_count += 1
            except Exception as e:
                print(f"{strat_name:>8} {'错误':>6} {'-':>8} {'-':>8} {str(e)[:40]}")
        
        # 基本面策略（使用可用数据）
        if 'pe_ttm' in df.columns and df['pe_ttm'].notna().sum() > 100:
            try:
                available_data = len(df[df['pe_ttm'].notna()])
                rolling_window = min(available_data, 756)
                
                if industry and industry_pe_data is not None and len(industry_pe_data) > 100:
                    pe_strat = PEStrategy(industry=industry, industry_pe_data=industry_pe_data, rolling_window=rolling_window)
                else:
                    pe_strat = PEStrategy(rolling_window=rolling_window)
                
                pe_strat.min_bars = max(100, available_data)
                
                if len(df) >= pe_strat.min_bars:
                    pe_sig = pe_strat.safe_analyze(df)
                    action_emoji = '🟢' if pe_sig.action == 'BUY' else ('🔴' if pe_sig.action == 'SELL' else '⚪')
                    print(f"{'PE':>8} {action_emoji}{pe_sig.action:>4} {pe_sig.confidence:>7.0%} {pe_sig.position:>7.0%} {pe_sig.reason[:50]}")
                    if pe_sig.action == 'BUY':
                        buy_count += 1
                    elif pe_sig.action == 'SELL':
                        sell_count += 1
                    else:
                        hold_count += 1
            except Exception as e:
                print(f"{'PE':>8} {'错误':>6} {'-':>8} {'-':>8} {str(e)[:40]}")
        else:
            print(f"{'PE':>8} {'无PE数据':>6} {'-':>8} {'-':>8} 缺少PE数据")
        
        if 'pb' in df.columns and df['pb'].notna().sum() > 100:
            try:
                available_data = len(df[df['pb'].notna()])
                rolling_window = min(available_data, 756)
                
                roe_passes, _, _ = fetcher.get_roe_for_filter(code)
                if industry and industry_pb_data is not None and len(industry_pb_data) > 100:
                    pb_strat = PBStrategy(industry=industry, industry_pb_data=industry_pb_data, min_roe=8.0 if roe_passes else 0, rolling_window=rolling_window)
                else:
                    pb_strat = PBStrategy(min_roe=8.0 if roe_passes else 0, rolling_window=rolling_window)
                
                pb_strat.min_bars = max(100, available_data)
                
                if len(df) >= pb_strat.min_bars:
                    pb_sig = pb_strat.safe_analyze(df)
                    action_emoji = '🟢' if pb_sig.action == 'BUY' else ('🔴' if pb_sig.action == 'SELL' else '⚪')
                    print(f"{'PB':>8} {action_emoji}{pb_sig.action:>4} {pb_sig.confidence:>7.0%} {pb_sig.position:>7.0%} {pb_sig.reason[:50]}")
                    if pb_sig.action == 'BUY':
                        buy_count += 1
                    elif pb_sig.action == 'SELL':
                        sell_count += 1
                    else:
                        hold_count += 1
            except Exception as e:
                print(f"{'PB':>8} {'错误':>6} {'-':>8} {'-':>8} {str(e)[:40]}")
        else:
            print(f"{'PB':>8} {'无PB数据':>6} {'-':>8} {'-':>8} 缺少PB数据")
        
        print("-" * 100)
        print(f"汇总: 🟢买入 {buy_count} | 🔴卖出 {sell_count} | ⚪观望 {hold_count}")
        
        # 综合建议
        total_signals = buy_count + sell_count + hold_count
        if total_signals == 0:
            suggestion = "⚠️  无有效信号"
        elif buy_count > sell_count and buy_count >= 3:
            suggestion = "🟢 多数策略看多，建议持有或加仓"
        elif sell_count > buy_count and sell_count >= 3:
            suggestion = "🔴 多数策略看空，建议减仓或止损"
        elif buy_count >= 4:
            suggestion = "🟢 强烈看多，建议加仓"
        elif sell_count >= 4:
            suggestion = "🔴 强烈看空，建议止损"
        elif buy_count == sell_count:
            suggestion = "⚪ 策略分歧，建议观望"
        else:
            suggestion = "⚪ 信号不明确，建议谨慎"
        
        print(f"建议: {suggestion}")
        print()
    
    bs.logout()
    fetcher._bs_logout()
    
    print("=" * 100)
    print("✅ 多策略分析完成!")

if __name__ == '__main__':
    main()
