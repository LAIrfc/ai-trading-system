#!/usr/bin/env python3
"""
K线数据获取工具
获取股票的日K线、周K线、月K线数据
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger

from src.data.realtime_data import RealtimeDataFetcher


def print_kline_data(stock_code: str, period='daily', days=30):
    """
    打印K线数据
    
    Args:
        stock_code: 股票代码
        period: 周期 ('daily', 'weekly', 'monthly')
        days: 获取天数
    """
    print("\n" + "="*80)
    print(f"  获取 {stock_code} 的K线数据")
    print("="*80 + "\n")
    
    # 创建数据获取器
    fetcher = RealtimeDataFetcher(data_source='akshare')
    
    # 计算日期范围
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=days + 50)).strftime('%Y%m%d')
    
    print(f"📅 时间范围: {start_date} ~ {end_date}")
    print(f"📊 周期: {period}")
    print(f"🔍 正在获取数据...\n")
    
    # 获取历史数据
    df = fetcher.get_historical_data(
        stock_code=stock_code,
        start_date=start_date,
        end_date=end_date,
        period=period
    )
    
    if df is None or df.empty:
        print("❌ 获取数据失败或无数据")
        return None
    
    # 只保留最近N天
    df = df.tail(days)
    
    print(f"✅ 成功获取 {len(df)} 条K线数据\n")
    
    # 显示统计信息
    print("📈 数据统计:")
    print(f"   最高价: {df['high'].max():.2f}")
    print(f"   最低价: {df['low'].min():.2f}")
    print(f"   平均价: {df['close'].mean():.2f}")
    print(f"   最新价: {df['close'].iloc[-1]:.2f}")
    print(f"   总成交量: {df['volume'].sum()/10000:.0f}万手")
    print()
    
    # 显示最近几天的K线
    print("📊 最近10个交易日K线:")
    print("-" * 80)
    
    # 格式化输出
    recent_data = df.tail(10).copy()
    recent_data.index = pd.to_datetime(recent_data.index)
    
    print(f"{'日期':<12} {'开盘':<8} {'最高':<8} {'最低':<8} {'收盘':<8} {'涨跌幅%':<8} {'成交量(万手)':<12}")
    print("-" * 80)
    
    for idx, row in recent_data.iterrows():
        date_str = idx.strftime('%Y-%m-%d')
        change_pct = row.get('change_pct', 0)
        change_color = "+" if change_pct >= 0 else ""
        
        print(f"{date_str:<12} "
              f"{row['open']:<8.2f} "
              f"{row['high']:<8.2f} "
              f"{row['low']:<8.2f} "
              f"{row['close']:<8.2f} "
              f"{change_color}{change_pct:<8.2f} "
              f"{row['volume']/10000:<12.0f}")
    
    print("-" * 80)
    print()
    
    # 获取实时数据
    print("🔴 实时行情:")
    realtime = fetcher.get_realtime_quotes([stock_code])
    
    if stock_code in realtime and realtime[stock_code]:
        quote = realtime[stock_code]
        print(f"   名称: {quote['name']}")
        print(f"   当前价: {quote['price']:.2f}")
        print(f"   涨跌幅: {quote['change_pct']:+.2f}%")
        print(f"   涨跌额: {quote['change_amount']:+.2f}")
        print(f"   今开: {quote['open']:.2f}")
        print(f"   昨收: {quote['pre_close']:.2f}")
        print(f"   最高: {quote['high']:.2f}")
        print(f"   最低: {quote['low']:.2f}")
        print(f"   成交量: {quote['volume']/10000:.0f}万手")
        print(f"   成交额: {quote['amount']/100000000:.2f}亿")
        print(f"   时间: {quote['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("   ⚠️  无法获取实时数据")
    
    print()
    print("="*80)
    
    return df


def export_to_csv(df: pd.DataFrame, stock_code: str, period: str):
    """导出到CSV"""
    if df is None or df.empty:
        return
    
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    filename = os.path.join(base_dir, "mydate", f"{stock_code}_{period}_kline_{datetime.now().strftime('%Y%m%d')}.csv")
    
    # 创建目录
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    # 保存
    df.to_csv(filename)
    print(f"💾 数据已保存到: {filename}")


def compare_with_realtime(stock_code: str):
    """对比历史和实时数据"""
    print("\n" + "="*80)
    print(f"  对比历史K线 vs 实时数据 ({stock_code})")
    print("="*80 + "\n")
    
    fetcher = RealtimeDataFetcher()
    
    # 获取最近5天K线
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=10)).strftime('%Y%m%d')
    
    df = fetcher.get_historical_data(stock_code, start_date, end_date)
    
    if df is not None and not df.empty:
        latest_kline = df.iloc[-1]
        print("📊 最新K线（昨日）:")
        print(f"   日期: {df.index[-1]}")
        print(f"   收盘: {latest_kline['close']:.2f}")
        print(f"   涨跌幅: {latest_kline.get('change_pct', 0):.2f}%")
        print()
    
    # 获取实时数据
    realtime = fetcher.get_realtime_quotes([stock_code])
    
    if stock_code in realtime and realtime[stock_code]:
        quote = realtime[stock_code]
        print("🔴 今日实时:")
        print(f"   时间: {quote['timestamp'].strftime('%H:%M:%S')}")
        print(f"   现价: {quote['price']:.2f}")
        print(f"   涨跌幅: {quote['change_pct']:+.2f}%")
        print(f"   今开: {quote['open']:.2f}")
        print(f"   最高: {quote['high']:.2f}")
        print(f"   最低: {quote['low']:.2f}")
        print()
        
        # 计算今日振幅
        if quote['high'] != quote['low']:
            amplitude = (quote['high'] - quote['low']) / quote['pre_close'] * 100
            print(f"📈 今日振幅: {amplitude:.2f}%")
    
    print("="*80 + "\n")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='K线数据获取工具')
    
    parser.add_argument('stock_code', type=str, nargs='?', help='股票代码（如600519）')
    parser.add_argument('--period', '-p', type=str, default='daily',
                       choices=['daily', 'weekly', 'monthly'],
                       help='K线周期: daily(日线), weekly(周线), monthly(月线)')
    parser.add_argument('--days', '-d', type=int, default=30,
                       help='获取天数（默认30）')
    parser.add_argument('--export', '-e', action='store_true',
                       help='导出到CSV文件')
    parser.add_argument('--compare', '-c', action='store_true',
                       help='对比历史和实时数据')
    parser.add_argument('--list', '-l', action='store_true',
                       help='列出热门股票')
    
    args = parser.parse_args()
    
    # 设置日志
    logger.remove()
    logger.add(sys.stdout, level="ERROR")
    
    # 列出热门股票
    if args.list:
        print("\n📊 常用股票代码:\n")
        stocks = {
            '600519': '贵州茅台',
            '000001': '平安银行',
            '600036': '招商银行',
            '601318': '中国平安',
            '000858': '五粮液',
            '600900': '长江电力',
            '601166': '兴业银行',
            '000002': '万科A',
            '600276': '恒瑞医药',
            '300750': '宁德时代',
        }
        
        for code, name in stocks.items():
            print(f"   {code} - {name}")
        
        print("\n使用方法:")
        print(f"   python3 {sys.argv[0]} 600519")
        print(f"   python3 {sys.argv[0]} 600519 --period weekly --days 60")
        print()
        return
    
    # 交互式输入
    if not args.stock_code:
        print("\n📊 K线数据获取工具\n")
        args.stock_code = input("请输入股票代码（如600519）: ").strip()
        
        if not args.stock_code:
            print("❌ 股票代码不能为空")
            return
    
    # 对比模式
    if args.compare:
        compare_with_realtime(args.stock_code)
        return
    
    # 获取K线数据
    df = print_kline_data(args.stock_code, args.period, args.days)
    
    # 导出
    if args.export and df is not None:
        export_to_csv(df, args.stock_code, args.period)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
