"""
AI量化交易系统 - 统一CLI入口

用法:
    python src/main.py recommend                    # 从股票池选股推荐
    python src/main.py recommend --pool mydate/stock_pool.json --top 20

    python src/main.py analyze 600519 贵州茅台       # 单股快速分析
    python src/main.py analyze 600519 贵州茅台 --full # 单股完整分析（含14策略）

    python src/main.py strategies                   # 列出所有可用策略
"""

import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


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
    """单股分析"""
    import subprocess
    cmd = [sys.executable, str(PROJECT_ROOT / 'tools/analysis/analyze_single_stock.py'),
           args.code, args.name]
    if args.full:
        cmd.append('--full')
    subprocess.run(cmd)


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

    p_rec = subparsers.add_parser('recommend', help='从股票池选股推荐')
    p_rec.add_argument('--pool', type=str, default='mydate/stock_pool.json', help='股票池文件')
    p_rec.add_argument('--top', type=int, default=20, help='推荐数量')
    p_rec.add_argument('--strategy', type=str, default='ensemble', help='使用的策略')
    p_rec.set_defaults(func=cmd_recommend)

    p_ana = subparsers.add_parser('analyze', help='单股分析')
    p_ana.add_argument('code', type=str, help='股票代码，如 600519')
    p_ana.add_argument('name', type=str, help='股票名称，如 贵州茅台')
    p_ana.add_argument('--full', action='store_true', help='完整分析（含14策略+新闻）')
    p_ana.set_defaults(func=cmd_analyze)

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
