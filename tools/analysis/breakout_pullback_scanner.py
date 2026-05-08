#!/usr/bin/env python3
"""
强势股回踩再启动 — 独立选股扫描器

完全独立于现有 14 策略 ensemble 系统，并行运行。
复用：UnifiedDataProvider（K线）、stock_pool_all.json（股票池）、fetch_index_daily（指数）

用法:
    # 默认稳健模式，输出 top 20
    python3 tools/analysis/breakout_pullback_scanner.py

    # 激进模式（回踩到位即可入场）
    python3 tools/analysis/breakout_pullback_scanner.py --mode aggressive

    # 指定股票池和输出数量
    python3 tools/analysis/breakout_pullback_scanner.py --pool mydate/stock_pool.json --top 30
"""

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Optional

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from src.strategies.breakout_pullback import BreakoutPullbackStrategy, ScanResult

logger = logging.getLogger(__name__)

# ============================================================
# 股票池加载（复用现有逻辑）
# ============================================================

def load_stock_pool(pool_file: str, max_count: int = 0) -> list:
    try:
        from src.utils.pool_loader import load_pool
        return load_pool(pool_file, max_count=max_count, include_etf=False)
    except Exception:
        pass

    with open(pool_file, "r", encoding="utf-8") as f:
        pool = json.load(f)

    stocks = []
    sectors = pool.get("stocks", pool.get("sectors", {}))
    for sec_name, sec_stocks in sectors.items():
        for s in sec_stocks:
            s = dict(s)
            s["sector"] = sec_name
            stocks.append(s)
    if max_count > 0 and len(stocks) > max_count:
        stocks = stocks[:max_count]
    return stocks


# ============================================================
# 市场环境检查
# ============================================================

def check_market_env() -> dict:
    """
    检查沪深300指数的 MA5/MA20 位置，返回环境等级。
    - above_ma20: 正常扫描
    - between: 只输出 A 级
    - below_ma5: 暂停
    """
    try:
        from src.data.fetchers.data_prefetch import fetch_index_daily
        idx_df = fetch_index_daily(code="000300", datalen=60, min_bars=25)
        if idx_df.empty or len(idx_df) < 25:
            return {"level": "above_ma20", "reason": "指数数据不足，默认正常运行"}

        close = idx_df["close"].astype(float)
        ma5 = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        last = close.iloc[-1]

        if last >= ma20:
            return {"level": "above_ma20", "reason": f"沪深300 {last:.0f} 在20日线 {ma20:.0f} 之上，正常扫描"}
        elif last >= ma5:
            return {"level": "between", "reason": f"沪深300 {last:.0f} 在5日线 {ma5:.0f} 和20日线 {ma20:.0f} 之间，只输出A级"}
        else:
            return {"level": "below_ma5", "reason": f"沪深300 {last:.0f} 在5日线 {ma5:.0f} 之下，市场环境不利"}
    except Exception as e:
        logger.warning("市场环境检查失败: %s，默认正常运行", e)
        return {"level": "above_ma20", "reason": f"环境检查异常({e})，默认正常"}


# ============================================================
# 单股扫描
# ============================================================

def scan_single_stock(stock: dict, strategy: BreakoutPullbackStrategy) -> Optional[ScanResult]:
    code = stock.get("code", stock.get("symbol", ""))
    name = stock.get("name", "")
    if not code:
        return None

    try:
        from src.data.fetchers.data_prefetch import fetch_stock_daily
        df = fetch_stock_daily(code, datalen=300, min_bars=120)
        if df.empty or len(df) < 120:
            return None

        result = strategy.scan(df, symbol=code, name=name)
        return result
    except Exception as e:
        logger.debug("扫描 %s(%s) 异常: %s", code, name, e)
        return None


# ============================================================
# 报告生成
# ============================================================

