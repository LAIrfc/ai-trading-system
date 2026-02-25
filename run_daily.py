#!/usr/bin/env python3
"""
📈 每日策略分析 - 主入口

功能:
  1. 获取最新市场数据
  2. 运行双核动量策略分析
  3. 生成买卖信号 + 完整决策理由
  4. 更新虚拟持仓
  5. 输出操盘日志到 data/daily_reports/

用法:
  python3 run_daily.py              # 正常运行
  python3 run_daily.py --reset      # 重置持仓（初始100万）
  python3 run_daily.py --history    # 查看历史交易记录
  python3 run_daily.py --status     # 查看当前持仓状态
"""

import sys
import os
import argparse

# 确保能导入 src
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loguru import logger
from src.data.market_data import MarketData, ETF_POOL
from src.core.signal_engine import DualMomentumEngine, Signal
from src.core.portfolio import Portfolio
from src.core.trade_journal import generate_daily_report


def run_daily_analysis(config: dict = None):
    """执行每日策略分析"""

    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║        📈 双核动量轮动策略 - 每日分析               ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    # 1. 加载持仓
    portfolio = Portfolio()
    print(portfolio.get_summary())
    print()

    # 2. 获取市场数据
    print("=" * 55)
    print("  📡 获取市场数据...")
    print("=" * 55)

    with MarketData() as md:
        # 获取所有 ETF 历史数据（至少 250 个交易日，约 400 自然日）
        all_data = md.get_all_etf_history(days=400)

        if not all_data:
            logger.error("无法获取市场数据，请检查网络连接")
            return

        # 获取最新价格
        latest_prices = md.get_latest_prices()

    # 显示市场概览
    print()
    print("📊 市场概览")
    print("-" * 55)
    for code, info in latest_prices.items():
        print(f"  {info['short']:6s} ({code})  "
              f"收盘: {info['close']:>10.4f}  "
              f"成交额: {info['amount']/1e8:>8.2f}亿  "
              f"{info['date']}")
    print()

    # 3. 运行策略分析
    print("=" * 55)
    print("  🧠 运行策略分析...")
    print("=" * 55)
    print()

    engine = DualMomentumEngine(config)
    signal, analysis = engine.analyze(all_data, portfolio.state)

    # 4. 显示信号
    print()
    print("=" * 55)
    action_display = {
        'BUY': '🟢 买入',
        'SELL': '🔴 卖出',
        'SWITCH': '🔄 换仓',
        'HOLD': '⏸️  持有',
        'EMPTY': '⬜ 空仓',
        'ERROR': '❌ 异常',
    }
    print(f"  📣 交易信号: {action_display.get(signal.action, signal.action)}")
    print("=" * 55)
    if signal.code:
        print(f"  标的: {signal.name} ({signal.code})")
        print(f"  价格: {signal.price:.4f}")
    print(f"  理由: {signal.reason}")
    print()

    # 5. 执行虚拟交易
    price_dict = {code: info['close'] for code, info in latest_prices.items()}
    portfolio.execute_signal(signal, price_dict)

    # 6. 显示更新后的持仓
    print(portfolio.get_summary(price_dict))
    print()

    # 7. 生成操盘日志
    report_path = generate_daily_report(signal, analysis, portfolio, latest_prices)
    print(f"📝 操盘日志: {report_path}")
    print()

    return signal, analysis


def show_status():
    """显示当前持仓状态"""
    portfolio = Portfolio()

    # 获取最新价格
    try:
        with MarketData() as md:
            prices = md.get_latest_prices()
            price_dict = {code: info['close'] for code, info in prices.items()}
    except Exception:
        price_dict = None

    print()
    print(portfolio.get_summary(price_dict))
    print()


def show_history():
    """显示历史交易记录"""
    portfolio = Portfolio()
    trades = portfolio.get_trade_history()

    if not trades:
        print("\n  暂无交易记录。\n")
        return

    print()
    print("📜 历史交易记录")
    print("=" * 90)
    print(f"{'日期':12s} {'操作':6s} {'标的':8s} {'价格':>10s} {'数量':>8s} {'盈亏':>12s} {'理由'}")
    print("-" * 90)

    total_pnl = 0
    for t in trades:
        pnl = t.get('pnl', 0)
        total_pnl += pnl
        pnl_str = f"{pnl:+.2f}" if pnl != 0 else '-'
        reason = t.get('reason', '')[:35]
        print(f"{t['date']:12s} {t['action']:6s} {t['name']:8s} "
              f"{t['price']:>10.4f} {t['shares']:>8d} {pnl_str:>12s} {reason}")

    print("-" * 90)
    print(f"  总计 {len(trades)} 笔交易  |  累计盈亏: {total_pnl:+,.2f} 元")
    print()


def reset_portfolio():
    """重置持仓"""
    portfolio = Portfolio()
    portfolio.reset()
    print("\n  ✅ 持仓已重置为初始状态（100万元）\n")


def main():
    parser = argparse.ArgumentParser(description='双核动量轮动策略 - 每日分析')
    parser.add_argument('--reset', action='store_true', help='重置持仓')
    parser.add_argument('--history', action='store_true', help='查看历史交易')
    parser.add_argument('--status', action='store_true', help='查看当前持仓')
    parser.add_argument('--N', type=int, default=200, help='绝对动量周期 (默认200)')
    parser.add_argument('--M', type=int, default=60, help='相对动量周期 (默认60)')
    parser.add_argument('--F', type=int, default=20, help='调仓频率 (默认20)')
    parser.add_argument('--K', type=int, default=1, help='持有数量 (默认1)')

    args = parser.parse_args()

    if args.reset:
        reset_portfolio()
        return

    if args.history:
        show_history()
        return

    if args.status:
        show_status()
        return

    config = {
        'abs_momentum_period': args.N,
        'rel_momentum_period': args.M,
        'rebalance_freq': args.F,
        'hold_count': args.K,
    }

    run_daily_analysis(config)


if __name__ == '__main__':
    main()
