#!/usr/bin/env python3
"""
大规模回测验证：从股票池中选取 N 只股票，用 6 个策略 + 组合策略进行 3 年回测

用法:
  python3 tools/backtest/batch_backtest.py                    # 默认500只，3年
  python3 tools/backtest/batch_backtest.py --v33 --count 20    # V33 新策略 + 组合，20只
  python3 tools/backtest/batch_backtest.py --workers 8         # 8个并发线程
  python3 tools/backtest/batch_backtest.py --pool mydate/stock_pool.json  # 指定股票池

可能失败点与处理:
  - fetch_sina: 10秒超时，捕获 TimeoutError/ConnectionError；主接口失败则备用东方财富→腾讯，均失败则 skip 该标的 reason=数据不足，并打日志。
  - 情绪指数: 预取 15 秒超时，主源 akshare 失败则备用 tushare；预取失败则 _backtest_sentiment_df=None，回测中该策略返回 HOLD；预取支持 3 次重试、间隔 2 秒。
  - 新闻/政策/龙虎榜: analyze 内 try/except，异常时尝试备用接口；均失败返回 HOLD，不中断回测；龙虎榜/大宗支持近 7 日缓存，接口异常时用缓存。
  - 单策略 backtest() 抛错: 已 try/except，该策略记为 status: error 并打日志，其余策略及标的照常；结束后输出错误策略统计清单。

回测行为:
  - 情绪：prepare_backtest + 日期范围缓存 + 超时/备用/重试；回测时无预取数据则 HOLD。
  - NewsSentiment/PolicyEvent/MoneyFlow：回测时 _BACKTEST_ACTIVE 为真则使用预取/缓存数据（预留 parquet 批量预取），无预取则 HOLD，避免每 bar I/O。
  - V33 动态权重：回测前预取沪深300（akshare→tushare 备用），按 bar 日期截面计算权重。
  - 建议先用 --count 3~5 验证流程，再酌情加大。
"""

import sys
import os
import json
import logging
import time
import argparse
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Optional

import requests
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
warnings.filterwarnings('ignore')

from src.strategies.ma_cross import MACrossStrategy
from src.strategies.macd_cross import MACDStrategy
from src.strategies.rsi_signal import RSIStrategy
from src.strategies.bollinger_band import BollingerBandStrategy
from src.strategies.kdj_signal import KDJStrategy
from src.strategies.dual_momentum import DualMomentumSingleStrategy
from src.strategies.fundamental_pe import PEStrategy
from src.strategies.ensemble import EnsembleStrategy, V33EnsembleStrategy
from src.strategies.sentiment import SentimentStrategy
from src.strategies.news_sentiment import NewsSentimentStrategy
from src.strategies.policy_event import PolicyEventStrategy
from src.strategies.money_flow import MoneyFlowStrategy
from src.data.fetchers.fundamental_fetcher import FundamentalFetcher, create_mock_fundamental_data

# V3.3 Phase 6.1：未来函数约束校验（可选）。逐日/截面回测时请使用 src.core.backtest_constraints 过滤新闻/政策/龙虎榜
try:
    from src.core.backtest_constraints import check_sentiment_no_future, filter_news_by_time, is_lhb_visible_at_date
    _HAS_BACKTEST_CONSTRAINTS = True
except ImportError:
    _HAS_BACKTEST_CONSTRAINTS = False

# 日线数据：统一走 data_prefetch（主 Sina → 备1 东方财富 → 备2 腾讯），与 docs/data/API_INTERFACES_AND_FETCHERS.md 一致
try:
    from src.data.fetchers.data_prefetch import fetch_stock_daily
except ImportError:
    fetch_stock_daily = None


