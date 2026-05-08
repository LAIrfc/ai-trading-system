#!/usr/bin/env python3
"""
数据源健康诊断 — 逐个检测所有策略依赖的数据源是否可用
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd

pd.set_option('future.no_silent_downcasting', True)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')
logger = logging.getLogger('diag')
logger.setLevel(logging.INFO)

TEST_CODES = ['600519', '000858', '300750', '601318', '002475']
TEST_NAMES = ['贵州茅台', '五粮液', '宁德时代', '中国平安', '立讯精密']


def check_kline():
    """1. K线数据源"""
    print('\n' + '=' * 60)
    print('1. K线数据源')
    print('=' * 60)
    from src.data.provider.data_provider import get_default_kline_provider
    provider = get_default_kline_provider()
    ok, fail = 0, 0
    for code, name in zip(TEST_CODES, TEST_NAMES):
        try:
            df = provider.get_kline(symbol=code, datalen=200, min_bars=60, retries=2, timeout=10)
            if df is not None and len(df) >= 60:
                print(f'  ✅ {code} {name}: {len(df)}条 [{df.iloc[0]["date"]} ~ {df.iloc[-1]["date"]}]')
                ok += 1
            else:
                print(f'  ❌ {code} {name}: 返回空或不足60条')
                fail += 1
        except Exception as e:
            print(f'  ❌ {code} {name}: {e}')
            fail += 1
    print(f'  结论: {ok}/{ok+fail} 成功')
    return ok > 0


def check_fundamental():
    """2. 基本面数据源 (PE/PB)"""
    print('\n' + '=' * 60)
    print('2. 基本面数据源 (PE/PB历史)')
    print('=' * 60)
    from src.data.fetchers.fundamental_fetcher import FundamentalFetcher
    fetcher = FundamentalFetcher()
    ok, fail = 0, 0
    for code, name in zip(TEST_CODES, TEST_NAMES):
        try:
            df = fetcher.get_daily_basic(code)
            if df is not None and not df.empty:
                pe_count = df['pe_ttm'].notna().sum() if 'pe_ttm' in df.columns else 0
                pb_count = df['pb'].notna().sum() if 'pb' in df.columns else 0
                print(f'  ✅ {code} {name}: {len(df)}条, PE有效={pe_count}, PB有效={pb_count}')
                ok += 1
            else:
                print(f'  ❌ {code} {name}: 返回空')
                fail += 1
        except Exception as e:
            print(f'  ❌ {code} {name}: {e}')
            fail += 1
    print(f'  结论: {ok}/{ok+fail} 成功')
    return ok > 0


def check_fundamental_spot():
    """3. 基本面实时数据 (市值/PE/PB 当日)"""
    print('\n' + '=' * 60)
    print('3. 基本面实时数据 (市值/PE/PB当日)')
    print('=' * 60)
    from src.data.fetchers.fundamental_fetcher import FundamentalFetcher
    fetcher = FundamentalFetcher()
    ok, fail = 0, 0
    for code, name in zip(TEST_CODES, TEST_NAMES):
        try:
            data = fetcher.get_fundamental_snapshot(code)
            if data and (data.get('pe_ttm') or data.get('market_cap_yi')):
                pe = data.get('pe_ttm', 'N/A')
                pb = data.get('pb', 'N/A')
                mcap = data.get('market_cap_yi', 'N/A')
                print(f'  ✅ {code} {name}: PE={pe}, PB={pb}, 市值={mcap}亿')
                ok += 1
            else:
                print(f'  ⚠️ {code} {name}: 数据不完整 {data}')
                fail += 1
        except Exception as e:
            print(f'  ❌ {code} {name}: {e}')
            fail += 1
    print(f'  结论: {ok}/{ok+fail} 成功')
    return ok > 0


def check_news():
    """4. 新闻数据源"""
    print('\n' + '=' * 60)
    print('4. 新闻数据源')
    print('=' * 60)
    try:
        from src.strategies.news_sentiment import _get_news_sentiment_v33, _get_news_sentiment_legacy
    except ImportError as e:
        print(f'  ❌ 导入失败: {e}')
        return False

    ok, fail = 0, 0
    for code, name in zip(TEST_CODES[:3], TEST_NAMES[:3]):
        try:
            result = _get_news_sentiment_v33(code, use_llm=False, stock_name=name)
            if result is not None:
                print(f'  ✅ {code} {name} V3.3: S_news={result[0]:.2f}, N={result[1]}, weight={result[2]:.2f}')
                ok += 1
            else:
                legacy = _get_news_sentiment_legacy(code, max_news=10)
                if legacy is not None:
                    print(f'  ⚠️ {code} {name}: V3.3无数据, 旧版agg={legacy:.2f}')
                    ok += 1
                else:
                    print(f'  ❌ {code} {name}: V3.3和旧版均无数据')
                    fail += 1
        except Exception as e:
            print(f'  ❌ {code} {name}: {e}')
            fail += 1
    print(f'  结论: {ok}/{ok+fail} 成功')
    return ok > 0


def check_sentiment():
    """5. 市场情绪数据源"""
    print('\n' + '=' * 60)
    print('5. 市场情绪数据源 (V3.3)')
    print('=' * 60)
    try:
        from src.strategies.sentiment import SentimentStrategy, _get_v33_sentiment
        v33 = _get_v33_sentiment()
        if v33 is not None:
            print(f'  ✅ V3.3情绪数据可用: {v33}')
            return True
        else:
            print(f'  ❌ V3.3情绪数据不可用(返回None)')
            print(f'  说明: 需要外部情绪数据源(如妙想API等)提供恐贪指数')
            return False
    except Exception as e:
        print(f'  ❌ 异常: {e}')
        return False


def check_money_flow():
    """6. 资金流数据源"""
    print('\n' + '=' * 60)
    print('6. 资金流数据源 (龙虎榜/大宗交易)')
    print('=' * 60)
    try:
        from src.strategies.money_flow import MoneyFlowStrategy
        strat = MoneyFlowStrategy(symbol='600519')
        from src.data.provider.data_provider import get_default_kline_provider
        provider = get_default_kline_provider()
        df = provider.get_kline(symbol='600519', datalen=100, min_bars=60)
        if df is not None:
            sig = strat.analyze(df)
            print(f'  信号: {sig.action} conf={sig.confidence} reason={sig.reason}')
            if sig.confidence > 0:
                print(f'  ✅ 资金流策略有数据')
                return True
            else:
                print(f'  ⚠️ 资金流策略无有效数据(可能龙虎榜/大宗接口不可用)')
                return False
        else:
            print(f'  ❌ K线数据获取失败')
            return False
    except Exception as e:
        print(f'  ❌ 异常: {e}')
        return False


def check_earnings():
    """7. 业绩预告数据源"""
    print('\n' + '=' * 60)
    print('7. 业绩预告数据源')
    print('=' * 60)
    try:
        from src.strategies.earnings_growth import EarningsGrowthStrategy
        from src.data.provider.data_provider import get_default_kline_provider
        provider = get_default_kline_provider()
        ok, fail = 0, 0
        for code, name in zip(TEST_CODES[:3], TEST_NAMES[:3]):
            strat = EarningsGrowthStrategy(symbol=code, stock_name=name)
            df = provider.get_kline(symbol=code, datalen=100, min_bars=60)
            if df is None:
                continue
            sig = strat.analyze(df)
            if sig.action != 'HOLD' or sig.confidence > 0:
                print(f'  ✅ {code} {name}: {sig.action} conf={sig.confidence:.2f} | {sig.reason[:60]}')
                ok += 1
            else:
                print(f'  ⚠️ {code} {name}: HOLD (无业绩预告匹配)')
                fail += 1
        print(f'  结论: {ok}/{ok+fail} 有数据')
        return ok > 0
    except Exception as e:
        print(f'  ❌ 异常: {e}')
        return False


def check_industry_trend():
    """8. 行业景气度数据源"""
    print('\n' + '=' * 60)
    print('8. 行业景气度数据源 (需要LLM)')
    print('=' * 60)
    api_key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not api_key:
        print(f'  ⚠️ DEEPSEEK_API_KEY 未设置或为空')
        print(f'  说明: 行业景气度分析依赖DeepSeek LLM，需要有效API Key')
        try:
            from src.strategies.industry_trend import IndustryTrendStrategy
            print(f'  ✅ 策略模块可导入')
        except Exception as e:
            print(f'  ❌ 策略模块导入失败: {e}')
        return False
    else:
        print(f'  ✅ DEEPSEEK_API_KEY 已设置 (长度={len(api_key)})')
        return True


def check_baostock():
    """9. Baostock 数据源"""
    print('\n' + '=' * 60)
    print('9. Baostock 连接测试')
    print('=' * 60)
    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code == '0':
            print(f'  ✅ Baostock 登录成功')
            bs.logout()
            return True
        else:
            print(f'  ❌ Baostock 登录失败: {lg.error_msg}')
            bs.logout()
            return False
    except Exception as e:
        print(f'  ❌ Baostock 异常: {e}')
        return False


def check_deepseek_api():
    """10. DeepSeek API 连通性"""
    print('\n' + '=' * 60)
    print('10. DeepSeek API 连通性')
    print('=' * 60)
    api_key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not api_key:
        print(f'  ⚠️ DEEPSEEK_API_KEY 未设置')
        return False
    try:
        import requests
        resp = requests.post(
            'https://api.deepseek.com/chat/completions',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'model': 'deepseek-chat', 'messages': [{'role': 'user', 'content': 'hi'}], 'max_tokens': 5},
            timeout=15,
        )
        if resp.status_code == 200:
            print(f'  ✅ DeepSeek API 可用 (status=200)')
            return True
        else:
            print(f'  ❌ DeepSeek API 返回 {resp.status_code}: {resp.text[:200]}')
            return False
    except Exception as e:
        print(f'  ❌ DeepSeek API 异常: {e}')
        return False


def main():
    print('=' * 60)
    print('  AI Trading System 数据源健康诊断')
    print('=' * 60)

    results = {}
    results['K线'] = check_kline()
    results['PE/PB历史'] = check_fundamental()
    results['基本面实时'] = check_fundamental_spot()
    results['Baostock'] = check_baostock()
    results['新闻'] = check_news()
    results['市场情绪'] = check_sentiment()
    results['资金流'] = check_money_flow()
    results['业绩预告'] = check_earnings()
    results['行业景气度'] = check_industry_trend()
    results['DeepSeek API'] = check_deepseek_api()

    print('\n' + '=' * 60)
    print('  汇总')
    print('=' * 60)
    for name, ok in results.items():
        status = '✅' if ok else '❌'
        print(f'  {status} {name}')

    broken = [k for k, v in results.items() if not v]
    if broken:
        print(f'\n  ⚠️ 有问题的数据源: {", ".join(broken)}')
        print(f'\n  影响:')
        impact = {
            'K线': '所有技术面策略无法运行',
            'PE/PB历史': 'PE/PB/PEPB策略无历史分位数 → 0%触发率',
            '基本面实时': '市值/PE/PB当日数据缺失 → 质量门控可能误判',
            'Baostock': 'PE/PB历史数据第一源不可用（有百度备用）',
            '新闻': 'NEWS策略无输入 → 0%触发率',
            '市场情绪': 'SENTIMENT策略无输入 → 0%触发率',
            '资金流': 'MONEY_FLOW策略无输入 → 0%触发率',
            '业绩预告': 'EARNINGS_GROWTH策略无输入 → 0%触发率',
            '行业景气度': 'INDUSTRY_TREND策略无输入 → 景气度维度≈0',
            'DeepSeek API': 'LLM分析不可用 → 行业景气度/新闻语义为空',
        }
        for b in broken:
            print(f'    - {b}: {impact.get(b, "未知影响")}')
    else:
        print(f'\n  ✅ 所有数据源正常!')


if __name__ == '__main__':
    main()
