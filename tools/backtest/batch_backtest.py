#!/usr/bin/env python3
"""
大规模回测验证：从股票池中选取 N 只股票，用 6 个策略 + 组合策略进行 3 年回测

用法:
  python3 tools/batch_backtest.py                    # 默认500只，3年
  python3 tools/batch_backtest.py --count 100        # 只跑100只
  python3 tools/batch_backtest.py --workers 8        # 8个并发线程
  python3 tools/batch_backtest.py --pool data/stock_pool.json  # 指定股票池
"""

import sys
import os
import json
import time
import argparse
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
warnings.filterwarnings('ignore')

from src.strategies.ma_cross import MACrossStrategy
from src.strategies.macd_cross import MACDStrategy
from src.strategies.rsi_signal import RSIStrategy
from src.strategies.bollinger_band import BollingerBandStrategy
from src.strategies.kdj_signal import KDJStrategy
from src.strategies.fundamental_pe import PEStrategy
from src.strategies.ensemble import EnsembleStrategy
from src.data.fetchers.fundamental_fetcher import FundamentalFetcher, create_mock_fundamental_data


# ── 数据获取（新浪日线，带重试）──
def fetch_sina(code: str, datalen: int = 800, retries: int = 3) -> pd.DataFrame:
    """从新浪财经获取日线数据"""
    prefix = 'sh' if code.startswith(('5', '6')) else 'sz'
    symbol = f'{prefix}{code}'
    url = ('https://money.finance.sina.com.cn/quotes_service/api/'
           'json_v2.php/CN_MarketData.getKLineData')

    for attempt in range(retries):
        try:
            r = requests.get(url,
                params={'symbol': symbol, 'scale': '240',
                        'ma': 'no', 'datalen': str(datalen)},
                headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'},
                timeout=15)
            data = json.loads(r.text) if r.text.strip() else None
            if not data:
                return pd.DataFrame()
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['day'])
            for c in ['open', 'high', 'low', 'close', 'volume']:
                df[c] = pd.to_numeric(df[c], errors='coerce')
            return df
        except Exception:
            if attempt < retries - 1:
                time.sleep(1 * (attempt + 1))
    return pd.DataFrame()