def fetch_sina(code: str, datalen: int = 800, retries: int = 3) -> pd.DataFrame:
    """
    个股日线：委托 data_prefetch.fetch_stock_daily（主 Sina timeout=10 → 备1 东方财富 → 备2 腾讯）。
    全部失败返回空 DataFrame，不中断回测。详见 docs/data/API_INTERFACES_AND_FETCHERS.md。
    """
    if fetch_stock_daily is not None:
        return fetch_stock_daily(code=code, datalen=datalen, retries=retries, min_bars=100)
    # 降级：无 data_prefetch 时使用简易 Sina 请求（仅主源）
    try:
        import requests as _req
        prefix = 'sh' if code.startswith(('5', '6')) else 'sz'
        url = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
        r = _req.get(url, params={'symbol': f'{prefix}{code}', 'scale': '240', 'ma': 'no', 'datalen': datalen},
                     headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        data = json.loads(r.text) if r.text and r.text.strip() else None
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['day'])
        for c in ['open', 'high', 'low', 'close', 'volume']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        return df if len(df) >= 100 else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def load_kline_for_backtest(
    code: str,
    datalen: int,
    local_kline_dir: Optional[str],
    min_bars: int = 100,
) -> pd.DataFrame:
    """
    回测用 K 线：若指定 local_kline_dir 则优先读 {dir}/{code}.parquet，缺失或不足再走 fetch_sina。
    """
    if local_kline_dir:
        path = os.path.join(local_kline_dir, f"{code}.parquet")
        if os.path.isfile(path):
            try:
                df = pd.read_parquet(path)
                if df is not None and not df.empty and len(df) >= min_bars:
                    if "date" in df.columns:
                        df["date"] = pd.to_datetime(df["date"])
                    return df.tail(datalen).reset_index(drop=True) if len(df) > datalen else df
            except Exception as e:
                logger.debug("读取本地 K 线 %s 失败: %s", path, e)
    return fetch_sina(code, datalen)


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


def _build_v33_strategies(symbol: str) -> tuple:
    """构建 V3.3 的 11 个子策略 + V33 组合（需传 symbol）。"""
    strategies = {
        'MA': MACrossStrategy(),
        'MACD': MACDStrategy(),
        'RSI': RSIStrategy(),
        'BOLL': BollingerBandStrategy(),
        'KDJ': KDJStrategy(),
        'DUAL': DualMomentumSingleStrategy(),
        'PE': PEStrategy(),
        'Sentiment': SentimentStrategy(),
        'NewsSentiment': NewsSentimentStrategy(symbol=symbol),
        'PolicyEvent': PolicyEventStrategy(),
        'MoneyFlow': MoneyFlowStrategy(symbol=symbol),
    }
    ensemble = V33EnsembleStrategy(symbol=symbol)
    return strategies, ensemble


def backtest_one_stock(stock_info: dict, strategies: dict,
                       ensemble: EnsembleStrategy,
                       datalen: int = 800,
                       enable_fundamental: bool = False,
                       min_market_cap: float = 50.0,
                       use_v33: bool = False,
                       local_kline_dir: Optional[str] = None) -> dict:
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

    if use_v33:
        strategies, ensemble = _build_v33_strategies(code)
        ensemble_key = 'V33组合'
    else:
        ensemble_key = 'Ensemble'

    df = load_kline_for_backtest(code, datalen, local_kline_dir, min_bars=100)
    if df.empty or len(df) < 100:
        return {'code': code, 'name': name, 'sector': sector,
                'status': 'skip', 'reason': f'数据不足({len(df)}条)'}
    
    # 合并基本面数据（如果启用）
    if enable_fundamental:
        try:
            # 使用baostock获取真实PE/PB数据
            fetcher = FundamentalFetcher(source='baostock')
            start_date = df['date'].iloc[0].strftime('%Y%m%d')
            end_date = df['date'].iloc[-1].strftime('%Y%m%d')
            fund_df = fetcher.get_daily_basic(code, start_date=start_date, end_date=end_date)
            
            if not fund_df.empty:
                df = fetcher.merge_to_daily(df, fund_df, fill_method='ffill')
            
            # 获取ROE数据，对齐到日频
            fina_df = fetcher.get_financial_indicators(code)
            if not fina_df.empty:
                df = fetcher.align_roe_to_daily(df, fina_df)
            
            fetcher._bs_logout()
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
            logger.error("backtest 策略报错 标的=%s 策略=%s: %s", code, sname, e, exc_info=False)
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
            results[ensemble_key] = {
                'total_return': bt['total_return'],
                'annualized_return': bt['annualized_return'],
                'max_drawdown': bt['max_drawdown'],
                'sharpe': bt['sharpe'],
                'win_rate': bt['win_rate'],
                'trade_count': bt['trade_count'],
            }
        else:
            results[ensemble_key] = {
                'total_return': 0, 'annualized_return': 0,
                'max_drawdown': 0, 'sharpe': 0,
                'win_rate': 0, 'trade_count': 0,
                'status': 'skip',
            }
    except Exception as e:
        logger.error("backtest 组合策略报错 标的=%s 策略=%s: %s", code, ensemble_key, e, exc_info=False)
        results[ensemble_key] = {
            'total_return': 0, 'annualized_return': 0,
            'max_drawdown': 0, 'sharpe': 0,
            'win_rate': 0, 'trade_count': 0,
            'status': f'error: {e}',
        }

    return results


