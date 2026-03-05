#!/usr/bin/env python3
"""
单股票多策略分析工具
使用多策略分析单只股票（11 单策略 + PE+PB双因子 + 多策略/保守/均衡/激进/V33 组合）

用法:
    python3 tools/analysis/analyze_single_stock.py 002015
    python3 tools/analysis/analyze_single_stock.py 002015 --name "协鑫能科"
"""

import sys
import os
import pandas as pd
from datetime import datetime, timedelta
import argparse
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

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
from src.strategies.fundamental_pe_pb import PE_PB_CombinedStrategy
from src.strategies.ensemble import (
    EnsembleStrategy,
    ConservativeEnsemble,
    BalancedEnsemble,
    AggressiveEnsemble,
    V33EnsembleStrategy,
)
from src.data.fetchers.fundamental_fetcher import FundamentalFetcher
from src.data.fetchers.market_data import MarketData
import akshare as ak
import baostock as bs


def get_stock_data_bs(code):
    """使用baostock获取历史数据（优先）"""
    prefix = 'sh' if code.startswith(('5', '6')) else 'sz'
    bs_code = f'{prefix}.{code}'
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=1200)).strftime('%Y-%m-%d')
    
    rs = bs.query_history_k_data_plus(bs_code, "date,open,high,low,close,volume,amount", 
                                       start_date=start_date, end_date=end_date, 
                                       frequency="d", adjustflag="2")
    rows = []
    while rs.error_code == '0' and rs.next():
        rows.append(rs.get_row_data())
    
    if rows and len(rows) >= 60:
        df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume', 'amount'])
        df['date'] = pd.to_datetime(df['date'])
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.sort_values('date').reset_index(drop=True)
        return df
    return None


def get_stock_data_akshare(code):
    """使用akshare获取最新数据（备用）"""
    try:
        if code.startswith('6') or code.startswith('5'):
            symbol = f'sh{code}'
        else:
            symbol = f'sz{code}'
        
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=1200)).strftime('%Y%m%d')
        
        # 尝试多种akshare接口
        df = None
        try:
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
            if not df.empty:
                df = df.rename(columns={
                    '日期': 'date',
                    '开盘': 'open',
                    '收盘': 'close',
                    '最高': 'high',
                    '最低': 'low',
                    '成交量': 'volume',
                    '成交额': 'amount'
                })
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                return df
        except Exception:
            pass
        
        # 备用方法：使用实时行情
        try:
            spot_df = ak.stock_zh_a_spot_em()
            stock_info = spot_df[spot_df['代码'] == code]
            if not stock_info.empty:
                # 至少返回一个数据点
                current_price = float(stock_info.iloc[0]['最新价'])
                df = pd.DataFrame([{
                    'date': datetime.now(),
                    'open': current_price,
                    'high': current_price,
                    'low': current_price,
                    'close': current_price,
                    'volume': 0,
                    'amount': 0
                }])
                return df
        except Exception:
            pass
    except Exception:
        pass
    return None


def get_etf_data_akshare(code):
    """使用 akshare 获取 ETF 历史数据（与 portfolio_strategy_analysis 保持一致）"""
    try:
        if code.startswith('15') or code.startswith('16'):
            symbol = f'sz{code}'
        elif code.startswith('51'):
            symbol = f'sh{code}'
        else:
            symbol = code
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=800)).strftime('%Y%m%d')
        # 方法1: stock_zh_a_hist（period 用 daily 兼容新版本 akshare）
        try:
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
            if not df.empty and len(df) >= 60:
                df = df.rename(columns={
                    '日期': 'date', '开盘': 'open', '收盘': 'close',
                    '最高': 'high', '最低': 'low', '成交量': 'volume'
                })
                if '成交额' in df.columns:
                    df = df.rename(columns={'成交额': 'amount'})
                else:
                    df['amount'] = 0
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                return df
        except Exception:
            pass
        # 方法2: fund_etf_hist_em（period 用 daily 兼容新版本 akshare）
        try:
            df = ak.fund_etf_hist_em(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
            if not df.empty and len(df) >= 60:
                df = df.rename(columns={
                    '日期': 'date', '开盘': 'open', '收盘': 'close',
                    '最高': 'high', '最低': 'low', '成交量': 'volume'
                })
                if '成交额' in df.columns:
                    df = df.rename(columns={'成交额': 'amount'})
                else:
                    df['amount'] = 0
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                return df
        except Exception:
            pass
    except Exception:
        pass
    return None


def get_etf_data_marketdata(code):
    """使用 MarketData（东方财富 push2his）获取 ETF 日 K，作为 akshare 后的备选"""
    try:
        md = MarketData(use_cache=True)
        df = md.get_history(code, days=800)
        if df is None or len(df) < 60:
            return None
        df = df[['date', 'open', 'high', 'low', 'close', 'volume']].copy()
        if 'amount' not in df.columns:
            df['amount'] = 0
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        return df
    except Exception as e:
        print(f"  MarketData 获取失败: {e}")
        return None


def get_etf_data_direct(code):
    """直接用东方财富 push2his 接口请求 ETF 日 K（最后手段）"""
    try:
        secid = f"1.{code}" if code.startswith('5') else f"0.{code}"
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "1",
            "end": "20500101",
            "lmt": "800",
        }
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()
        if not data.get("data") or not data["data"].get("klines"):
            return None
        rows = []
        for k in data["data"]["klines"]:
            parts = k.split(",")
            rows.append({
                "date": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
            })
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df["amount"] = 0
        df = df.sort_values("date").reset_index(drop=True)
        if len(df) < 60:
            return None
        return df
    except Exception as e:
        print(f"  直接 push2his 请求失败: {e}")
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


