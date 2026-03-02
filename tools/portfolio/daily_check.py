#!/usr/bin/env python3
"""
💼 每日持仓检查 + 策略分析 + 盈亏记录

用法:
    python3 tools/portfolio/daily_check.py              # 默认使用 data/my_portfolio.json
    python3 tools/portfolio/daily_check.py --detail      # 显示各策略详细信号

每天运行一次，自动追加记录到:
    data/portfolio_daily_records.csv   (每只股票明细)
    data/portfolio_daily_summary.csv   (每日汇总)
"""

import sys
import os
import json
import csv
import warnings
from datetime import datetime

import requests
import pandas as pd
import numpy as np

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from src.strategies.ma_cross import MACrossStrategy
from src.strategies.macd_cross import MACDStrategy
from src.strategies.rsi_signal import RSIStrategy
from src.strategies.bollinger_band import BollingerBandStrategy
from src.strategies.kdj_signal import KDJStrategy
from src.strategies.ensemble import EnsembleStrategy


# ── 数据获取 ──
def get_realtime(code: str) -> dict:
    """新浪实时行情"""
    prefix = 'sh' if code.startswith(('5', '6')) else 'sz'
    url = f'https://hq.sinajs.cn/list={prefix}{code}'
    r = requests.get(url,
                     headers={'Referer': 'https://finance.sina.com.cn',
                              'User-Agent': 'Mozilla/5.0'},
                     timeout=10)
    parts = r.text.split('="')[1].rstrip('";\n').split(',')
    return {
        'name': parts[0],
        'open': float(parts[1]),
        'prev_close': float(parts[2]),
        'price': float(parts[3]),
        'high': float(parts[4]),
        'low': float(parts[5]),
        'volume': float(parts[8]),
        'date': parts[30],
        'time': parts[31],
    }


