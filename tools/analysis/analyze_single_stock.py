#!/usr/bin/env python3
"""
个股分析脚本

用法：
  python tools/analysis/analyze_single_stock.py 301008 宏昌科技
  python tools/analysis/analyze_single_stock.py 301008 宏昌科技 --full  # 含14策略+新闻
"""
import sys
import argparse

sys.path.insert(0, 'tools/analysis')
sys.path.insert(0, '.')

from recommend_today import (
    fetch_stock_data,
    _deep_analyze_kline,
    run_full_12_analysis,
    FundamentalFetcher
)


def _format_pct(pct):
    if abs(pct) >= 15:
        return f'🔥 {pct:+.1f}%'
    elif abs(pct) >= 10:
        return f'⬆️ {pct:+.1f}%' if pct > 0 else f'⬇️ {pct:+.1f}%'
    else:
        return f'{pct:+.1f}%'


def analyze_stock(code: str, name: str, full: bool = False):
    """分析单只股票，full=True 时包含14策略详情"""
    print('=' * 80)
    print(f'{name}（{code}）{"完整" if full else "快速"}分析')
    print('=' * 80)

    df = fetch_stock_data(code, days=200)
    if df.empty:
        print(f'⚠️ 无法获取{name}数据')
        return

    print(f'✅ 获取到 {len(df)} 条K线数据\n')

    deep = _deep_analyze_kline(df)
    if not deep:
        print(f'⚠️ {name}数据不足，无法分析')
        return

    price = deep.get('price', 0)

    print(f'## 📊 基本信息')
    print(f'现价: ¥{price:.2f}')
    print(f'日期: {deep.get("date", "N/A")}')

    print(f'\n## 📈 多周期涨跌')
    ret_1d = deep.get("ret_1d", 0)
    ret_5d = deep.get("ret_5d", 0)
    ret_10d = deep.get("ret_10d", 0)
    ret_20d = deep.get("ret_20d", 0)
    ret_60d = deep.get("ret_60d", 0)
    print(f'1日: {_format_pct(ret_1d)} / 5日: {_format_pct(ret_5d)} / 10日: {_format_pct(ret_10d)}')
    print(f'20日: {_format_pct(ret_20d)} / 60日: {_format_pct(ret_60d)}')

    print(f'\n## 📉 均线系统')
    print(f'MA5={deep.get("ma5", 0):.2f} MA10={deep.get("ma10", 0):.2f} MA20={deep.get("ma20", 0):.2f} MA60={deep.get("ma60", 0):.2f}')
    print(f'排列: **{deep.get("ma_align", "N/A")}**')
    print(f'MA20斜率: {deep.get("ma20_slope", 0):.2f}%（5日）{deep.get("ma20_slope_trend", "")}')

    print(f'\n## 💹 MACD动能')
    print(f'DIF={deep.get("macd_dif", 0):.3f} DEA={deep.get("macd_dea", 0):.3f} 柱={deep.get("macd_hist", 0):.3f}')
    print(f'状态: **{deep.get("macd_status", "N/A")}** {deep.get("macd_hist_trend", "")}')
    if deep.get('macd_cross_date'):
        print(f'近期交叉: {deep.get("macd_cross_type", "")} {deep.get("macd_cross_date", "")}')

    rsi = deep.get('rsi', 50)
    rsi_status = "**超卖**" if rsi < 30 else "**超买**" if rsi > 70 else "中性"
    print(f'\n## 🎯 RSI')
    print(f'RSI(14): {rsi:.1f} {rsi_status}')

    pos_60d = deep.get("pos_60d", 0)
    pos_120d = deep.get("pos_120d", 0)
    print(f'\n## 📍 价格位置')
    print(f'60日位置: 高{deep.get("high_60d", 0):.2f} 低{deep.get("low_60d", 0):.2f} **当前{pos_60d:.0f}%**')
    print(f'120日位置: 高{deep.get("high_120d", 0):.2f} 低{deep.get("low_120d", 0):.2f} **当前{pos_120d:.0f}%**')

    print(f'\n## 📊 量价结构')
    vol_ratio = deep.get("vol_ratio", 1)
    vol_status = "**放量**" if vol_ratio > 1.5 else "**缩量**" if vol_ratio < 0.7 else "**正常**"
    print(f'量比: 5/20日={vol_ratio:.2f}x {vol_status}')
    print(f'多空量比: {deep.get("up_vol_ratio", 0):.2f} (涨{deep.get("up_days", 0)}天/跌{deep.get("down_days", 0)}天)')

    pe = deep.get('pe', 0)
    pb = deep.get('pb', 0)
    pe_pct = deep.get('pe_percentile', 50)
    pb_pct = deep.get('pb_percentile', 50)
    pe_status = "低估" if pe_pct < 30 else "高估" if pe_pct > 70 else "中等"
    pb_status = "低估" if pb_pct < 30 else "高估" if pb_pct > 70 else "中等"
    print(f'\n## 💰 估值')
    if pe > 0:
        print(f'PE={pe:.1f}(分位{pe_pct:.0f}% {pe_status}) / PB={pb:.2f}(分位{pb_pct:.0f}% {pb_status})')
    else:
        print(f'PE/PB数据暂无')

    print(f'\n## 📅 近5日K线')
    print('| 日期 | 开盘 | 最高 | 最低 | 收盘 | 涨跌 | 成交量 |')
    print('|------|------|------|------|------|------|--------|')
    recent = df.tail(5)
    for idx in range(len(recent)):
        row = recent.iloc[idx]
        date = row['date'].strftime('%m-%d') if hasattr(row['date'], 'strftime') else str(row['date'])
        if idx > 0:
            prev_close = recent.iloc[idx - 1]['close']
            chg = (row['close'] / prev_close - 1) * 100
        else:
            chg = 0
        arrow = '▲' if chg >= 0 else '▼'
        vol_m = row['volume'] / 1e4 if row['volume'] > 0 else 0
        vol_str = f'{vol_m:.0f}万' if vol_m < 10000 else f'{vol_m / 10000:.1f}亿'
        print(f'| {date} | {row["open"]:.2f} | {row["high"]:.2f} | {row["low"]:.2f} | {row["close"]:.2f} | {arrow}{chg:+.1f}% | {vol_str} |')

    if full:
        print(f'\n## 🎲 14策略分析')
        try:
            fetcher = FundamentalFetcher()
            sector = "未知"
            result = run_full_12_analysis(code, name, sector, df, fetcher, skip_industry=False)

            votes = result.get('strategy_votes', {})
            if votes:
                buy_strategies = []
                sell_strategies = []
                for strategy, vote in sorted(votes.items()):
                    if vote.signal == "BUY":
                        buy_strategies.append(f'{strategy}({vote.reason})')
                    elif vote.signal == "SELL":
                        sell_strategies.append(f'{strategy}({vote.reason})')

                if buy_strategies:
                    print(f'\n看多策略({len(buy_strategies)}个):')
                    for s in buy_strategies:
                        print(f'  🟢 {s}')
                if sell_strategies:
                    print(f'\n看空策略({len(sell_strategies)}个):')
                    for s in sell_strategies:
                        print(f'  🔴 {s}')

                print(f'\n综合得分: {result.get("final_score", 0):.1f}')
                print(f'  - 趋势分: {result.get("trend_score", 0):.1f}')
                print(f'  - 均值回归分: {result.get("mr_score", 0):.1f}')
        except Exception as e:
            print(f'⚠️ 策略分析失败: {e}')

    print(f'\n## 💡 综合判断')
    bullish = []
    bearish = []
    if rsi < 30:
        bullish.append('RSI超卖')
    elif rsi > 70:
        bearish.append('RSI超买')
    if deep.get('macd_status') in ['金叉', '多头']:
        bullish.append(f'MACD{deep.get("macd_status")}')
    elif deep.get('macd_status') in ['死叉', '空头']:
        bearish.append(f'MACD{deep.get("macd_status")}')
    if deep.get('ma_align') == '多头排列':
        bullish.append('均线多头')
    elif deep.get('ma_align') == '空头排列':
        bearish.append('均线空头')
    if pos_60d < 20:
        bullish.append('低位')
    elif pos_60d > 80:
        bearish.append('高位')
    if abs(ret_1d) >= 9.5:
        if ret_1d > 0:
            bullish.append('涨停')
        else:
            bearish.append('跌停')

    print(f'看多信号: {", ".join(bullish) if bullish else "无"}')
    print(f'看空信号: {", ".join(bearish) if bearish else "无"}')

    print(f'\n## 🎯 操作建议')
    if len(bullish) > len(bearish) and rsi < 40 and pos_60d < 30:
        print('✅ **超跌关注**，可考虑建仓或加仓')
    elif len(bearish) > len(bullish) and pos_60d > 70:
        print('⚠️ **高位风险**，建议减仓或观望')
    elif deep.get('ma_align') == '空头排列' and deep.get('macd_status') == '死叉':
        print('⚠️ **趋势偏弱**，建议观望或减仓')
    elif deep.get('ma_align') == '多头排列' and deep.get('macd_status') in ['金叉', '多头']:
        print('✅ **趋势向好**，可持有或加仓')
    elif abs(ret_5d) > 40:
        print('⚠️ **短期涨幅过大**，注意回调风险，不建议追高')
    else:
        print('⚪ **震荡整理**，观察为主')

    print('\n' + '=' * 80 + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='个股分析工具')
    parser.add_argument('code', help='股票代码，例如 301008')
    parser.add_argument('name', help='股票名称，例如 宏昌科技')
    parser.add_argument('--full', action='store_true', help='包含14策略+新闻的完整分析')
    args = parser.parse_args()
    analyze_stock(args.code, args.name, full=args.full)