def load_stock_pool(pool_file: str, max_count: int = 500) -> list:
    """从 JSON 股票池加载股票列表，支持多种格式（sectors/stocks+etf/categories）"""
    try:
        from src.utils.pool_loader import load_pool
        return load_pool(pool_file, max_count=max_count, include_etf=False)
    except ImportError:
        pass

    # fallback: 直接解析
    with open(pool_file, 'r', encoding='utf-8') as f:
        pool = json.load(f)

    # 兼容综合格式 (stocks字段) 和老格式 (sectors字段)
    sectors = pool.get('stocks', pool.get('sectors', {}))
    num_sectors = len(sectors)
    if num_sectors == 0:
        return []

    per_sector = max(1, max_count // num_sectors)
    remainder = max_count - per_sector * num_sectors

    stocks = []
    for sector_name, sector_stocks in sectors.items():
        quota = per_sector + (1 if remainder > 0 else 0)
        if remainder > 0:
            remainder -= 1
        for s in sector_stocks[:quota]:
            stocks.append({
                'code': s['code'],
                'name': s.get('name', s['code']),
                'sector': sector_name,
            })

    return stocks[:max_count]


def backtest_one_stock(stock_info: dict, strategies: dict,
                       ensemble: EnsembleStrategy,
                       datalen: int = 800,
                       enable_fundamental: bool = False,
                       min_market_cap: float = 50.0) -> dict:
    """
    对一只股票运行所有策略回测
    
    Args:
        stock_info: 股票信息
        strategies: 策略字典
        ensemble: 组合策略
        datalen: 数据长度
        enable_fundamental: 是否启用基本面数据（默认False）
                          ⚠️ 如果为True且未配置真实数据源，将使用模拟数据
                          模拟数据隐含未来信息，仅用于测试流程，不可用于真实回测
        min_market_cap: 最小市值过滤（单位：亿元，默认50亿）
                       实盘标准：熊市/震荡市过滤市值<50亿，牛市可下调至30亿
    """
    code = stock_info['code']
    name = stock_info['name']
    sector = stock_info['sector']

    df = fetch_sina(code, datalen)
    if df.empty or len(df) < 100:
        return {'code': code, 'name': name, 'sector': sector,
                'status': 'skip', 'reason': f'数据不足({len(df)}条)'}
    
    # 合并基本面数据（如果启用）
    if enable_fundamental:
        try:
            # 优先尝试从真实数据源获取（tushare）
            fetcher = FundamentalFetcher(source='tushare')
            start_date = df['date'].iloc[0].strftime('%Y%m%d')
            end_date = df['date'].iloc[-1].strftime('%Y%m%d')
            fund_df = fetcher.get_daily_basic(code, start_date=start_date, end_date=end_date)
            
            if not fund_df.empty:
                # 使用真实数据
                df = fetcher.merge_to_daily(df, fund_df, fill_method='ffill')
            else:
                # 真实数据获取失败，回退到模拟数据（仅用于测试）
                # ⚠️ 警告：模拟数据隐含未来信息，不可用于真实回测验证
                import warnings
                warnings.warn(
                    f"[{code}] 真实基本面数据获取失败，使用模拟数据（仅用于测试流程）",
                    UserWarning
                )
                import hashlib
                seed = int(hashlib.md5(code.encode()).hexdigest()[:8], 16) % 10000
                fund_df = create_mock_fundamental_data(df, random_seed=seed)
                if not fund_df.empty:
                    df = fetcher.merge_to_daily(df, fund_df, fill_method='ffill')
        except Exception as e:
            # 基本面数据获取失败不影响回测，继续使用纯技术数据
            pass
    
    # 实盘标准：市值过滤（前置风控）
    # 过滤市值过小的股票，降低流动性风险和退市风险
    if enable_fundamental and 'market_cap' in df.columns:
        latest_market_cap = df['market_cap'].iloc[-1]
        if pd.isna(latest_market_cap) or latest_market_cap < min_market_cap:
            return {'code': code, 'name': name, 'sector': sector,
                    'status': 'skip', 
                    'reason': f'市值过滤(市值={latest_market_cap:.1f}亿，要求>={min_market_cap}亿)'}

    results = {
        'code': code, 'name': name, 'sector': sector,
        'status': 'ok', 'bars': len(df),
        'date_range': f"{df['date'].iloc[0].strftime('%Y-%m-%d')} ~ "
                      f"{df['date'].iloc[-1].strftime('%Y-%m-%d')}",
    }

    # 各子策略回测
    for sname, strat in strategies.items():
        try:
            if len(df) < strat.min_bars:
                results[sname] = {
                    'total_return': 0, 'annualized_return': 0,
                    'max_drawdown': 0, 'sharpe': 0,
                    'win_rate': 0, 'trade_count': 0,
                    'status': 'skip',
                }
                continue
            bt = strat.backtest(df, initial_cash=100000,
                                stop_loss=0.08, trailing_stop=0.05)
            results[sname] = {
                'total_return': bt['total_return'],
                'annualized_return': bt['annualized_return'],
                'max_drawdown': bt['max_drawdown'],
                'sharpe': bt['sharpe'],
                'win_rate': bt['win_rate'],
                'trade_count': bt['trade_count'],
            }
        except Exception as e:
            results[sname] = {
                'total_return': 0, 'annualized_return': 0,
                'max_drawdown': 0, 'sharpe': 0,
                'win_rate': 0, 'trade_count': 0,
                'status': f'error: {e}',
            }

    # 组合策略回测
    try:
        if len(df) >= ensemble.min_bars:
            bt = ensemble.backtest(df, initial_cash=100000,
                                   stop_loss=0.08, trailing_stop=0.05)
            results['Ensemble'] = {
                'total_return': bt['total_return'],
                'annualized_return': bt['annualized_return'],
                'max_drawdown': bt['max_drawdown'],
                'sharpe': bt['sharpe'],
                'win_rate': bt['win_rate'],
                'trade_count': bt['trade_count'],
            }
        else:
            results['Ensemble'] = {
                'total_return': 0, 'annualized_return': 0,
                'max_drawdown': 0, 'sharpe': 0,
                'win_rate': 0, 'trade_count': 0,
                'status': 'skip',
            }
    except Exception as e:
        results['Ensemble'] = {
            'total_return': 0, 'annualized_return': 0,
            'max_drawdown': 0, 'sharpe': 0,
            'win_rate': 0, 'trade_count': 0,
            'status': f'error: {e}',
        }

    return results


def aggregate_results(all_results: list, strategy_names: list) -> dict:
    """汇总所有回测结果"""
    summary = {}
    for sname in strategy_names:
        returns = []
        ann_returns = []
        drawdowns = []
        sharpes = []
        win_rates = []
        trade_counts = []
        positive = 0
        total = 0

        for r in all_results:
            if r['status'] != 'ok':
                continue
            sr = r.get(sname, {})
            if sr.get('status') in ('skip', None) and 'total_return' not in sr:
                continue
            if 'error' in str(sr.get('status', '')):
                continue

            total += 1
            ret = sr['total_return']
            returns.append(ret)
            ann_returns.append(sr['annualized_return'])
            drawdowns.append(sr['max_drawdown'])
            sharpes.append(sr['sharpe'])
            win_rates.append(sr['win_rate'])
            trade_counts.append(sr['trade_count'])
            if ret > 0:
                positive += 1

        if not returns:
            summary[sname] = {'count': 0}
            continue

        returns = np.array(returns)
        summary[sname] = {
            'count': total,
            'avg_return': round(float(np.mean(returns)), 2),
            'median_return': round(float(np.median(returns)), 2),
            'avg_ann_return': round(float(np.mean(ann_returns)), 2),
            'avg_drawdown': round(float(np.mean(drawdowns)), 2),
            'avg_sharpe': round(float(np.mean(sharpes)), 2),
            'median_sharpe': round(float(np.median(sharpes)), 2),
            'avg_win_rate': round(float(np.mean(win_rates)), 2),
            'avg_trades': round(float(np.mean(trade_counts)), 1),
            'positive_pct': round(positive / total * 100, 1),
            'best_return': round(float(np.max(returns)), 2),
            'worst_return': round(float(np.min(returns)), 2),
            'return_std': round(float(np.std(returns)), 2),
        }

    return summary


def print_summary(summary: dict, strategy_names: list, elapsed: float,
                  total_stocks: int, ok_stocks: int, skip_stocks: int):
    """打印汇总报告"""
    print(f'\n{"="*100}')
    print(f'  大规模回测验证报告')
    print(f'  日期: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print(f'  股票: {total_stocks}只 (成功{ok_stocks}, 跳过{skip_stocks})')
    print(f'  耗时: {elapsed:.0f}秒 ({elapsed/60:.1f}分钟)')
    print(f'  风控: 止损8% + 跟踪止损5%')
    print(f'{"="*100}')

    # 表头
    header = f'{"策略":>10} | {"样本":>4} | {"平均收益%":>9} | {"中位收益%":>9} | {"年化%":>7} | {"回撤%":>6} | {"夏普":>6} | {"胜率%":>6} | {"盈利占比%":>9} | {"交易数":>6}'
    print(f'\n{header}')
    print('-' * len(header))

    # 按平均收益排序
    sorted_names = sorted(strategy_names,
                          key=lambda s: summary.get(s, {}).get('avg_return', -999),
                          reverse=True)

    for sname in sorted_names:
        s = summary.get(sname, {})
        if s.get('count', 0) == 0:
            print(f'{sname:>10} | {"N/A":>4} |')
            continue
        print(f'{sname:>10} | {s["count"]:>4} | '
              f'{s["avg_return"]:>+8.2f}% | {s["median_return"]:>+8.2f}% | '
              f'{s["avg_ann_return"]:>+6.2f}% | {s["avg_drawdown"]:>5.1f}% | '
              f'{s["avg_sharpe"]:>6.2f} | {s["avg_win_rate"]:>5.1f}% | '
              f'{s["positive_pct"]:>8.1f}% | {s["avg_trades"]:>5.1f}')

    # 最佳/最差
    print(f'\n{"─"*100}')
    print(f'  最佳/最差个股收益:')
    for sname in sorted_names:
        s = summary.get(sname, {})
        if s.get('count', 0) == 0:
            continue
        print(f'    {sname:>10}: 最佳 {s["best_return"]:+.1f}%  '
              f'最差 {s["worst_return"]:+.1f}%  '
              f'标准差 {s["return_std"]:.1f}%')

    print(f'\n{"="*100}')


def main():
    parser = argparse.ArgumentParser(description='大规模回测验证')
    parser.add_argument('--pool', default='data/stock_pool_600.json',
                        help='股票池JSON文件')
    parser.add_argument('--count', type=int, default=500,
                        help='测试股票数量')
    parser.add_argument('--workers', type=int, default=4,
                        help='并发线程数')
    parser.add_argument('--datalen', type=int, default=800,
                        help='拉取K线条数(800≈3.3年)')
    parser.add_argument('--output', default='data/backtest_results.json',
                        help='结果输出JSON')
    args = parser.parse_args()

    pool_path = os.path.join(os.path.dirname(__file__), '..', args.pool)
    output_path = os.path.join(os.path.dirname(__file__), '..', args.output)

    # 加载股票池
    stocks = load_stock_pool(pool_path, args.count)
    print(f'已加载 {len(stocks)} 只股票')

    # 策略实例（每个线程共享只读实例，无状态安全）
    strategies = {
        'MA':   MACrossStrategy(),
        'MACD': MACDStrategy(),
        'RSI':  RSIStrategy(),
        'BOLL': BollingerBandStrategy(),
        'KDJ':  KDJStrategy(),
        'PE':   PEStrategy(),  # 基本面策略
    }
    ensemble = EnsembleStrategy()
    strategy_names = list(strategies.keys()) + ['Ensemble']

    print(f'策略: {", ".join(strategy_names)}')
    print(f'数据: {args.datalen}条日线 (约{args.datalen/240:.1f}年)')
    print(f'并发: {args.workers} 线程')
    print(f'风控: 止损8% + 跟踪止损5%')
    print(f'\n开始回测...')

    start_time = time.time()
    all_results = []
    ok = 0
    skip = 0
    errors = 0

    # 用线程池并发获取数据和回测
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for stock in stocks:
            future = executor.submit(
                backtest_one_stock, stock, strategies, ensemble, args.datalen, False)
            futures[future] = stock

        for i, future in enumerate(as_completed(futures), 1):
            stock = futures[future]
            try:
                result = future.result(timeout=120)
                all_results.append(result)
                if result['status'] == 'ok':
                    ok += 1
                    # 打印进度
                    ens_ret = result.get('Ensemble', {}).get('total_return', 0)
                    ma_ret = result.get('MA', {}).get('total_return', 0)
                    if i % 20 == 0 or i <= 5:
                        elapsed = time.time() - start_time
                        eta = elapsed / i * (len(stocks) - i)
                        print(f'  [{i:>4}/{len(stocks)}] {stock["name"]:8s} '
                              f'({stock["code"]}) '
                              f'MA:{ma_ret:+.1f}% Ens:{ens_ret:+.1f}% '
                              f'| 已用{elapsed:.0f}s 预计剩余{eta:.0f}s')
                else:
                    skip += 1
            except Exception as e:
                errors += 1
                all_results.append({
                    'code': stock['code'], 'name': stock['name'],
                    'sector': stock['sector'], 'status': f'error: {e}',
                })

    elapsed = time.time() - start_time

    # 汇总
    summary = aggregate_results(all_results, strategy_names)

    # 打印报告
    print_summary(summary, strategy_names, elapsed,
                  len(stocks), ok, skip + errors)

    # 保存结果
    output = {
        'meta': {
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'total_stocks': len(stocks),
            'ok_stocks': ok,
            'skip_stocks': skip + errors,
            'datalen': args.datalen,
            'elapsed_seconds': round(elapsed, 1),
            'risk_control': 'stop_loss=8%, trailing_stop=5%',
        },
        'summary': summary,
        'details': all_results,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f'\n详细结果已保存: {output_path}')


if __name__ == '__main__':
    main()
