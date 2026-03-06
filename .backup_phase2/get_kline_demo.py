#!/usr/bin/env python3
"""
K线数据获取演示
展示如何获取和使用K线数据
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.realtime_data import RealtimeDataFetcher, MarketDataManager
import pandas as pd
from datetime import datetime


def demo_basic_kline():
    """基础K线获取"""
    print("\n" + "="*60)
    print("  演示1: 获取基础K线数据")
    print("="*60 + "\n")
    
    # 创建数据获取器
    fetcher = RealtimeDataFetcher(data_source='akshare')
    
    # 获取贵州茅台最近30天日K线
    stock_code = '600519'
    print(f"获取 {stock_code} (贵州茅台) 的日K线数据...")
    
    df = fetcher.get_historical_data(
        stock_code=stock_code,
        start_date='20240101',
        end_date=datetime.now().strftime('%Y%m%d'),
        period='daily'
    )
    
    if df is not None and not df.empty:
        print(f"✅ 成功获取 {len(df)} 天数据\n")
        
        # 显示数据结构
        print("📊 数据列:")
        print(f"   {df.columns.tolist()}\n")
        
        # 显示最近5天
        print("📈 最近5个交易日:")
        recent = df.tail(5)
        
        for idx, row in recent.iterrows():
            change_pct = row.get('change_pct', 0)
            direction = "📈" if change_pct >= 0 else "📉"
            print(f"\n   {idx.strftime('%Y-%m-%d')} {direction}")
            print(f"   开: {row['open']:.2f}  高: {row['high']:.2f}  低: {row['low']:.2f}  收: {row['close']:.2f}")
            print(f"   涨跌幅: {change_pct:+.2f}%  成交量: {row['volume']/10000:.0f}万手")
        
        return df
    else:
        print("❌ 获取数据失败")
        return None


def demo_realtime_quote():
    """实时行情"""
    print("\n\n" + "="*60)
    print("  演示2: 获取实时行情")
    print("="*60 + "\n")
    
    fetcher = RealtimeDataFetcher()
    
    # 获取多只股票实时行情
    stocks = ['600519', '000001', '600036']
    print(f"获取实时行情: {', '.join(stocks)}\n")
    
    quotes = fetcher.get_realtime_quotes(stocks)
    
    for code, quote in quotes.items():
        if quote:
            direction = "📈" if quote['change_pct'] >= 0 else "📉"
            print(f"{direction} {code} - {quote['name']}")
            print(f"   价格: {quote['price']:.2f}  涨跌幅: {quote['change_pct']:+.2f}%")
            print(f"   今开: {quote['open']:.2f}  昨收: {quote['pre_close']:.2f}")
            print(f"   最高: {quote['high']:.2f}  最低: {quote['low']:.2f}")
            print(f"   成交量: {quote['volume']/10000:.0f}万手")
            print()


def demo_strategy_data():
    """为策略准备数据"""
    print("\n" + "="*60)
    print("  演示3: 为策略准备完整数据（历史+实时）")
    print("="*60 + "\n")
    
    # 使用数据管理器
    manager = MarketDataManager(data_source='akshare')
    
    # 准备数据
    stocks = ['600519']
    print(f"准备策略数据: {', '.join(stocks)}")
    print("合并历史K线 + 今日实时数据...\n")
    
    market_data = manager.prepare_strategy_data(
        stock_codes=stocks,
        historical_days=100
    )
    
    for code, df in market_data.items():
        if df is not None and not df.empty:
            print(f"✅ {code}: {len(df)}天数据\n")
            
            # 显示最近3天（包括今天）
            recent = df.tail(3)
            print("📊 最近3天（含今日实时）:")
            
            for idx, row in recent.iterrows():
                is_today = idx.date() == datetime.now().date()
                tag = "🔴 今日实时" if is_today else ""
                
                print(f"\n   {idx.strftime('%Y-%m-%d')} {tag}")
                print(f"   开: {row['open']:.2f}  高: {row['high']:.2f}  低: {row['low']:.2f}  收: {row['close']:.2f}")
                print(f"   成交量: {row['volume']/10000:.0f}万手")
            
            # 计算简单指标
            print("\n📈 技术指标（MA）:")
            df['MA5'] = df['close'].rolling(window=5).mean()
            df['MA20'] = df['close'].rolling(window=20).mean()
            
            latest = df.iloc[-1]
            print(f"   MA5: {latest['MA5']:.2f}")
            print(f"   MA20: {latest['MA20']:.2f}")
            
            # 判断趋势
            if latest['MA5'] > latest['MA20']:
                print(f"   趋势: 📈 多头（MA5 > MA20）")
            else:
                print(f"   趋势: 📉 空头（MA5 < MA20）")
            
            return df


def demo_different_periods():
    """不同周期K线"""
    print("\n\n" + "="*60)
    print("  演示4: 获取不同周期K线")
    print("="*60 + "\n")
    
    fetcher = RealtimeDataFetcher()
    stock_code = '600519'
    
    periods = [
        ('daily', '日线'),
        ('weekly', '周线'),
        ('monthly', '月线'),
    ]
    
    for period, name in periods:
        print(f"📊 获取{name}...")
        
        df = fetcher.get_historical_data(
            stock_code=stock_code,
            start_date='20240101',
            end_date=datetime.now().strftime('%Y%m%d'),
            period=period
        )
        
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            print(f"   ✅ {len(df)}根K线")
            print(f"   最新: {df.index[-1]}  收盘: {latest['close']:.2f}")
        else:
            print(f"   ❌ 获取失败")
        
        print()


def demo_export_data():
    """导出数据"""
    print("\n" + "="*60)
    print("  演示5: 导出K线数据")
    print("="*60 + "\n")
    
    fetcher = RealtimeDataFetcher()
    
    df = fetcher.get_historical_data('600519')
    
    if df is not None and not df.empty:
        # 导出CSV
        filename = f"mydate/600519_kline_{datetime.now().strftime('%Y%m%d')}.csv"
        
        # 创建目录
        Path("mydate").mkdir(exist_ok=True)
        
        # 保存
        df.to_csv(filename)
        print(f"✅ 数据已导出到: {filename}")
        print(f"   总计: {len(df)}条记录")
        print(f"   时间范围: {df.index[0]} ~ {df.index[-1]}")
        
        # 也可以导出为Excel
        excel_filename = filename.replace('.csv', '.xlsx')
        df.to_excel(excel_filename)
        print(f"✅ 数据已导出到: {excel_filename}")


def main():
    """运行所有演示"""
    print("\n" + "="*60)
    print("  K线数据获取演示")
    print("  展示如何获取和使用股票K线数据")
    print("="*60)
    
    try:
        # 演示1: 基础K线
        df = demo_basic_kline()
        
        # 演示2: 实时行情
        demo_realtime_quote()
        
        # 演示3: 为策略准备数据
        demo_strategy_data()
        
        # 演示4: 不同周期
        demo_different_periods()
        
        # 演示5: 导出数据
        if df is not None:
            demo_export_data()
        
        # 完成
        print("\n" + "="*60)
        print("✅ 所有演示完成！")
        print("="*60)
        
        print("\n💡 提示:")
        print("   - 数据来自AKShare，和同花顺显示的一致")
        print("   - 支持日线、周线、月线")
        print("   - 支持前复权数据")
        print("   - 实时数据延迟约3-5秒")
        print("   - 可以直接用于策略分析\n")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
