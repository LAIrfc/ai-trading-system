"""
AI量化交易系统 - 统一CLI入口

用法:
    python src/main.py etf                          # ETF轮动日常分析（同 run_daily.py）
    python src/main.py etf --status                 # 查看ETF轮动持仓状态

    python src/main.py recommend                    # 从股票池选股推荐
    python src/main.py recommend --pool mydate/stock_pool.json --top 20

    python src/main.py analyze 600519               # 单股全策略分析
    python src/main.py analyze 600519 --name 贵州茅台

    python src/main.py portfolio                    # 分析实盘持仓

    python src/main.py backtest etf                 # 双核动量ETF回测
    python src/main.py backtest batch               # 批量策略回测
    python src/main.py backtest compare             # 基本面对比回测

    python src/main.py strategies                   # 列出所有可用策略
"""

import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def cmd_etf(args):
    """ETF轮动日常分析"""
    import run_daily
    if args.status:
        run_daily.show_status()
    else:
        run_daily.main()


def cmd_recommend(args):
    """从股票池选股推荐"""
    import subprocess
    cmd = [sys.executable, str(PROJECT_ROOT / 'tools/analysis/recommend_today.py')]
    if args.pool:
        cmd += ['--pool', args.pool]
    if args.top:
        cmd += ['--top', str(args.top)]
    if args.strategy:
        cmd += ['--strategy', args.strategy]
    subprocess.run(cmd)


def cmd_analyze(args):
    """单股全策略分析"""
    import subprocess
    cmd = [sys.executable, str(PROJECT_ROOT / 'tools/analysis/analyze_single_stock.py'), args.code]
    if args.name:
        cmd += ['--name', args.name]
    subprocess.run(cmd)


def cmd_portfolio(args):
    """分析实盘持仓"""
    import subprocess
    subprocess.run([sys.executable, str(PROJECT_ROOT / 'tools/analysis/portfolio_strategy_analysis.py')])


def cmd_backtest(args):
    """回测"""
    import subprocess
    script_map = {
        'etf':     'tools/backtest/backtest_dual_momentum.py',
        'batch':   'tools/backtest/batch_backtest.py',
        'compare': 'tools/backtest/compare_fundamental.py',
        'cross':   'tools/backtest/cross_validate.py',
    }
    script = script_map.get(args.target)
    if not script:
        print(f"未知回测目标: {args.target}，可选: {list(script_map.keys())}")
        sys.exit(1)
    subprocess.run([sys.executable, str(PROJECT_ROOT / script)])


def cmd_strategies(args):
    """列出所有可用策略"""
    from src.strategies import list_strategies
    strategies = list_strategies()
    print(f"\n{'='*60}")
    print(f"共 {len(strategies)} 个可用策略")
    print(f"{'='*60}")
    for s in strategies:
        print(f"\n  [{s['name']:12s}] {s['description']}")
        print(f"    最少K线: {s['min_bars']} 根")
        if s['param_ranges']:
            for param, (lo, default, hi, step) in s['param_ranges'].items():
                print(f"    参数 {param}: 默认={default}, 范围=[{lo}, {hi}], 步长={step}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description='AI量化交易系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    subparsers = parser.add_subparsers(dest='command', metavar='command')

    # etf
    p_etf = subparsers.add_parser('etf', help='ETF轮动日常分析')
    p_etf.add_argument('--status', action='store_true', help='查看持仓状态')
    p_etf.set_defaults(func=cmd_etf)

    # recommend
    p_rec = subparsers.add_parser('recommend', help='从股票池选股推荐')
    p_rec.add_argument('--pool', type=str, default='mydate/stock_pool.json', help='股票池文件')
    p_rec.add_argument('--top', type=int, default=20, help='推荐数量')
    p_rec.add_argument('--strategy', type=str, default='ensemble', help='使用的策略')
    p_rec.set_defaults(func=cmd_recommend)

    # analyze
    p_ana = subparsers.add_parser('analyze', help='单股全策略分析')
    p_ana.add_argument('code', type=str, help='股票代码，如 600519')
    p_ana.add_argument('--name', type=str, help='股票名称（可选）')
    p_ana.set_defaults(func=cmd_analyze)

    # portfolio
    p_port = subparsers.add_parser('portfolio', help='分析实盘持仓')
    p_port.set_defaults(func=cmd_portfolio)

    # backtest
    p_bt = subparsers.add_parser('backtest', help='回测')
    p_bt.add_argument('target', choices=['etf', 'batch', 'compare', 'cross'],
                      help='回测目标: etf=ETF轮动, batch=批量, compare=基本面对比, cross=交叉验证')
    p_bt.set_defaults(func=cmd_backtest)

    # strategies
    p_st = subparsers.add_parser('strategies', help='列出所有可用策略')
    p_st.set_defaults(func=cmd_strategies)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