def generate_report(results: List[ScanResult], env: dict, mode: str, today: str) -> str:
    lines = [
        f"# 强势股回踩再启动 — 每日扫描报告",
        f"",
        f"**日期**: {today}",
        f"**模式**: {mode}",
        f"**市场环境**: {env['reason']}",
        f"**命中数量**: {len(results)}",
        f"",
    ]

    if not results:
        lines.append("> 今日未发现符合条件的标的。")
        lines.append("")
        lines.append("---")
        lines.append("*该策略赚的是\"强势股的惯性\"，市场退潮期成功率显著下降。*")
        return "\n".join(lines)

    lines.append("## 信号列表")
    lines.append("")
    lines.append("| 排名 | 代码 | 名称 | 评分 | 等级 | 阶段 | 买法 | 入场价 | 止损价 | 突破日 | 突破价 | 回踩天数 | 缩量% | 120日涨幅 | 流动性(亿) | 风险标记 |")
    lines.append("|------|------|------|------|------|------|------|--------|--------|--------|--------|----------|-------|-----------|------------|----------|")

    for i, r in enumerate(results, 1):
        flags = ", ".join(r.risk_flags) if r.risk_flags else "-"
        lines.append(
            f"| {i} | {r.symbol} | {r.name} | {r.score:.0f} | {r.grade} | {r.stage} | {r.entry_type} "
            f"| {r.entry_price:.2f} | {r.stop_loss:.2f} | {r.breakout_date} | {r.breakout_price:.2f} "
            f"| {r.pullback_days} | {r.vol_shrink_pct:.0%} | {r.gain_120d:.1%} | {r.liquidity_score:.1f} | {flags} |"
        )

    lines.append("")
    lines.append("## 评分明细")
    lines.append("")
    for r in results:
        sd = r.score_detail
        lines.append(f"**{r.symbol} {r.name}** (总分 {r.score:.0f}, {r.grade}级)")
        lines.append(f"  - 突破质量: {sd.get('breakout_quality', 0):.0f}/30")
        lines.append(f"  - 回踩质量: {sd.get('pullback_quality', 0):.0f}/30")
        lines.append(f"  - 再启动信号: {sd.get('restart_signal', 0):.0f}/20")
        lines.append(f"  - 风险调整: {sd.get('risk_adjust', 0):+.0f}")
        lines.append(f"  - 趋势加分: {sd.get('trend_bonus', 0):+.0f}")
        if r.entry_triggered:
            lines.append(f"  - **已触发入场条件** ({r.entry_type})")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("### 交易纪律提醒")
    lines.append("- 止损纪律：**收盘价**跌破止损位 → 直接走，不犹豫")
    lines.append("- 板块冷门的个股即使形态好也要谨慎")
    lines.append("- 市场退潮期（指数破5日线）该策略成功率显著下降")
    lines.append(f"- 止损位计算方式：回踩最低价 x 0.985（留1.5%缓冲防针刺洗盘）")

    return "\n".join(lines)


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="强势股回踩再启动 — 独立选股扫描器")
    parser.add_argument("--pool", type=str, default="stock_pool_all.json",
                        help="股票池文件（默认 stock_pool_all.json）")
    parser.add_argument("--top", type=int, default=20, help="输出前 N 只（默认 20）")
    parser.add_argument("--mode", type=str, default="conservative",
                        choices=["aggressive", "conservative"],
                        help="买法模式：aggressive(低吸) / conservative(突破，默认)")
    parser.add_argument("--max-pool", type=int, default=0, help="最多扫描前 N 只（0=全部）")
    parser.add_argument("--workers", type=int, default=8, help="并行线程数（默认 8）")
    parser.add_argument("--skip-env-check", action="store_true", help="跳过市场环境检查")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    today = datetime.now().strftime("%Y-%m-%d")
    print(f"\n{'='*60}")
    print(f"  强势股回踩再启动 — 独立选股扫描器")
    print(f"  日期: {today}  模式: {args.mode}")
    print(f"{'='*60}\n")

    env = {"level": "above_ma20", "reason": "已跳过环境检查"}
    if not args.skip_env_check:
        print("📊 检查市场环境...")
        env = check_market_env()
        print(f"  {env['reason']}")
        if env["level"] == "below_ma5":
            print("\n⚠️  市场环境不利，建议观望。如需强制扫描请加 --skip-env-check")
            report_dir = os.path.join(BASE_DIR, "mydate", "breakout_reports")
            os.makedirs(report_dir, exist_ok=True)
            report_path = os.path.join(report_dir, f"breakout_{today}.md")
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(generate_report([], env, args.mode, today))
            print(f"📝 报告已保存: {report_path}")
            return

    pool_file = os.path.join(BASE_DIR, "mydate", args.pool)
    if not os.path.exists(pool_file):
        pool_file = os.path.join(BASE_DIR, "data", args.pool)
    if not os.path.exists(pool_file):
        pool_file = args.pool

    print(f"\n📂 加载股票池: {pool_file}")
    stocks = load_stock_pool(pool_file, max_count=args.max_pool if args.max_pool > 0 else 0)
    print(f"  共 {len(stocks)} 只标的")

    strategy = BreakoutPullbackStrategy(
        mode=args.mode,
        high_period=60,
        lookback_breakout=30,
        pullback_days_min=1,
        pullback_days_max=5,
        pullback_price_tol=0.05,
        vol_breakout_ratio=1.2,
        close_high_ratio=0.96,
        min_liquidity_yi=0.3,
        body_ratio_min=0.2,
    )
    results: List[ScanResult] = []
    failed = 0
    t0 = time.time()

    print(f"\n🔍 开始扫描 (线程数={args.workers})...\n")

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(scan_single_stock, s, strategy): s for s in stocks}
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            if done_count % 50 == 0 or done_count == len(stocks):
                print(f"  进度: {done_count}/{len(stocks)} ({done_count*100//len(stocks)}%)"
                      f"  命中: {len(results)}  耗时: {time.time()-t0:.0f}s")
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
            except Exception:
                failed += 1

    elapsed = time.time() - t0

    results.sort(key=lambda r: r.score, reverse=True)

    if env["level"] == "between":
        before = len(results)
        results = [r for r in results if r.grade == "A"]
        if before > len(results):
            print(f"\n⚠️  市场环境偏弱，已过滤非A级信号 ({before} -> {len(results)})")

    results = results[: args.top]

    print(f"\n{'='*60}")
    print(f"  扫描完成")
    print(f"  耗时: {elapsed:.1f}s | 扫描: {len(stocks)} | 命中: {len(results)} | 失败: {failed}")
    print(f"{'='*60}\n")

    if results:
        print(f"{'排名':>4} {'代码':<8} {'名称':<8} {'评分':>4} {'等级':<2} {'阶段':<8} "
              f"{'入场价':>8} {'止损价':>8} {'回踩天':>4} {'缩量%':>6} {'120d涨幅':>8}")
        print("-" * 90)
        for i, r in enumerate(results, 1):
            print(f"{i:>4} {r.symbol:<8} {r.name:<8} {r.score:>4.0f} {r.grade:<2} {r.stage:<8} "
                  f"{r.entry_price:>8.2f} {r.stop_loss:>8.2f} {r.pullback_days:>4} "
                  f"{r.vol_shrink_pct:>5.0%} {r.gain_120d:>7.1%}")
    else:
        print("  今日未发现符合条件的标的。")

    report_dir = os.path.join(BASE_DIR, "mydate", "breakout_reports")
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, f"breakout_{today}.md")
    report_content = generate_report(results, env, args.mode, today)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    print(f"\n📝 报告已保存: {report_path}")

    json_path = os.path.join(report_dir, f"breakout_{today}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([r.to_dict() for r in results], f, ensure_ascii=False, indent=2, default=str)
    print(f"📝 JSON 已保存: {json_path}")


if __name__ == "__main__":
    main()