def fetch_sina_kline(code: str, datalen: int = 100) -> pd.DataFrame:
    """新浪日K线"""
    prefix = 'sh' if code.startswith(('5', '6')) else 'sz'
    symbol = f'{prefix}{code}'
    url = ('https://money.finance.sina.com.cn/quotes_service/api/'
           'json_v2.php/CN_MarketData.getKLineData')
    try:
        r = requests.get(url,
                         params={'symbol': symbol, 'scale': '240',
                                 'ma': 'no', 'datalen': str(datalen)},
                         headers={'User-Agent': 'Mozilla/5.0'},
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
        return pd.DataFrame()


def append_realtime(df: pd.DataFrame, rt: dict) -> pd.DataFrame:
    """将实时数据追加到K线DataFrame"""
    new_row = pd.DataFrame([{
        'date': pd.Timestamp(rt['date']),
        'open': rt['open'], 'high': rt['high'],
        'low': rt['low'], 'close': rt['price'],
        'volume': rt['volume'],
    }])
    return pd.concat([df, new_row], ignore_index=True)


# ── 主逻辑 ──
def main():
    import argparse
    parser = argparse.ArgumentParser(description='每日持仓检查')
    parser.add_argument('--portfolio', default='data/my_portfolio.json',
                        help='持仓配置文件')
    parser.add_argument('--detail', action='store_true',
                        help='显示各策略详细信号')
    args = parser.parse_args()

    portfolio_path = os.path.join(
        os.path.dirname(__file__), '../..', args.portfolio)

    with open(portfolio_path, 'r', encoding='utf-8') as f:
        portfolio = json.load(f)

    strategies = {
        'MA': MACrossStrategy(),
        'MACD': MACDStrategy(),
        'RSI': RSIStrategy(),
        'BOLL': BollingerBandStrategy(),
        'KDJ': KDJStrategy(),
    }
    ensemble = EnsembleStrategy()

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    print()
    print('=' * 110)
    print(f'  💼 每日持仓检查 — {now_str}')
    print('=' * 110)
    print()
    print(f'  {"代码":>8} {"名称":>10} {"实时价":>10} {"日涨跌":>8} '
          f'{"持仓":>8} {"成本":>10} {"市值":>10} {"盈亏":>10} '
          f'{"盈亏%":>8} {"策略":>10}')
    print('  ' + '-' * 108)

    total_cost = 0
    total_mv = 0
    records = []
    day_pnl = 0  # 今日盈亏

    for h in portfolio['holdings']:
        code = h['code']
        name = h['name']
        shares = h.get('shares', 0)
        avg_cost = h.get('avg_cost', 0)
        total_cost_h = h.get('total_cost', 0)
        # 如果没有 total_cost，用 shares * avg_cost 计算
        if total_cost_h <= 0 and shares > 0 and avg_cost > 0:
            total_cost_h = round(shares * avg_cost, 2)

        if shares <= 0:
            print(f'  {code:>8} {name:>10} {"⚠️ 未填写股数，跳过":>40}')
            continue

        try:
            rt = get_realtime(code)
            price = rt['price']
            prev_close = rt['prev_close']
            day_chg = (price / prev_close - 1) * 100 if prev_close > 0 else 0

            cur_mv = shares * price
            cur_pnl = cur_mv - total_cost_h
            pnl_pct = cur_pnl / total_cost_h * 100 if total_cost_h > 0 else 0
            today_pnl = shares * (price - prev_close)

            # 策略信号
            df_s = fetch_sina_kline(code, 100)
            if len(df_s) >= 30:
                df_s = append_realtime(df_s, rt)
                buy_c = sell_c = 0
                detail_lines = []
                for sn, st in strategies.items():
                    sig = st.safe_analyze(df_s)
                    if sig.action == 'BUY':
                        buy_c += 1
                    elif sig.action == 'SELL':
                        sell_c += 1
                    detail_lines.append(
                        f'    {sn:>6}: {sig.action:<4} '
                        f'conf={sig.confidence:.0%} '
                        f'pos={sig.position:.0%} '
                        f'| {(sig.reason or "")[:40]}')

                if buy_c > sell_c:
                    strat_summary = f'🟢偏多({buy_c}买)'
                elif sell_c > buy_c:
                    strat_summary = f'🔴偏空({sell_c}卖)'
                else:
                    strat_summary = '⚪观望'
            else:
                strat_summary = '❓数据不足'
                detail_lines = []

            pnl_icon = '🟢' if cur_pnl >= 0 else '🔴'
            today_icon = '📈' if today_pnl >= 0 else '📉'

            print(f'  {code:>8} {name:>10} {price:>10.3f} {day_chg:>+7.2f}% '
                  f'{shares:>8,} {total_cost_h:>10,.0f} {cur_mv:>10,.0f} '
                  f'{pnl_icon}{cur_pnl:>+9,.0f} {pnl_pct:>+7.1f}% '
                  f'{strat_summary:>10}')

            if args.detail and detail_lines:
                for line in detail_lines:
                    print(line)
                print()

            total_cost += total_cost_h
            total_mv += cur_mv
            day_pnl += today_pnl

            records.append({
                'date': datetime.now().strftime('%Y-%m-%d'),
                'time': datetime.now().strftime('%H:%M'),
                'code': code,
                'name': name,
                'price': round(price, 3),
                'day_change_pct': round(day_chg, 2),
                'shares': shares,
                'avg_cost': avg_cost,
                'total_cost': total_cost_h,
                'market_value': round(cur_mv, 2),
                'pnl': round(cur_pnl, 2),
                'pnl_pct': round(pnl_pct, 2),
                'today_pnl': round(today_pnl, 2),
                'signal': strat_summary,
            })

        except Exception as e:
            print(f'  {code:>8} {name:>10} 获取失败: {e}')

    # 汇总
    total_pnl = total_mv - total_cost
    total_pnl_pct = total_pnl / total_cost * 100 if total_cost > 0 else 0
    pnl_icon = '🟢' if total_pnl >= 0 else '🔴'
    day_icon = '🟢' if day_pnl >= 0 else '🔴'

    print('  ' + '-' * 108)
    print(f'  {"合计":>18} {"":>10} {"":>8} '
          f'{"":>8} {total_cost:>10,.0f} {total_mv:>10,.0f} '
          f'{pnl_icon}{total_pnl:>+9,.0f} {total_pnl_pct:>+7.1f}%')

    print()
    print(f'  💰 总投入: ¥{total_cost:,.0f}')
    print(f'  📊 总市值: ¥{total_mv:,.0f}')
    print(f'  {pnl_icon} 总盈亏: ¥{total_pnl:+,.0f} ({total_pnl_pct:+.2f}%)')
    print(f'  {day_icon} 今日盈亏: ¥{day_pnl:+,.0f}')
    print()

    # 操作建议
    print('  📋 操作建议:')
    for rec in records:
        pnl_pct = rec['pnl_pct']
        sig = rec['signal']
        if pnl_pct < -10:
            advice = '⚠️ 亏损超10%，关注止损'
        elif pnl_pct < -5:
            advice = '⚠️ 注意风险'
        elif '偏空' in sig or '卖' in sig:
            advice = '📉 策略偏空，谨慎'
        elif '偏多' in sig:
            advice = '📈 策略偏多，持有'
        elif pnl_pct > 10:
            advice = '💰 盈利丰厚，可止盈'
        elif pnl_pct > 5:
            advice = '💰 可考虑部分止盈'
        else:
            advice = '⏸️ 观望'

        pnl_i = '🟢' if rec['pnl_pct'] >= 0 else '🔴'
        print(f'     {rec["name"]:>10}: {pnl_i}{pnl_pct:>+6.1f}% | '
              f'今日¥{rec["today_pnl"]:+,.0f} | {sig} → {advice}')

    # ── 保存记录 ──
    data_dir = os.path.join(os.path.dirname(__file__), '../../data')
    os.makedirs(data_dir, exist_ok=True)

    # 明细
    record_file = os.path.join(data_dir, 'portfolio_daily_records.csv')
    file_exists = os.path.exists(record_file) and os.path.getsize(record_file) > 0
    fieldnames = ['date', 'time', 'code', 'name', 'price', 'day_change_pct',
                  'shares', 'avg_cost', 'total_cost', 'market_value',
                  'pnl', 'pnl_pct', 'today_pnl', 'signal']
    with open(record_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for rec in records:
            writer.writerow(rec)

    # 汇总
    summary_file = os.path.join(data_dir, 'portfolio_daily_summary.csv')
    summary_exists = (os.path.exists(summary_file)
                      and os.path.getsize(summary_file) > 0)
    best = max(records, key=lambda x: x['pnl_pct']) if records else {}
    worst = min(records, key=lambda x: x['pnl_pct']) if records else {}

    with open(summary_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'date', 'time', 'total_cost', 'total_market_value',
            'total_pnl', 'total_pnl_pct', 'today_pnl',
            'num_holdings', 'best_stock', 'worst_stock',
        ])
        if not summary_exists:
            writer.writeheader()
        writer.writerow({
            'date': datetime.now().strftime('%Y-%m-%d'),
            'time': datetime.now().strftime('%H:%M'),
            'total_cost': total_cost,
            'total_market_value': round(total_mv, 2),
            'total_pnl': round(total_pnl, 2),
            'total_pnl_pct': round(total_pnl_pct, 2),
            'today_pnl': round(day_pnl, 2),
            'num_holdings': len(records),
            'best_stock': f'{best.get("name","")}({best.get("pnl_pct",0):+.1f}%)'
            if best else '',
            'worst_stock': f'{worst.get("name","")}({worst.get("pnl_pct",0):+.1f}%)'
            if worst else '',
        })

    print()
    print(f'  📝 明细已追加: {record_file}')
    print(f'  📝 汇总已追加: {summary_file}')
    print(f'  💡 每天运行 python3 tools/portfolio/daily_check.py 积累历史记录')
    print()


if __name__ == '__main__':
    main()