def collect_strategy_errors(all_results: list, strategy_names: list) -> list:
    """从回测结果中收集所有策略级 error，返回 [(code, strategy_name, error_msg), ...]。"""
    errors = []
    for r in all_results:
        if r.get("status") != "ok":
            continue
        code = r.get("code", "")
        for sname in strategy_names:
            sr = r.get(sname, {})
            st = sr.get("status", "")
            if st and "error" in str(st):
                errors.append((code, sname, str(st)))
    return errors


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
    parser.add_argument('--pool', default='mydate/stock_pool_all.json',
                        help='股票池JSON文件')
    parser.add_argument('--count', type=int, default=500,
                        help='测试股票数量')
    parser.add_argument('--workers', type=int, default=4,
                        help='并发线程数')
    parser.add_argument('--datalen', type=int, default=800,
                        help='拉取K线条数(800≈3.3年)')
    parser.add_argument('--output', default='mydate/backtest_results.json',
                        help='结果输出JSON')
    parser.add_argument('--check-future', action='store_true',
                        help='启用 V3.3 未来函数校验提示（逐日回测时请用 src.core.backtest_constraints 过滤新闻/政策/龙虎榜）')
    parser.add_argument('--v33', action='store_true',
                        help='使用 V3.3 新策略（情绪/消息/政策/龙虎榜）+ V33组合 回测')
    parser.add_argument('--local-kline', default=None, dest='local_kline',
                        help='本地 K 线目录（每只 code.parquet）；优先读本地，缺失再拉网络。可用 tools/data/backtest_prefetch.py 预取')
    parser.add_argument('--local-aux', default=None, dest='local_aux',
                        help='回测辅助数据目录（含 news/, lhb/ 子目录与 policy.parquet）；设置 BACKTEST_PREFETCH_DIR，新闻/政策/龙虎榜从本地读。可用 tools/data/backtest_prefetch_aux.py 预取')
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pool_path = os.path.join(base_dir, args.pool) if not os.path.isabs(args.pool) else args.pool
    output_path = os.path.join(base_dir, args.output) if not os.path.isabs(args.output) else args.output

    # 加载股票池
    stocks = load_stock_pool(pool_path, args.count)
    print(f'已加载 {len(stocks)} 只股票')

    use_v33 = getattr(args, 'v33', False)
    if use_v33:
        strategy_names = ['MA', 'MACD', 'RSI', 'BOLL', 'KDJ', 'DUAL', 'PE',
                          'Sentiment', 'NewsSentiment', 'PolicyEvent', 'MoneyFlow', 'V33组合']
        strategies = None
        ensemble = None
    else:
        strategies = {
            'MA':   MACrossStrategy(),
            'MACD': MACDStrategy(),
            'RSI':  RSIStrategy(),
            'BOLL': BollingerBandStrategy(),
            'KDJ':  KDJStrategy(),
            'PE':   PEStrategy(),
        }
        ensemble = EnsembleStrategy()
        strategy_names = list(strategies.keys()) + ['Ensemble']

    print(f'策略: {", ".join(strategy_names)}')
    print(f'数据: {args.datalen}条日线 (约{args.datalen/240:.1f}年)')
    print(f'并发: {args.workers} 线程')
    print(f'风控: 止损8% + 跟踪止损5%')
    if getattr(args, 'check_future', False) and _HAS_BACKTEST_CONSTRAINTS:
        print('  [V3.3] 未来函数校验: 已加载 backtest_constraints；逐日/截面回测时请用 filter_news_by_time / filter_policy_by_time / is_lhb_visible_at_date')
    print(f'\n开始回测...')

    start_time = time.time()
    all_results = []
    ok = 0
    skip = 0
    errors = 0

    ensemble_key = 'V33组合' if use_v33 else 'Ensemble'
    local_kline_dir = getattr(args, 'local_kline', None)
    auto_kline_n = 0
    if not local_kline_dir:
        default_kline_dir = os.path.join(base_dir, 'mydate', 'backtest_kline')
        if os.path.isdir(default_kline_dir):
            parquets = [f for f in os.listdir(default_kline_dir) if f.endswith('.parquet')]
            if parquets:
                local_kline_dir = default_kline_dir
                auto_kline_n = len(parquets)
    if local_kline_dir and not os.path.isabs(local_kline_dir):
        local_kline_dir = os.path.join(base_dir, local_kline_dir)
    if local_kline_dir:
        if auto_kline_n:
            print(f'本地 K 线: {local_kline_dir}（自动使用预取数据，共 {auto_kline_n} 只；缺失则走网络）')
        else:
            print(f'本地 K 线: {local_kline_dir}（缺失则走网络）')
    local_aux_dir = getattr(args, 'local_aux', None)
    if local_aux_dir:
        if not os.path.isabs(local_aux_dir):
            local_aux_dir = os.path.join(base_dir, local_aux_dir)
        os.environ["BACKTEST_PREFETCH_DIR"] = local_aux_dir
        print(f'本地辅助数据: {local_aux_dir}（新闻/政策/龙虎榜优先读本地）')
    # 用线程池并发获取数据和回测
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for stock in stocks:
            future = executor.submit(
                backtest_one_stock, stock,
                strategies or {}, ensemble or EnsembleStrategy(),
                args.datalen, False, 50.0, use_v33, local_kline_dir)
            futures[future] = stock

        for i, future in enumerate(as_completed(futures), 1):
            stock = futures[future]
            try:
                result = future.result(timeout=180)
                all_results.append(result)
                if result['status'] == 'ok':
                    ok += 1
                    # 打印进度
                    ens_ret = result.get(ensemble_key, {}).get('total_return', 0)
                    ma_ret = result.get('MA', {}).get('total_return', 0)
                    if i % 20 == 0 or i <= 5:
                        elapsed = time.time() - start_time
                        eta = elapsed / i * (len(stocks) - i)
                        print(f'  [{i:>4}/{len(stocks)}] {stock["name"]:8s} '
                              f'({stock["code"]}) '
                              f'MA:{ma_ret:+.1f}% {ensemble_key}:{ens_ret:+.1f}% '
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
    strategy_errors = collect_strategy_errors(all_results, strategy_names)
    if strategy_errors:
        print(f'\n  错误策略统计清单 (共 {len(strategy_errors)} 条):')
        for code, sname, msg in strategy_errors[:50]:
            print(f'    标的={code} 策略={sname} 报错={msg[:80]}{"..." if len(msg) > 80 else ""}')
        if len(strategy_errors) > 50:
            print(f'    ... 其余 {len(strategy_errors) - 50} 条见日志或 details')

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