def get_stock_name(code):
    """获取股票名称"""
    try:
        if code.startswith('6') or code.startswith('5'):
            symbol = f'sh{code}'
        else:
            symbol = f'sz{code}'
        spot_df = ak.stock_zh_a_spot_em()
        stock_info = spot_df[spot_df['代码'] == code]
        if not stock_info.empty:
            return stock_info.iloc[0]['名称']
    except Exception:
        pass
    return None


def analyze_stock(code: str, name: str = None):
    """分析单只股票"""
    
    # 获取股票名称
    if not name:
        name = get_stock_name(code)
        if not name:
            name = "未知"
    
    print("=" * 100)
    print(f"📈 {code} {name} - 多策略分析报告")
    print("=" * 100)
    print(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # 获取实时价格
    current_price = get_realtime_price(code)
    if current_price:
        print(f"💰 当前价格: ¥{current_price:.2f}")
    else:
        print(f"⚠️  无法获取实时价格")
    print()
    
    # 初始化数据源
    fetcher = FundamentalFetcher()
    bs.login()
    
    # 获取历史数据（优先baostock，失败则用akshare）
    print("📡 正在获取历史数据...")
    df = None
    try:
        df = get_stock_data_bs(code)
        if df is not None and len(df) >= 60:
            print("  ✅ 使用baostock获取数据")
    except Exception:
        pass
    
    if df is None or len(df) < 60:
        print("  ⚠️  baostock数据不足，尝试akshare...")
        try:
            df = get_stock_data_akshare(code)
            if df is not None and len(df) >= 60:
                print("  ✅ 使用akshare获取数据")
        except Exception as e:
            print(f"  ⚠️  akshare获取失败: {str(e)[:50]}")
    
    if df is None or len(df) < 60:
        if (code.startswith('5') and len(code) == 6) or code.startswith('159'):
            print("  ⚠️  尝试 ETF 专用接口...")
            try:
                df = get_etf_data_akshare(code)
                if df is not None and len(df) >= 60:
                    print("  ✅ ETF 接口(akshare)获取数据成功")
            except Exception as e:
                print(f"  ⚠️  ETF akshare 失败: {str(e)[:50]}")
            if df is None or len(df) < 60:
                df = get_etf_data_marketdata(code)
                if df is not None and len(df) >= 60:
                    print("  ✅ ETF 接口(MarketData/push2his)获取数据成功")
            if df is None or len(df) < 60:
                df = get_etf_data_direct(code)
                if df is not None and len(df) >= 60:
                    print("  ✅ ETF 接口(直接 push2his)获取数据成功")
        if df is None or len(df) < 60:
            print("  ❌ 历史数据不足，无法运行策略分析")
            try:
                bs.logout()
            except Exception:
                pass
            return
    
    print(f"  ✅ 历史数据: {len(df)}条 ({df['date'].iloc[0].strftime('%Y-%m-%d')} ~ {df['date'].iloc[-1].strftime('%Y-%m-%d')})")
    
    # 获取基本面数据
    print("📡 正在获取基本面数据...")
    try:
        start_dt = df['date'].iloc[0].strftime('%Y%m%d')
        end_dt = df['date'].iloc[-1].strftime('%Y%m%d')
        fund_df = fetcher.get_daily_basic(code, start_date=start_dt, end_date=end_dt)
        if not fund_df.empty:
            df = fetcher.merge_to_daily(df, fund_df, fill_method='ffill')
            print(f"  ✅ 基本面数据: PE/PB已加载")
        else:
            print(f"  ⚠️  未获取到基本面数据")
    except Exception as e:
        print(f"  ⚠️  获取基本面数据失败: {str(e)[:50]}")
    
    # 获取行业信息
    print("📡 正在获取行业信息...")
    industry = None
    industry_pe_data = None
    industry_pb_data = None
    try:
        industry = fetcher.get_industry_classification(code)
        if industry:
            print(f"  ✅ 行业: {industry}")
            industry_data = fetcher.get_industry_pe_pb_data(code, datalen=min(len(df), 800))
            industry_pe_data = industry_data.get('industry_pe')
            industry_pb_data = industry_data.get('industry_pb')
            if industry_pe_data is not None:
                print(f"  ✅ 行业PE数据: {len(industry_pe_data)}条")
            if industry_pb_data is not None:
                print(f"  ✅ 行业PB数据: {len(industry_pb_data)}条")
        else:
            print(f"  ⚠️  未获取到行业信息")
    except Exception as e:
        print(f"  ⚠️  获取行业信息失败: {str(e)[:50]}")
    
    print()
    
    # 显示最新数据摘要
    latest = df.iloc[-1]
    print("📊 最新数据摘要:")
    print(f"  日期: {latest['date'].strftime('%Y-%m-%d')}")
    print(f"  收盘: ¥{latest['close']:.2f}")
    print(f"  涨跌: {latest['close'] - df.iloc[-2]['close']:+.2f} ({((latest['close'] / df.iloc[-2]['close'] - 1) * 100):+.2f}%)")
    print(f"  成交量: {latest['volume']:,.0f} 手")
    if 'pe_ttm' in df.columns and pd.notna(latest.get('pe_ttm')):
        print(f"  PE(TTM): {latest['pe_ttm']:.2f}")
    if 'pb' in df.columns and pd.notna(latest.get('pb')):
        print(f"  PB: {latest['pb']:.2f}")
    print()
    
    # 运行所有策略
    print("=" * 100)
    print("📊 策略信号汇总 (11单策略 + PE+PB + 5组合)")
    print("=" * 100)
    print(f"{'策略':>8} {'信号':>8} {'信心':>10} {'仓位':>10} {'理由'}")
    print("-" * 100)
    
    buy_count = 0
    sell_count = 0
    hold_count = 0
    signals = []
    
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
                print(f"{strat_name:>8} {'数据不足':>8} {'-':>10} {'-':>10} 需要{strat.min_bars}条")
                continue
            
            sig = strat.safe_analyze(df)
            action_emoji = '🟢' if sig.action == 'BUY' else ('🔴' if sig.action == 'SELL' else '⚪')
            print(f"{strat_name:>8} {action_emoji}{sig.action:>6} {sig.confidence:>9.1%} {sig.position:>9.1%} {sig.reason[:45]}")
            signals.append((strat_name, sig))
            
            if sig.action == 'BUY':
                buy_count += 1
            elif sig.action == 'SELL':
                sell_count += 1
            else:
                hold_count += 1
        except Exception as e:
            print(f"{strat_name:>8} {'错误':>8} {'-':>10} {'-':>10} {str(e)[:40]}")
    
    # 基本面策略 - PE（与策略内过滤一致：0 < pe_ttm <= 100）
    if 'pe_ttm' in df.columns and df['pe_ttm'].notna().sum() > 100:
        try:
            pe_valid = df['pe_ttm'].dropna()
            pe_valid = pe_valid[(pe_valid > 0) & (pe_valid <= 100)]
            valid_pe_count = len(pe_valid)
            rolling_window = min(valid_pe_count, 756)
            
            if industry and industry_pe_data is not None and len(industry_pe_data) > 100:
                pe_strat = PEStrategy(industry=industry, industry_pe_data=industry_pe_data, rolling_window=rolling_window)
            else:
                pe_strat = PEStrategy(rolling_window=rolling_window)
            
            pe_strat.min_bars = max(100, min(valid_pe_count, 756))
            
            if valid_pe_count >= pe_strat.min_bars:
                pe_sig = pe_strat.safe_analyze(df)
                action_emoji = '🟢' if pe_sig.action == 'BUY' else ('🔴' if pe_sig.action == 'SELL' else '⚪')
                print(f"{'PE':>8} {action_emoji}{pe_sig.action:>6} {pe_sig.confidence:>9.1%} {pe_sig.position:>9.1%} {pe_sig.reason[:45]}")
                signals.append(('PE', pe_sig))
                if pe_sig.action == 'BUY':
                    buy_count += 1
                elif pe_sig.action == 'SELL':
                    sell_count += 1
                else:
                    hold_count += 1
            else:
                print(f"{'PE':>8} {'观望':>8} {'0%':>10} {'50%':>10} PE有效条数不足(需至少100条，实际{valid_pe_count}条，PE>100已过滤)")
        except Exception as e:
            print(f"{'PE':>8} {'错误':>8} {'-':>10} {'-':>10} {str(e)[:40]}")
    else:
        print(f"{'PE':>8} {'无PE数据':>8} {'-':>10} {'-':>10} 缺少PE数据")
    
    # 基本面策略 - PB（与策略内过滤一致：0 < pb <= 20）
    if 'pb' in df.columns and df['pb'].notna().sum() > 100:
        try:
            pb_valid = df['pb'].dropna()
            pb_valid = pb_valid[(pb_valid > 0) & (pb_valid <= 20)]
            valid_pb_count = len(pb_valid)
            rolling_window = min(valid_pb_count, 756)
            
            roe_passes, _, _ = fetcher.get_roe_for_filter(code)
            if industry and industry_pb_data is not None and len(industry_pb_data) > 100:
                pb_strat = PBStrategy(industry=industry, industry_pb_data=industry_pb_data, min_roe=8.0 if roe_passes else 0, rolling_window=rolling_window)
            else:
                pb_strat = PBStrategy(min_roe=8.0 if roe_passes else 0, rolling_window=rolling_window)
            
            pb_strat.min_bars = max(100, min(valid_pb_count, 756))
            
            if valid_pb_count >= pb_strat.min_bars:
                pb_sig = pb_strat.safe_analyze(df)
                action_emoji = '🟢' if pb_sig.action == 'BUY' else ('🔴' if pb_sig.action == 'SELL' else '⚪')
                print(f"{'PB':>8} {action_emoji}{pb_sig.action:>6} {pb_sig.confidence:>9.1%} {pb_sig.position:>9.1%} {pb_sig.reason[:45]}")
                signals.append(('PB', pb_sig))
                if pb_sig.action == 'BUY':
                    buy_count += 1
                elif pb_sig.action == 'SELL':
                    sell_count += 1
                else:
                    hold_count += 1
            else:
                print(f"{'PB':>8} {'观望':>8} {'0%':>10} {'50%':>10} PB有效条数不足(需至少100条，实际{valid_pb_count}条)")
        except Exception as e:
            print(f"{'PB':>8} {'错误':>8} {'-':>10} {'-':>10} {str(e)[:40]}")
    else:
        print(f"{'PB':>8} {'无PB数据':>8} {'-':>10} {'-':>10} 缺少PB数据")
    
    # 基本面策略 - PE+PB双因子（需 PE/PB 有效条数均>=100）
    if 'pe_ttm' in df.columns and 'pb' in df.columns:
        try:
            pe_v = df['pe_ttm'].dropna()
            pe_v = pe_v[(pe_v > 0) & (pe_v <= 100)]
            pb_v = df['pb'].dropna()
            pb_v = pb_v[(pb_v > 0) & (pb_v <= 20)]
            n_pe, n_pb = len(pe_v), len(pb_v)
            if n_pe >= 100 and n_pb >= 100:
                rw = min(min(n_pe, n_pb), 756)
                roe_ok, _, _ = fetcher.get_roe_for_filter(code)
                if industry and industry_pe_data is not None and industry_pb_data is not None and len(industry_pe_data) > 100 and len(industry_pb_data) > 100:
                    pe_pb_strat = PE_PB_CombinedStrategy(industry=industry, industry_pe_data=industry_pe_data, industry_pb_data=industry_pb_data, min_roe=8.0 if roe_ok else 0, rolling_window=rw)
                else:
                    pe_pb_strat = PE_PB_CombinedStrategy(min_roe=8.0 if roe_ok else 0, rolling_window=rw)
                pe_pb_strat.min_bars = max(100, rw)
                pe_pb_sig = pe_pb_strat.safe_analyze(df)
                action_emoji = '🟢' if pe_pb_sig.action == 'BUY' else ('🔴' if pe_pb_sig.action == 'SELL' else '⚪')
                print(f"{'PE+PB':>8} {action_emoji}{pe_pb_sig.action:>6} {pe_pb_sig.confidence:>9.1%} {pe_pb_sig.position:>9.1%} {pe_pb_sig.reason[:45]}")
                signals.append(('PE+PB', pe_pb_sig))
                if pe_pb_sig.action == 'BUY':
                    buy_count += 1
                elif pe_pb_sig.action == 'SELL':
                    sell_count += 1
                else:
                    hold_count += 1
            else:
                print(f"{'PE+PB':>8} {'观望':>8} {'0%':>10} {'50%':>10} PE或PB有效条数不足(需各>=100)")
        except Exception as e:
            print(f"{'PE+PB':>8} {'错误':>8} {'-':>10} {'-':>10} {str(e)[:40]}")
    else:
        print(f"{'PE+PB':>8} {'无数据':>8} {'-':>10} {'-':>10} 缺少PE或PB")
    
    # 组合策略（多策略/保守/均衡/激进/V33）
    ensemble_strategies = {
        '多策略': EnsembleStrategy(),
        '保守': ConservativeEnsemble(),
        '均衡': BalancedEnsemble(),
        '激进': AggressiveEnsemble(),
        'V33': V33EnsembleStrategy(symbol=code),
    }
    for strat_name, strat in ensemble_strategies.items():
        try:
            if len(df) < strat.min_bars:
                print(f"{strat_name:>8} {'数据不足':>8} {'-':>10} {'-':>10} 需要{strat.min_bars}条")
                continue
            sig = strat.safe_analyze(df)
            action_emoji = '🟢' if sig.action == 'BUY' else ('🔴' if sig.action == 'SELL' else '⚪')
            print(f"{strat_name:>8} {action_emoji}{sig.action:>6} {sig.confidence:>9.1%} {sig.position:>9.1%} {sig.reason[:45]}")
            signals.append((strat_name, sig))
            if sig.action == 'BUY':
                buy_count += 1
            elif sig.action == 'SELL':
                sell_count += 1
            else:
                hold_count += 1
        except Exception as e:
            print(f"{strat_name:>8} {'错误':>8} {'-':>10} {'-':>10} {str(e)[:40]}")
    
    print("-" * 100)
    print(f"汇总: 🟢买入 {buy_count} | 🔴卖出 {sell_count} | ⚪观望 {hold_count}")
    
    # 综合建议
    total_signals = buy_count + sell_count + hold_count
    if total_signals > 0:
        buy_ratio = buy_count / total_signals
        sell_ratio = sell_count / total_signals
        
        print()
        print("=" * 100)
        print("💡 综合建议:")
        print("=" * 100)
        
        if buy_ratio >= 0.6:
            print("  🟢 强烈买入 - 多数策略看涨")
        elif buy_ratio >= 0.4:
            print("  🟡 谨慎买入 - 部分策略看涨")
        elif sell_ratio >= 0.6:
            print("  🔴 强烈卖出 - 多数策略看跌")
        elif sell_ratio >= 0.4:
            print("  🟡 谨慎卖出 - 部分策略看跌")
        else:
            print("  ⚪ 观望 - 策略信号分歧较大")
        
        # 计算平均仓位建议
        valid_positions = [sig.position for _, sig in signals if hasattr(sig, 'position') and sig.position > 0]
        if valid_positions:
            avg_position = sum(valid_positions) / len(valid_positions)
            print(f"  📊 建议仓位: {avg_position:.1%}")
        
        # 计算平均信心度
        valid_confidences = [sig.confidence for _, sig in signals if hasattr(sig, 'confidence') and sig.confidence > 0]
        if valid_confidences:
            avg_confidence = sum(valid_confidences) / len(valid_confidences)
            print(f"  📈 平均信心度: {avg_confidence:.1%}")
    
    print()
    bs.logout()


def main():
    parser = argparse.ArgumentParser(description='单股票多策略分析')
    parser.add_argument('code', type=str, help='股票代码（如：002015）')
    parser.add_argument('--name', type=str, default=None, help='股票名称（可选）')
    args = parser.parse_args()
    
    analyze_stock(args.code, args.name)


if __name__ == '__main__':
    main()
